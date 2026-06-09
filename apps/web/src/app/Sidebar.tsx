/**
 * Sidebar (ui-design §5): nav sections + the "Brze akcije" block.
 * P1: Odobrenja entry (owner/admin) with a pending count, a Zabilješke badge,
 * and WIRED quick actions (Nova analiza → investigation dialog, Novi zadatak →
 * task dialog, Pitaj VALERI → chat).
 */
import { useState } from "react"
import {
  Briefcase,
  CheckSquare,
  ClipboardList,
  FileBarChart,
  Home,
  MessageSquare,
  NotebookPen,
  Package,
  Plus,
  Search,
  Settings,
  Upload,
  Users,
} from "lucide-react"
import { NavLink, useNavigate } from "react-router"

import { useT } from "@/lib/i18n"
import { useInboxSummary, useMe } from "@/lib/api/queries"
import { cn } from "@/lib/utils"

import { InvestigationDialog } from "@/components/widgets/InvestigationDialog"
import { NewTaskDialog } from "@/components/widgets/NewTaskDialog"

function CountBadge({ count }: { count: number }) {
  if (count <= 0) return null
  return (
    <span
      className="tnum flex h-5 min-w-5 items-center justify-center rounded-full bg-primary px-1 text-[11px] font-semibold text-white"
      data-testid="nav-count-badge"
    >
      {count}
    </span>
  )
}

export function Sidebar() {
  const t = useT()
  const navigate = useNavigate()
  const { data: user } = useMe()
  const { data: inbox } = useInboxSummary()
  const [taskDialogOpen, setTaskDialogOpen] = useState(false)
  const [analysisDialogOpen, setAnalysisDialogOpen] = useState(false)
  const isRep = user?.role === "sales_rep"
  const isAdmin = user?.role === "admin"
  const isApprover = user?.role === "owner" || isAdmin

  const zabiljeskeCount = (inbox?.pending_clarifications ?? 0) + (inbox?.proposed_kb_items ?? 0)

  // Reps land on tasks; finance/owner/admin see the full nav (RBAC-aware menu).
  const items = [
    ...(isRep ? [] : [{ to: "/", label: t.nav.pocetna, icon: Home, end: true }]),
    { to: "/zadaci", label: t.nav.zadaci, icon: ClipboardList },
    { to: "/kupci", label: t.nav.kupci, icon: Users },
    { to: "/artikli", label: t.nav.artikli, icon: Package },
    { to: "/prilike", label: t.nav.prilike, icon: Briefcase },
    ...(isRep ? [] : [{ to: "/ai-report", label: t.nav.ai_report, icon: FileBarChart }]),
    ...(isApprover
      ? [
          {
            to: "/odobrenja",
            label: t.nav.odobrenja,
            icon: CheckSquare,
            count: inbox?.pending_approvals ?? 0,
          },
        ]
      : []),
    { to: "/zabiljeske", label: t.nav.zabiljeske, icon: NotebookPen, count: zabiljeskeCount },
    ...(isAdmin ? [{ to: "/uvoz", label: t.nav.uvoz, icon: Upload }] : []),
    { to: "/postavke", label: t.nav.postavke, icon: Settings },
  ]

  const quickActionClass =
    "flex items-center gap-3 rounded-md px-3 py-2 text-sm text-text-2 transition-colors hover:bg-surface-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary"

  return (
    <aside className="flex w-[212px] shrink-0 flex-col border-r bg-surface">
      <nav className="flex flex-1 flex-col gap-1 p-3">
        {items.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={"end" in item ? item.end : false}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                "focus:outline-none focus-visible:ring-2 focus-visible:ring-primary",
                isActive
                  ? "bg-primary-soft font-medium text-primary"
                  : "text-text-2 hover:bg-surface-2",
              )
            }
          >
            <item.icon className="h-[18px] w-[18px]" />
            <span className="flex-1">{item.label}</span>
            {"count" in item && <CountBadge count={item.count ?? 0} />}
          </NavLink>
        ))}
      </nav>

      <div className="border-t p-3">
        <p className="px-3 pb-2 text-[11.5px] font-medium uppercase tracking-wide text-text-3">
          {t.nav.quick_actions}
        </p>
        <div className="flex flex-col gap-1">
          <button
            type="button"
            onClick={() => setAnalysisDialogOpen(true)}
            data-testid="quick-action-analysis"
            className={quickActionClass}
          >
            <span className="flex h-5 w-5 items-center justify-center rounded-full border">
              <Search className="h-3 w-3" />
            </span>
            {t.nav.nova_analiza}
          </button>
          <button
            type="button"
            onClick={() => setTaskDialogOpen(true)}
            data-testid="quick-action-task"
            className={quickActionClass}
          >
            <span className="flex h-5 w-5 items-center justify-center rounded-full border">
              <Plus className="h-3 w-3" />
            </span>
            {t.nav.novi_zadatak}
          </button>
          {/* Pitaj VALERI → the M9 chat screen */}
          <button
            type="button"
            onClick={() => navigate("/chat")}
            data-testid="quick-action-chat"
            className={quickActionClass}
          >
            <span className="flex h-5 w-5 items-center justify-center rounded-full border">
              <MessageSquare className="h-3 w-3" />
            </span>
            {t.nav.pitaj_valeri}
          </button>
        </div>
      </div>

      <NewTaskDialog open={taskDialogOpen} onClose={() => setTaskDialogOpen(false)} />
      <InvestigationDialog open={analysisDialogOpen} onClose={() => setAnalysisDialogOpen(false)} />
    </aside>
  )
}
