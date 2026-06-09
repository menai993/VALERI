/**
 * ApprovalCard (frontend-spec §4, built in P1): one pending customer-facing
 * draft with one-tap Odobri / Odbij / Odgodi. Always register 'akcija' + an
 * explicit status — the owner is never unsure whether something already
 * happened (principle 9/10).
 */
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { RegisterChip } from "@/components/widgets/RegisterChip"
import type { Approval } from "@/lib/api/types"
import { useT } from "@/lib/i18n"

export interface ApprovalCardProps {
  item: Approval
  onApprove: (item: Approval) => void
  onReject: (item: Approval) => void
  onDefer: (item: Approval) => void
  deciding?: boolean
}

export function ApprovalCard({ item, onApprove, onReject, onDefer, deciding }: ApprovalCardProps) {
  const t = useT()
  const payload = item.payload ?? {}
  const customerName = (payload.customer_name as string) ?? null
  const message = (payload.message as string) ?? null
  const pending = item.status === "pending_approval"

  return (
    <div
      className="flex flex-col gap-2 border-b border-border pb-4 last:border-0"
      data-testid="approval-card"
    >
      <div className="flex flex-wrap items-center gap-2">
        <RegisterChip register="akcija" />
        <Badge>{pending ? t.approvals.pending : item.status}</Badge>
        <span className="text-xs text-text-3">
          {t.approvals.kind}: {item.kind}
        </span>
      </div>

      {customerName && (
        <span className="text-sm font-medium text-text">
          {t.approvals.message_for}: {customerName}
        </span>
      )}
      {message && (
        <p className="whitespace-pre-line rounded-md bg-surface-2 p-3 text-sm text-text-2">
          {message}
        </p>
      )}

      {pending && (
        <div className="flex gap-2">
          <Button
            variant="positive"
            size="sm"
            disabled={deciding}
            onClick={() => onApprove(item)}
            data-testid="approve-button"
          >
            {t.approvals.approve}
          </Button>
          <Button size="sm" disabled={deciding} onClick={() => onReject(item)}>
            {t.approvals.reject}
          </Button>
          <Button variant="ghost" size="sm" disabled={deciding} onClick={() => onDefer(item)}>
            {t.approvals.defer}
          </Button>
        </div>
      )}
    </div>
  )
}
