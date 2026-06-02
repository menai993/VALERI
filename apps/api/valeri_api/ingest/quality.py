"""Data-quality report: 5 SQL checks over staging (this run) + core.

Runs BEFORE the upsert so renames and swaps are still visible as diffs
(spec m2-ingest, decision D4). Every value comes from SQL — no LLM anywhere.
"""

from sqlalchemy import text
from sqlalchemy.orm import Session

from valeri_api.ingest.schemas import (
    CodeSwapCandidate,
    DuplicateCode,
    MissingSegment,
    OrphanLine,
    QualityReport,
    RenamedArticle,
)


def build_quality_report(session: Session, run_id: int) -> QualityReport:
    return QualityReport(
        duplicate_customer_codes=_duplicate_codes(session, run_id, "kupci"),
        duplicate_article_codes=_duplicate_codes(session, run_id, "artikli"),
        renamed_articles=_renamed_articles(session, run_id),
        code_swap_candidates=_code_swap_candidates(session, run_id),
        missing_segments=_missing_segments(session, run_id),
        orphan_lines=_orphan_lines(session, run_id),
    )


def _duplicate_codes(session: Session, run_id: int, table: str) -> list[DuplicateCode]:
    """Codes that appear more than once with different names within this export."""
    rows = session.execute(
        text(
            f"SELECT sifra, ARRAY_AGG(DISTINCT naziv ORDER BY naziv) AS names "  # noqa: S608
            f"FROM staging.{table} WHERE import_run_id = :run AND sifra IS NOT NULL "
            f"GROUP BY sifra HAVING COUNT(DISTINCT naziv) > 1"
        ),
        {"run": run_id},
    ).all()
    return [DuplicateCode(code=row.sifra, names=list(row.names)) for row in rows]


def _renamed_articles(session: Session, run_id: int) -> list[RenamedArticle]:
    """Articles whose name in the export differs from the name currently in core."""
    rows = session.execute(
        text(
            "SELECT s.sifra, a.name AS old_name, s.naziv AS new_name "
            "FROM staging.artikli s "
            "JOIN core.article a ON a.code = s.sifra "
            "WHERE s.import_run_id = :run AND s.naziv IS NOT NULL AND s.naziv <> a.name"
        ),
        {"run": run_id},
    ).all()
    return [
        RenamedArticle(code=row.sifra, old_name=row.old_name, new_name=row.new_name) for row in rows
    ]


def _code_swap_candidates(session: Session, run_id: int) -> list[CodeSwapCandidate]:
    """Pairs of articles in this export with the same name where the old code is retired
    (inactive) and the new code took over its activity. Data-driven — no thresholds."""
    rows = session.execute(
        text("""
            WITH activity AS (
              SELECT s.sifra_artikla AS sifra,
                     MIN(f.datum) AS first_seen,
                     MAX(f.datum) AS last_seen
              FROM staging.stavke s
              JOIN staging.fakture f
                ON f.broj_fakture = s.broj_fakture AND f.import_run_id = s.import_run_id
              WHERE s.import_run_id = :run
              GROUP BY s.sifra_artikla
            )
            SELECT stari.sifra AS old_code,
                   novi.sifra  AS new_code,
                   stari.naziv AS name,
                   (alias.old_code IS NOT NULL) AS already_mapped
            FROM staging.artikli stari
            JOIN staging.artikli novi
              ON novi.naziv = stari.naziv
             AND novi.sifra <> stari.sifra
             AND novi.import_run_id = stari.import_run_id
            LEFT JOIN activity stara_akt ON stara_akt.sifra = stari.sifra
            LEFT JOIN activity nova_akt ON nova_akt.sifra = novi.sifra
            LEFT JOIN core.article_alias alias ON alias.old_code = stari.sifra
            WHERE stari.import_run_id = :run
              AND LOWER(COALESCE(stari.aktivan, '')) IN ('ne', 'false', '0', 'no')
              AND LOWER(COALESCE(novi.aktivan, '')) IN ('da', 'true', '1', 'yes')
              AND (stara_akt.last_seen IS NULL
                   OR nova_akt.first_seen IS NULL
                   OR stara_akt.last_seen <= nova_akt.last_seen)
            ORDER BY stari.sifra
            """),
        {"run": run_id},
    ).all()
    return [
        CodeSwapCandidate(
            old_code=row.old_code,
            new_code=row.new_code,
            name=row.name,
            already_mapped=row.already_mapped,
        )
        for row in rows
    ]


def _missing_segments(session: Session, run_id: int) -> list[MissingSegment]:
    """Customers in the export without a segment."""
    rows = session.execute(
        text(
            "SELECT sifra, naziv FROM staging.kupci "
            "WHERE import_run_id = :run AND (segment IS NULL OR segment = '')"
        ),
        {"run": run_id},
    ).all()
    return [MissingSegment(customer_code=row.sifra, name=row.naziv or "") for row in rows]


def _orphan_lines(session: Session, run_id: int) -> list[OrphanLine]:
    """Lines referencing an invoice or article that exists neither in the export nor in core."""
    unknown_invoice = session.execute(
        text(
            "SELECT s.row_no, s.broj_fakture, s.sifra_artikla "
            "FROM staging.stavke s "
            "LEFT JOIN staging.fakture f "
            "  ON f.broj_fakture = s.broj_fakture AND f.import_run_id = s.import_run_id "
            "WHERE s.import_run_id = :run AND f.id IS NULL"
        ),
        {"run": run_id},
    ).all()

    unknown_article = session.execute(
        text(
            "SELECT s.row_no, s.broj_fakture, s.sifra_artikla "
            "FROM staging.stavke s "
            "LEFT JOIN staging.artikli a "
            "  ON a.sifra = s.sifra_artikla AND a.import_run_id = s.import_run_id "
            "LEFT JOIN core.article ca ON ca.code = s.sifra_artikla "
            "LEFT JOIN core.article_alias al ON al.old_code = s.sifra_artikla "
            "WHERE s.import_run_id = :run "
            "  AND a.id IS NULL AND ca.id IS NULL AND al.old_code IS NULL"
        ),
        {"run": run_id},
    ).all()

    orphans = [
        OrphanLine(
            row_no=row.row_no,
            broj_fakture=row.broj_fakture,
            sifra_artikla=row.sifra_artikla,
            reason="unknown_invoice",
        )
        for row in unknown_invoice
    ]
    orphans.extend(
        OrphanLine(
            row_no=row.row_no,
            broj_fakture=row.broj_fakture,
            sifra_artikla=row.sifra_artikla,
            reason="unknown_article",
        )
        for row in unknown_article
    )
    return sorted(orphans, key=lambda orphan: orphan.row_no)
