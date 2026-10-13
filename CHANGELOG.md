# Changelog

All notable changes are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Contribution guide, security policy, issue and pull request templates, Dependabot.
- Conventional Commit messages enforced by a commit-msg hook.

## [0.1.0] - 2026-10-14

### Added

- Agent on Microsoft Agent Framework with `search_kb`, `find_open_tickets` and `create_ticket`
  tools, served both as `/api/chat` and as a remote MCP server for Copilot Studio.
- Hybrid search (BM25 + vectors, reciprocal rank fusion) over 647 Microsoft troubleshooting
  articles: Azure AI Search, or SQLite FTS5 + numpy locally.
- Zammad ticketing, verified against a live Zammad 7.2.
- Entra ID token validation; ticket owner taken from the token.
- Guards against invented tickets and broken links.
- Evaluation: 50 labelled questions, retrieval and action-accuracy metrics, `escalon report`.
- Bicep infrastructure (keyless), container image, CI with lint, types, coverage, dependency
  audit, secret scanning, Bicep and Dockerfile checks.
