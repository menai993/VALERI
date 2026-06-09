/**
 * Zadaci (frontend-spec §5): the prioritized task stack — title, AI body,
 * evidence, proposed action, due date, status controls + feedback.
 */
import { useEffect, useRef, useState } from "react"
import { useSearchParams } from "react-router"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { useToast } from "@/components/ui/toast"
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
import { ActivityPrompt } from "@/components/widgets/ActivityPrompt"
import { RegisterChip } from "@/components/widgets/RegisterChip"
import {
  useTaskFeedbackMutation,
  useTasks,
  useTaskStatusMutation,
} from "@/lib/api/queries"
import type { TaskRow } from "@/lib/api/types"
import { formatDate } from "@/lib/format"
import { useT } from "@/lib/i18n"

function TaskCard({
  task,
  onDone,
  highlighted,
}: {
  task: TaskRow
  onDone: (task: TaskRow) => void
  highlighted?: boolean
}) {
  const t = useT()
  const toast = useToast()
  const statusMutation = useTaskStatusMutation()
  const feedbackMutation = useTaskFeedbackMutation()
  const [feedbackSent, setFeedbackSent] = useState(false)

  function sendFeedback(useful: boolean) {
    feedbackMutation.mutate(
      { taskId: task.id, useful },
      { onSuccess: () => toast(t.tasks.feedback_thanks) },
    )
    setFeedbackSent(true)
  }

  return (
    <Card
      id={`task-${task.id}`}
      className={"flex flex-col gap-3 p-5" + (highlighted ? " ring-2 ring-primary" : "")}
      data-testid="task-card"
    >
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
          {task.customer_name && (
            <span className="text-xs text-text-3">{task.customer_name}</span>
          )}
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
              onClick={() =>
                statusMutation.mutate(
                  { taskId: task.id, status: "done" },
                  { onSuccess: () => onDone(task) },
                )
              }
              data-testid="mark-done"
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
            <Button size="sm" variant="ghost" onClick={() => sendFeedback(true)}>
              👍 {t.tasks.feedback_useful}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => sendFeedback(false)}>
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
  const [searchParams] = useSearchParams()
  const [statusFilter, setStatusFilter] = useState<string>("open")
  const [dueFilter, setDueFilter] = useState<"all" | "today" | "overdue">(
    searchParams.get("due") === "today" ? "today" : "all",
  )
  const [activityTask, setActivityTask] = useState<TaskRow | null>(null)
  const highlightId = searchParams.get("task")
  const scrolledRef = useRef(false)

  const { data, isLoading, isError, refetch } = useTasks({
    ...(statusFilter === "all" || dueFilter !== "all" ? {} : { status: statusFilter }),
    ...(dueFilter !== "all" ? { due: dueFilter } : {}),
  })

  // /zadaci?task={id}: scroll the linked task into view once it renders (P1 D5).
  useEffect(() => {
    if (!highlightId || scrolledRef.current || !data) return
    const element = document.getElementById(`task-${highlightId}`)
    if (element) {
      element.scrollIntoView({ behavior: "smooth", block: "center" })
      scrolledRef.current = true
    }
  }, [highlightId, data])

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-[26px] font-semibold leading-tight text-text">{t.tasks.title}</h1>
          <p className="text-sm text-text-2">{t.tasks.subtitle}</p>
        </div>

        <div className="flex items-center gap-2">
          {(["all", "today", "overdue"] as const).map((value) => (
            <Button
              key={value}
              size="sm"
              variant={dueFilter === value ? "primary" : "default"}
              onClick={() => setDueFilter(value)}
              data-testid={`due-${value}`}
            >
              {value === "all"
                ? t.tasks.due_all
                : value === "today"
                  ? t.tasks.due_today
                  : t.tasks.due_overdue}
            </Button>
          ))}
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
        {data?.items.map((task) => (
          <TaskCard
            key={task.id}
            task={task}
            onDone={setActivityTask}
            highlighted={highlightId === String(task.id)}
          />
        ))}
      </div>

      {/* P1: log what was done in the same flow as completing the task. */}
      <ActivityPrompt task={activityTask} onClose={() => setActivityTask(null)} />
    </div>
  )
}
