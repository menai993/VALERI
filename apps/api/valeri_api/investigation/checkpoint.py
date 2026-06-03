"""LangGraph Postgres checkpointing (M13).

The checkpointer lives in the same on-prem Postgres as everything else; its
tables (checkpoints, checkpoint_blobs, checkpoint_writes, checkpoint_migrations)
are created by LangGraph's own setup() on first use — per the data-model.md note,
they are not Alembic-managed.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from langgraph.checkpoint.postgres import PostgresSaver

from valeri_api.config import get_settings


def _raw_dsn() -> str:
    """The psycopg DSN LangGraph expects (no SQLAlchemy driver prefix)."""
    return get_settings().database_url.replace("postgresql+psycopg://", "postgresql://")


@contextmanager
def open_checkpointer() -> Iterator[PostgresSaver]:
    """A ready-to-use Postgres checkpointer (tables created on first use)."""
    with PostgresSaver.from_conn_string(_raw_dsn()) as saver:
        saver.setup()  # idempotent
        yield saver
