"""CSA: the capability catalog reflects the registry + tools, RBAC-filtered.

Pure unit tests (no DB): list_capabilities reads the semantic registry and the
tool catalog, so newly registered metrics appear automatically.
"""

from valeri_api.semantic.capabilities import list_capabilities


def _metric_names(role: str) -> set[str]:
    return {c.name for c in list_capabilities(role) if c.kind == "metric"}


def _tool_names(role: str) -> set[str]:
    return {c.name for c in list_capabilities(role) if c.kind == "tool"}


def test_owner_sees_the_new_csa_metrics() -> None:
    metrics = _metric_names("owner")
    assert {"top_articles", "category_sales", "top_customers", "article_catalog"} <= metrics
    # The originals are still there too.
    assert {"turnover", "turnover_by_month", "customer_turnover_60d"} <= metrics


def test_hidden_meta_tools_not_listed_as_capabilities() -> None:
    tools = _tool_names("owner")
    # query_metric is surfaced via its metrics; describe_capabilities is meta.
    assert "query_metric" not in tools
    assert "describe_capabilities" not in tools
    # Real action/lookup tools are present.
    assert "list_signals" in tools


def test_rep_only_sees_customer_scopable_metrics() -> None:
    """A sales_rep cannot run company/segment-wide metrics (finance data, D2)."""
    rep_metrics = _metric_names("sales_rep")
    # Customer-scoped metrics are visible.
    assert "customer_turnover_60d" in rep_metrics
    # Pure company/segment-wide rankings are hidden (no customer_id param).
    assert "top_articles" not in rep_metrics
    assert "category_sales" not in rep_metrics
    assert "top_customers" not in rep_metrics


def test_descriptions_are_present_and_nonempty() -> None:
    for cap in list_capabilities("owner"):
        assert cap.description.strip(), f"capability {cap.name} has no description"
