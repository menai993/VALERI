"""M3 semantic-layer tests: registry validation + query builder discipline.

The semantic layer is the only sanctioned way for later layers (tools, NL→SQL)
to run metric queries: registered metrics only, validated bind params only.
"""

import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from tests.fixtures import metrics_fixture as fx

API_SRC = Path(__file__).resolve().parent.parent / "valeri_api"


# ── registry ─────────────────────────────────────────────────────────────────


def test_registry_loads_and_validates() -> None:
    """registry.yaml parses; every metric has descriptions, entity, grain, valid params."""
    from valeri_api.semantic.registry import load_registry

    registry = load_registry()
    assert len(registry) >= 8, "expected at least the 8 M3 metrics"

    for name, definition in registry.items():
        assert definition.description_bs, f"{name}: missing Bosnian description"
        assert definition.description_en, f"{name}: missing English description"
        assert definition.entity in {"customer", "article", "segment", "company"}
        assert definition.grain in {"scalar", "row", "series"}
        assert definition.sql.strip(), f"{name}: empty SQL"
        # Every declared param appears in the SQL as a bind placeholder.
        for param in definition.params:
            assert f":{param.name}" in definition.sql, f"{name}: param {param.name} not in SQL"


def test_unknown_metric_rejected() -> None:
    from valeri_api.semantic.query_builder import MetricValidationError, build_metric_query

    with pytest.raises(MetricValidationError):
        build_metric_query("nepostojeca_metrika", {})


def test_param_validation() -> None:
    from valeri_api.semantic.query_builder import MetricValidationError, build_metric_query

    # Missing required param.
    with pytest.raises(MetricValidationError):
        build_metric_query("customer_turnover_60d", {})

    # Unknown param.
    with pytest.raises(MetricValidationError):
        build_metric_query("customer_turnover_60d", {"customer_id": 1, "hacker": "x"})

    # Wrong type.
    with pytest.raises(MetricValidationError):
        build_metric_query("customer_turnover_60d", {"customer_id": "not-a-number"})


# ── execution against the golden fixture ────────────────────────────────────


@pytest.fixture(scope="module")
def golden_semantic_db(db_engine: Engine, seed_data):
    """Golden fixture + recompute, for semantic-layer execution tests."""
    from valeri_api.metrics.recompute import recompute_all
    from valeri_api.seed.loader import load, reset

    with Session(db_engine) as session:
        fx.load_fixture(session)
        recompute_all(session, as_of=fx.AS_OF)
        session.commit()

    yield db_engine

    with Session(db_engine) as session:
        reset(session)
        load(seed_data, session)
        session.commit()


def test_metric_results_equal_direct_sql(golden_semantic_db: Engine) -> None:
    """run_metric results equal the hand-computed golden values to the cent."""
    from valeri_api.semantic.query_builder import run_metric

    with Session(golden_semantic_db) as session:
        # Stored metric (reads core.customer_metrics).
        stored = run_metric(session, "customer_turnover_60d", {"customer_id": 1})
        assert stored.scalar() == Decimal("400.00")

        # Ad-hoc turnover over the whole company in the 60d window.
        window_start = fx.AS_OF - datetime.timedelta(days=60)
        total = run_metric(
            session, "turnover", {"from_date": window_start, "to_date": fx.AS_OF}
        )
        assert total.scalar() == fx.EXPECTED_TOTAL_TURNOVER_60D

        # Ad-hoc turnover filtered to one customer equals its stored 60d turnover.
        c2 = run_metric(
            session,
            "turnover",
            {"from_date": window_start, "to_date": fx.AS_OF, "customer_id": 2},
        )
        assert c2.scalar() == Decimal("122.00")


def test_bind_params_only(golden_semantic_db: Engine) -> None:
    """Malicious string values are bound, never interpolated; loader rejects f-string SQL."""
    from valeri_api.semantic.query_builder import run_metric
    from valeri_api.semantic.registry import MetricDefinition, MetricParam

    # 1. A hostile segment value executes safely (bound, matches nothing).
    with Session(golden_semantic_db) as session:
        window_start = fx.AS_OF - datetime.timedelta(days=60)
        result = run_metric(
            session,
            "turnover",
            {
                "from_date": window_start,
                "to_date": fx.AS_OF,
                "segment": "'; DROP TABLE core.invoice;--",
            },
        )
        assert result.scalar() == Decimal("0")

    # The invoice table survived.
    with golden_semantic_db.connect() as conn:
        from sqlalchemy import text

        count = conn.execute(text("SELECT COUNT(*) FROM core.invoice")).scalar()
        assert count == len(fx.INVOICES)

    # 2. The registry model rejects SQL with string-interpolation placeholders.
    with pytest.raises(ValueError):
        MetricDefinition(
            name="zlonamjerna",
            description_bs="x",
            description_en="x",
            entity="company",
            grain="scalar",
            params=[MetricParam(name="x", type="string", required=True)],
            sql="SELECT * FROM core.invoice WHERE id = %s",
        )
    with pytest.raises(ValueError):
        MetricDefinition(
            name="zlonamjerna2",
            description_bs="x",
            description_en="x",
            entity="company",
            grain="scalar",
            params=[],
            sql="SELECT * FROM core.invoice WHERE id = {value}",
        )


def test_llm_not_involved() -> None:
    """Static check: metrics/ and semantic/ import nothing LLM- or network-related."""
    forbidden = ("anthropic", "litellm", "openai", "httpx", "requests", "valeri_api.llm")

    for package in ("metrics", "semantic"):
        package_dir = API_SRC / package
        assert package_dir.is_dir(), f"{package_dir} missing"
        for source_file in package_dir.rglob("*.py"):
            content = source_file.read_text(encoding="utf-8")
            for module in forbidden:
                assert f"import {module}" not in content, f"{source_file}: imports {module}"
                assert f"from {module}" not in content, f"{source_file}: imports from {module}"
