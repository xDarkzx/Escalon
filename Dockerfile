# syntax=docker/dockerfile:1.7

FROM python:3.11.9-slim-bookworm AS build
COPY --from=ghcr.io/astral-sh/uv:0.10.10 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# Dependencies first so code changes don't invalidate this layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY README.md ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

FROM python:3.11.9-slim-bookworm AS runtime
RUN useradd --system --uid 10001 --no-create-home escalon
COPY --from=build --chown=escalon /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER escalon
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"]
ENTRYPOINT ["escalon", "serve", "--host", "0.0.0.0", "--port", "8000"]
