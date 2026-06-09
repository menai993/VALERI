/**
 * Sidebar (ui-design §5): nav sections + the "Brze akcije" block.
 * MVP quick actions only (Nova analiza, Novi zadatak, Pitaj VALERI);
 * Prilike renders with an "uskoro" marker (Phase 2 honesty, ui-design §2).
 */
import {
  Briefcase,
  ClipboardList,
  FileBarChart,
  Home,
  MessageSquare,
  NotebookPen,
  Package,
  Plus,
  Settings,
  Upload,
  Users,
} from "lucide-react"
import { NavLink, useNavigate } from "react-router"

import { Badge } from "@/components/ui/badge"
import { useT } from "@/lib/i18n"
import { useMe } from "@/lib/api/queries"
import { cn } from "@/lib/utils"

export function Sidebar() {
  const t = useT()
  const navigate = useNavigate()
  const { data: user } = useMe()
  const isRep = user?.role === "sales_rep"
  const isAdmin = user?.role === "admin"

  // Reps land on tasks; finance/owner/admin see the full nav (RBAC-aware menu).
  const items = [
    ...(isRep ? [] : [{ to: "/", label: t.nav.pocetna, icon: Home, end: true }]),
    { to: "/zadaci", label: t.nav.zadaci, icon: ClipboardList },
    { to: "/kupci", label: t.nav.kupci, icon: Users },
    { to: "/artikli", label: t.nav.artikli, icon: Package },
    { to: "/prilike", label: t.nav.prilike, icon: Briefcase, soon: true },
    ...(isRep ? [] : [{ to: "/ai-report", label: t.nav.ai_report, icon: FileBarChart }]),
    { to: "/zabiljeske", label: t.nav.zabiljeske, icon: NotebookPen },
    ...(isAdmin ? [{ to: "/uvoz", label: t.nav.uvoz, icon: Upload }] : []),
    { to: "/postavke", label: t.nav.postavke, icon: Settings },
  ]

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
            {"soon" in item && item.soon && (
              <Badge className="scale-90 text-[10px]">{t.app.soon}</Badge>
            )}
          </NavLink>
        ))}
      </nav>

      <div className="border-t p-3">
        <p className="px-3 pb-2 text-[11.5px] font-medium uppercase tracking-wide text-text-3">
          {t.nav.quick_actions}
        </p>
        <div className="flex flex-col gap-1">
          {[t.nav.nova_analiza, t.nav.novi_zadatak].map((label) => (
            <button
              key={label}
              type="button"
              className="flex items-center gap-3 rounded-md px-3 py-2 text-sm text-text-2 transition-colors hover:bg-surface-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary"
            >
              <span className="flex h-5 w-5 items-center justify-center rounded-full border">
                <Plus className="h-3 w-3" />
              </span>
              {label}
            </button>
          ))}
          {/* Pitaj VALERI → the M9 chat screen */}
          <button
            type="button"
            onClick={() => navigate("/chat")}
            data-testid="quick-action-chat"
            className="flex items-center gap-3 rounded-md px-3 py-2 text-sm text-text-2 transition-colors hover:bg-surface-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary"
          >
            <span className="flex h-5 w-5 items-center justify-center rounded-full border">
              <MessageSquare className="h-3 w-3" />
            </span>
            {t.nav.pitaj_valeri}
          </button>
        </div>
      </div>
    </aside>
  )
}
