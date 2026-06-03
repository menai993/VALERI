"""Shared fixtures for the tool-catalog contract tests (M9).

One package-scoped database (seed + scan → signals + tasks exist) shared by all
tool tests, plus per-role ToolContext factories. Every test runs in its own
rolled-back transaction so tools can mutate freely.
"""

import datetime
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from valeri_api.auth.models import AppUser
from valeri_api.scanner.scan import run_scan
from valeri_api.seed.users import ADMIN_EMAIL, FINANCE_EMAIL, OWNER_EMAIL
from valeri_api.tools.base import ToolContext


def _reset_app_tables(session: Session) -> None:
    session.execute(
        text(
            "TRUNCATE audit.ai_log, audit.task_log, app.task_feedback, app.approval, "
            "app.owner_report, app.tool_call_log, app.message, app.conversation, app.decision, "
            "app.task, app.signal, app.learned_rule RESTART IDENTITY CASCADE"
        )
    )


@pytest.fixture(scope="package")
def tools_db(db_engine: Engine, seed_data) -> Iterator[Engine]:
    """Seed + scan once for the whole tools test package."""
    from valeri_api.seed.loader import load, reset

    as_of = datetime.date.fromisoformat(seed_data.manifest["as_of"])
    with Session(db_engine) as session:
        _reset_app_tables(session)
        reset(session)
        load(seed_data, session)
        run_scan(session, as_of=as_of, create_tasks=True)
        session.commit()

    yield db_engine

    with Session(db_engine) as session:
        _reset_app_tables(session)
        reset(session)
        load(seed_data, session)
        session.commit()


@pytest.fixture
def tool_session(tools_db: Engine) -> Iterator[Session]:
    """A session inside a transaction that always rolls back (mutations stay local)."""
    connection = tools_db.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    try:
        yield session
    finally:
        session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()


def _user_by_email(session: Session, email: str) -> AppUser:
    user = session.query(AppUser).filter(AppUser.email == email).one()
    return user


@pytest.fixture
def owner_context(tool_session: Session) -> ToolContext:
    return ToolContext(session=tool_session, user=_user_by_email(tool_session, OWNER_EMAIL))


@pytest.fixture
def admin_context(tool_session: Session) -> ToolContext:
    return ToolContext(session=tool_session, user=_user_by_email(tool_session, ADMIN_EMAIL))


@pytest.fixture
def finance_context(tool_session: Session) -> ToolContext:
    return ToolContext(session=tool_session, user=_user_by_email(tool_session, FINANCE_EMAIL))


@pytest.fixture
def rep_context(tool_session: Session) -> ToolContext:
    """The first seeded sales rep's login."""
    rep_user = (
        tool_session.query(AppUser).filter(AppUser.role == "sales_rep").order_by(AppUser.id).first()
    )
    assert rep_user is not None, "the seed must create sales_rep logins"
    return ToolContext(session=tool_session, user=rep_user)


# ── shared assertion helpers ──────────────────────────────────────────────────


def tool_log_rows(session: Session, tool: str) -> list:
    """All tool_call_log rows for a tool, oldest first."""
    return session.execute(
        text(
            "SELECT tool, args, ok, latency_ms FROM app.tool_call_log WHERE tool = :t ORDER BY id"
        ),
        {"t": tool},
    ).all()


def rep_customer_ids(session: Session, sales_rep_id: int) -> set[int]:
    """Ground truth: the customers currently assigned to a rep (direct SQL)."""
    rows = session.execute(
        text(
            "SELECT customer_id FROM ("
            "  SELECT DISTINCT ON (customer_id) customer_id, sales_rep_id"
            "  FROM core.customer_rep ORDER BY customer_id, from_date DESC"
            ") cur WHERE sales_rep_id = :rep_id"
        ),
        {"rep_id": sales_rep_id},
    )
    return {row[0] for row in rows}
