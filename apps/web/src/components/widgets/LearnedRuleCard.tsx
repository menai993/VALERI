/**
 * LearnedRuleCard (frontend-spec §4, M11): one learned rule with its origin, its
 * real effect ("what it hid", viewable evidence), status/autonomy, the auditor's
 * "Na provjeri" flag, and the owner's controls: Undo / Zadrži / Edit scope.
 *
 * Every number shown is SQL output (suppression_count, effect_estimate, evidence);
 * every action writes an append-only decision server-side.
 */
import { useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { CardSkeleton } from "@/components/widgets/CardState"
import { ConfidenceLabel } from "@/components/widgets/ConfidenceLabel"
import { EvidenceExpander } from "@/components/widgets/EvidenceExpander"
import { ScopeChips } from "@/components/widgets/RuleCard"
import {
  useEditScopeMutation,
  useKeepRuleMutation,
  useLearnedRuleDetail,
  useUndoRuleMutation,
} from "@/lib/api/queries"
import type { LearnedRule } from "@/lib/api/types"
import { formatDate } from "@/lib/format"
import { useT } from "@/lib/i18n"
import { cn } from "@/lib/utils"

const statusStyles: Record<LearnedRule["status"], string> = {
  active: "bg-register-akcija-bg text-register-akcija-text",
  pending_confirm: "bg-register-preporuka-bg text-register-preporuka-text",
  reverted: "bg-surface-2 text-text-3",
  expired: "bg-surface-2 text-text-3",
}

export function LearnedRuleCard({ rule }: { rule: LearnedRule }) {
  const t = useT()
  const [showHidden, setShowHidden] = useState(false)
  const [editingScope, setEditingScope] = useState(false)
  const [scopeRule, setScopeRule] = useState(rule.scope.rule ?? "all")

  // "What it hid" loads lazily — only when the owner expands it.
  const detail = useLearnedRuleDetail(showHidden ? rule.id : null)
  const undo = useUndoRuleMutation()
  const keep = useKeepRuleMutation()
  const editScope = useEditScopeMutation()

  const busy = undo.isPending || keep.isPending || editScope.isPending

  function saveScope() {
    editScope.mutate(
      {
        ruleId: rule.id,
        scope: { ...rule.scope, rule: scopeRule === "all" ? null : scopeRule },
      },
      { onSuccess: () => setEditingScope(false) },
    )
  }

  return (
    <Card className="flex flex-col gap-3 p-5" data-testid="learned-rule-card">
      {/* status + autonomy + the Na provjeri flag */}
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={cn(
            "inline-flex items-center rounded-sm px-2 py-0.5 text-xs font-medium",
            statusStyles[rule.status],
          )}
          data-testid="rule-status"
        >
          {t.learned.status[rule.status]}
        </span>
        <Badge variant="outline">{t.learned.autonomy[rule.autonomy]}</Badge>
        {rule.na_provjeri && (
          <span
            className="inline-flex items-center rounded-sm bg-risk-mid/10 px-2 py-0.5 text-xs font-medium text-risk-mid"
            data-testid="na-provjeri-flag"
          >
            {t.learned.na_provjeri}
          </span>
        )}
      </div>

      {/* the Bosnian description Tier-1 wrote at proposal time */}
      <p className="text-sm font-medium text-text">{rule.description}</p>

      {/* origin: where this rule came from, who created it, when */}
      <p className="text-[11.5px] text-text-3" data-testid="rule-origin">
        {rule.source_signal_id !== null ? t.learned.origin_signal : t.learned.origin_chat}
        {rule.source_customer_name ? ` · ${rule.source_customer_name}` : ""}
        {rule.created_by_name ? ` · ${t.learned.origin_by} ${rule.created_by_name}` : ""}
        {` · ${formatDate(rule.created_at)}`}
        {rule.expires_at ? ` · ${t.learned.expires} ${formatDate(rule.expires_at)}` : ""}
      </p>

      <ScopeChips scope={rule.scope} customerName={rule.source_customer_name} />

      {/* effect: the SQL-counted reality vs the prediction */}
      <p className="text-xs text-text-2">
        {t.learned.effect_label}: <span className="tnum" data-testid="effect-count">{rule.suppression_count}</span>
        {rule.effect_estimate && (
          <>
            {" "}
            · {t.learned.predicted_label}:{" "}
            <span className="tnum">{rule.effect_estimate.total_signals}</span>
          </>
        )}
        <span className="text-text-3"> · {t.app.sql_footer}</span>
      </p>

      {rule.na_provjeri && (
        <p
          className="rounded-md bg-risk-mid/10 p-3 text-xs text-risk-mid"
          data-testid="na-provjeri-note"
        >
          {t.learned.na_provjeri_note}
        </p>
      )}

      {/* "what it hid" — the suppressed signals' evidence, one tap away */}
      <button
        type="button"
        onClick={() => setShowHidden((value) => !value)}
        className="self-start text-sm font-medium text-primary hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-primary"
        data-testid="show-hidden-toggle"
      >
        {showHidden ? t.learned.hide_hidden : t.learned.show_hidden}
      </button>

      {showHidden && (
        <div className="flex flex-col gap-2 rounded-md bg-surface-2 p-3" data-testid="hidden-signals">
          {detail.isLoading && <CardSkeleton rows={2} />}
          {detail.data && detail.data.hits.length === 0 && (
            <p className="text-xs text-text-3">{t.learned.hidden_empty}</p>
          )}
          {detail.data?.hits.map((hit) => (
            <div key={hit.id} className="flex flex-col gap-1 border-b pb-2 last:border-b-0">
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <span className="font-medium text-text">{hit.customer_name ?? "—"}</span>
                <span className="text-xs text-text-3">
                  {hit.rule ? (t.rules[hit.rule as keyof typeof t.rules] ?? hit.rule) : ""}
                </span>
                <span className="tnum text-[11.5px] text-text-3">
                  {formatDate(hit.suppressed_at)}
                </span>
              </div>
              {hit.conf_band && <ConfidenceLabel band={hit.conf_band} />}
              {hit.evidence && <EvidenceExpander evidence={hit.evidence} />}
            </div>
          ))}
        </div>
      )}

      {/* controls — only active rules can be acted on */}
      {rule.status === "active" && (
        <div className="flex flex-wrap items-center gap-2">
          {rule.na_provjeri && (
            <Button
              variant="positive"
              size="sm"
              onClick={() => keep.mutate(rule.id)}
              disabled={busy}
              data-testid="keep-rule-button"
            >
              {t.learned.keep}
            </Button>
          )}
          <Button
            variant="default"
            size="sm"
            onClick={() => undo.mutate(rule.id)}
            disabled={busy}
            data-testid="undo-rule-button"
          >
            {t.learned.undo}
          </Button>
          {rule.rule_type !== "threshold" && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setEditingScope((value) => !value)}
              disabled={busy}
              data-testid="edit-scope-button"
            >
              {t.learned.edit_scope}
            </Button>
          )}
        </div>
      )}

      {/* inline scope editor: which detection rule the suppression applies to */}
      {editingScope && rule.status === "active" && (
        <div className="flex flex-wrap items-center gap-2" data-testid="scope-editor">
          <Select value={scopeRule} onValueChange={setScopeRule}>
            <SelectTrigger className="w-56">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t.learned.scope_all_rules}</SelectItem>
              {Object.entries(t.rules).map(([key, label]) => (
                <SelectItem key={key} value={key}>
                  {label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            variant="positive"
            size="sm"
            onClick={saveScope}
            disabled={busy}
            data-testid="save-scope-button"
          >
            {t.learned.scope_save}
          </Button>
        </div>
      )}
    </Card>
  )
}
