/**
 * CSV templates for the 4 ERP export files (data-ingest-ui). Exact headers the
 * ingest pipeline expects (apps/api/.../ingest/staging.py), with one sample row.
 * Semicolon-delimited, UTF-8 — matches the auto-detected reader.
 */
import type { IngestFileKey } from "@/lib/api/types"

export const INGEST_TEMPLATES: Record<IngestFileKey, string> = {
  kupci:
    "sifra;naziv;jib;naziv_pravnog_lica;segment;status;komercijalista\n" +
    "K-001;Hotel Primjer — recepcija;4200000000001;Hotel Primjer d.o.o.;hotel;active;Amila Amilić\n",
  artikli:
    "sifra;naziv;kategorija;aktivan\n" +
    "A-001;Tečni sapun 5L;hemija;da\n",
  fakture:
    "broj_fakture;sifra_kupca;datum;ukupno\n" +
    "F-2026-0001;K-001;2026-05-20;1250.00\n",
  stavke:
    "broj_fakture;sifra_artikla;kolicina;cijena;iznos\n" +
    "F-2026-0001;A-001;10;125.00;1250.00\n",
}

/** Trigger a browser download of one template CSV. */
export function downloadTemplate(key: IngestFileKey): void {
  const blob = new Blob([INGEST_TEMPLATES[key]], { type: "text/csv;charset=utf-8" })
  const url = URL.createObjectURL(blob)
  const link = document.createElement("a")
  link.href = url
  link.download = `${key}.csv`
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}
