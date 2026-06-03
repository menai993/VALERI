# VALERI — Real-data import & pilot tuning

How to load the real Ultra Higijena export into VALERI and tune detection against
known cases before the pilot goes live. Pairs with `docs/RUNBOOK.md` (operations)
and `docs/data-model.md` (the `staging.*` → `core.*` mapping).

**Trust posture (non-negotiable):** VALERI reads a **copy/export** from the ERP.
It never connects to or writes the live ERP (Principle 4/5). The export is the only
data that moves.

---

## 1. The export contract

The ERP must produce **four files** — CSV (UTF-8) or XLSX. Column **headers must
match exactly** (they map 1:1 to `staging.*`). Extra columns are ignored; order
doesn't matter. All values are read as text and parsed by the ingest layer.

### `kupci` (customers / objects)
| Column | Meaning | Required |
|---|---|---|
| `sifra` | customer code in the ERP (natural key) | yes |
| `naziv` | customer/object name | yes |
| `jib` | legal-entity tax id (JIB/PDV) — groups objects under one legal entity | recommended |
| `naziv_pravnog_lica` | legal-entity name | recommended |
| `segment` | hotel/restoran/kafić/klinika/škola/… | recommended (drives segment logic) |
| `status` | active/inactive/closed | optional (default active) |
| `komercijalista` | assigned sales rep name | recommended (drives task assignment) |

### `artikli` (articles)
| Column | Meaning | Required |
|---|---|---|
| `sifra` | article code (natural key) | yes |
| `naziv` | article name | yes |
| `kategorija` | category name (papir/hemija/dispenzeri/…) | recommended |
| `aktivan` | active flag (da/ne, true/false, 1/0) | optional |

### `fakture` (invoice headers)
| Column | Meaning | Required |
|---|---|---|
| `broj_fakture` | invoice number (natural key — drives idempotent re-import) | yes |
| `sifra_kupca` | customer code (→ `kupci.sifra`) | yes |
| `datum` | invoice date (ISO `YYYY-MM-DD` preferred) | yes |
| `ukupno` | invoice total | yes |

### `stavke` (invoice lines)
| Column | Meaning | Required |
|---|---|---|
| `broj_fakture` | invoice number (→ `fakture.broj_fakture`) | yes |
| `sifra_artikla` | article code (→ `artikli.sifra`) | yes |
| `kolicina` | quantity | yes |
| `cijena` | unit price | yes |
| `iznos` | line total | yes |

**History depth:** export **at least 18 months** of invoices+lines. The baselines
(6-month normalized to 60 days) and the seasonal/year-over-year guards need a year
of history to work; more is better.

---

## 2. Import procedure

### Option A — API (multipart)
```sh
# one call with all four files:
curl -k -X POST https://localhost/api/ingest/import \
  -H "Authorization: Bearer <admin-token>" \
  -F kupci=@kupci.csv -F artikli=@artikli.csv \
  -F fakture=@fakture.csv -F stavke=@stavke.csv
# → {"import_id": N}
curl -k https://localhost/api/ingest/report/N    # the data-quality report
```

### Option B — CLI (files in a directory)
```sh
docker compose cp ./export valeri-api-1:/tmp/export    # files named kupci.* etc.
docker compose exec api python -m valeri_api.ingest --dir /tmp/export
```

Import is **idempotent**: re-running with the same export changes nothing (natural
keys — JIB, customer/article codes, invoice numbers). Totals are preserved to the
cent (verified by `tests/test_ingest.py`).

---

## 3. Read the data-quality report

`GET /api/ingest/report/{import_id}` returns:
- `duplicate_customer_codes` / `duplicate_article_codes` — same code, different names;
- `renamed_articles` — same code, name changed across imports;
- `code_swap_candidates` — an article retired and replaced (so lost-article detection
  doesn't false-fire on the old code);
- `missing_segments` — customers with no segment (segment logic will skip them);
- `orphan_lines` — invoice lines whose invoice/article code didn't resolve.

**Fix at the source** (the ERP export) where possible, then re-import. Orphan lines
and missing segments directly reduce detection quality — clear them first.

---

## 4. Pilot tuning checklist

Do this **with the owner present** — they hold the ground truth.

- [ ] **Import** the real export (above); confirm the import succeeds.
- [ ] **Verify totals to the cent.** Pick 5 customers; compare VALERI's 60-day
      turnover (Kupci → customer 360) against the ERP. Must match exactly.
      _If not: a parsing/mapping issue — fix before going further._
- [ ] **Clear the quality report.** No orphan lines; segments filled for active
      customers; code-swaps confirmed.
- [ ] **Recompute + scan:**
      ```sh
      docker compose exec api python -c "import datetime; \
      from valeri_api.scanner.scan import run_scan; from valeri_api.db import get_engine; \
      from sqlalchemy.orm import Session; s=Session(get_engine()); \
      run_scan(s, as_of=datetime.date.today()); s.commit()"
      ```
- [ ] **Label 10–15 known cases with the owner.** For each, write down the truth:
      - declining customers the owner already knows about → should fire;
      - seasonal customers (e.g. summer-only cafés) → should **not** fire;
      - genuinely lost articles → should fire; code-swaps → should **not**;
      - sleeping customers the owner agrees are dormant → should fire.
- [ ] **Compare** VALERI's signals (AI Report, Kupci-at-risk, Artikli lost) to the
      labels. Record hits / misses / false-fires.
- [ ] **Tune thresholds** in **Postavke → Pragovi detekcije** to resolve mismatches:
      - too many false declines → raise `customer_decline.decline_ratio_threshold`;
      - missed real declines → lower it;
      - seasonal false-fires → check the seasonal-guard params;
      - lost-article noise → adjust the gap thresholds.
      Every change is logged as a reversible `app.decision`.
- [ ] **Re-scan and re-compare** until the labeled cases pass at the agreed accuracy.
      Detection thresholds living in `app.rule_config` means this loop touches no code.
- [ ] **Spot-check Bosnian narration** on a few tasks (M6 quality gate). If phrasing
      is weak on Haiku, route narration to Sonnet in Postavke → AI model (cost-aware).
- [ ] **Confirm the weekly schedule** is running (worker logs show the daily scan +
      Sunday cycle).
- [ ] **Create the real users** (Postavke → Korisnici) and rotate off the dev
      password (RUNBOOK §5).

When the labeled cases pass and the team can see their real business in the
dashboard, the pilot is live. Track acceptance items 8 (useless-task share) and the
voluntary-usage gate over the following weeks — see `docs/ACCEPTANCE-REPORT.md`.
