/**
 * CaptureChip (CI1, §6): the in-chat transparency affordance. VALERI captures
 * knowledge from a message in the background; this quietly says so and links to
 * the review queue (Zabilješke) where proposed items are confirmed.
 */
import { Sparkles } from "lucide-react"
import { Link } from "react-router"

import { useT } from "@/lib/i18n"

export function CaptureChip() {
  const t = useT()
  return (
    <Link
      to="/zabiljeske"
      className="inline-flex items-center gap-1 text-[11.5px] text-text-3 hover:text-primary"
      data-testid="capture-chip"
    >
      <Sparkles className="h-3 w-3" />
      {t.kb.captured} · {t.kb.review_link}
    </Link>
  )
}
