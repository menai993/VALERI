# syntax=docker/dockerfile:1
#
# Targets:
#   dev   - source as-is; used by infra/docker-compose.yml (development / pilot)
#   dist  - client-distribution image: all valeri_api code compiled to native
#           binaries (Cython), no readable .py source inside (spec decision D10)
#
#   docker build --target dev  -t valeri-api:dev  .
#   docker build --target dist -t valeri-api:dist .

# ── deps: locked dependency environment via uv ───────────────────────────────
FROM python:3.12-slim AS deps
COPY --from=ghcr.io/astral-sh/uv:0.8.17 /uv /uvx /bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PATH="/app/.venv/bin:$PATH"
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# ── dev: run from source (default for compose) ───────────────────────────────
FROM deps AS dev
COPY alembic.ini docker-entrypoint.sh ./
COPY migrations/ ./migrations/
COPY valeri_api/ ./valeri_api/
RUN chmod +x docker-entrypoint.sh \
    && useradd --create-home --uid 1000 valeri \
    && chown -R valeri:valeri /app
USER valeri
EXPOSE 8000
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["uvicorn", "valeri_api.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ── dist-build: compile valeri_api to native extensions ──────────────────────
FROM deps AS dist-build
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev --group dist
COPY valeri_api/ ./valeri_api/
COPY build_ext.py ./
RUN python build_ext.py \
    && find valeri_api -name "*.py" ! -name "__init__.py" | grep -q . \
       && { echo "ERROR: readable sources remain in dist build"; exit 1; } \
       || echo "OK: valeri_api contains compiled binaries only"

# ── dist: client image — compiled binaries, no readable source ───────────────
FROM deps AS dist
COPY alembic.ini docker-entrypoint.sh ./
COPY migrations/ ./migrations/
COPY --from=dist-build /app/valeri_api/ ./valeri_api/
RUN chmod +x docker-entrypoint.sh \
    && useradd --create-home --uid 1000 valeri \
    && chown -R valeri:valeri /app
USER valeri
EXPOSE 8000
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["uvicorn", "valeri_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
