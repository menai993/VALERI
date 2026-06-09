/**
 * Kupac 360-lite (frontend-spec §5): metrics, monthly trend, basket, signals, tasks.
 */
import { useState } from "react"
import { ArrowLeft, Search } from "lucide-react"
import { Link, useParams } from "react-router"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { CardSkeleton, EmptyState, ErrorState } from "@/components/widgets/CardState"
import { ComboChart } from "@/components/widgets/ComboChart"
import { ConfidenceLabel } from "@/components/widgets/ConfidenceLabel"
import { EvidenceExpander } from "@/components/widgets/EvidenceExpander"
import { InvestigationDialog } from "@/components/widgets/InvestigationDialog"
import { KnowledgePanel } from "@/components/widgets/KnowledgePanel"
import { RegisterChip } from "@/components/widgets/RegisterChip"
import { RelationshipMap } from "@/components/widgets/RelationshipMap"
import { RiskBadge } from "@/components/widgets/RiskBadge"
import { useCustomer } from "@/lib/api/queries"
import type { ConfBand, Register } from "@/lib/api/types"
import { formatDate, formatMoney, formatNumber } from "@/lib/format"
import { useT } from "@/lib/i18n"

export function CustomerDetailPage() {
  const t = useT()
  const params = useParams<{ customerId: string }>()
  const customerId = params.customerId ? Number.parseInt(params.customerId, 10) : null
  const { data, isLoading, isError, refetch } = useCustomer(customerId)
  const [investigateOpen, setInvestigateOpen] = useState(false)

  if (isLoading) return <CardSkeleton rows={10} />
  if (isError) return <ErrorState onRetry={() => refetch()} />
  if (!data) return <EmptyState />

  const { customer, metrics, basket, contacts } = {
    customer: data.customer,
    metrics: data.metrics,
    basket: data.metrics?.basket ?? [],
    contacts: data.contacts,
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-3">
        <Link to="/kupci" className="text-text-3 hover:text-text">
          <ArrowLeft className="h-5 w-5" />
        </Link>
        <div className="flex-1">
          <h1 className="text-[26px] font-semibold leading-tight text-text">{customer.name}</h1>
          <p className="text-sm text-text-2">
            {customer.segment} · {customer.legal_entity_name}
          </p>
        </div>
        <Button
          size="sm"
          onClick={() => setInvestigateOpen(true)}
          data-testid="istrazi-button"
        >
          <Search className="mr-1 h-4 w-4" />
          {t.new_analysis.istrazi}
        </Button>
        {customer.risk_band && <RiskBadge band={customer.risk_band} />}
      </div>

      {/* Metrics row */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card className="flex flex-col gap-1 p-4">
          <span className="text-sm text-text-2">{t.customers.turnover}</span>
          <span className="tnum text-2xl font-bold text-text">
            {formatMoney(customer.turnover_60d)}
          </span>
        </Card>
        <Card className="flex flex-col gap-1 p-4">
          <span className="text-sm text-text-2">{t.customers.baseline}</span>
          <span className="tnum text-2xl font-bold text-text">
            {formatMoney(customer.baseline_60d)}
          </span>
        </Card>
        <Card className="flex flex-col gap-1 p-4">
          <span className="text-sm text-text-2">{t.customers.last_order}</span>
          <span className="tnum text-2xl font-bold text-text">
            {formatDate(customer.last_order_date)}
          </span>
        </Card>
        <Card className="flex flex-col gap-1 p-4">
          <span className="text-sm text-text-2">{t.customers.detail.interval}</span>
          <span className="tnum text-2xl font-bold text-text">
            {metrics?.avg_order_interval_d
              ? `${formatNumber(metrics.avg_order_interval_d)} ${t.customers.detail.days}`
              : "—"}
          </span>
        </Card>
      </div>

      {/* Monthly trend */}
      <Card className="flex flex-col gap-3 p-5">
        <h2 className="text-[17px] font-semibold text-text">
          {t.customers.detail.turnover_trend}
        </h2>
        {metrics && metrics.monthly_turnover.length > 0 ? (
          <ComboChart
            months={metrics.monthly_turnover.map((row) => row.month)}
            revenue={metrics.monthly_turnover.map((row) => row.revenue)}
            secondary={metrics.monthly_turnover.map(() => "0")}
          />
        ) : (
          <EmptyState />
        )}
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* Basket */}
        <Card className="flex flex-col gap-3 p-5">
          <h2 className="text-[17px] font-semibold text-text">{t.customers.detail.basket}</h2>
          {basket.length === 0 && <EmptyState />}
          <div className="flex flex-col gap-2">
            {basket.map((row) => (
              <div
                key={row.category_id ?? "none"}
                className="flex items-center justify-between border-b border-border pb-2 text-sm last:border-0"
              >
                <span className="text-text-2">{row.category_name ?? "—"}</span>
                <span className="tnum font-medium text-text">{formatMoney(row.total_spent)}</span>
              </div>
            ))}
          </div>
        </Card>

        {/* Contacts */}
        <Card className="flex flex-col gap-3 p-5">
          <h2 className="text-[17px] font-semibold text-text">{t.customers.detail.contacts}</h2>
          {contacts.length === 0 && <EmptyState />}
          <div className="flex flex-col gap-2">
            {contacts.map((contact) => (
              <div key={contact.id} className="flex flex-col border-b border-border pb-2 text-sm last:border-0">
                <span className="font-medium text-text">{contact.name}</span>
                <span className="text-text-3">
                  {contact.email} · {contact.phone}
                </span>
              </div>
            ))}
          </div>
        </Card>
      </div>

      {/* Šta VALERI zna — the conversational knowledge base (CI1) + the
          relationship map over confirmed links (CI2). */}
      {customerId !== null && (
        <>
          <KnowledgePanel customerId={customerId} />
          <RelationshipMap customerId={customerId} />
        </>
      )}

      {/* Signals + tasks for this customer — AI surfaces: every row carries
          register + confidence + evidence (principles 2/3/9). */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="flex flex-col gap-3 p-5">
          <h2 className="text-[17px] font-semibold text-text">{t.customers.detail.signals}</h2>
          {data.signals.length === 0 && <EmptyState />}
          <div className="flex flex-col gap-3">
            {data.signals.map((signal) => (
              <Link
                key={String(signal.id)}
                to="/ai-report"
                className="flex flex-col gap-1 border-b border-border pb-3 text-sm last:border-0 hover:bg-surface-2"
                data-testid="customer-signal-link"
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <RegisterChip register={signal.register as Register} />
                    <span className="font-medium text-text">
                      {t.rules[signal.rule as keyof typeof t.rules] ?? String(signal.rule)}
                    </span>
                  </div>
                  <Badge>{String(signal.status)}</Badge>
                </div>
                <ConfidenceLabel band={signal.conf_band as ConfBand} />
                <EvidenceExpander evidence={signal.evidence as Record<string, unknown>} />
              </Link>
            ))}
          </div>
        </Card>

        <Card className="flex flex-col gap-3 p-5">
          <h2 className="text-[17px] font-semibold text-text">{t.customers.detail.tasks}</h2>
          {data.tasks.length === 0 && <EmptyState />}
          <div className="flex flex-col gap-2">
            {data.tasks.map((task) => (
              <Link
                key={String(task.id)}
                to={`/zadaci?task=${task.id}&due=all`}
                className="flex items-center justify-between gap-2 border-b border-border pb-2 text-sm last:border-0 hover:bg-surface-2"
                data-testid="customer-task-link"
              >
                <div className="flex min-w-0 items-center gap-2">
                  <RegisterChip register={task.register as Register} className="shrink-0" />
                  <span className="truncate text-text-2">{String(task.title)}</span>
                </div>
                <Badge>{t.tasks.status[task.status as keyof typeof t.tasks.status]}</Badge>
              </Link>
            ))}
          </div>
        </Card>
      </div>
      <InvestigationDialog
        open={investigateOpen}
        onClose={() => setInvestigateOpen(false)}
        defaultQuestion={`Zašto je ${customer.name} promijenio ponašanje narudžbi?`}
      />
    </div>
  )
}
