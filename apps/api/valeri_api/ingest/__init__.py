"""Read-only ERP import path (M2).

CSV/Excel export → staging.* (raw rows, kept per run) → idempotent upsert to
core.* by natural keys → data-quality report. The source system is never
written to; VALERI only reads export files.
"""
