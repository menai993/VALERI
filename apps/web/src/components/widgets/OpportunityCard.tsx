/**
 * OpportunityCard (C-CRM1): one kanban card — title, customer, value, effective
 * probability, weighted value, and a stage <Select> that moves it (PATCH).
 *
 * These are user-entered pipeline data, not AI output — no register/confidence chip.
 */
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { useUpdateOpportunity } from "@/lib/api/queries"
import type { Opportunity, OppStage } from "@/lib/api/types"
import { formatMoney } from "@/lib/format"
import { useT } from "@/lib/i18n"

const STAGES: OppStage[] = ["lead", "qualified", "proposal", "negotiation", "won", "lost"]

export function OpportunityCard({ opportunity }: { opportunity: Opportunity }) {
  const t = useT()
  const update = useUpdateOpportunity()

  return (
    <div
      className="flex flex-col gap-2 rounded-md border bg-surface p-3 shadow-card-sm"
      data-testid="opportunity-card"
    >
      <span className="text-sm font-medium text-text">{opportunity.title}</span>
      <span className="text-xs text-text-2">{opportunity.customer_name ?? "—"}</span>

      <div className="flex items-center justify-between text-xs text-text-3">
        <span className="tnum">{opportunity.value ? formatMoney(opportunity.value) : "—"}</span>
        {opportunity.effective_probability && (
          <span className="tnum">
            {Math.round(Number(opportunity.effective_probability) * 100)}%
          </span>
        )}
      </div>

      {opportunity.weighted_value && (
        <span className="tnum text-xs font-medium text-primary" data-testid="card-weighted">
          {formatMoney(opportunity.weighted_value)}
        </span>
      )}

      <Select
        value={opportunity.stage}
        onValueChange={(stage) =>
          update.mutate({ id: opportunity.id, changes: { stage } })
        }
      >
        <SelectTrigger className="h-7 text-xs" data-testid={`stage-select-${opportunity.id}`}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {STAGES.map((stage) => (
            <SelectItem key={stage} value={stage}>
              {t.opportunities.stages[stage]}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}
