/**
 * ActivityPrompt (P1): "Šta je urađeno?" — shown when a task is marked done so
 * the rep logs the activity (poziv/sastanak/…) in the same flow. Skippable;
 * posts to the existing /api/activity (C-CRM2).
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
import { Label } from "@/components/ui/label"
import { useToast } from "@/components/ui/toast"
import { useLogActivity } from "@/lib/api/queries"
import type { TaskRow } from "@/lib/api/types"
import { useT } from "@/lib/i18n"

const ACTIVITY_KINDS = ["call", "meeting", "offer", "follow_up", "analysis"] as const

export function ActivityPrompt({
  task,
  onClose,
}: {
  task: TaskRow | null
  onClose: () => void
}) {
  const t = useT()
  const toast = useToast()
  const logActivity = useLogActivity()
  const [kind, setKind] = useState<string>("call")

  function save() {
    if (!task) return
    logActivity.mutate(
      {
        kind: kind as (typeof ACTIVITY_KINDS)[number],
        customer_id: task.customer_id ?? undefined,
        done: true,
        // owner/admin log on behalf of the task's assignee; a rep is forced to
        // their own sales_rep_id server-side anyway.
        sales_rep_id: task.assignee_id ?? undefined,
      },
      {
        onSuccess: () => {
          toast(t.activity_prompt.saved)
          onClose()
        },
      },
    )
  }

  return (
    <Dialog open={task !== null} onOpenChange={(value) => !value && onClose()}>
      <DialogContent data-testid="activity-prompt">
        <DialogHeader>
          <DialogTitle>{t.activity_prompt.title}</DialogTitle>
        </DialogHeader>
        {task && <p className="text-sm text-text-2">{task.title}</p>}
        <div className="flex flex-col gap-1">
          <Label htmlFor="activity-kind">{t.activity_prompt.kind_label}</Label>
          <select
            id="activity-kind"
            value={kind}
            onChange={(event) => setKind(event.target.value)}
            className="h-9 rounded-md border bg-surface px-3 text-sm"
            data-testid="activity-kind-select"
          >
            {ACTIVITY_KINDS.map((value) => (
              <option key={value} value={value}>
                {t.activity_prompt.kinds[value] ?? value}
              </option>
            ))}
          </select>
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose} data-testid="activity-skip">
            {t.activity_prompt.skip}
          </Button>
          <Button
            variant="positive"
            onClick={save}
            disabled={logActivity.isPending}
            data-testid="activity-save"
          >
            {t.activity_prompt.save}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
