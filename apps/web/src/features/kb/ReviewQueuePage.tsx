/**
 * Zabilješke — the KB review queue (CI1, §6). Proposed facts/events/relationships
 * awaiting Potvrdi/Odbaci, plus the clarification questions VALERI raised. Every
 * action writes a reversible decision server-side.
 */
import { Card } from "@/components/ui/card"
import { CardSkeleton, EmptyState, ErrorState } from "@/components/widgets/CardState"
import { ClarificationCard } from "@/components/widgets/ClarificationCard"
import { ConfidenceLabel } from "@/components/widgets/ConfidenceLabel"
import { KbFactRow } from "@/components/widgets/KbFactRow"
import { RegisterChip } from "@/components/widgets/RegisterChip"
import {
  useAnswerClarification,
  useConfirmKbItem,
  useKbPending,
  useRejectKbItem,
} from "@/lib/api/queries"
import type { KbItem } from "@/lib/api/types"
import { useT } from "@/lib/i18n"

export function ReviewQueuePage() {
  const t = useT()
  const { data, isLoading, isError, refetch } = useKbPending()
  const confirm = useConfirmKbItem()
  const reject = useRejectKbItem()
  const answer = useAnswerClarification()

  const factActions = (itemType: KbItem["item_type"]) => ({
    onConfirm: (item: KbItem) => confirm.mutate({ itemId: item.id, itemType }),
    onReject: (item: KbItem) => reject.mutate({ itemId: item.id, itemType }),
  })

  const isEmpty =
    data &&
    data.facts.length === 0 &&
    data.events.length === 0 &&
    data.relationships.length === 0 &&
    data.clarifications.length === 0

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-[26px] font-semibold leading-tight text-text">{t.kb.queue_title}</h1>
        <p className="text-sm text-text-2">{t.kb.queue_subtitle}</p>
      </div>

      {isError && <ErrorState onRetry={() => refetch()} />}
      {isLoading && <CardSkeleton rows={6} />}
      {isEmpty && <EmptyState message={t.kb.queue_empty} />}

      {data && data.clarifications.length > 0 && (
        <Card className="flex flex-col gap-3 p-5">
          <h2 className="text-[17px] font-semibold text-text">{t.kb.clarifications}</h2>
          <div className="flex flex-col gap-3">
            {data.clarifications.map((clar) => (
              <ClarificationCard
                key={clar.id}
                clarification={clar}
                onAnswer={(clarificationId, option) =>
                  answer.mutate({ clarificationId, option })
                }
              />
            ))}
          </div>
        </Card>
      )}

      {data && data.facts.length > 0 && (
        <Card className="flex flex-col gap-3 p-5">
          <h2 className="text-[17px] font-semibold text-text">{t.kb.pending_facts}</h2>
          {data.facts.map((fact) => (
            <KbFactRow key={fact.id} item={fact} {...factActions("fact")} />
          ))}
        </Card>
      )}

      {data && data.events.length > 0 && (
        <Card className="flex flex-col gap-3 p-5">
          <h2 className="text-[17px] font-semibold text-text">{t.kb.pending_events}</h2>
          {data.events.map((event) => (
            <KbFactRow key={event.id} item={event} {...factActions("event")} />
          ))}
        </Card>
      )}

      {data && data.relationships.length > 0 && (
        <Card className="flex flex-col gap-3 p-5">
          <h2 className="text-[17px] font-semibold text-text">{t.kb.pending_relationships}</h2>
          {data.relationships.map((rel) => (
            <div
              key={rel.id}
              className="flex items-center justify-between gap-2 border-b border-border pb-3 text-sm last:border-0"
              data-testid="kb-pending-relationship"
            >
              <div className="flex flex-wrap items-center gap-2">
                <RegisterChip register={rel.register} />
                <span className="text-text-2">
                  {rel.from_name} ·{" "}
                  {t.kb.rel[rel.rel_type as keyof typeof t.kb.rel] ?? rel.rel_type} → {rel.to_name}
                </span>
                <ConfidenceLabel band={rel.conf_band} />
              </div>
            </div>
          ))}
        </Card>
      )}
    </div>
  )
}
