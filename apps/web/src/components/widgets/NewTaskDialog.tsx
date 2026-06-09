/**
 * NewTaskDialog (P1): the "Novi zadatak" quick action — a MANUAL task
 * (user data, no signal/AI envelope) via POST /tasks. A sales_rep is
 * self-assigned server-side; owner/admin pick the assignee.
 */
import { useState } from "react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useToast } from "@/components/ui/toast"
import { useCreateTask, useMe, useReps } from "@/lib/api/queries"
import { useT } from "@/lib/i18n"

export function NewTaskDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const t = useT()
  const toast = useToast()
  const { data: user } = useMe()
  const { data: reps } = useReps()
  const create = useCreateTask()
  const [title, setTitle] = useState("")
  const [body, setBody] = useState("")
  const [assignee, setAssignee] = useState("")
  const [due, setDue] = useState("")

  const isRep = user?.role === "sales_rep"

  function submit() {
    const assigneeId = isRep ? (user?.sales_rep_id ?? 0) : Number(assignee)
    if (title.trim().length < 2 || !assigneeId) return
    create.mutate(
      {
        title: title.trim(),
        body: body.trim() || undefined,
        assignee_id: assigneeId,
        due_date: due || undefined,
      },
      {
        onSuccess: () => {
          toast(t.new_task.created)
          setTitle("")
          setBody("")
          setAssignee("")
          setDue("")
          onClose()
        },
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={(value) => !value && onClose()}>
      <DialogContent data-testid="new-task-dialog">
        <DialogHeader>
          <DialogTitle>{t.new_task.title}</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1">
            <Label htmlFor="task-title">{t.new_task.task_title}</Label>
            <Input
              id="task-title"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
            />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="task-body">{t.new_task.body}</Label>
            <Input id="task-body" value={body} onChange={(event) => setBody(event.target.value)} />
          </div>
          {!isRep && (
            <div className="flex flex-col gap-1">
              <Label htmlFor="task-assignee">{t.new_task.assignee}</Label>
              <select
                id="task-assignee"
                value={assignee}
                onChange={(event) => setAssignee(event.target.value)}
                className="h-9 rounded-md border bg-surface px-3 text-sm"
              >
                <option value="">—</option>
                {reps?.items.map((rep) => (
                  <option key={rep.id} value={rep.id}>
                    {rep.name}
                  </option>
                ))}
              </select>
            </div>
          )}
          <div className="flex flex-col gap-1">
            <Label htmlFor="task-due">{t.new_task.due}</Label>
            <Input
              id="task-due"
              type="date"
              value={due}
              onChange={(event) => setDue(event.target.value)}
            />
          </div>
        </div>
        <DialogFooter>
          <Button
            variant="primary"
            onClick={submit}
            disabled={create.isPending}
            data-testid="create-task-submit"
          >
            {t.new_task.create}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
