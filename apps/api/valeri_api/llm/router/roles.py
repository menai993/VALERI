"""Task roles + tier ordering (M12).

A role describes WHAT an LLM call does; the router maps roles to tiers. The
mapping itself lives in app.rule_config (rule='llm_router') — these constants are
the vocabulary and the fallback defaults the migration seeds, never the source of
truth at runtime.
"""

# ── roles (one per kind of LLM work in the codebase) ──────────────────────────

ROLE_NARRATION = "narration"  # task bodies (M6, scan pipeline)
ROLE_INTENT = "intent"  # chat intent classification (M9)
ROLE_SIMPLE_QA = "simple_qa"  # chat answers over tool output (M9)
ROLE_NL_RULE = "nl_rule"  # dismissal/feedback → rule proposal (M10)
ROLE_REPORT_NARRATION = "report_narration"  # weekly report sections (M7)
ROLE_CUSTOMER_DRAFT = "customer_draft"  # approval-gated message drafts (M7)
ROLE_OVER_SUPPRESSION_AUDIT = "over_suppression_audit"  # the M11 auditor
ROLE_INVESTIGATION = "investigation"  # M13 (registered now, used then)
ROLE_INVESTIGATION_SYNTHESIS = "investigation_synthesis"  # M13 hardest cases
ROLE_KB_GATE = "kb_gate"  # CI1 relevance gate (skip greetings/pure questions)
ROLE_KB_EXTRACTION = "kb_extraction"  # CI1 structured knowledge extraction
ROLE_KB_SUMMARY = "kb_summary"  # CI1 client-profile summary narration

# ── tiers, cheapest → strongest (cascade walks this list upward) ──────────────

TIER_ORDER = ["tier1", "tier2", "tier2_strong"]

# Fallback defaults (the migration seeds these into rule_config; runtime reads the DB).
DEFAULT_ROLE_TIERS = {
    ROLE_NARRATION: "tier1",
    ROLE_INTENT: "tier1",
    ROLE_SIMPLE_QA: "tier1",
    ROLE_NL_RULE: "tier1",
    ROLE_REPORT_NARRATION: "tier1",
    ROLE_CUSTOMER_DRAFT: "tier1",
    ROLE_OVER_SUPPRESSION_AUDIT: "tier2",
    ROLE_INVESTIGATION: "tier2",
    ROLE_INVESTIGATION_SYNTHESIS: "tier2_strong",
    ROLE_KB_GATE: "tier1",
    ROLE_KB_EXTRACTION: "tier1",
    ROLE_KB_SUMMARY: "tier1",
}

# An unknown role routes to the cheapest tier — fail cheap, never fail expensive.
FALLBACK_TIER = "tier1"
