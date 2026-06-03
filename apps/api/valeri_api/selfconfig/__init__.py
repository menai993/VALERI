"""Self-configuration (M10): dismissal + reason → reversible learned rule.

The LLM only STRUCTURES the rule change (scope, description, confidence); whether
it applies is decided by deterministic code over app.rule_config thresholds, the
blast radius comes from SQL, and every application is an append-only reversible
app.decision.
"""
