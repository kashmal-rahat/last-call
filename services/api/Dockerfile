FROM python:3.12-slim

# Install uv for deterministic, lockfile-reproducible builds
COPY --from=ghcr.io/astral-sh/uv:0.6.5 /uv /uvx /bin/

ARG GIT_COMMIT=dev
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    GIT_COMMIT=${GIT_COMMIT}

WORKDIR /app

# Create unprivileged user
RUN useradd -m -u 1000 appuser

# Copy workspace metadata, lockfile, and package directories
COPY pyproject.toml uv.lock ./
COPY shared/ ./shared/
COPY services/api/ ./services/api/

# Sync exact frozen dependencies from uv.lock for lastcall-api
RUN uv sync --frozen --no-dev --package lastcall-api

WORKDIR /app/services/api

ENV PORT=8080 \
    PATH="/app/.venv/bin:$PATH"

EXPOSE 8080

USER appuser

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT} --no-access-log"]
