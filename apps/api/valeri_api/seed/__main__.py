"""Seed CLI: generate and load the synthetic Ultra Higijena dataset.

Usage (from apps/api):
    python -m valeri_api.seed [--as-of YYYY-MM-DD] [--rng-seed N] [--reset]
                              [--manifest-out PATH]
"""

import argparse
import datetime
import json
import sys
from pathlib import Path

from sqlalchemy.orm import Session

from valeri_api.db import get_engine
from valeri_api.seed.config import SeedConfig
from valeri_api.seed.generate import generate
from valeri_api.seed.loader import load, reset


def _default_manifest_path() -> Path | None:
    """db/seed/planted_cases.json at the repo root, if the repo layout is present.

    Returns None when running outside the repo (e.g. inside a container image
    without the db/ tree); the manifest is then skipped unless --manifest-out
    is given.
    """
    repo_root = Path(__file__).resolve().parents[4]
    db_dir = repo_root / "db"
    return db_dir / "seed" / "planted_cases.json" if db_dir.is_dir() else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m valeri_api.seed",
        description="Generate and load the deterministic VALERI synthetic seed.",
    )
    parser.add_argument(
        "--as-of",
        type=datetime.date.fromisoformat,
        default=None,
        help="reference date for the data (default: today)",
    )
    parser.add_argument("--rng-seed", type=int, default=20260601, help="RNG seed")
    parser.add_argument(
        "--reset", action="store_true", help="truncate core.* tables before loading"
    )
    parser.add_argument(
        "--manifest-out",
        type=Path,
        default=None,
        help="where to write the planted-cases manifest (default: db/seed/planted_cases.json)",
    )
    args = parser.parse_args(argv)

    config = SeedConfig(rng_seed=args.rng_seed, as_of=args.as_of or datetime.date.today())
    print(f"Generating seed (rng_seed={config.rng_seed}, as_of={config.as_of}) ...")
    data = generate(config)

    engine = get_engine()
    with Session(engine) as session:
        if args.reset:
            reset(session)
        load(data, session)
        session.commit()

    manifest_path = args.manifest_out or _default_manifest_path()
    if manifest_path is not None:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(data.manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"Planted-cases manifest written to {manifest_path}")
    else:
        print("Repo db/ directory not found - manifest skipped (use --manifest-out to force).")

    print(
        f"Loaded: {len(data.legal_entities)} legal entities, {len(data.customers)} customers, "
        f"{len(data.articles)} articles, {len(data.invoices)} invoices, "
        f"{len(data.invoice_lines)} lines."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
