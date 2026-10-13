import pytest

from escalon.evals import RecordingTickets
from escalon.search import LocalIndex
from escalon.tools import HelpdeskTools, ticket_body
from tests.conftest import make_chunk

PRINTER = make_chunk("windows-client/printing/a", 0, "Printer error 0x0000052e", "Add a Windows credential.")


@pytest.fixture
async def tools(tmp_path, embedder):
    index = LocalIndex(tmp_path / "i.sqlite", embedder)
    await index.upsert([PRINTER])
    return HelpdeskTools(index=index, tickets=RecordingTickets(), user_email="sam@contoso.test")


async def test_search_formats_results_without_repeating_the_chunk_header(tools):
    out = await tools.search_kb("0x0000052e")

    assert out.startswith(
        "[1] Printer error 0x0000052e\nSection: Resolution\nURL: https://learn.microsoft.com/"
    )
    assert out.count("Printer error 0x0000052e") == 1
    assert PRINTER.url in tools.retrieved


async def test_search_with_empty_index(tmp_path, embedder):
    empty = HelpdeskTools(LocalIndex(tmp_path / "e.sqlite", embedder), RecordingTickets(), "a@b.test")
    assert await empty.search_kb("anything") == "No articles found."


async def test_ticket_is_filed_for_the_bound_user_with_structured_body(tools):
    await tools.search_kb("printer")
    result = await tools.create_ticket("Printer error", "0x0000052e when adding", "restarted", [PRINTER.url])

    assert result.startswith("Created ticket #EVAL-1")
    email, title, body = tools.tickets.created[0]
    assert email == "sam@contoso.test"
    assert title == "Printer error"
    assert f"- {PRINTER.url}" in body


async def test_long_titles_are_truncated(tools):
    await tools.create_ticket("x" * 500, "s", "none", [])
    assert len(tools.tickets.created[0][1]) == 120


async def test_find_open_tickets_reports_none(tools):
    assert await tools.find_open_tickets() == "The user has no open tickets."


def test_ticket_body_handles_no_articles_and_blank_steps():
    body = ticket_body("Laptop dropped", "  ", [])
    assert "Already tried:\nnone" in body
    assert "- none matched" in body
