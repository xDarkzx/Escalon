# Contributing

## Setup

```bash
uv sync                      # Python 3.11, all dependencies from the lockfile
uv run pre-commit install    # pre-commit and commit-msg hooks
cp .env.local.example .env
```

## Workflow

1. Branch from `main`: `feat/<short-name>`, `fix/<short-name>`, `docs/<short-name>`.
2. Make one logical change per pull request. If a change alters a design decision, update
   [docs/design.md](docs/design.md) in the same pull request.
3. Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/)
   (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `perf:`, `build:`, `ci:`, `chore:`, and
   `eval:` for changes to evaluation data or results). The commit-msg hook enforces this.
4. Open a pull request using the template. CI must pass before merging; `main` is protected and
   only accepts squash merges.

## Quality gates

These run on every commit (pre-commit) and every pull request (CI). None of them may be skipped
or weakened in a pull request without a written reason in the pull request description.

| Gate | Command |
|---|---|
| Lint, including security rules | `uv run ruff check src tests` |
| Formatting | `uv run ruff format --check src tests` |
| Types | `uv run mypy` (strict) |
| Tests, coverage at least 85% | `uv run pytest --cov` |
| Known-vulnerable dependencies | `uv export --no-emit-project --format requirements-txt > r.txt && uvx pip-audit -r r.txt --strict --disable-pip` |
| Secrets | gitleaks (pre-commit and CI) |
| Infrastructure and container | `az bicep lint --file infra/main.bicep`, hadolint, image smoke test (CI) |

## Evaluation changes

The questions and labels in `evals/questions.jsonl` are ground truth. A label may only change
to match the labelling rules in [evals/README.md](evals/README.md), never to match model
output, and every change is listed there with its reason. Results are committed alongside the
code that produced them.

## Tests

- Unit tests must not touch the network or a model server. Use the fakes in `tests/`.
- Tests that need live services are marked `@pytest.mark.integration` and skipped unless the
  service is configured (`uv run pytest -m integration`).
