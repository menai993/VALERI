/**
 * Minimal toast (P1): context + fixed-position stack, no external dependency.
 * Use for visible confirmations ("Hvala na povratnoj informaciji") instead of
 * silent ✓ marks. Auto-dismisses; success/error variants only.
 */
import { createContext, useCallback, useContext, useMemo, useRef, useState } from "react"

import { cn } from "@/lib/utils"

export interface ToastItem {
  id: number
  message: string
  variant: "success" | "error"
}

const ToastContext = createContext<(message: string, variant?: ToastItem["variant"]) => void>(
  () => {},
)

/** `const toast = useToast(); toast("Sačuvano")` */
export function useToast() {
  return useContext(ToastContext)
}

const TOAST_MS = 3500

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([])
  const nextId = useRef(1)

  const push = useCallback((message: string, variant: ToastItem["variant"] = "success") => {
    const id = nextId.current++
    setItems((previous) => [...previous, { id, message, variant }])
    setTimeout(() => {
      setItems((previous) => previous.filter((item) => item.id !== id))
    }, TOAST_MS)
  }, [])

  const value = useMemo(() => push, [push])

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        className="pointer-events-none fixed bottom-4 right-4 z-50 flex flex-col gap-2"
        data-testid="toast-stack"
        aria-live="polite"
      >
        {items.map((item) => (
          <div
            key={item.id}
            className={cn(
              "pointer-events-auto rounded-md border px-4 py-2 text-sm shadow-card",
              item.variant === "success" && "border-border bg-surface text-text",
              item.variant === "error" && "border-down/40 bg-surface text-down",
            )}
            role="status"
          >
            {item.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}
