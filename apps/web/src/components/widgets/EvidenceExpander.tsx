/**
 * EvidenceExpander (ui-design §4): "Prikaži brojke" → reveals the SQL evidence
 * rows (tabular numerals) + the "brojke iz baze · SQL" footer.
 * Required one tap away on every AI surface (principle 2).
 */
import { useState } from "react"
import { ChevronDown, ChevronUp } from "lucide-react"

import { useT } from "@/lib/i18n"
import { cn } from "@/lib/utils"

function renderValue(value: unknown): string {
  if (value === null || value === undefined) return "—"
  if (typeof value === "object") return JSON.stringify(value)
  return String(value)
}

export function EvidenceExpander({
  evidence,
  className,
}: {
  evidence: Record<string, unknown>
  className?: string
}) {
  const t = useT()
  const [open, setOpen] = useState(false)

  // Flat scalar entries first; nested objects/arrays summarised below them.
  const entries = Object.entries(evidence ?? {})

  return (
    <div className={cn("text-sm", className)}>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-primary"
      >
        {open ? t.evidence.hide : t.evidence.show}
        {open ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
      </button>

      {open && (
        <div className="mt-2 rounded-md border bg-surface-2 p-3" data-testid="evidence-panel">
          <div className="grid gap-1">
            {entries.map(([key, value]) => (
              <div key={key} className="flex items-start justify-between gap-4 text-xs">
                <span className="text-text-3">{key}</span>
                <span className="tnum text-right font-medium text-text">
                  {renderValue(value)}
                </span>
              </div>
            ))}
          </div>
          <p className="mt-2 border-t pt-2 text-[11.5px] text-text-3">{t.app.sql_footer}</p>
        </div>
      )}
    </div>
  )
}
