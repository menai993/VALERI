/**
 * AuthGuard: protected routes require a session (/auth/me succeeds).
 * Unauthenticated users are sent to /login; the httpOnly cookie carries the session.
 */
import { Navigate, Outlet } from "react-router"

import { CardSkeleton } from "@/components/widgets/CardState"
import { useMe } from "@/lib/api/queries"

export function AuthGuard() {
  const { data: user, isLoading, isError } = useMe()

  if (isLoading) {
    return (
      <div className="flex min-h-svh items-center justify-center bg-bg p-6">
        <div className="w-full max-w-sm">
          <CardSkeleton rows={4} />
        </div>
      </div>
    )
  }

  if (isError || !user) {
    return <Navigate to="/login" replace />
  }

  return <Outlet />
}
