"""Evaluation: retrieval quality, and end-to-end agent behaviour."""

from __future__ import annotations

import json
import re
import statistics
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from escalon.kb import article_url
from escalon.search import SearchIndex
from escalon.tickets import Ticket
from escalon.tools import HelpdeskTools


@dataclass(frozen=True)
class Question:
    id: str
    question: str
    expected_articles: list[str]
    expected_action: str  # "answer" | "escalate"


def load_questions(path: Path) -> list[Question]:
    with path.open(encoding="utf-8") as f:
        return [Question(**json.loads(line)) for line in f if line.strip()]


@dataclass
class RetrievalResult:
    question_id: str
    rank: int | None  # 1-based rank of the first expected article, None if not retrieved
    retrieved_articles: list[str]


@dataclass
class RetrievalReport:
    k: int
    questions: int
    hit_at_1: float
    hit_at_k: float
    mrr: float
    results: list[RetrievalResult] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)


def unique_articles(article_ids: list[str]) -> list[str]:
    return list(dict.fromkeys(article_ids))


async def evaluate_retrieval(index: SearchIndex, questions: list[Question], k: int) -> RetrievalReport:
    """Article-level ranking metrics over questions that have an expected article."""
    results: list[RetrievalResult] = []
    for q in questions:
        if not q.expected_articles:
            continue
        hits = await index.search(q.question, top_k=k)
        articles = unique_articles([h.article_id for h in hits])
        rank = next((i + 1 for i, a in enumerate(articles) if a in q.expected_articles), None)
        results.append(RetrievalResult(q.id, rank, articles))

    n = len(results)
    return RetrievalReport(
        k=k,
        questions=n,
        hit_at_1=sum(r.rank == 1 for r in results) / n,
        hit_at_k=sum(r.rank is not None for r in results) / n,
        mrr=sum(1 / r.rank for r in results if r.rank) / n,
        results=results,
    )


# ── End-to-end agent evaluation ──────────────────────────────────────────────

URL_PATTERN = re.compile(r"https://learn\.microsoft\.com/[^\s)\]>,]+")


class RecordingTickets:
    """Eval harness ticket system: records what the agent would have filed. No open tickets."""

    def __init__(self) -> None:
        self.created: list[tuple[str, str, str]] = []

    async def find_open_tickets(self, customer_email: str) -> list[Ticket]:  # noqa: ARG002
        return []

    async def create_ticket(self, customer_email: str, title: str, body: str) -> Ticket:
        self.created.append((customer_email, title, body))
        n = len(self.created)
        return Ticket(id=n, number=f"EVAL-{n}", title=title, state="new", url=f"eval://ticket/{n}")


@dataclass
class AgentCaseResult:
    question_id: str
    expected_action: str
    action: str
    action_correct: bool
    # Expected article cited in the reply or attached to the ticket; None if no expectation.
    expected_article_used: bool | None
    fabricated_urls: list[str]  # learn.microsoft.com URLs in the reply that search never returned
    checked_open_tickets_first: bool | None  # None if no ticket was created
    searches: int
    seconds: float
    reply: str
    error: str | None = None


@dataclass
class AgentReport:
    model: str
    questions: int
    action_accuracy: float
    answered_when_should_escalate: int
    escalated_when_could_answer: int
    expected_article_used: float
    replies_with_fabricated_urls: int
    checked_open_tickets_first: float
    errors: int
    median_seconds: float
    results: list[AgentCaseResult] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)


async def evaluate_case(
    q: Question, run: Callable[[HelpdeskTools, str], Awaitable[str]], index: SearchIndex
) -> AgentCaseResult:
    tickets = RecordingTickets()
    tools = HelpdeskTools(index=index, tickets=tickets, user_email="eval.user@contoso.test")
    start = time.perf_counter()
    error = None
    try:
        reply = await run(tools, q.question)
    except Exception as exc:  # noqa: BLE001 - recorded and counted as a failure, never hidden
        reply, error = "", f"{type(exc).__name__}: {exc}"
    seconds = time.perf_counter() - start

    escalated = bool(tools.created)
    action = "escalate" if escalated else "answer"
    used_urls = set(URL_PATTERN.findall(reply))
    for call in tools.calls:
        if call.name == "create_ticket" and tools.created:
            used_urls.update(call.arguments.get("relevant_article_urls", []))  # type: ignore[arg-type]
    expected_urls = {article_url(a) for a in q.expected_articles}
    names = [c.name for c in tools.calls]
    return AgentCaseResult(
        question_id=q.id,
        expected_action=q.expected_action,
        action=action,
        action_correct=action == q.expected_action and error is None,
        expected_article_used=bool(expected_urls & used_urls) if expected_urls else None,
        fabricated_urls=sorted(u for u in URL_PATTERN.findall(reply) if u.rstrip(".") not in tools.retrieved),
        checked_open_tickets_first=(
            "find_open_tickets" in names[: names.index("create_ticket")] if "create_ticket" in names else None
        ),
        searches=names.count("search_kb"),
        seconds=round(seconds, 1),
        reply=reply,
        error=error,
    )


def summarise(model: str, results: list[AgentCaseResult]) -> AgentReport:
    with_expected = [r for r in results if r.expected_article_used is not None]
    escalations = [r for r in results if r.checked_open_tickets_first is not None]
    return AgentReport(
        model=model,
        questions=len(results),
        action_accuracy=_ratio(sum(r.action_correct for r in results), len(results)),
        answered_when_should_escalate=sum(
            r.expected_action == "escalate" and r.action == "answer" for r in results
        ),
        escalated_when_could_answer=sum(
            r.expected_action == "answer" and r.action == "escalate" for r in results
        ),
        expected_article_used=_ratio(
            sum(bool(r.expected_article_used) for r in with_expected), len(with_expected)
        ),
        replies_with_fabricated_urls=sum(bool(r.fabricated_urls) for r in results),
        checked_open_tickets_first=_ratio(
            sum(bool(r.checked_open_tickets_first) for r in escalations), len(escalations)
        ),
        errors=sum(r.error is not None for r in results),
        median_seconds=statistics.median(r.seconds for r in results) if results else 0.0,
        results=results,
    )


def _ratio(n: int, d: int) -> float:
    return round(n / d, 3) if d else 0.0
