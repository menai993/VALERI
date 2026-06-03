/**
 * ClarificationCard (CI1, §8.3): one short question VALERI asks instead of guessing,
 * with tappable options (link to a candidate / not-a-match / new customer).
 */
import { HelpCircle } from "lucide-react"

import { Button } from "@/components/ui/button"
import type { KbClarification, KbClarificationOption } from "@/lib/api/types"

export interface ClarificationCardProps {
  clarification: KbClarification
  onAnswer: (clarificationId: number, option: KbClarificationOption) => void
}

export function ClarificationCard({ clarification, onAnswer }: ClarificationCardProps) {
  return (
    <div
      className="flex flex-col gap-2 rounded-md border border-border bg-surface-2 p-3"
      data-testid="clarification-card"
    >
      <div className="flex items-start gap-2">
        <HelpCircle className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
        <span className="text-sm text-text">{clarification.question}</span>
      </div>
      <div className="flex flex-wrap gap-2 pl-6">
        {clarification.options.map((option, index) => (
          <Button
            key={index}
            size="sm"
            variant={option.action === "link" ? "primary" : "default"}
            onClick={() => onAnswer(clarification.id, option)}
          >
            {option.label}
          </Button>
        ))}
      </div>
    </div>
  )
}
