/**
 * ThemeProvider: applies the .dark class on <html> from the Zustand theme store.
 * Initial theme follows prefers-color-scheme; the toggle lives in the ProfileMenu.
 * No localStorage — theme persists for the session only (CLAUDE.md).
 */
import { useEffect, type ReactNode } from "react"

import { useThemeStore } from "@/store/ui"

export function ThemeProvider({ children }: { children: ReactNode }) {
  const theme = useThemeStore((state) => state.theme)

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark")
  }, [theme])

  return children
}
