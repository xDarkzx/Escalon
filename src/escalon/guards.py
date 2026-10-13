"""Deterministic checks on the agent's reply, applied after the model has answered.

Small models sometimes say "I've opened ticket #24576" without calling ``create_ticket``.
A user told about a ticket that doesn't exist waits for help that never comes, so this
is enforced in code rather than trusted to the prompt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from escalon.tools import HelpdeskTools

# A ticket reference: the word "ticket", then within a few words an id such as #31007,
# **EVAL-3** or "number: 89017".
_TICKET_REF = re.compile(
    r"ticket\b[^.\n]{0,40}?(?:#|number(?:\s+is)?[:\s]*)\s*\**\s*#?([A-Z]+-\d+|\d{3,})",
    re.IGNORECASE,
)


LINK = re.compile(r"https://learn\.microsoft\.com/[^\s)\]>,*]+")


def ungrounded_links(reply: str, tools: HelpdeskTools) -> list[str]:
    """learn.microsoft.com links that are neither a retrieved article nor quoted in one."""
    shown = "\n".join(hit.text for hit in tools.retrieved.values())
    links = {u.rstrip(".") for u in LINK.findall(reply)}
    return sorted(u for u in links if u not in tools.retrieved and u not in shown)


def repair_truncated_links(reply: str, tools: HelpdeskTools) -> str:
    """Models sometimes cut a long article URL short. Restore it when exactly one retrieved
    article starts with the truncated link; otherwise leave it (and the eval counts it)."""
    for url in set(LINK.findall(reply)):
        stem = url.rstrip(".")
        if stem in tools.retrieved:
            continue
        matches = [full for full in tools.retrieved if full.startswith(stem)]
        if len(matches) == 1:
            reply = re.sub(re.escape(stem) + r"(?![\w-])", matches[0], reply)
    return reply


@dataclass(frozen=True)
class GuardedReply:
    text: str
    unbacked_claims: list[str]  # ticket ids the model claimed but never created
    fallback_ticket: str | None  # ticket the guard filed itself, if it had to


def claimed_ticket_ids(reply: str) -> set[str]:
    return {m.upper() for m in _TICKET_REF.findall(reply)}


async def enforce_ticket_honesty(reply: str, tools: HelpdeskTools, user_message: str) -> GuardedReply:
    reply = repair_truncated_links(reply, tools)
    real = {t.number.upper() for t in tools.created}
    unbacked = sorted(claimed_ticket_ids(reply) - real)
    if not unbacked:
        return GuardedReply(reply, [], None)

    if tools.created:
        # A ticket exists but the reply quotes the wrong number: state the real one(s).
        numbers = ", ".join(f"#{t.number}" for t in tools.created)
        return GuardedReply(
            f"I've logged ticket {numbers}. A technician will follow up with you.", unbacked, None
        )

    # The model promised a ticket it never filed. Escalating is the safe failure, so file it.
    await tools.create_ticket(
        title=user_message.strip().splitlines()[0][:120] or "Support request",
        symptoms=user_message,
        steps_tried="unknown (filed automatically: the assistant did not create a ticket it promised)",
        relevant_article_urls=[],
    )
    ticket = tools.created[-1]
    return GuardedReply(
        f"I've logged ticket #{ticket.number}. A technician will follow up with you.", unbacked, ticket.number
    )
