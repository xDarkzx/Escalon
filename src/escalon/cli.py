"""Command-line entry point: ``escalon <command>``."""

from __future__ import annotations

import argparse
import asyncio
import logging
from dataclasses import asdict
from pathlib import Path

from escalon.config import get_settings

DEFAULT_KB_DIR = Path("data/SupportArticles-docs")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="escalon")
    commands = parser.add_subparsers(dest="command", required=True)

    fetch = commands.add_parser("fetch-kb", help="download the pinned knowledge-base snapshot")
    fetch.add_argument("--dest", type=Path, default=DEFAULT_KB_DIR)

    ingest = commands.add_parser("ingest", help="chunk, embed and index the knowledge base")
    ingest.add_argument("--kb", type=Path, default=DEFAULT_KB_DIR / "support")

    search = commands.add_parser("search", help="run a raw retrieval query")
    search.add_argument("query")

    ev = commands.add_parser("eval-retrieval", help="article-level retrieval metrics")
    ev.add_argument("--questions", type=Path, default=Path("evals/questions.jsonl"))
    ev.add_argument("--k", type=int, default=5)
    ev.add_argument("--out", type=Path)

    ev_agent = commands.add_parser("eval-agent", help="end-to-end agent behaviour on the question set")
    ev_agent.add_argument("--questions", type=Path, default=Path("evals/questions.jsonl"))
    ev_agent.add_argument("--only", nargs="*", help="question ids to run")
    ev_agent.add_argument("--out", type=Path)

    serve = commands.add_parser("serve", help="run the MCP server and chat API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "httpx2", "azure"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    if args.command == "fetch-kb":
        from escalon.ingest import fetch_kb

        print(fetch_kb(args.dest))
    elif args.command == "ingest":
        asyncio.run(_ingest(args.kb))
    elif args.command == "search":
        asyncio.run(_search(args.query))
    elif args.command == "eval-retrieval":
        _write(args.out, asyncio.run(_eval_retrieval(args.questions, args.k)))
    elif args.command == "serve":
        import uvicorn

        from escalon.server import create_app

        uvicorn.run(create_app(get_settings()), host=args.host, port=args.port, proxy_headers=True)
    elif args.command == "eval-agent":
        _write(args.out, asyncio.run(_eval_agent(args.questions, args.only)))


async def _ingest(kb: Path) -> None:
    from escalon.ingest import ingest
    from escalon.services import build_index

    index = build_index(get_settings())
    if hasattr(index, "ensure_index"):
        await index.ensure_index()
    await ingest(kb, index)


async def _search(query: str) -> None:
    from escalon.services import build_index

    settings = get_settings()
    for hit in await build_index(settings).search(query, settings.search_top_k):
        print(f"{hit.score:.4f}  {hit.title} | {hit.section}\n        {hit.url}")


async def _eval_retrieval(questions_path: Path, k: int) -> str:
    from escalon.evals import evaluate_retrieval, load_questions
    from escalon.services import build_index

    report = await evaluate_retrieval(build_index(get_settings()), load_questions(questions_path), k)
    for r in report.results:
        if r.rank != 1:
            print(f"{r.question_id}: rank={r.rank} got {r.retrieved_articles[:3]}")
    print(
        f"questions={report.questions} hit@1={report.hit_at_1:.3f} hit@{k}={report.hit_at_k:.3f} "
        f"mrr={report.mrr:.3f}"
    )
    return report.to_json()


async def _eval_agent(questions_path: Path, only: list[str] | None) -> str:
    from escalon.agent import build_agent
    from escalon.evals import evaluate_case, load_questions, summarise
    from escalon.models import openai_client
    from escalon.services import build_index
    from escalon.tools import HelpdeskTools

    settings = get_settings()
    client = openai_client(settings)
    index = build_index(settings)

    async def run(tools: HelpdeskTools, question: str) -> str:
        response = await build_agent(client, settings.chat_model, tools).run(question)
        return str(response.text)

    results = []
    for q in load_questions(questions_path):
        if only and q.id not in only:
            continue
        r = await evaluate_case(q, run, index)
        mark = "ok " if r.action_correct else "BAD"
        print(
            f"{mark} {r.question_id} expected={r.expected_action} got={r.action} "
            f"article={r.expected_article_used} searches={r.searches} {r.seconds}s {r.error or ''}"
        )
        results.append(r)
    report = summarise(settings.chat_model, results)
    summary = {k: v for k, v in asdict(report).items() if k != "results"}
    print(" ".join(f"{k}={v}" for k, v in summary.items()))
    return report.to_json()


def _write(out: Path | None, content: str) -> None:
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
