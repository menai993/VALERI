/**
 * KbFactRow (CI1): one captured fact/event with its provenance — register chip,
 * source + confidence, the source sentence as evidence, and optional actions
 * (Confirm/Reject in the review queue; Undo in the knowledge panel).
 */
import { Button } from "@/components/ui/button"
import { ConfidenceLabel } from "@/components/widgets/ConfidenceLabel"
import { RegisterChip } from "@/components/widgets/RegisterChip"
import type { KbItem } from "@/lib/api/types"
import { useT } from "@/lib/i18n"

export interface KbFactRowProps {
  item: KbItem
  onConfirm?: (item: KbItem) => void
  onReject?: (item: KbItem) => void
  onUndo?: (item: KbItem) => void
}

export function KbFactRow({ item, onConfirm, onReject, onUndo }: KbFactRowProps) {
  const t = useT()
  const sourceLabel = t.kb.source[item.source]

  return (
    <div
      className="flex flex-col gap-1 border-b border-border pb-3 last:border-0"
      data-testid="kb-item"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <RegisterChip register={item.register} />
          <span className="font-medium text-text">{item.title}</span>
          <span className="rounded-sm bg-surface-2 px-1.5 py-0.5 text-[11px] text-text-2">
            {sourceLabel}
          </span>
        </div>
        <div className="flex shrink-0 gap-1">
          {onConfirm && (
            <Button size="sm" variant="positive" onClick={() => onConfirm(item)}>
              {t.kb.confirm}
            </Button>
          )}
          {onReject && (
            <Button size="sm" onClick={() => onReject(item)}>
              {t.kb.reject}
            </Button>
          )}
          {onUndo && (
            <Button size="sm" variant="ghost" onClick={() => onUndo(item)}>
              {t.kb.undo}
            </Button>
          )}
        </div>
      </div>

      {item.customer_name ? (
        <span className="text-xs text-text-3">{item.customer_name}</span>
      ) : (
        item.mentioned_name && (
          <span className="text-xs text-text-3">„{item.mentioned_name}“</span>
        )
      )}

      <ConfidenceLabel band={item.conf_band} />

      {item.evidence_text && (
        <span className="text-xs italic text-text-3" data-testid="kb-evidence">
          „{item.evidence_text}“
        </span>
      )}
    </div>
  )
}
