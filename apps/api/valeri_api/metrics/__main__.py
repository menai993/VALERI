"""Metrics CLI: recompute the derived metric tables.

Usage (from apps/api):
    python -m valeri_api.metrics [--as-of YYYY-MM-DD]
"""

import argparse
import datetime
import sys

from sqlalchemy.orm import Session

from valeri_api.db import get_engine
from valeri_api.metrics.recompute import recompute_all


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m valeri_api.metrics",
        description="Recompute core.customer_metrics, cust_article_cadence, segment_basket.",
    )
    parser.add_argument(
        "--as-of",
        type=datetime.date.fromisoformat,
        default=None,
        help="reference date for the metric windows (default: today)",
    )
    args = parser.parse_args(argv)

    engine = get_engine()
    with Session(engine) as session:
        result = recompute_all(session, as_of=args.as_of)
        session.commit()

    print(f"Metrics recomputed as of {result.as_of}:")
    for table, count in result.rows.items():
        print(f"  {table}: {count} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
