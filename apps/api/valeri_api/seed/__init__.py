"""Deterministic synthetic seed resembling Ultra Higijena (M1).

Generates the core.* business graph: legal entities, customers, contacts,
reps, categories, articles, and ~18 months of cadence-based invoices, with
17 planted cases that later milestones must detect (or must NOT flag).
Everything is deterministic given (rng_seed, as_of).
"""
