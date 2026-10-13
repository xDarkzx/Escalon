"""Ticketing: the ``TicketSystem`` protocol and a Zammad REST implementation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, TypeAdapter

OPEN_STATES = ("new", "open", "pending reminder")


@dataclass(frozen=True)
class Ticket:
    id: int
    number: str
    title: str
    state: str
    url: str


class TicketSystem(Protocol):
    async def find_open_tickets(self, customer_email: str) -> list[Ticket]: ...

    async def create_ticket(self, customer_email: str, title: str, body: str) -> Ticket: ...


class ZammadTicket(BaseModel):
    """The fields we read from Zammad's ticket JSON; validated, not trusted."""

    id: int
    number: str
    title: str
    state: str | None = None  # present when the request used expand=true
    state_id: int | None = None


_TICKET_LIST = TypeAdapter(list[ZammadTicket])


class TicketingError(RuntimeError):
    pass


class ZammadTickets:
    def __init__(
        self, base_url: str, token: str, group: str, client: httpx.AsyncClient | None = None
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._group = group
        self._http = client or httpx.AsyncClient(timeout=15.0)
        self._headers = {"Authorization": f"Token token={token}"}

    async def find_open_tickets(self, customer_email: str) -> list[Ticket]:
        states = " OR ".join(f'"{s}"' for s in OPEN_STATES)
        query = f'customer.email:"{_escape(customer_email)}" AND state.name:({states})'
        data = await self._request("GET", "/api/v1/tickets/search", params={"query": query, "expand": "true"})
        return [self._ticket(t) for t in _TICKET_LIST.validate_python(data)]

    async def create_ticket(self, customer_email: str, title: str, body: str) -> Ticket:
        payload = {
            "title": title,
            "group": self._group,
            # "guess:" makes Zammad find the customer by email, or create them on first contact.
            "customer_id": f"guess:{customer_email}",
            "article": {
                "subject": title,
                "body": body,
                "type": "web",
                "internal": False,
                "content_type": "text/plain",
            },
        }
        data = await self._request("POST", "/api/v1/tickets", json=payload)
        return self._ticket(ZammadTicket.model_validate(data))

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        try:
            response = await self._http.request(
                method, self._base_url + path, headers=self._headers, params=params, json=json
            )
        except httpx.HTTPError as exc:
            raise TicketingError(f"Zammad unreachable: {exc}") from exc
        if response.is_error:
            raise TicketingError(f"Zammad {method} {path} -> {response.status_code}: {response.text[:300]}")
        try:
            return response.json()
        except ValueError as exc:
            raise TicketingError(f"Zammad {method} {path} returned non-JSON: {response.text[:200]}") from exc

    def _ticket(self, data: ZammadTicket) -> Ticket:
        return Ticket(
            id=data.id,
            number=data.number,
            title=data.title,
            state=data.state or f"state_id={data.state_id}",
            url=f"{self._base_url}/#ticket/zoom/{data.id}",
        )


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
