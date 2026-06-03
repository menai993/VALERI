/**
 * RuleCard (frontend-spec §4, M10): the self-configuration card opened by
 * dismissing an AI insight.
 *
 * Flow: reason → POST /signals/{id}/dismiss → VALERI's proposal (Bosnian
 * description + resolved scope + SQL blast radius + interpretation confidence):
 *   - auto-applied (narrow + confident) → Akcija · reversible · "Poništi" (undo)
 *   - requires confirm (broad/vague)    → Preporuka · "Primijeni" (one-tap confirm)
 *
 * Every outcome is visible and reversible — nothing happens silently
 * (principles 9/10); all numbers shown come from SQL (principle 1).
 */
import { useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { RegisterChip } from "@/components/widgets/RegisterChip"
import {
  useApplyRuleMutation,
  useDismissSignalMutation,
  useUndoRuleMutation,
} from "@/lib/api/queries"
import type { DismissResponse, InsightRow, RuleScope } from "@/lib/api/types"
import { useT } from "@/lib/i18n"

/** Human-readable chips for a (resolved) rule scope. */
function ScopeChips({ scope, customerName }: { scope: RuleScope; customerName?: string | null }) {
  const t = useT()
  const ruleLabel = scope.rule ? (t.rules[scope.rule as keyof typeof t.rules] ?? scope.rule) : null
  return (
    <div className="flex flex-wrap gap-2" data-testid="scope-chips">
      <Badge variant="outline">{t.rule_card.scope_kinds[scope.kind] ?? scope.kind}</Badge>
      {ruleLabel && <Badge variant="outline">{ruleLabel}</Badge>}
      {scope.entity_type === "customer" && customerName && (
        <Badge variant="outline">{customerName}</Badge>
      )}
      {scope.category && <Badge variant="outline">{scope.category}</Badge>}
      {scope.metric && (
        <Badge variant="outline">
          {scope.metric} {scope.op} {scope.value}
        </Badge>
      )}
    </div>
  )
}

/** The SQL blast radius line ("Predviđeni efekat: N signala u zadnjih X dana"). */
function EffectLine({ response }: { response: DismissResponse }) {
  const t = useT()
  return (
    <p className="text-xs text-text-2" data-testid="effect-estimate">
      {t.rule_card.effect_label}: <span className="tnum">{response.effect_estimate.total_signals}</span>{" "}
      {t.rule_card.effect_signals} <span className="tnum">{response.effect_estimate.window_days}</span>{" "}
      {t.rule_card.effect_days}
      <span className="text-text-3"> · {t.app.sql_footer}</span>
    </p>
  )
}

export function RuleCard({
  insight,
  open,
  onClose,
}: {
  insight: InsightRow | null
  open: boolean
  onClose: () => void
}) {
  const t = useT()
  const [reason, setReason] = useState("")
  const [proposal, setProposal] = useState<DismissResponse | null>(null)
  const [undone, setUndone] = useState(false)

  const dismiss = useDismissSignalMutation()
  const apply = useApplyRuleMutation()
  const undo = useUndoRuleMutation()

  if (!insight) return null

  // The rule counts as applied once auto-applied or explicitly confirmed.
  const applied = proposal !== null && (proposal.applied || apply.isSuccess) && !undone
  const busy = dismiss.isPending || apply.isPending || undo.isPending
  const failed = dismiss.isError || apply.isError || undo.isError

  function close() {
    // Reset local state so reopening starts fresh (the server state is persisted).
    setReason("")
    setProposal(null)
    setUndone(false)
    dismiss.reset()
    apply.reset()
    undo.reset()
    onClose()
  }

  async function submit() {
    if (!insight || reason.trim().length < 3) return
    try {
      const response = await dismiss.mutateAsync({
        signalId: insight.signal_id,
        reasonText: reason.trim(),
      })
      setProposal(response)
    } catch {
      // Surfaced via dismiss.isError below.
    }
  }

  async function confirmApply() {
    if (!proposal) return
    try {
      await apply.mutateAsync(proposal.learned_rule.id)
    } catch {
      // Surfaced via apply.isError below.
    }
  }

  async function revert() {
    if (!proposal) return
    try {
      await undo.mutateAsync(proposal.learned_rule.id)
      setUndone(true)
    } catch {
      // Surfaced via undo.isError below.
    }
  }

  return (
    <Dialog open={open} onOpenChange={(value) => !value && close()}>
      <DialogContent data-testid="rule-card">
        <DialogHeader>
          <DialogTitle>
            {proposal ? t.rule_card.proposal_title : t.rule_card.title}
          </DialogTitle>
          <DialogDescription>{t.rule_card.description}</DialogDescription>
        </DialogHeader>

        {/* ── phase 1: compose the dismissal reason ─────────────────────────── */}
        {proposal === null && (
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <Label htmlFor="dismiss-reason">{t.rule_card.reason_label}</Label>
              <Input
                id="dismiss-reason"
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                placeholder={t.rule_card.reason_placeholder}
                disabled={busy}
              />
            </div>

            <div className="flex flex-col gap-2">
              <span className="text-sm font-medium text-text-2">{t.rule_card.scope_title}</span>
              <div className="flex flex-wrap gap-2">
                <Badge variant="outline">
                  {t.rules[insight.rule as keyof typeof t.rules] ?? insight.rule}
                </Badge>
                <Badge variant="outline">{insight.customer_name}</Badge>
                {insight.segment && <Badge variant="outline">{insight.segment}</Badge>}
              </div>
            </div>
          </div>
        )}

        {/* ── phase 2: the proposal (pending or applied) ────────────────────── */}
        {proposal !== null && !undone && (
          <div className="flex flex-col gap-4" data-testid="rule-proposal">
            <div className="flex items-center gap-2">
              <RegisterChip register={applied ? "akcija" : "preporuka"} />
              <Badge>
                {applied ? t.rule_card.status_applied : t.rule_card.status_pending}
              </Badge>
            </div>

            {/* The Bosnian description Tier-1 wrote from the reason. */}
            <p className="text-sm text-text" data-testid="rule-description">
              {proposal.learned_rule.description}
            </p>

            <ScopeChips scope={proposal.learned_rule.scope} customerName={insight.customer_name} />
            <EffectLine response={proposal} />
            <p className="text-[11.5px] text-text-3">
              {t.rule_card.interpretation}:{" "}
              <span className="tnum">
                {Math.round(proposal.proposal.interpretation_confidence * 100)}%
              </span>
            </p>

            <p className="rounded-md bg-surface-2 p-3 text-xs text-text-2" data-testid="status-note">
              {applied ? t.rule_card.applied_note : t.rule_card.pending_note}
            </p>
          </div>
        )}

        {/* ── phase 3: undone ───────────────────────────────────────────────── */}
        {undone && (
          <p className="rounded-md bg-surface-2 p-3 text-sm text-text-2" data-testid="undone-note">
            {t.rule_card.undone_note}
          </p>
        )}

        {failed && (
          <p className="text-sm text-down" data-testid="rule-card-error">
            {t.rule_card.error}
          </p>
        )}

        <DialogFooter>
          {proposal === null && (
            <>
              <Button variant="default" onClick={close} disabled={busy}>
                {t.rule_card.cancel}
              </Button>
              <Button
                variant="positive"
                onClick={() => void submit()}
                disabled={busy || reason.trim().length < 3}
                data-testid="submit-dismiss-button"
              >
                {t.rule_card.submit}
              </Button>
            </>
          )}

          {proposal !== null && !undone && !applied && (
            <>
              <Button variant="default" onClick={close} disabled={busy}>
                {t.rule_card.cancel}
              </Button>
              <Button
                variant="positive"
                onClick={() => void confirmApply()}
                disabled={busy}
                data-testid="apply-rule-button"
              >
                {t.rule_card.apply}
              </Button>
            </>
          )}

          {proposal !== null && !undone && applied && (
            <>
              <Button
                variant="default"
                onClick={() => void revert()}
                disabled={busy}
                data-testid="undo-rule-button"
              >
                {t.rule_card.undo}
              </Button>
              <Button variant="primary" onClick={close} disabled={busy}>
                {t.rule_card.close}
              </Button>
            </>
          )}

          {undone && (
            <Button variant="primary" onClick={close}>
              {t.rule_card.close}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
