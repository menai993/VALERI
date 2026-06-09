/**
 * TopBar (ui-design §5): brand, global search (chat entry in M9), notifications,
 * profile menu with theme/language toggles and logout.
 */
import { useState } from "react"

import { Bell, ChevronDown, Globe, LogOut, Moon, Search, Sun } from "lucide-react"
import { useNavigate } from "react-router"

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { useInboxSummary, useLogout, useMe } from "@/lib/api/queries"
import { useT } from "@/lib/i18n"
import { useLanguageStore, useThemeStore } from "@/store/ui"

export function TopBar() {
  const t = useT()
  const navigate = useNavigate()
  const [search, setSearch] = useState("")
  const { data: user } = useMe()
  const logout = useLogout()
  const { theme, toggleTheme } = useThemeStore()
  const { data: inbox } = useInboxSummary()
  const { language, toggleLanguage } = useLanguageStore()

  const roleLabel = user ? t.settings.roles[user.role] : ""

  return (
    <header className="flex h-16 items-center justify-between gap-4 border-b bg-surface px-6">
      <div className="flex items-center gap-6">
        <span className="text-lg font-bold tracking-tight text-text">VALERI</span>
      </div>

      {/* GlobalSearch doubles as the Ask-VALERI entry: submitting routes to chat. */}
      <form
        className="relative hidden max-w-md flex-1 md:block"
        onSubmit={(event) => {
          event.preventDefault()
          const query = search.trim()
          if (query) {
            navigate(`/chat?q=${encodeURIComponent(query)}`)
            setSearch("")
          }
        }}
      >
        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-3" />
        <Input
          className="pl-9"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder={t.nav.search_placeholder}
          aria-label={t.nav.search_placeholder}
        />
      </form>

      <div className="flex items-center gap-3">
        {/* P1: the functional inbox bell — badge + per-category dropdown. */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              data-testid="inbox-bell"
              className="relative flex h-9 w-9 items-center justify-center rounded-md text-text-2 transition-colors hover:bg-surface-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary"
              aria-label={t.inbox.aria}
            >
              <Bell className="h-[18px] w-[18px]" />
              {(inbox?.total ?? 0) > 0 && (
                <span
                  className="tnum absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-down px-1 text-[10px] font-semibold text-white"
                  data-testid="inbox-badge"
                >
                  {inbox?.total}
                </span>
              )}
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" data-testid="inbox-dropdown">
            <DropdownMenuLabel>{t.inbox.title}</DropdownMenuLabel>
            <DropdownMenuSeparator />
            {(inbox?.total ?? 0) === 0 && (
              <DropdownMenuItem disabled>{t.inbox.empty}</DropdownMenuItem>
            )}
            {(inbox?.pending_approvals ?? 0) > 0 && (
              <DropdownMenuItem onClick={() => navigate("/odobrenja")}>
                {t.inbox.approvals}: {inbox?.pending_approvals}
              </DropdownMenuItem>
            )}
            {((inbox?.pending_clarifications ?? 0) > 0 || (inbox?.proposed_kb_items ?? 0) > 0) && (
              <DropdownMenuItem onClick={() => navigate("/zabiljeske")}>
                {t.inbox.clarifications}: {(inbox?.pending_clarifications ?? 0) +
                  (inbox?.proposed_kb_items ?? 0)}
              </DropdownMenuItem>
            )}
            {(inbox?.tasks_due_today ?? 0) > 0 && (
              <DropdownMenuItem onClick={() => navigate("/zadaci?due=today")}>
                {t.inbox.due_today}: {inbox?.tasks_due_today}
              </DropdownMenuItem>
            )}
          </DropdownMenuContent>
        </DropdownMenu>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              data-testid="profile-menu"
              className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors hover:bg-surface-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary"
            >
              <span className="flex h-7 w-7 items-center justify-center rounded-full bg-primary-soft text-xs font-semibold text-primary">
                {user?.name?.charAt(0) ?? "?"}
              </span>
              <span className="hidden flex-col items-start leading-tight sm:flex">
                <span className="font-medium text-text">{user?.name}</span>
                <span className="text-[11.5px] text-text-3">{roleLabel}</span>
              </span>
              <ChevronDown className="h-4 w-4 text-text-3" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuLabel>{user?.email}</DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={toggleTheme}>
              {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
              {theme === "dark" ? t.app.theme_light : t.app.theme_dark}
            </DropdownMenuItem>
            <DropdownMenuItem onClick={toggleLanguage} data-testid="language-toggle">
              <Globe className="h-4 w-4" />
              {t.app.language}: {language === "bs" ? "EN" : "BS"}
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onClick={() => logout.mutate(undefined, { onSuccess: () => navigate("/login") })}
            >
              <LogOut className="h-4 w-4" />
              {t.app.logout}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  )
}
