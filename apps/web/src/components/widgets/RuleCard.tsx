/**
 * RuleCard (frontend-spec §4): the self-configuration card opened by dismissing
 * an AI insight.
 *
 * M8 (D3): PREVIEW ONLY — the reason input and scope chips render, but
 * "Primijeni" is disabled with an explanation; the apply call lands in M10.
 */
import { useState } from "react"

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
import { Badge } from "@/components/ui/badge"
import { useT } from "@/lib/i18n"
import type { InsightRow } from "@/lib/api/types"

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

  if (!insight) return null

  return (
    <Dialog open={open} onOpenChange={(value) => !value && onClose()}>
      <DialogContent data-testid="rule-card">
        <DialogHeader>
          <DialogTitle>{t.rule_card.title}</DialogTitle>
          <DialogDescription>{t.rule_card.description}</DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <Label htmlFor="dismiss-reason">{t.rule_card.reason_label}</Label>
            <Input
              id="dismiss-reason"
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder={t.rule_card.reason_placeholder}
            />
          </div>

          <div className="flex flex-col gap-2">
            <span className="text-sm font-medium text-text-2">{t.rule_card.scope_title}</span>
            <div className="flex flex-wrap gap-2">
              <Badge variant="outline">{t.rules[insight.rule as keyof typeof t.rules] ?? insight.rule}</Badge>
              <Badge variant="outline">{insight.customer_name}</Badge>
              {insight.segment && <Badge variant="outline">{insight.segment}</Badge>}
            </div>
          </div>

          <p className="rounded-md bg-surface-2 p-3 text-xs text-text-2" data-testid="m10-note">
            {t.rule_card.m10_note}
          </p>
        </div>

        <DialogFooter>
          <Button variant="default" onClick={onClose}>
            {t.rule_card.cancel}
          </Button>
          {/* Disabled until M10 implements POST /signals/{id}/dismiss + /rules/apply */}
          <Button variant="positive" disabled data-testid="apply-rule-button">
            {t.rule_card.apply}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
