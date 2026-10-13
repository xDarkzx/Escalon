# Escalon — design

## Problem

A small business's staff hit Windows, sign-in/MFA and device-enrolment problems. The answer
usually exists in Microsoft's troubleshooting articles, but nobody reads them, so everything
becomes a ticket — and the ticket says "printer broken" with no context.

Escalon is a first-line IT support agent. It answers from Microsoft's real troubleshooting
articles with citations, and when it cannot resolve an issue it opens a ticket in Zammad that
already contains the symptoms, what was tried, and which articles were relevant.

## Knowledge base

`MicrosoftDocs/SupportArticles-docs` (CC-BY-4.0): `support/windows-client`, `support/entra/entra-id/mfa`,
`support/mem/intune` — ~520 troubleshooting articles. Outlook/Teams articles are not openly
licensed in English, so they are out of scope.

Each article maps to its public page: `support/<path>.md` →
`https://learn.microsoft.com/en-us/troubleshoot/<path>`. Articles are chunked by heading section
(not fixed character windows), keeping title + section path in each chunk.

## Components

| Module | Responsibility |
|---|---|
| `escalon.config` | Settings; `ESCALON_PROFILE=azure\|local`. Missing settings for the chosen profile are an error at startup. |
| `escalon.kb` | Parse article markdown → sections → chunks with source URL. |
| `escalon.search` | `SearchIndex` protocol. `AzureSearchIndex` (Azure AI Search, hybrid BM25 + vector) and `LocalIndex` (SQLite FTS5 + numpy vectors, fused with reciprocal rank fusion). |
| `escalon.models` | Chat + embedding clients: Azure OpenAI with Entra ID tokens, or an OpenAI-compatible local endpoint (Ollama). |
| `escalon.tickets` | `TicketSystem` protocol; `ZammadTickets` over Zammad's REST API. |
| `escalon.tools` | The three tools — `search_kb`, `find_open_tickets`, `create_ticket` — shared by the agent and the MCP server. |
| `escalon.agent` | Microsoft Agent Framework agent using the tools. |
| `escalon.mcp_server` | Remote MCP server (streamable HTTP) exposing the tools; bearer tokens validated against Entra ID. Copilot Studio connects here to put Escalon in Teams. |
| `escalon.api` | FastAPI `/chat` endpoint for the agent. |
| `evals/` | Question set + runner. |
| `infra/` | Bicep: AI Search, Azure OpenAI, Container Apps, managed identity + RBAC, Key Vault, Log Analytics. |

The profile is an explicit choice. Nothing silently falls back from Azure to local.

## Agent behaviour

1. Search the knowledge base with the user's problem.
2. If the results answer it, reply with steps and cite the article URLs used.
3. If results are weak, or the user says the fix did not work, check for an open ticket for that
   user, then create one with: summary, symptoms, steps already tried, cited articles.
4. Never invent steps that are not in a retrieved article.

## Evaluation

`evals/questions.jsonl`: ~50 questions phrased the way staff actually write ("printer says
0x0000052e when I add it"), each labelled with the expected article(s) and expected action
(`answer` or `escalate`), plus out-of-scope questions whose correct action is `escalate`.
Questions are written before tuning.

Metrics: retrieval hit@5 and MRR, action accuracy, citation precision (cited URLs were actually
retrieved), and an LLM-judged faithfulness score. Results are committed per run, failures included.

## Out of scope

Voice, a custom web UI, multi-tenant, admin actions (password resets), model training.
