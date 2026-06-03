/**
 * Prilike: the Phase-2 CRM pipeline placeholder (ui-design §2 — labeled "uskoro",
 * never fake pipeline data).
 */
import { Briefcase } from "lucide-react"

import { Card } from "@/components/ui/card"
import { useT } from "@/lib/i18n"

export function OpportunitiesPage() {
  const t = useT()
  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-[26px] font-semibold leading-tight text-text">
          {t.opportunities.title}
        </h1>
      </div>
      <Card className="flex flex-col items-center gap-3 p-12 text-center">
        <Briefcase className="h-8 w-8 text-text-3" />
        <p className="text-sm text-text-2">{t.opportunities.phase2}</p>
        <span className="rounded-sm bg-surface-2 px-2 py-0.5 text-xs font-medium text-text-3">
          {t.app.soon}
        </span>
      </Card>
    </div>
  )
}
