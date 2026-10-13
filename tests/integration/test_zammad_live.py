"""Against a real Zammad. Skipped unless ZAMMAD_TEST_URL and ZAMMAD_TEST_TOKEN are set.

docker compose up  (zammad/zammad-docker-compose), create an API token, then:
ZAMMAD_TEST_URL=http://localhost:8080 ZAMMAD_TEST_TOKEN=... uv run pytest -m integration
"""

import asyncio
import os
import uuid

import pytest

from escalon.tickets import OPEN_STATES, ZammadTickets

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not (os.environ.get("ZAMMAD_TEST_URL") and os.environ.get("ZAMMAD_TEST_TOKEN")),
        reason="needs a live Zammad (ZAMMAD_TEST_URL, ZAMMAD_TEST_TOKEN)",
    ),
]


async def eventually(query, attempts=60, delay=0.5):
    """Zammad's search index is updated by a background job a few seconds after writes."""
    for _ in range(attempts):
        if result := await query():
            return result
        await asyncio.sleep(delay)
    return await query()


@pytest.fixture
def zammad():
    return ZammadTickets(os.environ["ZAMMAD_TEST_URL"], os.environ["ZAMMAD_TEST_TOKEN"], "Users")


async def test_new_customer_ticket_round_trip(zammad):
    email = f"staff-{uuid.uuid4().hex[:8]}@contoso.test"  # unseen customer, exercises guess:<email>

    created = await zammad.create_ticket(email, "Printer error 0x0000052e", "Symptoms:\nerror when adding")
    open_tickets = await eventually(lambda: zammad.find_open_tickets(email))

    assert created.number
    assert [t.number for t in open_tickets] == [created.number]
    assert open_tickets[0].state in OPEN_STATES


async def test_other_users_tickets_are_not_returned(zammad):
    mine = f"a-{uuid.uuid4().hex[:8]}@contoso.test"
    theirs = f"b-{uuid.uuid4().hex[:8]}@contoso.test"
    await zammad.create_ticket(theirs, "Their ticket", "x")

    assert await zammad.find_open_tickets(mine) == []
