"""Write the seed as an ERP-style export (the input format the M2 ingest reads).

Four files with Bosnian headers, ';' delimiter, UTF-8, external codes only —
internal database IDs never appear in an export. Contact PII is deliberately
not exported (spec m2-ingest, decision D2).
"""

import csv
from pathlib import Path

from valeri_api.seed.articles import CATEGORY_ORDER
from valeri_api.seed.types import SeedData

DELIMITER = ";"

KUPCI_HEADERS = [
    "sifra",
    "naziv",
    "jib",
    "naziv_pravnog_lica",
    "segment",
    "status",
    "komercijalista",
]
ARTIKLI_HEADERS = ["sifra", "naziv", "kategorija", "aktivan"]
FAKTURE_HEADERS = ["broj_fakture", "sifra_kupca", "datum", "ukupno"]
STAVKE_HEADERS = ["broj_fakture", "sifra_artikla", "kolicina", "cijena", "iznos"]


def _write_csv(path: Path, headers: list[str], rows: list[list]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter=DELIMITER)
        writer.writerow(headers)
        writer.writerows(rows)
    return path


def write_export_csvs(data: SeedData, out_dir: Path) -> list[Path]:
    """Write kupci.csv, artikli.csv, fakture.csv, stavke.csv into out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)

    entity_by_id = {e["id"]: e for e in data.legal_entities}
    rep_by_id = {r["id"]: r for r in data.sales_reps}
    rep_by_customer = {a["customer_id"]: rep_by_id[a["sales_rep_id"]] for a in data.customer_reps}
    category_name_by_id = {i + 1: name for i, name in enumerate(CATEGORY_ORDER)}
    customer_code_by_id = {c["id"]: c["external_code"] for c in data.customers}
    article_code_by_id = {a["id"]: a["code"] for a in data.articles}
    invoice_by_id = {i["id"]: i for i in data.invoices}

    kupci_rows = [
        [
            c["external_code"],
            c["name"],
            entity_by_id[c["legal_entity_id"]]["tax_id"],
            entity_by_id[c["legal_entity_id"]]["name"],
            c["segment"] or "",
            c["status"],
            rep_by_customer[c["id"]]["name"],
        ]
        for c in data.customers
    ]

    artikli_rows = [
        [
            a["code"],
            a["name"],
            category_name_by_id[a["category_id"]],
            "da" if a["active"] else "ne",
        ]
        for a in data.articles
    ]

    fakture_rows = [
        [
            i["external_no"],
            customer_code_by_id[i["customer_id"]],
            i["date"].isoformat(),
            str(i["total"]),
        ]
        for i in data.invoices
    ]

    stavke_rows = [
        [
            invoice_by_id[line["invoice_id"]]["external_no"],
            article_code_by_id[line["article_id"]],
            str(line["qty"]),
            str(line["unit_price"]),
            str(line["line_total"]),
        ]
        for line in data.invoice_lines
    ]

    return [
        _write_csv(out_dir / "kupci.csv", KUPCI_HEADERS, kupci_rows),
        _write_csv(out_dir / "artikli.csv", ARTIKLI_HEADERS, artikli_rows),
        _write_csv(out_dir / "fakture.csv", FAKTURE_HEADERS, fakture_rows),
        _write_csv(out_dir / "stavke.csv", STAVKE_HEADERS, stavke_rows),
    ]
