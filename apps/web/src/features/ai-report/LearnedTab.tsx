/**
 * "Šta je VALERI naučio" (frontend-spec §5, M11): every learned rule with origin,
 * effect, status, Na provjeri flag and Undo/Zadrži/Edit-scope — plus the append-only
 * decision feed ("show the decision on the platform"), filterable by kind.
 */
import { useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { CardSkeleton, EmptyState, ErrorState } from "@/components/widgets/CardState"
import { LearnedRuleCard } from "@/components/widgets/LearnedRuleCard"
import { useDecisions, useLearnedRules } from "@/lib/api/queries"
import type { Decision } from "@/lib/api/types"
import { formatDate } from "@/lib/format"
import { useT } from "@/lib/i18n"

function DecisionRow({ decision }: { decision: Decision }) {
  const t = useT()
  const kindLabel =
    t.learned.decision_kinds[decision.kind as keyof typeof t.learned.decision_kinds] ??
    decision.kind
  return (
    <div className="flex flex-col gap-1 border-b py-3 last:border-b-0" data-testid="decision-row">
      <div className="flex flex-wrap items-center gap-2">
        <Badge>{kindLabel}</Badge>
        <Badge variant="outline">
          {t.learned.actor[decision.actor as keyof typeof t.learned.actor] ?? decision.actor}
        </Badge>
        {decision.reversible && (
          <span className="text-[11.5px] text-text-3">{t.learned.reversible}</span>
        )}
        <span className="tnum ml-auto text-[11.5px] text-text-3">
          {formatDate(decision.created_at)}
        </span>
      </div>
      <p className="text-sm text-text-2">{decision.summary}</p>
    </div>
  )
}

export function LearnedTab() {
  const t = useT()
  const rules = useLearnedRules()
  const [kindFilter, setKindFilter] = useState("all")
  const decisions = useDecisions(kindFilter === "all" ? undefined : kindFilter)

  return (
    <div className="flex flex-col gap-4">
      {/* ── learned rules ────────────────────────────────────────────────────── */}
      <div className="flex flex-col gap-3" data-testid="learned-rules-list">
        <h2 className="text-[17px] font-semibold text-text">{t.learned.title}</h2>

        {rules.isLoading && (
          <Card className="p-5">
            <CardSkeleton rows={5} />
          </Card>
        )}
        {rules.isError && (
          <Card className="p-5">
            <ErrorState onRetry={() => rules.refetch()} />
          </Card>
        )}
        {rules.data && rules.data.items.length === 0 && (
          <Card className="p-5">
            <EmptyState message={t.learned.empty} />
          </Card>
        )}
        {rules.data?.items.map((rule) => <LearnedRuleCard key={rule.id} rule={rule} />)}
      </div>

      {/* ── the decision feed ────────────────────────────────────────────────── */}
      <Card className="flex flex-col gap-3 p-5" data-testid="decision-feed">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-[17px] font-semibold text-text">{t.learned.decisions_title}</h2>
          <Select value={kindFilter} onValueChange={setKindFilter}>
            <SelectTrigger className="w-48">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t.learned.filter_all}</SelectItem>
              {Object.entries(t.learned.decision_kinds).map(([kind, label]) => (
                <SelectItem key={kind} value={kind}>
                  {label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {decisions.isLoading && <CardSkeleton rows={4} />}
        {decisions.data && decisions.data.items.length === 0 && (
          <EmptyState message={t.learned.decisions_empty} />
        )}
        {decisions.data && decisions.data.items.length > 0 && (
          <div className="flex flex-col">
            {decisions.data.items.map((decision) => (
              <DecisionRow key={decision.id} decision={decision} />
            ))}
          </div>
        )}
      </Card>
    </div>
  )
}
