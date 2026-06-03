/**
 * CardState: explicit loading (skeleton) / empty / error states for every card
 * (ui-design §5 "States").
 */
import { AlertCircle, Inbox } from "lucide-react"

import { Skeleton } from "@/components/ui/skeleton"
import { useT } from "@/lib/i18n"

export function CardSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="flex flex-col gap-3 p-1" data-testid="card-skeleton">
      {Array.from({ length: rows }).map((_, index) => (
        <Skeleton key={index} className="h-5 w-full" />
      ))}
    </div>
  )
}

export function EmptyState({ message }: { message?: string }) {
  const t = useT()
  return (
    <div
      className="flex flex-col items-center gap-2 py-8 text-center text-sm text-text-3"
      data-testid="empty-state"
    >
      <Inbox className="h-6 w-6" />
      {message ?? t.app.empty}
    </div>
  )
}

export function ErrorState({ message, onRetry }: { message?: string; onRetry?: () => void }) {
  const t = useT()
  return (
    <div
      className="flex flex-col items-center gap-2 py-8 text-center text-sm text-down"
      data-testid="error-state"
    >
      <AlertCircle className="h-6 w-6" />
      {message ?? t.app.error}
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="text-xs font-medium text-primary hover:underline"
        >
          {t.app.retry}
        </button>
      )}
    </div>
  )
}
