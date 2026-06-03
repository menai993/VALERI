/**
 * AI Report (frontend-spec §5): Sedmični izvještaj (live, M7 data) +
 * "Šta je VALERI naučio" (live, M11) + Istrage (live, M13).
 */
import { Card } from "@/components/ui/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { CardSkeleton, EmptyState, ErrorState } from "@/components/widgets/CardState"
import { EvidenceExpander } from "@/components/widgets/EvidenceExpander"
import { RegisterChip } from "@/components/widgets/RegisterChip"
import { useWeeklyReport } from "@/lib/api/queries"
import { ApiRequestError } from "@/lib/api/client"
import { formatDate } from "@/lib/format"
import { useT } from "@/lib/i18n"

import { InvestigationsTab } from "./InvestigationsTab"
import { LearnedTab } from "./LearnedTab"

function WeeklyReportTab() {
  const t = useT()
  const { data, isLoading, isError, error, refetch } = useWeeklyReport()

  if (isLoading) return <CardSkeleton rows={10} />
  if (isError) {
    // A 404 means no report yet (it runs Sunday night) — that's an empty state, not an error.
    if (error instanceof ApiRequestError && error.status === 404) {
      return <EmptyState message={t.ai_report.no_report} />
    }
    return <ErrorState onRetry={() => refetch()} />
  }
  if (!data) return <EmptyState message={t.ai_report.no_report} />

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-text-2">
        {t.ai_report.week}: <span className="tnum">{formatDate(data.week_start)}</span> —{" "}
        <span className="tnum">{formatDate(data.week_end)}</span> · {t.ai_report.generated}:{" "}
        <span className="tnum">{formatDate(data.generated_at)}</span>
      </p>

      {data.sections.map((section) => (
        <Card key={section.key} className="flex flex-col gap-3 p-5" data-testid="report-section">
          <div className="flex items-center gap-2">
            <RegisterChip register={section.register} />
            <h2 className="text-[17px] font-semibold text-text">{section.title}</h2>
          </div>
          <p className="whitespace-pre-line text-sm text-text-2">{section.narrative}</p>
          <EvidenceExpander evidence={section.data} />
        </Card>
      ))}
    </div>
  )
}

export function AIReportPage() {
  const t = useT()
  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-[26px] font-semibold leading-tight text-text">
          {t.ai_report.title}
        </h1>
        <p className="text-sm text-text-2">{t.ai_report.subtitle}</p>
      </div>

      <Tabs defaultValue="weekly">
        <TabsList>
          <TabsTrigger value="weekly">{t.ai_report.tab_weekly}</TabsTrigger>
          <TabsTrigger value="learned">{t.ai_report.tab_learned}</TabsTrigger>
          <TabsTrigger value="investigations">{t.ai_report.tab_investigations}</TabsTrigger>
        </TabsList>

        <TabsContent value="weekly">
          <WeeklyReportTab />
        </TabsContent>

        {/* M11: the learning loop, transparent — rules + the decision feed. */}
        <TabsContent value="learned">
          <LearnedTab />
        </TabsContent>

        {/* M13: the investigation agent — list, new-investigation form, reports. */}
        <TabsContent value="investigations">
          <InvestigationsTab />
        </TabsContent>
      </Tabs>
    </div>
  )
}
