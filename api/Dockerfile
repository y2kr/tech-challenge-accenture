FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.3 /uv /uvx /bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app/src"

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY alembic.ini ./
COPY migrations ./migrations
COPY src ./src

CMD ["sh", "-c", "alembic upgrade head && exec uvicorn monitor.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
