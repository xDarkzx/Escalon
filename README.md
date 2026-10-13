# Escalon

First-line IT support agent that answers from Microsoft's real troubleshooting articles, cites
them, and files a well-formed helpdesk ticket when it can't (or shouldn't) solve the problem
itself.

[![CI](https://github.com/xDarkzx/Escalon/actions/workflows/ci.yml/badge.svg)](https://github.com/xDarkzx/Escalon/actions/workflows/ci.yml)

```
staff member ──► /api/chat (own agent)  ─┐
Teams / Copilot Studio ──► /mcp (tools) ─┼─► search_kb ──► hybrid index (BM25 + vectors)
                                         ├─► find_open_tickets ─┐
                                         └─► create_ticket ─────┴─► Zammad
     every request authenticated with an Entra ID token; the ticket owner comes from the token
```

## What it does

- **Answers from real documentation.** 647 Microsoft troubleshooting articles (Windows client,
  Entra MFA, Intune) from `MicrosoftDocs/SupportArticles-docs`, pinned to one commit so results
  are reproducible. Articles are chunked by section, not by character count.
- **Finds exact error codes.** Hybrid search: BM25 keyword ranking plus vector similarity,
  fused with reciprocal rank fusion. Users paste `0x0000052e` or `AADSTS50076`; embeddings
  alone blur those together.
- **Knows when to hand over.** The agent escalates when no article matches, when the fix needs
  an administrator, or for hardware, requests and security incidents. Tickets arrive with
  symptoms, steps already tried and the relevant articles.
- **Doesn't let the model lie about actions.** A deterministic check after every reply: if the
  model claims a ticket it never created, a real one is filed and the reply corrected.
  Truncated article links are repaired. Tickets can only cite articles the search returned.
- **Acts as the signed-in user.** Identity comes from the validated Entra ID token, never from a
  tool argument, so a prompt can't file tickets as someone else.

## Results

Measured on 50 questions written the way staff phrase them ([evals/README.md](evals/README.md)
has the labelling rules and every label change). Local model, `qwen3.5:9b` via Ollama.

**Retrieval** (41 questions with a known answer article): hit@1 0.83, hit@5 0.95, MRR 0.88.

| Run | Action accuracy | Answered, should escalate | Escalated, could answer | Right article used | Ungrounded links | Model invented a ticket |
|---|---|---|---|---|---|---|
| v1 baseline | 0.76 | 3 | 9 | 0.90 | 1 | n/a |
| v2 admin-vs-user prompt + guards | 0.80 | 3 | 7 | 0.98 | 2 | 2 (both caught) |
| v3a v2 at temperature 0 | 0.66 | 6 | 10 | 0.90 | 0 | 0 |
| v3b repeat of v3a | 0.68 | 5 | 10 | 0.85 | 0 | 0 |

Generated with `escalon report`; raw per-question results are in [evals/results](evals/results).

What these numbers do and don't say:

- **v1 → v2 is a single sampled run each,** so some of the gain may be noise. Repeated runs at
  the model's default temperature are needed before calling it an improvement.
- **Temperature 0 made this model worse,** and on one question it produced a malformed tool
  call every time. Temperature is now a setting that defaults to the model's own default.
- **The question set is biased toward covered problems.** Most questions were written from the
  articles, so real-world coverage would be lower.
- **The guard matters.** In v2 the model claimed tickets it never created twice; users never saw
  either, because the guard filed a real ticket instead.

## Engineering

| | |
|---|---|
| Agent | Microsoft Agent Framework, any OpenAI-protocol model (Azure OpenAI or local Ollama) |
| Search | Azure AI Search (hybrid, HNSW) or local SQLite FTS5 + numpy, same interface and behaviour |
| Tools | Shared by the in-process agent and a remote MCP server (streamable HTTP) for Copilot Studio |
| Ticketing | Zammad REST API, responses schema-validated; verified against a live Zammad 7.2 |
| Auth | Entra ID bearer tokens: signature, issuer, audience, expiry and `Helpdesk.Use` scope |
| Infra | Bicep: AI Search, Azure OpenAI, Container Apps, managed identity + RBAC, Key Vault. No API keys anywhere |

Quality gates, run in CI and as pre-commit hooks:

- Ruff with security (bandit), pytest-style, async-safety and pylint rule sets
- mypy `--strict`
- pytest with an 85% coverage floor (currently ~87%), including a test that drives the real
  Agent Framework tool loop against a scripted model
- Live integration tests against Zammad (opt-in: `-m integration`)
- pip-audit on the locked dependencies, gitleaks secret scanning
- Bicep lint/build, hadolint, and a container smoke test

## Run it locally

Needs Python 3.11, [uv](https://docs.astral.sh/uv/) and [Ollama](https://ollama.com) with
`nomic-embed-text` and a chat model that supports tool calls.

```bash
uv sync
cp .env.local.example .env
uv run escalon fetch-kb          # pinned snapshot of the articles
uv run escalon ingest            # chunk, embed, index (~1 min on a GPU)
uv run escalon search "printer error 0x0000052e"
uv run escalon eval-retrieval
uv run escalon eval-agent --out evals/results/my-run.json
uv run escalon serve             # /mcp, /api/chat, /healthz
```

Tests: `uv run pytest`. Everything: `uv run pre-commit run --all-files`.

## Deploying to Azure

See [docs/deploy.md](docs/deploy.md). The Bicep compiles and lints clean and the image builds
and passes its health check, but the Azure deployment has **not yet been run** against a live
subscription. Design notes are in [docs/design.md](docs/design.md).

## Licence

Code: MIT. Knowledge-base content: © Microsoft, [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/),
from [MicrosoftDocs/SupportArticles-docs](https://github.com/MicrosoftDocs/SupportArticles-docs);
two articles are included as test fixtures.
