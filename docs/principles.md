# VALERI — Principles (`docs/principles.md`)

1. AI does not compute financial numbers — SQL/Python computes, the AI interprets.
2. Every AI task carries evidence from the database.
3. Every AI conclusion carries a confidence score.
4. No writes to the source ERP without explicit approval.
5. Read-only / export / staging access in phase one.
6. PII masking before AI processing.
7. AI log + task log + decision log are mandatory and append-only.
8. The feedback loop is a core function, not an add-on.
9. Distinguish analysis / recommendation / action; nothing happens silently.
10. Human approval for every external customer communication; self-configuration is an internal action and may auto-apply only if reversible and recorded as a visible decision.
