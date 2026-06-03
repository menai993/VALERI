/**
 * Istrage (frontend-spec §5, M13): the investigation list + "Nova istraga" form +
 * the report view with the HITL approve/reject panel for needs_input runs.
 */
import { useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { CardSkeleton, EmptyState, ErrorState } from "@/components/widgets/CardState"
import { InvestigationReport } from "@/components/widgets/InvestigationReport"
import {
  useCreateInvestigation,
  useInvestigation,
  useInvestigations,
  useResumeInvestigation,
} from "@/lib/api/queries"
import { ApiRequestError } from "@/lib/api/client"
import type { Investigation, InvestigationStatus } from "@/lib/api/types"
import { formatDate } from "@/lib/format"
import { useT } from "@/lib/i18n"
import { cn } from "@/lib/utils"

const statusStyles: Record<InvestigationStatus, string> = {
  queued: "bg-surface-2 text-text-2",
  running: "bg-register-analiza-bg text-register-analiza-text",
  needs_input: "bg-risk-mid/10 text-risk-mid",
  done: "bg-register-akcija-bg text-register-akcija-text",
  failed: "bg-risk-high/10 text-risk-high",
}

function StatusChip({ status }: { status: InvestigationStatus }) {
  const t = useT()
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-sm px-2 py-0.5 text-xs font-medium",
        statusStyles[status],
      )}
      data-testid="investigation-status"
    >
      {t.investigations.status[status]}
    </span>
  )
}

/** The detail view for one investigation: report, progress, or the HITL decision panel. */
function InvestigationDetailView({
  investigationId,
  onBack,
}: {
  investigationId: number
  onBack: () => void
}) {
  const t = useT()
  const { data, isLoading, isError, refetch } = useInvestigation(investigationId)
  const resume = useResumeInvestigation()

  if (isLoading) return <CardSkeleton rows={8} />
  if (isError) return <ErrorState onRetry={() => refetch()} />
  if (!data) return null

  const status = data.investigation.status

  return (
    <div className="flex flex-col gap-4" data-testid="investigation-detail">
      <button
        type="button"
        onClick={onBack}
        className="self-start text-sm font-medium text-primary hover:underline"
        data-testid="back-to-list"
      >
        {t.investigations.back_to_list}
      </button>

      <Card className="flex flex-col gap-3 p-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <StatusChip status={status} />
          <span className="tnum text-[11.5px] text-text-3">
            {formatDate(data.investigation.created_at)}
          </span>
        </div>
        <p className="text-[15px] font-medium text-text">{data.investigation.question}</p>

        {/* in-progress: the page polls automatically (useInvestigation refetchInterval) */}
        {(status === "queued" || status === "running") && (
          <p className="text-sm text-text-2" data-testid="running-note">
            {t.investigations.running_note}
          </p>
        )}

        {status === "failed" && (
          <p className="text-sm text-down" data-testid="failed-note">
            {t.investigations.failed_note}
          </p>
        )}

        {/* the HITL decision panel — nothing executes until the human decides */}
        {status === "needs_input" && (
          <div
            className="flex flex-col gap-3 rounded-md bg-risk-mid/10 p-4"
            data-testid="hitl-panel"
          >
            <p className="text-sm font-medium text-text">{t.investigations.pending_title}</p>
            {data.pending_actions.map((action, index) => (
              <div key={index} className="rounded-md bg-surface p-3 text-sm text-text-2">
                <Badge>{String(action.tool)}</Badge>
                <p className="mt-1">{String((action.params as Record<string, unknown>)?.title ?? "")}</p>
              </div>
            ))}
            <div className="flex gap-2">
              <Button
                variant="positive"
                size="sm"
                onClick={() =>
                  resume.mutate({ investigationId: data.investigation.id, decision: "approve" })
                }
                disabled={resume.isPending}
                data-testid="approve-actions"
              >
                {t.investigations.approve}
              </Button>
              <Button
                variant="default"
                size="sm"
                onClick={() =>
                  resume.mutate({ investigationId: data.investigation.id, decision: "reject" })
                }
                disabled={resume.isPending}
                data-testid="reject-actions"
              >
                {t.investigations.reject}
              </Button>
            </div>
          </div>
        )}

        {/* the finished report */}
        {data.report && <InvestigationReport report={data.report} steps={data.steps} />}
      </Card>
    </div>
  )
}

export function InvestigationsTab() {
  const t = useT()
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [question, setQuestion] = useState("")
  const investigations = useInvestigations()
  const createInvestigation = useCreateInvestigation()

  if (selectedId !== null) {
    return (
      <InvestigationDetailView investigationId={selectedId} onBack={() => setSelectedId(null)} />
    )
  }

  function start() {
    if (question.trim().length < 10) return
    createInvestigation.mutate(
      { question: question.trim() },
      {
        onSuccess: (created) => {
          setQuestion("")
          setSelectedId(created.investigation_id)
        },
      },
    )
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Nova istraga */}
      <Card className="flex flex-col gap-3 p-5" data-testid="new-investigation-form">
        <h2 className="text-[17px] font-semibold text-text">{t.investigations.new_title}</h2>
        <div className="flex flex-col gap-2">
          <Label htmlFor="investigation-question">{t.investigations.question_label}</Label>
          <Input
            id="investigation-question"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder={t.investigations.question_placeholder}
          />
        </div>
        <Button
          variant="primary"
          className="self-start"
          onClick={start}
          disabled={createInvestigation.isPending || question.trim().length < 10}
          data-testid="start-investigation"
        >
          {t.investigations.start}
        </Button>
      </Card>

      {/* the list */}
      <Card className="flex flex-col gap-3 p-5" data-testid="investigation-list">
        <h2 className="text-[17px] font-semibold text-text">{t.investigations.title}</h2>
        {investigations.isLoading && <CardSkeleton rows={4} />}
        {investigations.isError &&
          (investigations.error instanceof ApiRequestError &&
          investigations.error.status === 403 ? (
            <EmptyState message={t.app.forbidden} />
          ) : (
            <ErrorState onRetry={() => investigations.refetch()} />
          ))}
        {investigations.data && investigations.data.items.length === 0 && (
          <EmptyState message={t.investigations.empty} />
        )}
        {investigations.data && investigations.data.items.length > 0 && (
          <div className="flex flex-col divide-y divide-border">
            {investigations.data.items.map((investigation: Investigation) => (
              <button
                key={investigation.id}
                type="button"
                onClick={() => setSelectedId(investigation.id)}
                className="flex flex-wrap items-center justify-between gap-2 py-3 text-left hover:bg-surface-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary"
                data-testid="investigation-row"
              >
                <span className="min-w-0 flex-1 truncate text-sm font-medium text-text">
                  {investigation.question}
                </span>
                <div className="flex items-center gap-2">
                  <StatusChip status={investigation.status} />
                  <span className="tnum text-[11.5px] text-text-3">
                    {formatDate(investigation.created_at)}
                  </span>
                </div>
              </button>
            ))}
          </div>
        )}
      </Card>
    </div>
  )
}
