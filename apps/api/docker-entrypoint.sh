#!/bin/sh
# Apply database migrations, then exec the container command (uvicorn).
# The worker service overrides this entrypoint in docker-compose.yml so that
# only the api container runs migrations.
set -e

echo "Applying database migrations..."
alembic upgrade head

exec "$@"
