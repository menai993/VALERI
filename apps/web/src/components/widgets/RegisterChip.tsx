/**
 * RegisterChip (ui-design §4/§5): the Analiza/Preporuka/Akcija pill.
 * Required on every AI surface (principle 9) — text + color, never color alone.
 */
import { cn } from "@/lib/utils"
import { useT } from "@/lib/i18n"
import type { Register } from "@/lib/api/types"

const styles: Record<Register, string> = {
  analiza: "bg-register-analiza-bg text-register-analiza-text",
  preporuka: "bg-register-preporuka-bg text-register-preporuka-text",
  akcija: "bg-register-akcija-bg text-register-akcija-text",
}

export function RegisterChip({
  register,
  className,
}: {
  register: Register
  className?: string
}) {
  const t = useT()
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-sm px-2 py-0.5 text-xs font-medium",
        styles[register],
        className,
      )}
    >
      {t.register[register]}
    </span>
  )
}
