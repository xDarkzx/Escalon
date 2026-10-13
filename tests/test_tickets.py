import json

import httpx
import pytest
import respx

from escalon.tickets import TicketingError, ZammadTickets

BASE = "https://desk.example.test"


@pytest.fixture
def zammad():
    return ZammadTickets(BASE, "secret", "Users", client=httpx.AsyncClient())


@respx.mock
async def test_find_open_tickets_queries_by_customer_and_open_states(zammad):
    route = respx.get(f"{BASE}/api/v1/tickets/search").mock(
        return_value=httpx.Response(200, json=[{"id": 7, "number": "31007", "title": "VPN", "state": "open"}])
    )

    tickets = await zammad.find_open_tickets('sam"@contoso.test')

    query = route.calls.last.request.url.params["query"]
    assert (
        query == 'customer.email:"sam\\"@contoso.test" AND state.name:("new" OR "open" OR "pending reminder")'
    )
    assert route.calls.last.request.headers["Authorization"] == "Token token=secret"
    assert tickets[0].number == "31007"
    assert tickets[0].url == f"{BASE}/#ticket/zoom/7"


@respx.mock
async def test_create_ticket_guesses_customer_from_email(zammad):
    route = respx.post(f"{BASE}/api/v1/tickets").mock(
        return_value=httpx.Response(201, json={"id": 8, "number": "31008", "title": "t", "state_id": 1})
    )

    ticket = await zammad.create_ticket("sam@contoso.test", "Printer error", "details")

    sent = json.loads(route.calls.last.request.content)
    assert sent["customer_id"] == "guess:sam@contoso.test"
    assert sent["group"] == "Users"
    assert sent["article"]["body"] == "details"
    assert ticket.id == 8


@respx.mock
async def test_http_errors_surface_as_ticketing_errors(zammad):
    respx.post(f"{BASE}/api/v1/tickets").mock(return_value=httpx.Response(422, text="group missing"))

    with pytest.raises(TicketingError, match="422: group missing"):
        await zammad.create_ticket("sam@contoso.test", "t", "b")


@respx.mock
async def test_unexpected_response_shape_is_a_ticketing_error_not_a_crash(zammad):
    html = httpx.Response(200, text="<html>login</html>")
    respx.get(f"{BASE}/api/v1/tickets/search").mock(return_value=html)

    with pytest.raises(TicketingError, match="non-JSON"):
        await zammad.find_open_tickets("sam@contoso.test")
