## What and why

<!-- One or two sentences: the problem, and how this change addresses it. -->

## How it was verified

<!-- Tests added or changed, eval runs (attach the result file), manual checks. -->

## Checklist

- [ ] Conventional Commit title (`feat:`, `fix:`, `docs:`, ...)
- [ ] Tests cover the change; `uv run pytest --cov` passes
- [ ] `uv run ruff check`, `uv run ruff format --check` and `uv run mypy` pass
- [ ] docs/design.md updated if this changes a design decision
- [ ] Eval re-run and results committed if agent behaviour changed
- [ ] CHANGELOG.md updated under "Unreleased"
