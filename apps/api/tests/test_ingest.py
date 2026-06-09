"""M2 ingest tests: idempotent import, totals to the cent, data-quality report.

These are trust-critical: the import path is how real company data enters
VALERI, so every number must round-trip exactly and re-imports must never
duplicate or corrupt anything.
"""

import csv
import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

DELIMITER = ";"


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def export_dir(tmp_path_factory: pytest.TempPathFactory, seed_data) -> Path:
    """The seed written as an ERP-style export (the M2 acceptance input)."""
    from valeri_api.seed.export import write_export_csvs

    out_dir = tmp_path_factory.mktemp("uh-export")
    write_export_csvs(seed_data, out_dir)
    return out_dir


def _restore_m1_seed(engine: Engine, seed_data) -> None:
    """Restore the M1-loaded seed so later test modules see the canonical state."""
    from valeri_api.seed.loader import load, reset

    with Session(engine) as session:
        reset(session)
        load(seed_data, session)
        session.commit()


@pytest.fixture(scope="module")
def fresh_import_db(db_engine: Engine, export_dir: Path, seed_data):
    """Empty core, then import the export once. Yields (engine, import_run_id).

    Teardown restores the M1 seed so other test modules are unaffected.
    """
    from valeri_api.ingest.pipeline import run_import
    from valeri_api.seed.loader import reset

    with Session(db_engine) as session:
        reset(session)
        session.commit()

    with Session(db_engine) as session:
        run = run_import(session, _export_files(export_dir), source="test-fresh")
        session.commit()
        run_id = run.id

    yield db_engine, run_id

    _restore_m1_seed(db_engine, seed_data)


def _export_files(directory: Path) -> dict[str, Path]:
    return {
        "kupci": directory / "kupci.csv",
        "artikli": directory / "artikli.csv",
        "fakture": directory / "fakture.csv",
        "stavke": directory / "stavke.csv",
    }


def _seed_sums(seed_data) -> tuple[Decimal, Decimal]:
    invoice_sum = sum((i["total"] for i in seed_data.invoices), Decimal("0"))
    line_sum = sum((line["line_total"] for line in seed_data.invoice_lines), Decimal("0"))
    return invoice_sum, line_sum


def _core_counts_and_sums(engine: Engine) -> dict:
    with engine.connect() as conn:
        return {
            "customers": conn.execute(text("SELECT COUNT(*) FROM core.customer")).scalar(),
            "articles": conn.execute(text("SELECT COUNT(*) FROM core.article")).scalar(),
            "invoices": conn.execute(text("SELECT COUNT(*) FROM core.invoice")).scalar(),
            "lines": conn.execute(text("SELECT COUNT(*) FROM core.invoice_line")).scalar(),
            "invoice_sum": conn.execute(
                text("SELECT COALESCE(SUM(total), 0) FROM core.invoice")
            ).scalar(),
            "line_sum": conn.execute(
                text("SELECT COALESCE(SUM(line_total), 0) FROM core.invoice_line")
            ).scalar(),
            "sample_invoice_ids": [
                row[0]
                for row in conn.execute(
                    text("SELECT id FROM core.invoice ORDER BY external_no LIMIT 5")
                )
            ],
        }


def _get_report(engine: Engine, run_id: int) -> dict:
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT status, stats, report FROM staging.import_run WHERE id = :id"),
            {"id": run_id},
        ).one()
    return {"status": row[0], "stats": row[1], "quality": row[2]}


# ── tests: fresh import ──────────────────────────────────────────────────────


def test_fresh_import_populates_core_to_the_cent(fresh_import_db, seed_data) -> None:
    """A fresh import recreates the business graph with totals exact to the cent."""
    engine, run_id = fresh_import_db
    state = _core_counts_and_sums(engine)
    invoice_sum, line_sum = _seed_sums(seed_data)

    assert state["customers"] == len(seed_data.customers)
    assert state["articles"] == len(seed_data.articles)
    assert state["invoices"] == len(seed_data.invoices)
    assert state["lines"] == len(seed_data.invoice_lines)
    assert state["invoice_sum"] == invoice_sum, "invoice totals not preserved to the cent"
    assert state["line_sum"] == line_sum, "line totals not preserved to the cent"

    # A sampled invoice matches exactly.
    sample = seed_data.invoices[len(seed_data.invoices) // 2]
    with engine.connect() as conn:
        imported_total = conn.execute(
            text("SELECT total FROM core.invoice WHERE external_no = :no"),
            {"no": sample["external_no"]},
        ).scalar()
    assert imported_total == sample["total"]

    report = _get_report(engine, run_id)
    assert report["status"] == "completed"
    assert report["stats"]["fakture"]["created"] == len(seed_data.invoices)


def test_reimport_is_idempotent(fresh_import_db, export_dir: Path, seed_data) -> None:
    """Importing the same export again changes nothing: same counts, sums, and IDs."""
    from valeri_api.ingest.pipeline import run_import

    engine, _ = fresh_import_db
    before = _core_counts_and_sums(engine)

    with Session(engine) as session:
        rerun = run_import(session, _export_files(export_dir), source="test-reimport")
        session.commit()
        rerun_id = rerun.id

    after = _core_counts_and_sums(engine)
    assert after == before, "re-import changed core data"

    report = _get_report(engine, rerun_id)
    stats = report["stats"]
    assert stats["kupci"]["created"] == 0
    assert stats["artikli"]["created"] == 0
    assert stats["fakture"]["created"] == 0
    assert stats["fakture"]["updated"] == 0
    assert stats["fakture"]["unchanged"] == len(seed_data.invoices)
    assert stats["stavke"]["replaced"] == 0


def test_import_over_seeded_data_is_idempotent(db_engine: Engine, export_dir: Path, seed_data):
    """Importing the export over the M1-loaded seed creates nothing (natural keys match)."""
    from valeri_api.ingest.pipeline import run_import
    from valeri_api.seed.loader import load, reset

    # Load the M1 seed (with external_no now part of the seed).
    with Session(db_engine) as session:
        reset(session)
        load(seed_data, session)
        session.commit()

    before = _core_counts_and_sums(db_engine)

    with Session(db_engine) as session:
        run = run_import(session, _export_files(export_dir), source="test-over-seed")
        session.commit()
        run_id = run.id

    after = _core_counts_and_sums(db_engine)
    assert after == before, "import over seeded data changed core data"

    stats = _get_report(db_engine, run_id)["stats"]
    assert stats["kupci"]["created"] == 0
    assert stats["artikli"]["created"] == 0
    assert stats["fakture"]["created"] == 0


# ── tests: data-quality report ───────────────────────────────────────────────


def test_report_detects_code_swap_candidates(fresh_import_db, seed_data) -> None:
    """The report flags both planted code swaps (old/new code pairs from the manifest)."""
    engine, run_id = fresh_import_db
    quality = _get_report(engine, run_id)["quality"]

    found_pairs = {
        (candidate["old_code"], candidate["new_code"])
        for candidate in quality["code_swap_candidates"]
    }
    planted_pairs = {
        (swap["old_code"], swap["new_code"]) for swap in seed_data.manifest["code_swaps"]
    }
    assert (
        planted_pairs <= found_pairs
    ), f"planted swaps {planted_pairs} not all detected; found {found_pairs}"


def test_report_detects_renamed_article(
    db_engine: Engine, export_dir: Path, tmp_path: Path, seed_data
) -> None:
    """Renaming an article in the export between imports is flagged and applied."""
    from valeri_api.ingest.pipeline import run_import
    from valeri_api.seed.loader import reset

    # Fresh import of the original export.
    with Session(db_engine) as session:
        reset(session)
        session.commit()
    with Session(db_engine) as session:
        run_import(session, _export_files(export_dir), source="test-rename-1")
        session.commit()

    # Copy the export and rename one article (a non-planted one).
    renamed_dir = tmp_path / "renamed-export"
    renamed_dir.mkdir()
    swap_old_codes = {s["old_code"] for s in seed_data.manifest["code_swaps"]}
    swap_new_codes = {s["new_code"] for s in seed_data.manifest["code_swaps"]}

    target_code = None
    old_name = None
    new_name = "Toaletni papir PREMIUM 4-sl 10/1 (novo pakovanje)"

    for name in ("kupci.csv", "artikli.csv", "fakture.csv", "stavke.csv"):
        source_path = export_dir / name
        if name != "artikli.csv":
            (renamed_dir / name).write_text(source_path.read_text(encoding="utf-8"), "utf-8")
            continue

        with source_path.open(encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle, delimiter=DELIMITER))
        for row in rows:
            if row["sifra"] not in swap_old_codes | swap_new_codes and row["aktivan"] == "da":
                target_code = row["sifra"]
                old_name = row["naziv"]
                row["naziv"] = new_name
                break
        with (renamed_dir / name).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=["sifra", "naziv", "kategorija", "aktivan"], delimiter=DELIMITER
            )
            writer.writeheader()
            writer.writerows(rows)

    assert target_code is not None

    # Re-import the modified export.
    with Session(db_engine) as session:
        rerun = run_import(session, _export_files(renamed_dir), source="test-rename-2")
        session.commit()
        rerun_id = rerun.id

    quality = _get_report(db_engine, rerun_id)["quality"]
    renamed = {
        (item["code"], item["old_name"], item["new_name"]) for item in quality["renamed_articles"]
    }
    assert (target_code, old_name, new_name) in renamed

    # The rename is applied to core (core mirrors the source ERP).
    with db_engine.connect() as conn:
        core_name = conn.execute(
            text("SELECT name FROM core.article WHERE code = :code"), {"code": target_code}
        ).scalar()
    assert core_name == new_name

    _restore_m1_seed(db_engine, seed_data)


def test_report_flags_dupes_missing_segments_orphans(
    db_engine: Engine, tmp_path: Path, seed_data
) -> None:
    """Handcrafted bad export: duplicate codes, missing segment, orphan lines all flagged."""
    from valeri_api.ingest.pipeline import run_import
    from valeri_api.seed.loader import reset

    bad_dir = tmp_path / "bad-export"
    bad_dir.mkdir()

    (bad_dir / "kupci.csv").write_text(
        "sifra;naziv;jib;naziv_pravnog_lica;segment;status;komercijalista\n"
        "K-001;Hotel Test;9900000000001;Hotel Test d.o.o.;hotel;active;Test Rep\n"
        "K-002;Kafić Bez Segmenta;9900000000002;Kafić Bez Segmenta d.o.o.;;active;Test Rep\n",
        encoding="utf-8",
    )
    (bad_dir / "artikli.csv").write_text(
        "sifra;naziv;kategorija;aktivan\n"
        "A-001;Artikal Jedan;papir;da\n"
        "A-001;Artikal Jedan Drugo Ime;papir;da\n"
        "A-002;Artikal Dva;hemija;da\n",
        encoding="utf-8",
    )
    (bad_dir / "fakture.csv").write_text(
        "broj_fakture;sifra_kupca;datum;ukupno\nRN-001;K-001;2026-01-15;100.00\n",
        encoding="utf-8",
    )
    (bad_dir / "stavke.csv").write_text(
        "broj_fakture;sifra_artikla;kolicina;cijena;iznos\n"
        "RN-001;A-001;2.000;25.0000;50.00\n"
        "RN-001;A-002;2.000;25.0000;50.00\n"
        "RN-999;A-001;1.000;10.0000;10.00\n"  # orphan: unknown invoice
        "RN-001;A-999;1.000;10.0000;10.00\n",  # orphan: unknown article
        encoding="utf-8",
    )

    with Session(db_engine) as session:
        reset(session)
        session.commit()
    with Session(db_engine) as session:
        run = run_import(session, _export_files(bad_dir), source="test-bad")
        session.commit()
        run_id = run.id

    quality = _get_report(db_engine, run_id)["quality"]

    dupes = {d["code"] for d in quality["duplicate_article_codes"]}
    assert "A-001" in dupes

    missing = {m["customer_code"] for m in quality["missing_segments"]}
    assert "K-002" in missing

    orphan_reasons = {(o["broj_fakture"], o["reason"]) for o in quality["orphan_lines"]}
    assert ("RN-999", "unknown_invoice") in orphan_reasons
    assert ("RN-001", "unknown_article") in orphan_reasons

    _restore_m1_seed(db_engine, seed_data)


# ── tests: traceability, CLI, Excel ──────────────────────────────────────────


def test_staging_keeps_raw_rows(fresh_import_db, seed_data) -> None:
    """Every imported raw row is kept in staging, tagged with its import run."""
    engine, run_id = fresh_import_db
    with engine.connect() as conn:
        for table, expected in (
            ("kupci", len(seed_data.customers)),
            ("artikli", len(seed_data.articles)),
            ("fakture", len(seed_data.invoices)),
            ("stavke", len(seed_data.invoice_lines)),
        ):
            count = conn.execute(
                text(
                    f"SELECT COUNT(*) FROM staging.{table} WHERE import_run_id = :run"
                ),  # noqa: S608
                {"run": run_id},
            ).scalar()
            assert count == expected, f"staging.{table}: {count} != {expected}"


def test_cli_import(db_engine: Engine, export_dir: Path, seed_data, capsys) -> None:
    """python -m valeri_api.ingest <dir> runs the pipeline and prints a summary."""
    from valeri_api.ingest.__main__ import main
    from valeri_api.seed.loader import reset

    with Session(db_engine) as session:
        reset(session)
        session.commit()

    exit_code = main([str(export_dir)])
    assert exit_code == 0

    output = capsys.readouterr().out
    assert "import" in output.lower()

    state = _core_counts_and_sums(db_engine)
    assert state["customers"] == len(seed_data.customers)
    assert state["invoices"] == len(seed_data.invoices)

    _restore_m1_seed(db_engine, seed_data)


def test_excel_import(db_engine: Engine, export_dir: Path, tmp_path: Path, seed_data) -> None:
    """An .xlsx file imports identically to its CSV counterpart."""
    import openpyxl

    from valeri_api.ingest.pipeline import run_import
    from valeri_api.seed.loader import reset

    # Convert artikli.csv to artikli.xlsx; keep the rest as CSV.
    mixed_dir = tmp_path / "mixed-export"
    mixed_dir.mkdir()
    for name in ("kupci.csv", "fakture.csv", "stavke.csv"):
        (mixed_dir / name).write_text((export_dir / name).read_text("utf-8"), "utf-8")

    with (export_dir / "artikli.csv").open(encoding="utf-8") as handle:
        rows = list(csv.reader(handle, delimiter=DELIMITER))
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    workbook.save(mixed_dir / "artikli.xlsx")

    files = _export_files(mixed_dir)
    files["artikli"] = mixed_dir / "artikli.xlsx"

    with Session(db_engine) as session:
        reset(session)
        session.commit()
    with Session(db_engine) as session:
        run_import(session, files, source="test-excel")
        session.commit()

    state = _core_counts_and_sums(db_engine)
    assert state["articles"] == len(seed_data.articles)
    assert state["invoices"] == len(seed_data.invoices)

    _restore_m1_seed(db_engine, seed_data)


# ── tests: API ───────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_api_import_and_report_endpoints(
    db_engine: Engine, export_dir: Path, seed_data, monkeypatch
) -> None:
    """POST /api/ingest/import (multipart) → import_id; GET report → stats+quality; 404 handled."""
    import httpx
    from sqlalchemy import insert

    from valeri_api.auth.models import AppUser
    from valeri_api.seed.loader import reset
    from valeri_api.seed.users import ADMIN_EMAIL

    with Session(db_engine) as session:
        reset(session)
        # M8: the import API is admin-gated — keep the non-rep logins available
        # (rep logins need core.sales_rep rows, which an empty import DB lacks).
        session.execute(
            insert(AppUser),
            [user for user in seed_data.app_users if user["sales_rep_id"] is None],
        )
        session.commit()

    from tests.conftest import login
    from valeri_api.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await login(client, ADMIN_EMAIL)
        files = {
            name: (f"{name}.csv", (export_dir / f"{name}.csv").read_bytes(), "text/csv")
            for name in ("kupci", "artikli", "fakture", "stavke")
        }
        response = await client.post("/api/ingest/import", files=files, timeout=120)
        assert response.status_code == 201, response.text
        import_id = response.json()["import_id"]

        report_response = await client.get(f"/api/ingest/report/{import_id}")
        assert report_response.status_code == 200
        report = report_response.json()
        assert report["status"] == "completed"
        assert report["stats"]["fakture"]["created"] == len(seed_data.invoices)
        assert "code_swap_candidates" in report["quality"]

        missing = await client.get("/api/ingest/report/999999")
        assert missing.status_code == 404
        assert "error" in missing.json()

    _restore_m1_seed(db_engine, seed_data)


def test_dates_and_money_round_trip_exactly(fresh_import_db, seed_data) -> None:
    """Spot-check: dates and Decimal money survive the CSV round trip exactly."""
    engine, _ = fresh_import_db
    sample_line = seed_data.invoice_lines[len(seed_data.invoice_lines) // 3]
    invoice = next(i for i in seed_data.invoices if i["id"] == sample_line["invoice_id"])

    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT l.qty, l.unit_price, l.line_total, i.date "
                "FROM core.invoice_line l "
                "JOIN core.invoice i ON i.id = l.invoice_id "
                "JOIN core.article a ON a.id = l.article_id "
                "WHERE i.external_no = :no AND a.code = :code"
            ),
            {
                "no": invoice["external_no"],
                "code": next(
                    a["code"] for a in seed_data.articles if a["id"] == sample_line["article_id"]
                ),
            },
        ).first()

    assert row is not None
    qty, unit_price, line_total, invoice_date = row
    assert qty == sample_line["qty"]
    assert unit_price == sample_line["unit_price"]
    assert line_total == sample_line["line_total"]
    assert invoice_date == invoice["date"]
    assert isinstance(line_total, Decimal)
    assert isinstance(invoice_date, datetime.date)


# ── data-ingest-ui: import history list endpoint (admin only) ─────────────────


@pytest.mark.anyio
async def test_list_imports_admin_only(seeded_db) -> None:
    """GET /api/ingest/imports is admin-only (owner/finance/rep → 403)."""
    from tests.conftest import login, make_client
    from valeri_api.seed.users import ADMIN_EMAIL, OWNER_EMAIL

    owner = make_client()
    try:
        await login(owner, OWNER_EMAIL)
        assert (await owner.get("/api/ingest/imports")).status_code == 403
    finally:
        await owner.aclose()

    admin = make_client()
    try:
        await login(admin, ADMIN_EMAIL)
        assert (await admin.get("/api/ingest/imports")).status_code == 200
    finally:
        await admin.aclose()


@pytest.mark.anyio
async def test_list_imports_returns_run_after_import(seeded_db, export_dir: Path) -> None:
    """After an API import, the run appears in the history with status + counts."""
    from tests.conftest import login, make_client
    from valeri_api.seed.users import ADMIN_EMAIL

    admin = make_client()
    try:
        await login(admin, ADMIN_EMAIL)
        files = _export_files(export_dir)
        upload = await admin.post(
            "/api/ingest/import",
            files={name: (f"{name}.csv", path.read_bytes(), "text/csv") for name, path in files.items()},
        )
        assert upload.status_code == 201, upload.text
        import_id = upload.json()["import_id"]

        listing = await admin.get("/api/ingest/imports")
        assert listing.status_code == 200
        items = listing.json()["items"]
        run = next((r for r in items if r["import_id"] == import_id), None)
        assert run is not None
        assert run["status"] == "completed"
        assert run["stats"] is not None
    finally:
        await admin.aclose()
