/**
 * KnowledgePanel — "Šta VALERI zna" (CI1, §6): the client-360 knowledge block.
 * Profile summary + active facts (with source/confidence + Undo) + an events
 * timeline + a relationships list. All read-only KB data with provenance.
 */
import { Card } from "@/components/ui/card"
import { CardSkeleton, EmptyState } from "@/components/widgets/CardState"
import { ConfidenceLabel } from "@/components/widgets/ConfidenceLabel"
import { KbFactRow } from "@/components/widgets/KbFactRow"
import { RegisterChip } from "@/components/widgets/RegisterChip"
import { useCustomerKnowledge, useRejectKbItem } from "@/lib/api/queries"
import type { KbItem } from "@/lib/api/types"
import { formatDate } from "@/lib/format"
import { useT } from "@/lib/i18n"

export function KnowledgePanel({ customerId }: { customerId: number }) {
  const t = useT()
  const { data, isLoading } = useCustomerKnowledge(customerId)
  const reject = useRejectKbItem()

  const empty =
    data &&
    !data.profile?.summary &&
    data.facts.length === 0 &&
    data.events.length === 0 &&
    data.relationships.length === 0

  return (
    <Card className="flex flex-col gap-4 p-5" data-testid="knowledge-panel">
      <h2 className="text-[17px] font-semibold text-text">{t.kb.panel_title}</h2>

      {isLoading && <CardSkeleton rows={4} />}
      {empty && <EmptyState message={t.kb.no_knowledge} />}

      {data?.profile?.summary && (
        <p className="text-sm text-text-2" data-testid="kb-profile-summary">
          {data.profile.summary}
        </p>
      )}

      {data && data.facts.length > 0 && (
        <section className="flex flex-col gap-2">
          <h3 className="text-[11.5px] font-medium uppercase text-text-3">{t.kb.facts}</h3>
          {data.facts.map((fact: KbItem) => (
            <KbFactRow
              key={fact.id}
              item={fact}
              onUndo={(item) => reject.mutate({ itemId: item.id, itemType: "fact" })}
            />
          ))}
        </section>
      )}

      {data && data.events.length > 0 && (
        <section className="flex flex-col gap-2">
          <h3 className="text-[11.5px] font-medium uppercase text-text-3">{t.kb.events}</h3>
          {data.events.map((event) => (
            <div
              key={event.id}
              className="flex items-center justify-between gap-2 border-b border-border pb-2 text-sm last:border-0"
              data-testid="kb-event"
            >
              <span className="truncate text-text-2">{event.title}</span>
              <span className="tnum shrink-0 text-text-3">{formatDate(event.created_at)}</span>
            </div>
          ))}
        </section>
      )}

      {data && data.relationships.length > 0 && (
        <section className="flex flex-col gap-2">
          <h3 className="text-[11.5px] font-medium uppercase text-text-3">
            {t.kb.relationships}
          </h3>
          {data.relationships.map((rel) => (
            <div
              key={rel.id}
              className="flex flex-col gap-1 border-b border-border pb-2 text-sm last:border-0"
              data-testid="kb-relationship"
            >
              <div className="flex flex-wrap items-center gap-2">
                <RegisterChip register={rel.register} />
                <span className="text-text-2">
                  {rel.from_name} · {t.kb.rel[rel.rel_type as keyof typeof t.kb.rel] ?? rel.rel_type}{" "}
                  → {rel.to_name}
                </span>
              </div>
              <ConfidenceLabel band={rel.conf_band} />
            </div>
          ))}
        </section>
      )}
    </Card>
  )
}
