from escalon.evals import Question, evaluate_case, evaluate_retrieval, markdown_report, rescore, summarise
from escalon.kb import article_url
from escalon.search import LocalIndex
from tests.conftest import make_chunk

ARTICLE = "windows-client/printing/a"


async def index_with_printer(tmp_path, embedder):
    index = LocalIndex(tmp_path / "i.sqlite", embedder)
    await index.upsert([make_chunk(ARTICLE, 0, "Printer error 0x0000052e", "Add a credential.")])
    return index


async def test_answer_case_scores_citation_and_flags_fabricated_urls(tmp_path, embedder):
    index = await index_with_printer(tmp_path, embedder)
    q = Question("q1", "printer 0x0000052e", [ARTICLE], "answer")

    async def run(tools, question):
        await tools.search_kb(question)
        return f"Do this. {article_url(ARTICLE)} and https://learn.microsoft.com/en-us/troubleshoot/made-up"

    result = await evaluate_case(q, run, index)

    assert result.action == "answer"
    assert result.action_correct
    assert result.expected_article_used
    assert result.fabricated_urls == ["https://learn.microsoft.com/en-us/troubleshoot/made-up"]


async def test_escalation_counts_ticket_articles_and_open_ticket_check(tmp_path, embedder):
    index = await index_with_printer(tmp_path, embedder)
    q = Question("q2", "printer 0x0000052e", [ARTICLE], "escalate")

    async def run(tools, question):
        await tools.search_kb(question)
        await tools.find_open_tickets()
        await tools.create_ticket("t", "s", "none", [article_url(ARTICLE)])
        return "Ticket created."

    result = await evaluate_case(q, run, index)

    assert result.action == "escalate"
    assert result.expected_article_used
    assert result.checked_open_tickets_first


async def test_agent_exceptions_are_recorded_as_failures(tmp_path, embedder):
    index = await index_with_printer(tmp_path, embedder)

    async def run(tools, question):
        raise TimeoutError("model hung")

    result = await evaluate_case(Question("q3", "x", [], "escalate"), run, index)

    assert not result.action_correct
    assert result.error == "TimeoutError: model hung"
    report = summarise("m", [result])
    assert report.errors == 1
    assert report.action_accuracy == 0.0


async def test_retrieval_metrics(tmp_path, embedder):
    index = await index_with_printer(tmp_path, embedder)
    questions = [
        Question("a", "printer 0x0000052e", [ARTICLE], "answer"),
        Question("b", "unrelated", ["some/other-article"], "answer"),
        Question("c", "no expectation", [], "escalate"),
    ]

    report = await evaluate_retrieval(index, questions, k=5)

    assert report.questions == 2
    assert report.hit_at_1 == 0.5
    assert report.mrr == 0.5


def test_rescore_uses_current_labels_and_report_renders():
    run = {
        "model": "m",
        "replies_with_fabricated_urls": 0,
        "expected_article_used": 1.0,
        "median_seconds": 9.6,
        "action_accuracy": 0.0,
        "results": [
            {"question_id": "a", "action": "escalate", "error": None},
            {"question_id": "b", "action": "answer", "error": None},
        ],
    }
    rescored = rescore(run, {"a": "escalate", "b": "escalate"})

    assert rescored["action_accuracy"] == 0.5
    assert rescored["answered_when_should_escalate"] == 1
    table = markdown_report(
        [("v1", rescored)], {"questions": 2, "k": 5, "hit_at_1": 1, "hit_at_k": 1, "mrr": 1}
    )
    assert "| v1 | m | 0.50 | 1 | 0 | 1.00 | 0 | n/a | 10 s |" in table
