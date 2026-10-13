"""The helpdesk tools, shared by the in-process agent and the MCP server.

``HelpdeskTools`` is created per authenticated user. The user's email is bound here from
their verified identity and is never a tool argument, so nothing in a conversation can
make the agent read or file tickets as somebody else.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from escalon.search import Hit, SearchIndex
from escalon.tickets import Ticket, TicketSystem

TICKET_TITLE_MAX = 120


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, object]


@dataclass
class HelpdeskTools:
    index: SearchIndex
    tickets: TicketSystem
    user_email: str
    top_k: int = 5
    calls: list[ToolCall] = field(default_factory=list)
    retrieved: dict[str, Hit] = field(default_factory=dict)  # url -> best hit seen this session
    created: list[Ticket] = field(default_factory=list)

    async def search_kb(self, query: str) -> str:
        """Search Microsoft's troubleshooting articles. Use the user's own wording, including any
        error codes. Search again with different wording if the results don't match the problem."""
        self.calls.append(ToolCall("search_kb", {"query": query}))
        hits = await self.index.search(query, self.top_k)
        for hit in hits:
            self.retrieved.setdefault(hit.url, hit)
        if not hits:
            return "No articles found."
        return "\n\n---\n\n".join(
            f"[{i}] {hit.title}\nSection: {hit.section}\nURL: {hit.url}\n\n{_body(hit)}"
            for i, hit in enumerate(hits, start=1)
        )

    async def find_open_tickets(self) -> str:
        """List the user's tickets that are still open, so a duplicate isn't created."""
        self.calls.append(ToolCall("find_open_tickets", {}))
        found = await self.tickets.find_open_tickets(self.user_email)
        # Zammad indexes new tickets asynchronously (~3 s), so one created moments ago in this
        # conversation may not be searchable yet. Include it so it is never filed twice.
        seen = {t.number for t in found}
        tickets = found + [t for t in self.created if t.number not in seen]
        if not tickets:
            return "The user has no open tickets."
        return "\n".join(f"#{t.number} [{t.state}] {t.title} — {t.url}" for t in tickets)

    async def create_ticket(
        self, title: str, symptoms: str, steps_tried: str, relevant_article_urls: list[str]
    ) -> str:
        """Escalate to a human technician. Call this when the knowledge base doesn't cover the
        problem, the fix needs an administrator, or the user says the suggested steps didn't work.

        title: one line describing the problem.
        symptoms: what the user reported, including exact error messages and codes.
        steps_tried: what the user already tried, or "none".
        relevant_article_urls: URLs from search_kb results that the technician should read; may be empty.
        """
        self.calls.append(
            ToolCall(
                "create_ticket",
                {
                    "title": title,
                    "symptoms": symptoms,
                    "steps_tried": steps_tried,
                    "relevant_article_urls": relevant_article_urls,
                },
            )
        )
        unknown = [u for u in relevant_article_urls if u not in self.retrieved]
        if unknown:
            return (
                f"Not created: these URLs were not returned by search_kb in this conversation: {unknown}. "
                "Only include URLs from search results."
            )
        ticket = await self.tickets.create_ticket(
            self.user_email,
            title.strip()[:TICKET_TITLE_MAX],
            ticket_body(symptoms, steps_tried, relevant_article_urls),
        )
        self.created.append(ticket)
        return f"Created ticket #{ticket.number}: {ticket.url}"


def ticket_body(symptoms: str, steps_tried: str, article_urls: list[str]) -> str:
    articles = "\n".join(f"- {u}" for u in article_urls) or "- none matched"
    return (
        f"Reported by the user via Escalon\n\n"
        f"Symptoms:\n{symptoms.strip()}\n\n"
        f"Already tried:\n{steps_tried.strip() or 'none'}\n\n"
        f"Possibly relevant Microsoft articles:\n{articles}\n"
    )


def _body(hit: Hit) -> str:
    # The chunk text starts with "<title>\nSection: <section>\n\n", already shown above.
    return hit.text.split("\n\n", 1)[1] if "\n\n" in hit.text else hit.text
