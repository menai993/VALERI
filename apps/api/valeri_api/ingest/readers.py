"""File readers: CSV (auto-detected delimiter) and Excel (.xlsx) → raw row dicts.

Everything is read as text; parsing/validation happens in the upsert step.
"""

import csv
from pathlib import Path


def read_table(path: Path) -> list[dict[str, str]]:
    """Read an export file into a list of {column: value} dicts (all values text)."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return _read_csv(path)
    if suffix in (".xlsx", ".xlsm"):
        return _read_xlsx(path)
    raise ValueError(f"Unsupported file type: {path.name} (expected .csv or .xlsx)")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        sample = handle.read(4096)
        handle.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=";,")
        except csv.Error:
            dialect = csv.excel  # default to comma
        reader = csv.DictReader(handle, dialect=dialect)
        return [{key: (value or "").strip() for key, value in row.items()} for row in reader]


def _read_xlsx(path: Path) -> list[dict[str, str]]:
    import openpyxl

    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = workbook.active
        rows_iter = sheet.iter_rows(values_only=True)
        headers = [str(cell).strip() if cell is not None else "" for cell in next(rows_iter)]
        rows: list[dict[str, str]] = []
        for raw_row in rows_iter:
            if all(cell is None for cell in raw_row):
                continue
            rows.append(
                {
                    header: (str(cell).strip() if cell is not None else "")
                    for header, cell in zip(headers, raw_row, strict=False)
                }
            )
        return rows
    finally:
        workbook.close()
