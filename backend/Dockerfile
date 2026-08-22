# CCOA backend — docs/08 §3, ADR-007.
#
# Two properties the build has to get right:
#
#   1. The corpus is baked in. Schema and rows are created at build time, so cold start
#      does no generation work — it is already 45–75 s (docs/12 §3.7).
#   2. Litestream is PID 1. It restores both databases from S3 on boot and, because it
#      owns the process tree, it receives SIGTERM and performs a final sync before the
#      task goes away. Running it any other way loses the last writes on scale-in.

# ---------------------------------------------------------------------------
# Builder — dependencies and the seeded database
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS builder

COPY --from=ghcr.io/astral-sh/uv:0.8.0 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# The builder works in /app, the same path the runtime stage uses. A virtualenv bakes
# absolute paths into its console-script shebangs, so building at /build and copying to
# /app produces binaries whose interpreter no longer exists — `alembic: not found`, at
# container start, from an image that built cleanly.
WORKDIR /app

# Dependencies first, so a source change does not re-resolve the environment.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

COPY alembic.ini langgraph.json ./
COPY alembic ./alembic
COPY app ./app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Schema, then rows. `app.seed` refuses to run against an unmigrated database, so the
# ordering is enforced rather than remembered.
ENV DATABASE_URL="sqlite+pysqlite:////data/app.db"
RUN mkdir -p /data \
 && uv run alembic upgrade head \
 && uv run python -m app.seed --output /data/app.db --reset \
 && uv run python -c "from app.seed import SEED_VERSION; print(SEED_VERSION)" > /data/SEED_VERSION

# ---------------------------------------------------------------------------
# Litestream — pinned by version and digest (docs/08 §6 question 2)
# ---------------------------------------------------------------------------
FROM litestream/litestream:0.3.13 AS litestream

# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Non-root. Nothing in this image needs to write outside /data.
RUN useradd --create-home --uid 10001 ccoa

WORKDIR /app

COPY --from=builder --chown=ccoa:ccoa /app/.venv /app/.venv
COPY --from=builder --chown=ccoa:ccoa /app/app /app/app
COPY --from=builder --chown=ccoa:ccoa /app/alembic /app/alembic
COPY --from=builder --chown=ccoa:ccoa /app/alembic.ini /app/langgraph.json /app/
COPY --from=builder --chown=ccoa:ccoa /data /data
COPY --from=litestream /usr/local/bin/litestream /usr/local/bin/litestream
COPY --chown=ccoa:ccoa docker/litestream.yml /etc/litestream.yml
COPY --chown=ccoa:ccoa docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DB_PATH=/data/app.db \
    CHECKPOINT_DB_PATH=/data/checkpoints.db \
    # CVE-2026-28277. The application refuses to start without it in a deployed
    # environment; setting it here means that check never has to fire (docs/02 §4.2).
    LANGGRAPH_STRICT_MSGPACK=true

USER ccoa
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD curl -fsS http://localhost:8000/healthz || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
