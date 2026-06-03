/**
 * CaptureChip (CI1, §6): the in-chat transparency affordance. After a message,
 * VALERI shows inline what it captured ("VALERI je zabilježio: …") with a link to
 * the review queue (Zabilješke). Driven by the chat 'capture' SSE event — it only
 * appears when something was actually captured.
 */
import { Sparkles } from "lucide-react"
import { Link } from "react-router"

import { useT } from "@/lib/i18n"

export interface CaptureContent {
  titles: string[]
  autoSaved: number
  proposed: number
  clarifications: number
}

export function CaptureChip({ content }: { content?: CaptureContent }) {
  const t = useT()
  const titles = content?.titles ?? []
  const clarifications = content?.clarifications ?? 0

  return (
    <Link
      to="/zabiljeske"
      className="inline-flex flex-wrap items-center gap-1 text-[11.5px] text-text-3 hover:text-primary"
      data-testid="capture-chip"
    >
      <Sparkles className="h-3 w-3 shrink-0" />
      {titles.length > 0 ? (
        <span data-testid="capture-titles">
          {t.kb.captured_prefix}: {titles.join(", ")}
        </span>
      ) : (
        <span>{t.kb.captured}</span>
      )}
      {clarifications > 0 && (
        <span>
          · {clarifications} {t.kb.questions}
        </span>
      )}
      <span>· {t.kb.review_link}</span>
    </Link>
  )
}
