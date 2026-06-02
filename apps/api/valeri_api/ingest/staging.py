"""Load raw export rows into staging.* (kept per import run for traceability)."""

from sqlalchemy import insert
from sqlalchemy.orm import Session

from valeri_api.ingest.models import (
    ImportRun,
    StagingArtikal,
    StagingFaktura,
    StagingKupac,
    StagingStavka,
)

# export file name → (staging model, accepted payload columns)
STAGING_TABLES = {
    "kupci": (
        StagingKupac,
        ("sifra", "naziv", "jib", "naziv_pravnog_lica", "segment", "status", "komercijalista"),
    ),
    "artikli": (StagingArtikal, ("sifra", "naziv", "kategorija", "aktivan")),
    "fakture": (StagingFaktura, ("broj_fakture", "sifra_kupca", "datum", "ukupno")),
    "stavke": (StagingStavka, ("broj_fakture", "sifra_artikla", "kolicina", "cijena", "iznos")),
}


def create_import_run(session: Session, source: str) -> ImportRun:
    """Open a new import run (status=running)."""
    run = ImportRun(source=source, status="running")
    session.add(run)
    session.flush()  # assign run.id
    return run


def load_to_staging(
    session: Session, run_id: int, tables: dict[str, list[dict[str, str]]]
) -> dict[str, int]:
    """Bulk-insert raw rows into the staging tables, tagged with the run id."""
    counts: dict[str, int] = {}
    for name, rows in tables.items():
        model, columns = STAGING_TABLES[name]
        staged = [
            {
                "import_run_id": run_id,
                "row_no": row_no,
                **{column: row.get(column) or None for column in columns},
            }
            for row_no, row in enumerate(rows, start=1)
        ]
        if staged:
            session.execute(insert(model), staged)
        counts[name] = len(staged)
    return counts
