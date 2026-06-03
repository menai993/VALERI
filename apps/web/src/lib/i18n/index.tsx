/**
 * i18n provider (frontend-spec §6): bs default, en toggle.
 *
 * All UI strings come from the catalogs — components never hard-code Bosnian.
 * The language lives in Zustand app state (no localStorage, per CLAUDE.md).
 */
/* eslint-disable react-refresh/only-export-components -- provider + hook belong together */
import { createContext, useContext, type ReactNode } from "react"

import { useLanguageStore } from "@/store/ui"

import { bs, type StringCatalog } from "./bs"
import { en } from "./en"

const catalogs: Record<string, StringCatalog> = { bs, en }

const I18nContext = createContext<StringCatalog>(bs)

export function I18nProvider({ children }: { children: ReactNode }) {
  const language = useLanguageStore((state) => state.language)
  return (
    <I18nContext.Provider value={catalogs[language] ?? bs}>{children}</I18nContext.Provider>
  )
}

/** The active string catalog: `const t = useT(); t.nav.pocetna`. */
export function useT(): StringCatalog {
  return useContext(I18nContext)
}
