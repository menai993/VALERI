"""Alembic environment — wired to the application settings and metadata."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

import valeri_api.approvals.models  # noqa: F401  (registers app.approval)
import valeri_api.audit.models  # noqa: F401  (registers audit.* models)
import valeri_api.domain.models  # noqa: F401  (registers core.* models on Base.metadata)
import valeri_api.ingest.models  # noqa: F401  (registers staging.* models)
import valeri_api.reports.models  # noqa: F401  (registers app.owner_report)
import valeri_api.rules.models  # noqa: F401  (registers app.* detection models)
import valeri_api.signals.models  # noqa: F401  (registers app.task* models)
from valeri_api.config import get_settings
from valeri_api.db import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL to stdout)."""
    context.configure(
        url=get_settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against the configured database."""
    engine = create_engine(get_settings().database_url, poolclass=pool.NullPool)

    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()

    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
