import json

import pytest
from starlette.testclient import TestClient

from escalon.auth import EntraTokenVerifier
from escalon.config import Settings
from escalon.search import Hit
from escalon.server import create_app
from escalon.tickets import Ticket
from tests.conftest import make_chunk
from tests.test_auth import AUDIENCE, KEY, TENANT, token


class FakeIndex:
    async def search(self, query, top_k):
        c = make_chunk("windows-client/printing/a", 0, "Network printer error", "Use Credential Manager.")
        return [Hit(c.id, c.article_id, c.title, c.section, c.url, c.text, 1.0)]

    async def upsert(self, chunks):
        raise AssertionError("not used")


class FakeTickets:
    def __init__(self):
        self.created = []

    async def find_open_tickets(self, email):
        return []

    async def create_ticket(self, email, title, body):
        self.created.append((email, title, body))
        return Ticket(1, "31001", title, "new", "https://desk/#ticket/zoom/1")


def settings(**overrides) -> Settings:
    values = {
        "profile": "local",
        "chat_model": "m",
        "embedding_model": "e",
        "embedding_dimensions": 8,
        "local_openai_base_url": "http://localhost:11434/v1",
        "auth_mode": "entra",
        "entra_tenant_id": TENANT,
        "entra_audience": AUDIENCE,
        "public_url": "http://testserver",
        **overrides,
    }
    return Settings(_env_file=None, **values)


@pytest.fixture
def tickets():
    return FakeTickets()


@pytest.fixture
def client(tickets):
    verifier = EntraTokenVerifier(TENANT, AUDIENCE, signing_key=lambda _: KEY.public_key())
    app = create_app(settings(), index=FakeIndex(), tickets=tickets, verifier=verifier)
    with TestClient(app) as c:
        yield c


MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def rpc(client, method, params, bearer=None):
    headers = dict(MCP_HEADERS)
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    return client.post(
        "/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    )


def result_of(response):
    body = response.text
    payload = (
        body.split("data: ", 1)[1].splitlines()[0] if body.startswith("event:") or "data: " in body else body
    )
    return json.loads(payload)["result"]


def test_health_is_public(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_mcp_requires_a_token_and_advertises_entra(client):
    response = rpc(client, "tools/list", {})

    assert response.status_code == 401
    assert "resource_metadata" in response.headers["www-authenticate"]
    metadata = client.get("/.well-known/oauth-protected-resource").json()
    assert metadata["authorization_servers"] == [f"https://login.microsoftonline.com/{TENANT}/v2.0"]


def test_mcp_rejects_token_without_scope(client):
    assert rpc(client, "tools/list", {}, bearer=token(scp="User.Read")).status_code in (401, 403)


def test_create_ticket_is_filed_as_the_token_user_not_an_argument(client, tickets):
    bearer = token()
    rpc(client, "tools/call", {"name": "search_kb", "arguments": {"query": "printer"}}, bearer)
    response = rpc(
        client,
        "tools/call",
        {
            "name": "create_ticket",
            "arguments": {
                "title": "Printer error",
                "symptoms": "0x0000052e",
                "steps_tried": "none",
                "relevant_article_urls": [
                    "https://learn.microsoft.com/en-us/troubleshoot/windows-client/printing/a"
                ],
            },
        },
        bearer,
    )

    assert "Created ticket #31001" in json.dumps(result_of(response))
    assert tickets.created[0][0] == "sam.taylor@contoso.test"


def test_create_ticket_refuses_urls_that_search_never_returned(client, tickets):
    response = rpc(
        client,
        "tools/call",
        {
            "name": "create_ticket",
            "arguments": {
                "title": "t",
                "symptoms": "s",
                "steps_tried": "none",
                "relevant_article_urls": ["https://evil.example/phish"],
            },
        },
        token(),
    )

    assert "Not created" in json.dumps(result_of(response))
    assert tickets.created == []


def test_chat_api_requires_token(client):
    assert client.post("/api/chat", json={"message": "hi"}).status_code == 401


def test_disabled_auth_requires_explicit_dev_identity():
    with pytest.raises(ValueError, match="ESCALON_DEV_USER_EMAIL"):
        settings(auth_mode="disabled")
