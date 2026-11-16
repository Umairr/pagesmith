# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PAGESMITH_RUNS_DIR=/data/runs

COPY --from=ghcr.io/astral-sh/uv:0.8.17 /uv /usr/local/bin/uv

WORKDIR /app

# Dependencies first, so code changes do not bust the layer cache.
COPY pyproject.toml uv.lock .python-version README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY briefs ./briefs
RUN uv sync --frozen --no-dev

RUN useradd --create-home --uid 1000 app && mkdir -p /data/runs && chown -R app /data /app
USER app

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')" || exit 1

CMD ["sh", "-c", "pagesmith serve --host 0.0.0.0 --port ${PORT:-8000}"]
