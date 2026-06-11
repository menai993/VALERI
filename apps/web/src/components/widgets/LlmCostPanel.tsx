/**
 * Troškovi AI (P3): LLM spend versus budget, broken down by feature/model/user,
 * with cost-per-useful-task and the recent expensive calls. Owner/admin only (the
 * endpoint 403s everyone else); admin can edit the budget. All figures are SQL
 * over audit.ai_log — the model never produces a cost.
 */
import { useState } from "react"

import { Banknote, Pencil } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { CardSkeleton, EmptyState, ErrorState } from "@/components/widgets/CardState"
import { ApiRequestError } from "@/lib/api/client"
import { useLlmRecent, useLlmUsage, usePatchLlmBudget } from "@/lib/api/queries"
import type { LlmUsageGroupBy } from "@/lib/api/types"
import { formatNumber } from "@/lib/format"
import { useT } from "@/lib/i18n"

function usd(value: string | null | undefined): string {
  if (value === null || value === undefined) return "—"
  return `$${Number(value).toFixed(2)}`
}

export function LlmCostPanel({ isAdmin }: { isAdmin: boolean }) {
  const t = useT()
  const c = t.settings.llm_cost
  const [groupBy, setGroupBy] = useState<LlmUsageGroupBy>("feature")
  const { data, isLoading, isError, error, refetch } = useLlmUsage(groupBy)
  const { data: recent } = useLlmRecent()
  const patchBudget = usePatchLlmBudget()
  const [editing, setEditing] = useState(false)
  const [limit, setLimit] = useState("")
  const [alertPct, setAlertPct] = useState("80")

  if (isLoading) return <CardSkeleton rows={6} />
  if (isError) {
    if (error instanceof ApiRequestError && error.status === 403) {
      return <EmptyState message={t.app.forbidden} />
    }
    return <ErrorState onRetry={() => refetch()} />
  }
  if (!data) return null

  const { budget } = data
  const pct = budget.pct ?? 0
  const over = pct >= budget.alert_pct
  const groupLabel: Record<LlmUsageGroupBy, string> = {
    feature: c.group_feature,
    model: c.group_model,
    user: c.group_user,
  }

  return (
    <div className="flex flex-col gap-4" data-testid="llm-cost-panel">
      {/* Spend vs budget + cost-per-useful-task. */}
      <div className="grid gap-4 sm:grid-cols-2">
        <Card className="flex flex-col gap-3 p-5" data-testid="llm-spend">
          <div className="flex items-start gap-3">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-primary-soft text-primary">
              <Banknote className="h-4 w-4" />
            </span>
            <div className="flex flex-col">
              <h2 className="text-[15px] font-semibold text-text">{c.spend_this_month}</h2>
              <p className="tnum text-[26px] font-bold leading-tight text-text">
                {usd(data.total.cost_usd)}
              </p>
            </div>
          </div>
          {budget.limit_usd !== null && (
            <>
              <div className="h-2 overflow-hidden rounded-full bg-surface-2">
                <div
                  className={`h-full rounded-full ${over ? "bg-down" : "bg-primary"}`}
                  style={{ width: `${Math.min(pct, 100)}%` }}
                  data-testid="llm-budget-bar"
                />
              </div>
              <p className="text-xs text-text-3">
                {c.budget}: {usd(budget.spent_usd)} {c.of} {usd(budget.limit_usd)}
                {budget.pct !== null && (
                  <span className={over ? "ml-1 font-medium text-down" : "ml-1 text-text-2"}>
                    ({budget.pct.toFixed(0)}%)
                  </span>
                )}
              </p>
            </>
          )}
          {isAdmin && !editing && (
            <Button
              className="self-start"
              onClick={() => {
                setLimit(budget.limit_usd ?? "")
                setAlertPct(String(budget.alert_pct))
                setEditing(true)
              }}
              data-testid="llm-edit-budget"
            >
              <Pencil className="h-4 w-4" />
              {c.edit_budget}
            </Button>
          )}
          {isAdmin && editing && (
            <div className="flex flex-col gap-2" data-testid="llm-budget-form">
              <label className="text-xs text-text-2">{c.budget_limit}</label>
              <Input value={limit} onChange={(e) => setLimit(e.target.value)} inputMode="decimal" />
              <label className="text-xs text-text-2">{c.alert_at}</label>
              <Input
                value={alertPct}
                onChange={(e) => setAlertPct(e.target.value)}
                inputMode="numeric"
              />
              <Button
                variant="primary"
                disabled={patchBudget.isPending}
                onClick={() =>
                  patchBudget.mutate(
                    { limit_usd: limit, alert_pct: Number(alertPct) },
                    { onSuccess: () => setEditing(false) },
                  )
                }
                data-testid="llm-save-budget"
              >
                {c.save}
              </Button>
            </div>
          )}
        </Card>

        <Card className="flex flex-col justify-center gap-1 p-5" data-testid="llm-cput">
          <h2 className="text-[15px] font-semibold text-text">{c.cost_per_useful_task}</h2>
          <p className="tnum text-[26px] font-bold leading-tight text-text">
            {data.cost_per_useful_task.value !== null
              ? usd(String(data.cost_per_useful_task.value))
              : c.none}
          </p>
          <p className="text-xs text-text-3">
            {formatNumber(data.cost_per_useful_task.useful_tasks)} {c.useful_tasks}
          </p>
        </Card>
      </div>

      {/* Breakdown by feature / model / user. */}
      <Card className="flex flex-col gap-3 p-5" data-testid="llm-breakdown">
        <Tabs value={groupBy} onValueChange={(v) => setGroupBy(v as LlmUsageGroupBy)}>
          <TabsList>
            <TabsTrigger value="feature">{c.by_feature}</TabsTrigger>
            <TabsTrigger value="model">{c.by_model}</TabsTrigger>
            <TabsTrigger value="user">{c.by_user}</TabsTrigger>
          </TabsList>
        </Tabs>
        {data.groups.length === 0 ? (
          <p className="text-sm text-text-3">{c.no_data}</p>
        ) : (
          <div className="flex flex-col gap-1">
            <div className="grid grid-cols-[2fr_1fr_1fr] gap-3 border-b pb-2 text-xs text-text-3">
              <span>{groupLabel[groupBy]}</span>
              <span className="text-right">{c.col_cost}</span>
              <span className="text-right">{c.col_calls}</span>
            </div>
            {data.groups.map((g) => (
              <div
                key={g.key ?? "—"}
                className="grid grid-cols-[2fr_1fr_1fr] items-center gap-3 border-b py-2 text-sm last:border-b-0"
                data-testid="llm-group-row"
              >
                <span className="text-text">{g.key ?? c.none}</span>
                <span className="tnum text-right font-medium text-text">{usd(g.cost_usd)}</span>
                <span className="tnum text-right text-text-2">{formatNumber(g.calls)}</span>
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* Recent expensive calls. */}
      {recent && recent.items.length > 0 && (
        <Card className="flex flex-col gap-1 p-5" data-testid="llm-recent">
          <h2 className="mb-1 text-[15px] font-semibold text-text">{c.recent_expensive}</h2>
          <div className="grid grid-cols-[1.4fr_1fr_1fr_auto] gap-3 border-b pb-2 text-xs text-text-3">
            <span>{c.group_feature}</span>
            <span>{c.group_model}</span>
            <span className="text-right">{c.col_tokens}</span>
            <span className="text-right">{c.col_cost}</span>
          </div>
          {recent.items.map((r) => (
            <div
              key={r.id}
              className="grid grid-cols-[1.4fr_1fr_1fr_auto] items-center gap-3 border-b py-2 text-sm last:border-b-0"
            >
              <span className="flex items-center gap-1 text-text">
                {r.feature ?? c.none}
                {r.batched && <Badge variant="outline">{c.batched}</Badge>}
                {r.cached && <Badge variant="outline">{c.cached}</Badge>}
              </span>
              <span className="text-text-2">{r.model}</span>
              <span className="tnum text-right text-text-2">
                {formatNumber(r.input_tokens ?? 0)}/{formatNumber(r.output_tokens ?? 0)}
              </span>
              <span className="tnum text-right font-medium text-text">{usd(r.cost_usd)}</span>
            </div>
          ))}
        </Card>
      )}
    </div>
  )
}
