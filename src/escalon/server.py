"""HTTP server: the remote MCP endpoint (``/mcp``), the agent chat API (``/api/chat``) and ``/healthz``.

Copilot Studio connects to ``/mcp`` and uses the three tools with its own orchestration, which
puts Escalon in Teams. ``/api/chat`` runs Escalon's own agent, the one the evals measure.
Both authenticate the caller with an Entra ID access token and act as that user.
"""

from __future__ import annotations

import logging
import uuid
from collections import OrderedDict

from agent_framework import AgentSession
from fastapi import Depends, FastAPI, HTTPException, Request
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from openai import AsyncOpenAI
from pydantic import AnyHttpUrl, BaseModel
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from escalon.agent import build_agent
from escalon.auth import REQUIRED_SCOPE, EntraTokenVerifier, entra_issuers, user_email
from escalon.config import AuthMode, Settings
from escalon.guards import enforce_ticket_honesty
from escalon.models import openai_client
from escalon.search import SearchIndex
from escalon.services import build_index
from escalon.tickets import TicketSystem, ZammadTickets
from escalon.tools import HelpdeskTools

log = logging.getLogger(__name__)

MAX_ACTIVE_USERS = 500


class UserSessions:
    """Per-user tool state (which articles they were shown), bounded LRU.

    State lives in this process, so the app runs as a single replica; see docs/design.md.
    """

    def __init__(self, index: SearchIndex, tickets: TicketSystem, top_k: int) -> None:
        self._index = index
        self._tickets = tickets
        self._top_k = top_k
        self._tools: OrderedDict[str, HelpdeskTools] = OrderedDict()
        self.chats: dict[str, tuple[str, AgentSession]] = {}

    def tools_for(self, email: str) -> HelpdeskTools:
        tools = self._tools.pop(email, None) or HelpdeskTools(
            index=self._index, tickets=self._tickets, user_email=email, top_k=self._top_k
        )
        self._tools[email] = tools
        while len(self._tools) > MAX_ACTIVE_USERS:
            evicted, _ = self._tools.popitem(last=False)
            self.chats = {k: v for k, v in self.chats.items() if v[0] != evicted}
        return tools


def create_app(
    settings: Settings,
    *,
    index: SearchIndex | None = None,
    tickets: TicketSystem | None = None,
    verifier: EntraTokenVerifier | None = None,
    llm: AsyncOpenAI | None = None,
) -> Starlette:
    if index is None:
        index = build_index(settings)
    if tickets is None:
        url, token = settings.require_zammad()
        tickets = ZammadTickets(url, token, settings.zammad_group)
    sessions = UserSessions(index, tickets, settings.search_top_k)
    llm = llm or openai_client(settings)

    if settings.auth_mode is AuthMode.ENTRA:
        verifier = verifier or EntraTokenVerifier(
            settings.required("entra_tenant_id"), settings.required("entra_audience")
        )
    else:
        log.warning("AUTH DISABLED: all requests act as %s. Local development only.", settings.dev_user_email)

    def current_user() -> str:
        if verifier is None:
            return settings.required("dev_user_email")
        access = get_access_token()
        email = user_email(access.claims or {}) if access else None
        if email is None:  # the auth middleware rejects these first; this is defence in depth
            raise PermissionError("no authenticated user")
        return email

    mcp = _build_mcp(settings, verifier, sessions, current_user)
    app = mcp.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        transport_security=_transport_security(settings),
    )

    api = _build_api(settings, verifier, sessions, llm)
    app.router.routes.append(Mount("/api", app=api))
    app.router.routes.append(Route("/healthz", lambda _: JSONResponse({"status": "ok"})))
    return app


def _build_mcp(settings, verifier, sessions: UserSessions, current_user) -> MCPServer:  # type: ignore[no-untyped-def]
    auth = None
    if verifier is not None:
        auth = AuthSettings(
            issuer_url=AnyHttpUrl(entra_issuers(settings.required("entra_tenant_id"))[0]),
            resource_server_url=AnyHttpUrl(settings.public_url),
            required_scopes=[REQUIRED_SCOPE],
            # EntraTokenVerifier already checks the audience (the app ID URI, not this URL).
            validate_token_resource=False,
        )
    mcp = MCPServer(
        name="Escalon",
        instructions="IT support tools: search Microsoft troubleshooting articles and file helpdesk tickets.",
        token_verifier=verifier,
        auth=auth,
    )

    async def search_kb(query: str) -> str:
        """Search Microsoft's Windows, Entra sign-in/MFA and Intune troubleshooting articles.
        Pass the user's problem in their words, including any error codes."""
        return await sessions.tools_for(current_user()).search_kb(query)

    async def find_open_tickets() -> str:
        """List the signed-in user's open helpdesk tickets."""
        return await sessions.tools_for(current_user()).find_open_tickets()

    async def create_ticket(
        title: str, symptoms: str, steps_tried: str, relevant_article_urls: list[str]
    ) -> str:
        """Create a helpdesk ticket for the signed-in user. Only include article URLs returned by
        search_kb. Use when articles don't cover the problem, an administrator is needed, or the
        suggested steps didn't work."""
        return await sessions.tools_for(current_user()).create_ticket(
            title, symptoms, steps_tried, relevant_article_urls
        )

    for fn in (search_kb, find_open_tickets, create_ticket):
        mcp.add_tool(fn)
    return mcp


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None


class ChatResponse(BaseModel):
    conversation_id: str
    reply: str
    tickets_created: list[str]


def _build_api(settings: Settings, verifier, sessions: UserSessions, llm) -> FastAPI:  # type: ignore[no-untyped-def]
    api = FastAPI(title="Escalon", docs_url=None, redoc_url=None)

    async def authenticated_user(request: Request) -> str:
        if verifier is None:
            return settings.dev_user_email  # type: ignore[return-value]
        header = request.headers.get("authorization", "")
        if not header.lower().startswith("bearer "):
            raise HTTPException(401, "bearer token required", headers={"WWW-Authenticate": "Bearer"})
        access = await verifier.verify_token(header[7:])
        if access is None:
            raise HTTPException(401, "invalid token", headers={"WWW-Authenticate": "Bearer"})
        return user_email(access.claims or {})  # type: ignore[return-value]  # verifier guarantees it

    @api.post("/chat")
    async def chat(body: ChatRequest, email: str = Depends(authenticated_user)) -> ChatResponse:
        tools = sessions.tools_for(email)
        agent = build_agent(llm, settings.chat_model, tools, settings.temperature)
        conversation_id = body.conversation_id or str(uuid.uuid4())
        owner, session = sessions.chats.get(conversation_id, (email, agent.create_session()))
        if owner != email:
            raise HTTPException(404, "conversation not found")
        before = len(tools.created)
        response = await agent.run(body.message, session=session)
        sessions.chats[conversation_id] = (email, session)
        guarded = await enforce_ticket_honesty(response.text, tools, body.message)
        if guarded.unbacked_claims:
            log.warning("model claimed tickets it never created: %s", guarded.unbacked_claims)
        return ChatResponse(
            conversation_id=conversation_id,
            reply=guarded.text,
            tickets_created=[t.number for t in tools.created[before:]],
        )

    return api


def _transport_security(settings: Settings) -> TransportSecuritySettings:
    # DNS-rebinding protection: only accept requests addressed to our own host.
    host = settings.public_url.split("://", 1)[-1].split("/", 1)[0]
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[host, f"{host}:*", "localhost:*", "127.0.0.1:*"],
        allowed_origins=[settings.public_url.rstrip("/")],
    )
