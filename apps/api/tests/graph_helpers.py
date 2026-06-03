"""Shared inserts for the CI2 graph-rule tests (run on a rolled-back db_session)."""

import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session


def add_customer(session: Session, name: str, segment: str = "hotel") -> int:
    le_id = session.execute(
        text("INSERT INTO core.legal_entity (name) VALUES (:n) RETURNING id"),
        {"n": f"{name} d.o.o."},
    ).scalar_one()
    return session.execute(
        text(
            "INSERT INTO core.customer (legal_entity_id, name, segment) "
            "VALUES (:le, :n, :seg) RETURNING id"
        ),
        {"le": le_id, "n": name, "seg": segment},
    ).scalar_one()


def add_metrics(
    session: Session,
    customer_id: int,
    *,
    turnover_60d: float,
    baseline_60d: float,
    last_order: datetime.date | None = None,
    interval_d: float | None = None,
) -> None:
    session.execute(
        text(
            "INSERT INTO core.customer_metrics "
            "(customer_id, turnover_60d, turnover_6m_avg_60d, last_order_date, "
            " avg_order_interval_d) "
            "VALUES (:cid, :t, :b, :lo, :iv)"
        ),
        {
            "cid": customer_id,
            "t": turnover_60d,
            "b": baseline_60d,
            "lo": last_order,
            "iv": interval_d,
        },
    )


def add_expectation(
    session: Session,
    customer_id: int,
    *,
    interval_d: float | None = None,
    gap_days: int | None = None,
    stretch_ratio: float | None = None,
    early_decline: bool = False,
) -> None:
    session.execute(
        text(
            "INSERT INTO core.client_expectation "
            "(customer_id, expected_interval_d, gap_days, stretch_ratio, early_decline) "
            "VALUES (:cid, :iv, :gap, :sr, :ed)"
        ),
        {
            "cid": customer_id,
            "iv": interval_d,
            "gap": gap_days,
            "sr": stretch_ratio,
            "ed": early_decline,
        },
    )


def add_edge(
    session: Session,
    from_id: int,
    to_id: int,
    rel_type: str,
    *,
    status: str = "active",
    confidence: float = 0.9,
) -> None:
    session.execute(
        text(
            "INSERT INTO app.client_relationship "
            "(from_customer_id, to_customer_id, rel_type, source, confidence, conf_band, status) "
            "VALUES (:f, :t, :rt, 'stated', :conf, 'visoka', :status)"
        ),
        {"f": from_id, "t": to_id, "rt": rel_type, "conf": confidence, "status": status},
    )
