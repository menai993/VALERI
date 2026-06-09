/**
 * InvestigationDialog (P1): one shared "Nova istraga" form — opened from the
 * sidebar quick action, the Istraži button on the customer 360, and the
 * Istrage tab. Starts an async M13 investigation and points at AI Report.
 */
import { useState } from "react"
import { useNavigate } from "react-router"

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
import { useCreateInvestigation } from "@/lib/api/queries"
import { useT } from "@/lib/i18n"

export interface InvestigationDialogProps {
  open: boolean
  onClose: () => void
  /** Prefill, e.g. from the customer 360 Istraži button. */
  defaultQuestion?: string
}

export function InvestigationDialog({ open, onClose, defaultQuestion }: InvestigationDialogProps) {
  const t = useT()
  const toast = useToast()
  const navigate = useNavigate()
  const create = useCreateInvestigation()
  const [question, setQuestion] = useState(defaultQuestion ?? "")
  const [wasOpen, setWasOpen] = useState(open)

  // Render-time adjustment: a fresh open replaces any stale draft with the prefill.
  if (open !== wasOpen) {
    setWasOpen(open)
    if (open) setQuestion(defaultQuestion ?? "")
  }

  function submit() {
    if (question.trim().length < 5) return
    create.mutate(
      { question: question.trim() },
      {
        onSuccess: () => {
          toast(t.new_analysis.started)
          onClose()
          navigate("/ai-report")
        },
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={(value) => !value && onClose()}>
      <DialogContent data-testid="investigation-dialog">
        <DialogHeader>
          <DialogTitle>{t.new_analysis.title}</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-1">
          <Label htmlFor="investigation-question">{t.new_analysis.question}</Label>
          <textarea
            id="investigation-question"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder={t.new_analysis.placeholder}
            rows={3}
            className="rounded-md border bg-surface p-3 text-sm"
          />
        </div>
        <DialogFooter>
          <Button
            variant="primary"
            onClick={submit}
            disabled={create.isPending || question.trim().length < 5}
            data-testid="start-investigation-submit"
          >
            {t.new_analysis.start}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
