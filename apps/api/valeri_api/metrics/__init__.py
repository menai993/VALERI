"""Deterministic SQL metrics (M3) — the only place business numbers are produced.

Everything here is PostgreSQL: window functions, FILTER aggregates, SQL division.
Python only orchestrates (reads .sql files, binds :as_of, commits). No LLM is
involved in any calculation, ever (principle 1).
"""
