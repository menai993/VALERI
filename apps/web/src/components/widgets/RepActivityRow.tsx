/**
 * RepActivityRow (ui-design §5, C-CRM2): one rep's activity rollup row —
 * avatar + name, a count chip, an activity summary ("2 sastanka, 1 poziv"),
 * and a right-aligned completion progress bar.
 *
 * Every number (total/done/by-kind/completion) comes from SQL via the
 * rep-activity rollup — this widget only formats; it never computes a figure.
 */
import { Progress } from "@/components/ui/progress"
import { useT } from "@/lib/i18n"
import type { RepActivityRow as RepActivityRowData } from "@/lib/api/types"

function initials(name: string | null): string {
  if (!name) return "?"
  const parts = name.trim().split(/\s+/)
  return (parts[0]?.[0] ?? "") + (parts.length > 1 ? (parts[parts.length - 1][0] ?? "") : "")
}

export function RepActivityRow({ rep }: { rep: RepActivityRowData }) {
  const t = useT()
  const kindLabels: Record<string, string> = t.dashboard.rep_activity.kinds

  // Build "2 sastanka · 1 poziv" from the non-zero by_kind counts (numbers from SQL).
  const summary = Object.entries(rep.by_kind)
    .filter(([, count]) => count > 0)
    .map(([kind, count]) => `${count} ${kindLabels[kind] ?? kind}`)
    .join(" · ")

  const completionPct = Number(rep.completion) * 100

  return (
    <div className="flex items-center gap-3 py-2" data-testid="rep-activity-row">
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary-soft text-xs font-semibold uppercase text-primary">
        {initials(rep.name)}
      </span>

      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <div className="flex items-center gap-2">
          <span className="truncate text-sm font-medium text-text">{rep.name ?? "—"}</span>
          <span className="tnum shrink-0 rounded-sm bg-surface-2 px-1.5 py-0.5 text-[11.5px] font-medium text-text-2">
            {rep.total}
          </span>
        </div>
        <span className="truncate text-xs text-text-3">{summary || t.app.empty}</span>
      </div>

      <div className="flex w-28 shrink-0 flex-col gap-1">
        <span className="tnum text-right text-[11.5px] text-text-3">
          {completionPct.toFixed(0)}% {t.dashboard.rep_activity.completed}
        </span>
        <Progress value={completionPct} />
      </div>
    </div>
  )
}
