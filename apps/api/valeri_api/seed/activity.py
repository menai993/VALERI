"""Demo rep activities + monthly revenue targets for the seed (C-CRM2).

Deterministic (driven by the seed RNG) so the Aktivnosti komercijalista widget, the
revenue-vs-plan forecast, and the owner-report sections all see stable data, and the
tests have fixtures. Activities land in the month of `as_of` (so the dashboard's
month rollup picks them up); targets cover the months around `as_of`.
"""

import datetime
from decimal import Decimal
from random import Random

from valeri_api.crm.probability import ACTIVITY_KINDS


def generate_activities(
    rng: Random, sales_reps: list[dict], customers: list[dict], as_of: datetime.date
) -> list[dict]:
    """~40 activities across reps/kinds in the month of as_of; ~60% marked done."""
    activities: list[dict] = []
    activity_id = 1
    for _ in range(40):
        rep = rng.choice(sales_reps)
        customer = rng.choice(customers)
        # A day within the current month, on or before as_of.
        day = rng.randint(1, as_of.day)
        at = datetime.datetime(
            as_of.year, as_of.month, day, rng.randint(8, 17), 0, tzinfo=datetime.UTC
        )
        activities.append(
            {
                "id": activity_id,
                "sales_rep_id": rep["id"],
                "customer_id": customer["id"],
                "kind": rng.choice(ACTIVITY_KINDS),
                "done": rng.random() < 0.6,
                "at": at,
            }
        )
        activity_id += 1
    return activities


def generate_revenue_targets(rng: Random, as_of: datetime.date) -> list[dict]:
    """Monthly company targets for the 6 months ending at as_of's month."""
    targets: list[dict] = []
    year, month = as_of.year, as_of.month
    for offset in range(6):
        m = month - offset
        y = year
        while m <= 0:
            m += 12
            y -= 1
        period = f"{y:04d}-{m:02d}"
        # A plausible monthly plan with a little variation (deterministic).
        amount = Decimal("120000.00") + Decimal(rng.randint(-15, 15) * 1000)
        targets.append({"period": period, "target_amount": amount})
    return targets
