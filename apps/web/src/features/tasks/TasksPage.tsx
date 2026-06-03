/**
 * Zadaci (frontend-spec §5): the prioritized task stack — title, AI body,
 * evidence, proposed action, due date, status controls + feedback.
 */
import { useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { CardSkeleton, EmptyState, ErrorState } from "@/components/widgets/CardState"
import { ConfidenceLabel } from "@/components/widgets/ConfidenceLabel"
import { EvidenceExpander } from "@/components/widgets/EvidenceExpander"
import { RegisterChip } from "@/components/widgets/RegisterChip"
import {
  useTaskFeedbackMutation,
  useTasks,
  useTaskStatusMutation,
} from "@/lib/api/queries"
import type { TaskRow } from "@/lib/api/types"
import { formatDate } from "@/lib/format"
import { useT } from "@/lib/i18n"

function TaskCard({ task }: { task: TaskRow }) {
  const t = useT()
  const statusMutation = useTaskStatusMutation()
  const feedbackMutation = useTaskFeedbackMutation()
  const [feedbackSent, setFeedbackSent] = useState(false)

  return (
    <Card className="flex flex-col gap-3 p-5" data-testid="task-card">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex flex-col gap-1">
          <div className="flex flex-wrap items-center gap-2">
            <RegisterChip register={task.register} />
            <Badge>{t.tasks.status[task.status]}</Badge>
            {task.rule && (
              <Badge variant="outline">
                {t.rules[task.rule as keyof typeof t.rules] ?? task.rule}
              </Badge>
            )}
          </div>
          <h3 className="text-[15px] font-medium text-text">{task.title}</h3>
          {task.conf_band && <ConfidenceLabel band={task.conf_band} />}
        </div>
        <div className="text-right text-sm">
          <p className="text-text-3">{t.tasks.due}</p>
          <p className="tnum font-medium text-text">{formatDate(task.due_date)}</p>
        </div>
      </div>

      {task.body && <p className="whitespace-pre-line text-sm text-text-2">{task.body}</p>}

      {task.evidence && <EvidenceExpander evidence={task.evidence} />}

      {task.proposed_action && (
        <div className="rounded-md bg-surface-2 p-3 text-sm">
          <span className="font-medium text-text-2">{t.tasks.proposed_action}: </span>
          <span className="text-text-2">{task.proposed_action}</span>
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-2 border-t pt-3">
        <div className="flex gap-2">
          {task.status === "open" && (
            <Button
              size="sm"
              variant="primary"
              onClick={() => statusMutation.mutate({ taskId: task.id, status: "in_progress" })}
            >
              {t.tasks.mark_in_progress}
            </Button>
          )}
          {task.status === "in_progress" && (
            <Button
              size="sm"
              variant="positive"
              onClick={() => statusMutation.mutate({ taskId: task.id, status: "done" })}
            >
              {t.tasks.mark_done}
            </Button>
          )}
          {(task.status === "open" || task.status === "in_progress") && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => statusMutation.mutate({ taskId: task.id, status: "dismissed" })}
            >
              {t.tasks.mark_dismissed}
            </Button>
          )}
        </div>

        {!feedbackSent ? (
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                feedbackMutation.mutate({ taskId: task.id, useful: true })
                setFeedbackSent(true)
              }}
            >
              👍 {t.tasks.feedback_useful}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                feedbackMutation.mutate({ taskId: task.id, useful: false })
                setFeedbackSent(true)
              }}
            >
              👎 {t.tasks.feedback_not_useful}
            </Button>
          </div>
        ) : (
          <span className="text-xs text-text-3">✓</span>
        )}
      </div>
    </Card>
  )
}

export function TasksPage() {
  const t = useT()
  const [statusFilter, setStatusFilter] = useState<string>("open")
  const { data, isLoading, isError, refetch } = useTasks(
    statusFilter === "all" ? {} : { status: statusFilter },
  )

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-[26px] font-semibold leading-tight text-text">{t.tasks.title}</h1>
          <p className="text-sm text-text-2">{t.tasks.subtitle}</p>
        </div>

        <Select value={statusFilter} onValueChange={setStatusFilter}>
          <SelectTrigger className="w-44">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">{t.tasks.filter_all}</SelectItem>
            <SelectItem value="open">{t.tasks.status.open}</SelectItem>
            <SelectItem value="in_progress">{t.tasks.status.in_progress}</SelectItem>
            <SelectItem value="done">{t.tasks.status.done}</SelectItem>
            <SelectItem value="dismissed">{t.tasks.status.dismissed}</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {isLoading && <CardSkeleton rows={8} />}
      {isError && <ErrorState onRetry={() => refetch()} />}
      {data && data.items.length === 0 && <EmptyState message={t.tasks.empty} />}

      <div className="flex flex-col gap-3">
        {data?.items.map((task) => <TaskCard key={task.id} task={task} />)}
      </div>
    </div>
  )
}
