import { useEffect, useState } from "react"

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"

type HealthState = "checking" | "ok" | "unavailable"

/**
 * M0 placeholder shell. The owner command dashboard (Početna) lands in M8
 * per docs/frontend-spec.md; this page only proves the toolchain: Vite +
 * React + Tailwind tokens + shadcn/ui components + the /api proxy.
 */
function App() {
  const [apiStatus, setApiStatus] = useState<HealthState>("checking")

  useEffect(() => {
    let cancelled = false
    fetch("/api/health")
      .then((res) => res.json())
      .then((body: { status: string; db: string }) => {
        if (!cancelled) setApiStatus(body.status === "ok" ? "ok" : "unavailable")
      })
      .catch(() => {
        if (!cancelled) setApiStatus("unavailable")
      })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <main className="flex min-h-svh items-center justify-center bg-bg p-6">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle className="text-[26px] font-semibold leading-tight">
            VALERI
          </CardTitle>
          <CardDescription>
            AI poslovni operativni sloj — sistem je pokrenut.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-between border-t pt-4">
            <span className="text-sm text-text-2">API status</span>
            <span
              className={
                apiStatus === "ok"
                  ? "rounded-sm bg-register-akcija-bg px-2 py-0.5 text-xs font-medium text-register-akcija-text"
                  : apiStatus === "checking"
                    ? "rounded-sm bg-surface-2 px-2 py-0.5 text-xs font-medium text-text-3"
                    : "rounded-sm bg-risk-high/10 px-2 py-0.5 text-xs font-medium text-risk-high"
              }
            >
              {apiStatus === "ok"
                ? "povezan"
                : apiStatus === "checking"
                  ? "provjera…"
                  : "nedostupan"}
            </span>
          </div>
          <p className="mt-4 text-xs text-text-3">
            Komandna tabla (Početna) stiže u milestone-u M8.
          </p>
        </CardContent>
      </Card>
    </main>
  )
}

export default App
