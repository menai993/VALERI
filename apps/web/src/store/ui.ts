/**
 * UI state (Zustand): theme, language, ephemeral UI state.
 *
 * Nothing here touches localStorage/sessionStorage (CLAUDE.md) — theme and
 * language live for the session; the initial theme follows prefers-color-scheme.
 */
import { create } from "zustand"

// ── theme ─────────────────────────────────────────────────────────────────────

type Theme = "light" | "dark"

function systemTheme(): Theme {
  if (typeof window !== "undefined" && window.matchMedia?.("(prefers-color-scheme: dark)").matches) {
    return "dark"
  }
  return "light"
}

interface ThemeState {
  theme: Theme
  setTheme: (theme: Theme) => void
  toggleTheme: () => void
}

export const useThemeStore = create<ThemeState>((set) => ({
  theme: systemTheme(),
  setTheme: (theme) => set({ theme }),
  toggleTheme: () => set((state) => ({ theme: state.theme === "dark" ? "light" : "dark" })),
}))

// ── language (bs default, en toggle) ─────────────────────────────────────────

type Language = "bs" | "en"

interface LanguageState {
  language: Language
  setLanguage: (language: Language) => void
  toggleLanguage: () => void
}

export const useLanguageStore = create<LanguageState>((set) => ({
  language: "bs",
  setLanguage: (language) => set({ language }),
  toggleLanguage: () => set((state) => ({ language: state.language === "bs" ? "en" : "bs" })),
}))

// ── ephemeral UI state ────────────────────────────────────────────────────────

interface UiState {
  sidebarOpen: boolean
  setSidebarOpen: (open: boolean) => void
}

export const useUiStore = create<UiState>((set) => ({
  sidebarOpen: true,
  setSidebarOpen: (open) => set({ sidebarOpen: open }),
}))
