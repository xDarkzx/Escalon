import pytest

from escalon.evals import RecordingTickets
from escalon.guards import claimed_ticket_ids, enforce_ticket_honesty, ungrounded_links
from escalon.search import Hit, LocalIndex
from escalon.tools import HelpdeskTools


@pytest.mark.parametrize(
    ("reply", "ids"),
    [
        ("I've opened a ticket for you: **#24576**", {"24576"}),
        ("Ticket #EVAL-1 created. A technician will follow up.", {"EVAL-1"}),
        ("Ticket number: **EVAL-2**", {"EVAL-2"}),
        ("Your ticket number is 89017.", {"89017"}),
        ("Error 0x0000052e when adding the printer.", set()),
        ("See KB4505903 for details.", set()),
    ],
)
def test_claimed_ticket_ids(reply, ids):
    assert claimed_ticket_ids(reply) == ids


@pytest.fixture
def tools(tmp_path, embedder):
    return HelpdeskTools(LocalIndex(tmp_path / "i.sqlite", embedder), RecordingTickets(), "sam@contoso.test")


async def test_honest_reply_passes_through(tools):
    await tools.create_ticket("t", "s", "none", [])
    guarded = await enforce_ticket_honesty("Ticket #EVAL-1 created.", tools, "help")

    assert guarded.text == "Ticket #EVAL-1 created."
    assert guarded.unbacked_claims == []


async def test_invented_ticket_is_replaced_by_a_real_one(tools):
    guarded = await enforce_ticket_honesty(
        "I've opened a ticket for you: **#24576**", tools, "reset my password"
    )

    assert guarded.unbacked_claims == ["24576"]
    assert guarded.fallback_ticket == "EVAL-1"
    assert guarded.text.startswith("I've logged ticket #EVAL-1.")
    assert tools.tickets.created[0][1] == "reset my password"


async def test_wrong_number_is_corrected_without_filing_twice(tools):
    await tools.create_ticket("t", "s", "none", [])
    guarded = await enforce_ticket_honesty("Ticket #99999 created.", tools, "help")

    assert guarded.text.startswith("I've logged ticket #EVAL-1.")
    assert len(tools.tickets.created) == 1


async def test_truncated_article_link_is_restored(tools):
    full = "https://learn.microsoft.com/en-us/troubleshoot/windows-client/shell-experience/display-reverts-resume-standby"
    tools.retrieved[full] = Hit("a#0", "a", "t", "s", full, "body", 1.0)
    cut = full.removesuffix("-standby")

    guarded = await enforce_ticket_honesty(f"Steps... See {cut}.", tools, "q")

    assert guarded.text == f"Steps... See {full}."


async def test_links_quoted_inside_retrieved_articles_are_grounded(tools):
    article = "https://learn.microsoft.com/en-us/troubleshoot/a"
    quoted = "https://learn.microsoft.com/en-us/windows/security/tpm/initialize"
    tools.retrieved[article] = Hit("a#0", "a", "t", "s", article, f"see {quoted} for details", 1.0)
    invented = "https://learn.microsoft.com/en-us/troubleshoot/made-up"

    assert ungrounded_links(f"{article} {quoted} {invented}", tools) == [invented]
