/**
 * DateRangePicker (ui-design §5): the range presets dropdown (Danas / 30d / 90d / 12m).
 */
import { Calendar } from "lucide-react"

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { useT } from "@/lib/i18n"

export type RangePreset = "1d" | "30d" | "90d" | "12m"

export function DateRangePicker({
  range,
  onChange,
}: {
  range: RangePreset
  onChange: (range: RangePreset) => void
}) {
  const t = useT()
  return (
    <Select value={range} onValueChange={(value) => onChange(value as RangePreset)}>
      <SelectTrigger className="w-48" data-testid="date-range-picker">
        <span className="flex items-center gap-2">
          <Calendar className="h-4 w-4 text-text-3" />
          <SelectValue />
        </span>
      </SelectTrigger>
      <SelectContent>
        {(["1d", "30d", "90d", "12m"] as const).map((preset) => (
          <SelectItem key={preset} value={preset}>
            {t.dashboard.range[preset]}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
