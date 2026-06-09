/**
 * AppShell: TopBar + Sidebar + routed content (ui-design §5/§6 layout).
 */
import { Outlet } from "react-router"

import { ToastProvider } from "@/components/ui/toast"

import { Sidebar } from "./Sidebar"
import { TopBar } from "./TopBar"

export function AppShell() {
  return (
    <ToastProvider>
      <div className="flex min-h-svh flex-col bg-bg">
        <TopBar />
        <div className="flex flex-1">
          <Sidebar />
          <main className="mx-auto w-full max-w-[1180px] flex-1 p-6">
            <Outlet />
          </main>
        </div>
      </div>
    </ToastProvider>
  )
}
