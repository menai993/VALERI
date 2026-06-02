"""Seed configuration: volumes, segment profiles, planted-case parameters.

These are synthetic-data generation parameters (test fixture configuration),
not business rule thresholds — business thresholds live in app.rule_config
from M4 onward.
"""

import datetime
from dataclasses import dataclass, field


@dataclass(frozen=True)
class SegmentProfile:
    """How customers of a segment buy: which categories, how much, how often."""

    categories: tuple[str, ...]
    basket_size: tuple[int, int]  # (min, max) number of articles in the basket
    cadence_days: tuple[int, int]  # (min, max) days between orders
    qty_scale: float  # multiplier on typical quantities


SEGMENT_PROFILES: dict[str, SegmentProfile] = {
    "hotel": SegmentProfile(
        categories=(
            "papir",
            "hemija",
            "dispenzeri",
            "rukavice",
            "kozmetika",
            "tekstil",
            "oprema",
        ),
        basket_size=(14, 22),
        cadence_days=(7, 14),
        qty_scale=2.0,
    ),
    "restoran": SegmentProfile(
        categories=("papir", "hemija", "rukavice", "dispenzeri", "oprema"),
        basket_size=(9, 16),
        cadence_days=(7, 14),
        qty_scale=1.2,
    ),
    "kafić": SegmentProfile(
        categories=("papir", "hemija", "dispenzeri"),
        basket_size=(6, 10),
        cadence_days=(10, 21),
        qty_scale=0.8,
    ),
    "klinika": SegmentProfile(
        categories=("rukavice", "hemija", "papir", "dispenzeri", "kozmetika"),
        basket_size=(10, 16),
        cadence_days=(14, 21),
        qty_scale=1.0,
    ),
    "škola": SegmentProfile(
        categories=("papir", "hemija", "dispenzeri", "oprema"),
        basket_size=(8, 13),
        cadence_days=(14, 28),
        qty_scale=1.5,
    ),
}

# Months in which planted seasonal cafés do weak business (repeat every year).
SEASONAL_LOW_MONTHS: frozenset[int] = frozenset({4, 5, 6, 7, 8, 9})


@dataclass(frozen=True)
class SeedConfig:
    """All knobs of the deterministic seed."""

    rng_seed: int = 20260601
    as_of: datetime.date = field(default_factory=datetime.date.today)
    history_days: int = 547  # ~18 months

    # Volumes
    n_hotel_groups: int = 5
    n_restoran: int = 20
    n_kafic: int = 18
    n_klinika: int = 13
    n_skola: int = 16
    n_reps: int = 4

    # Planted case counts (17 total)
    n_declines: int = 3
    n_seasonal_cafes: int = 2
    n_lost_articles: int = 4
    n_code_swaps: int = 2
    n_narrow_baskets: int = 3
    n_sleeping: int = 3

    # Planted case parameters
    decline_window_days: int = 60  # the drop happens in the last N days
    decline_qty_factor: float = 0.5  # quantity multiplier inside the drop window
    seasonal_low_factor: float = 0.45  # low-season quantity multiplier (every year)
    seasonal_cadence_days: int = 10  # fixed cadence for seasonal cafés (low variance)
    lost_article_gap_days: int = 100  # article disappears this many days before as_of
    code_swap_days_before: int = 120  # code swap happens this many days before as_of
    sleeping_gap_days: int = 100  # sleeping customers stop ordering this long before as_of
