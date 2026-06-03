"""Detection rules (M4).

Each rule is deterministic SQL over the metric/core tables: it computes its
candidates, evidence values, and confidence score inside PostgreSQL, and emits
app.signal rows. Thresholds live in app.rule_config — never in code. The LLM
plays no part in detection.
"""
