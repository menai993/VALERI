/**
 * Početna (the flagship command dashboard) — ui-design §6 grid:
 *
 *   Row 1: title + DateRangePicker
 *   Row 2: KPI row (4 StatCards)
 *   Row 3: 8/4 — ComboChart + SubStatStrip | AI uvidi (AIInsightItem list)
 *   Row 4: 6/6 — Top kupci u riziku | Izgubljeni artikli (MVP recovery tables)
 *   Row 5: 6/6 — Aktivnosti komercijalista (Phase-2 placeholder) | Owner-report summary
 *
 * One useDashboard() query hydrates everything; every card has skeleton/empty/
 * error states; every AI surface carries register + confidence + evidence.
 */
import { useState } from "react"
import { ClipboardList, PackageX, TrendingDown, Wallet } from "lucide-react"
import { Link } from "react-router"

import { Card } from "@/components/ui/card"
import { AIInsightItem } from "@/components/widgets/AIInsightItem"
import { CardSkeleton, EmptyState, ErrorState } from "@/components/widgets/CardState"
import { ComboChart } from "@/components/widgets/ComboChart"
import { DataTable, type Column } from "@/components/widgets/DataTable"
import { DateRangePicker, type RangePreset } from "@/components/widgets/DateRangePicker"
import { EvidenceExpander } from "@/components/widgets/EvidenceExpander"
import { OwnerReportSummary } from "@/components/widgets/OwnerReportSummary"
import { RiskBadge } from "@/components/widgets/RiskBadge"
import { RuleCard } from "@/components/widgets/RuleCard"
import { StatCard } from "@/components/widgets/StatCard"
import { SubStatStrip } from "@/components/widgets/SubStatStrip"
import { useDashboard } from "@/lib/api/queries"
import type { AtRiskRow, InsightRow, KpiTile, LostArticleRow } from "@/lib/api/types"
import { formatDate, formatMoney } from "@/lib/format"
import { useT } from "@/lib/i18n"

function SectionCard({
  title,
  children,
}: {
  title: string
  children: React.ReactNode
}) {
  return (
    <Card className="flex flex-col gap-3 p-5">
      <h2 className="text-[17px] font-semibold text-text">{title}</h2>
      {children}
    </Card>
  )
}

export function DashboardPage() {
  const t = useT()
  const [range, setRange] = useState<RangePreset>("30d")
  const [dismissTarget, setDismissTarget] = useState<InsightRow | null>(null)
  const { data, isLoading, isError, refetch } = useDashboard(range)

  const kpiMeta: Record<string, { label: string; icon: typeof Wallet; money?: boolean }> = {
    ukupan_prihod: { label: t.dashboard.kpi.ukupan_prihod, icon: Wallet, money: true },
    kupci_u_padu: { label: t.dashboard.kpi.kupci_u_padu, icon: TrendingDown },
    izgubljeni_artikli: { label: t.dashboard.kpi.izgubljeni_artikli, icon: PackageX },
    zadaci_danas: { label: t.dashboard.kpi.zadaci_danas, icon: ClipboardList },
  }

  const atRiskColumns: Column<AtRiskRow>[] = [
    {
      key: "customer",
      header: t.dashboard.at_risk.customer,
      render: (row) => (
        <div className="flex flex-col gap-1">
          <span className="font-medium text-text">{row.customer_name}</span>
          <span className="text-xs text-text-3">{row.segment ?? ""}</span>
          <EvidenceExpander evidence={row.evidence} />
        </div>
      ),
    },
    {
      key: "value",
      header: t.dashboard.at_risk.value,
      align: "right",
      render: (row) => formatMoney(row.value),
    },
    {
      key: "baseline",
      header: t.dashboard.at_risk.baseline,
      align: "right",
      render: (row) => formatMoney(row.baseline),
    },
    {
      key: "risk",
      header: t.dashboard.at_risk.risk,
      align: "right",
      render: (row) => <RiskBadge band={row.risk_band} />,
    },
  ]

  const lostColumns: Column<LostArticleRow>[] = [
    {
      key: "article",
      header: t.dashboard.lost_articles.article,
      render: (row) => (
        <div className="flex flex-col gap-1">
          <span className="font-medium text-text">{row.article_name}</span>
          <span className="text-xs text-text-3">{row.article_code}</span>
          <EvidenceExpander evidence={row.evidence} />
        </div>
      ),
    },
    {
      key: "customer",
      header: t.dashboard.lost_articles.customer,
      render: (row) => <span className="text-text-2">{row.customer_name}</span>,
    },
    {
      key: "last_seen",
      header: t.dashboard.lost_articles.last_seen,
      align: "right",
      render: (row) => formatDate(row.last_seen),
    },
    {
      key: "gap",
      header: t.dashboard.lost_articles.gap,
      align: "right",
      render: (row) => row.gap_days ?? "—",
    },
  ]

  return (
    <div className="flex flex-col gap-4">
      {/* Row 1: header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-[26px] font-semibold leading-tight text-text">
            {t.dashboard.title}
          </h1>
          <p className="text-sm text-text-2">{t.dashboard.subtitle}</p>
        </div>
        <DateRangePicker range={range} onChange={setRange} />
      </div>

      {isError && <ErrorState onRetry={() => refetch()} />}

      {/* Row 2: KPI row */}
      <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(230px, 1fr))" }}>
        {isLoading &&
          Array.from({ length: 4 }).map((_, index) => (
            <Card key={index} className="p-5">
              <CardSkeleton rows={3} />
            </Card>
          ))}
        {data?.kpis.map((tile: KpiTile) => {
          const meta = kpiMeta[tile.key]
          return (
            <StatCard
              key={tile.key}
              label={meta?.label ?? tile.key}
              value={meta?.money ? formatMoney(String(tile.value)) : String(tile.value)}
              delta={tile.delta_pct}
              deltaUnit={tile.delta_unit}
              spark={tile.spark}
              progress={tile.progress}
              icon={meta?.icon}
            />
          )
        })}
      </div>

      {/* Row 3: 8/4 — revenue chart | AI uvidi */}
      <div className="grid gap-4 lg:grid-cols-12">
        <div className="lg:col-span-8">
          <SectionCard title={t.dashboard.revenue_chart.title}>
            {isLoading && <CardSkeleton rows={6} />}
            {data && data.revenue_trend.months.length > 0 && (
              <>
                <ComboChart
                  months={data.revenue_trend.months}
                  revenue={data.revenue_trend.revenue}
                  secondary={data.revenue_trend.secondary}
                />
                <SubStatStrip stats={data.revenue_trend.substats} />
              </>
            )}
            {data && data.revenue_trend.months.length === 0 && <EmptyState />}
          </SectionCard>
        </div>

        <div className="lg:col-span-4">
          <SectionCard title={t.dashboard.insights.title}>
            {isLoading && <CardSkeleton rows={5} />}
            {data && data.ai_insights.length === 0 && (
              <EmptyState message={t.dashboard.insights.empty} />
            )}
            {data && data.ai_insights.length > 0 && (
              <div className="flex flex-col divide-y divide-border">
                {data.ai_insights.map((insight) => (
                  <AIInsightItem
                    key={insight.signal_id}
                    insight={insight}
                    onDismiss={setDismissTarget}
                  />
                ))}
              </div>
            )}
          </SectionCard>
        </div>
      </div>

      {/* Row 4: 6/6 — at-risk | lost articles */}
      <div className="grid gap-4 lg:grid-cols-2">
        <SectionCard title={t.dashboard.at_risk.title}>
          {isLoading && <CardSkeleton rows={5} />}
          {data && data.customers_at_risk.length === 0 && <EmptyState />}
          {data && data.customers_at_risk.length > 0 && (
            <DataTable
              columns={atRiskColumns}
              rows={data.customers_at_risk}
              rowKey={(row) => row.signal_id}
              footer={
                <Link to="/kupci" className="text-sm font-medium text-primary hover:underline">
                  {t.dashboard.at_risk.view_all}
                </Link>
              }
            />
          )}
        </SectionCard>

        <SectionCard title={t.dashboard.lost_articles.title}>
          {isLoading && <CardSkeleton rows={5} />}
          {data && data.lost_articles.length === 0 && <EmptyState />}
          {data && data.lost_articles.length > 0 && (
            <DataTable
              columns={lostColumns}
              rows={data.lost_articles}
              rowKey={(row) => row.signal_id}
              footer={
                <Link to="/artikli" className="text-sm font-medium text-primary hover:underline">
                  {t.dashboard.lost_articles.view_all}
                </Link>
              }
            />
          )}
        </SectionCard>
      </div>

      {/* Row 5: 6/6 — rep activity (Phase 2 placeholder) | owner report summary */}
      <div className="grid gap-4 lg:grid-cols-2">
        <SectionCard title={t.dashboard.rep_activity.title}>
          {/* Honest Phase-2 placeholder (ui-design §2) — never fake data */}
          <EmptyState message={t.dashboard.rep_activity.phase2} />
        </SectionCard>

        <SectionCard title={t.dashboard.owner_report.title}>
          {isLoading && <CardSkeleton rows={5} />}
          {data && !data.owner_report_summary && (
            <EmptyState message={t.dashboard.owner_report.empty} />
          )}
          {data?.owner_report_summary && (
            <OwnerReportSummary summary={data.owner_report_summary} />
          )}
        </SectionCard>
      </div>

      {/* Dismissing an insight opens the RuleCard (M10): reason → proposal → apply/undo */}
      <RuleCard
        insight={dismissTarget}
        open={dismissTarget !== null}
        onClose={() => setDismissTarget(null)}
      />
    </div>
  )
}
