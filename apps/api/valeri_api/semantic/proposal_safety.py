"""Safety validation for self-proposed metric SQL (CSA Phase 3).

A proposed metric is INERT until a human approves it; this gate is what makes
that approval safe. We accept ONLY a single read-only SELECT over allow-listed
schemas, expressed with bind parameters (never string interpolation), and we
EXPLAIN it against the DB to prove it is valid and touches only permitted
relations. Anything else is rejected with a Bosnian reason. The LLM never
executes SQL — it drafts a candidate; this module is the wall it must pass.
"""

import re

from sqlalchemy import text
from sqlalchemy.orm import Session

# Read-only access is permitted to these schemas only (never staging/pg_catalog/etc.).
_ALLOWED_SCHEMAS = frozenset({"core", "app"})

# Write/DDL/admin/side-effecting keywords that must never appear in a metric.
_FORBIDDEN_KEYWORDS = re.compile(
    r"\b(insert|update|delete|drop|alter|truncate|create|grant|revoke|comment|copy|merge|"
    r"call|do|vacuum|analyze|reindex|cluster|lock|into|nextval|setval|pg_sleep|dblink|"
    r"pg_read_file|lo_import|lo_export)\b",
    re.IGNORECASE,
)
# Interpolation tokens (mirror registry.py: bind params only, never f-string/% formatting).
_INTERP_TOKENS = ("%s", "%(", "{", "}")
_COMMENT_TOKENS = ("--", "/*", "*/")
_BIND_RE = re.compile(r":([a-zA-Z_][a-zA-Z0-9_]*)")
# Every relation must be schema-qualified (schema.table) after FROM/JOIN.
_TABLE_REF_RE = re.compile(r"\b(?:from|join)\s+([a-zA-Z_]\w*)\.([a-zA-Z_]\w*)", re.IGNORECASE)
# PII guard (Principle 6): self-proposed metrics must never read personal PII.
# core.contact is entirely PII; customer identity must be returned as customer_id,
# never name/email/phone/address (the app masks/rehydrates by id downstream).
_PII_TABLES = frozenset({"contact"})
_PII_COLUMNS = re.compile(r"\b(email|phone|address|telefon|adresa|e_?mail)\b", re.IGNORECASE)
# A bare FROM/JOIN target that is NOT schema-qualified (caught and rejected).
_UNQUALIFIED_REF_RE = re.compile(r"\b(?:from|join)\s+([a-zA-Z_]\w*)(?!\s*\.)", re.IGNORECASE)


class UnsafeMetricSQL(Exception):
    """The proposed metric SQL failed a safety check; carries Bosnian reasons."""

    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons


def validate_metric_sql(
    sql: str, declared_params: set[str], *, session: Session | None = None
) -> None:
    """Raise UnsafeMetricSQL unless `sql` is a safe, read-only, bind-param SELECT.

    Static checks always run; when a `session` is given, the query is also
    EXPLAINed (read-only — never EXPLAIN ANALYZE) to confirm it is valid and
    references only existing, allow-listed relations.
    """
    reasons: list[str] = []
    stripped = sql.strip()
    body = stripped.rstrip(";").strip()

    if ";" in body:
        reasons.append("SQL mora biti tačno jedna naredba (bez ';').")
    if not re.match(r"(?is)^\s*select\b", body):
        reasons.append("Dozvoljen je isključivo SELECT upit (bez WITH/DDL/DML).")
    for token in _INTERP_TOKENS:
        if token in sql:
            reasons.append(f"Zabranjen token za interpolaciju {token!r} — koristi :parametar.")
    for token in _COMMENT_TOKENS:
        if token in sql:
            reasons.append(f"Komentari nisu dozvoljeni u SQL-u metrike ({token!r}).")

    forbidden = {m.group(0).lower() for m in _FORBIDDEN_KEYWORDS.finditer(body)}
    if forbidden:
        reasons.append("Zabranjene ključne riječi: " + ", ".join(sorted(forbidden)) + ".")

    refs = _TABLE_REF_RE.findall(body)
    qualified_targets = {m.start() for m in _TABLE_REF_RE.finditer(body)}
    unqualified = [
        m.group(1) for m in _UNQUALIFIED_REF_RE.finditer(body) if m.start() not in qualified_targets
    ]
    if unqualified:
        reasons.append(
            "Svaka tabela mora biti navedena kao schema.tabela (npr. core.invoice); "
            "neispravno: " + ", ".join(sorted(set(unqualified))) + "."
        )
    elif not refs:
        reasons.append("Upit mora čitati bar jednu tabelu (schema.tabela).")
    for schema, table in refs:
        if schema.lower() not in _ALLOWED_SCHEMAS:
            reasons.append(f"Nedozvoljena šema: {schema} (dozvoljeno: core, app).")
        if table.lower() in _PII_TABLES:
            reasons.append(f"PII tabela nije dozvoljena u metrici: {schema}.{table}.")
    if _PII_COLUMNS.search(body):
        reasons.append(
            "PII kolone (email/telefon/adresa) nisu dozvoljene — vrati identitet kupca "
            "isključivo kao customer_id."
        )

    used = set(_BIND_RE.findall(sql))
    undeclared = used - declared_params
    if undeclared:
        reasons.append("Korišteni nedeklarisani parametri: " + ", ".join(sorted(undeclared)) + ".")

    if reasons:
        raise UnsafeMetricSQL(reasons)

    if session is not None:
        binds = {param: None for param in declared_params}
        # Probe inside a SAVEPOINT: a failing EXPLAIN aborts only the nested
        # transaction, leaving the caller's session usable (approve continues).
        savepoint = session.begin_nested()
        try:
            session.execute(text(f"EXPLAIN {body}"), binds)  # plan only — never ANALYZE
        except Exception as error:  # noqa: BLE001 — any planner error means the SQL is unusable
            savepoint.rollback()
            raise UnsafeMetricSQL(
                [f"Upit nije valjan (EXPLAIN nije uspio): {error.__class__.__name__}"]
            ) from error
        savepoint.rollback()  # EXPLAIN was validation only — discard it
