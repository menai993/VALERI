/** data-ingest-ui: the admin Uvoz screen — upload 4 files → POST import → report;
 * history lists runs; non-admin is forbidden. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { IngestPage } from "@/features/ingest/IngestPage"
import { I18nProvider } from "@/lib/i18n"
import type { ImportReport, User } from "@/lib/api/types"
import { useLanguageStore } from "@/store/ui"

const adminUser: User = {
  id: 2,
  name: "Administrator",
  email: "admin@ultrahigijena.ba",
  role: "admin",
  sales_rep_id: null,
  preferred_language: "bs",
  created_at: "2026-01-01T00:00:00Z",
}
const ownerUser: User = { ...adminUser, id: 1, role: "owner" }

const report: ImportReport = {
  import_id: 7,
  status: "completed",
  source: "api",
  started_at: "2026-06-04T10:00:00Z",
  finished_at: "2026-06-04T10:00:05Z",
  stats: {
    kupci: { created: 3, updated: 1, unchanged: 0 },
    artikli: { created: 2, updated: 0, unchanged: 5 },
    fakture: { created: 10, updated: 0, unchanged: 0 },
    stavke: { created: 30, replaced: 0, unchanged: 0 },
  },
  quality: {
    duplicate_customer_codes: [],
    duplicate_article_codes: [],
    renamed_articles: [],
    code_swap_candidates: [{ old_code: "A1", new_code: "A2", name: "Sapun", already_mapped: false }],
    missing_segments: [],
    orphan_lines: [],
  },
}

function mockApi(user: User) {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string | URL | Request, _init?: RequestInit) => {
      const path = typeof url === "string" ? url : url instanceof URL ? url.pathname : url.url
      const ok = (body: unknown) =>
        Promise.resolve(
          new Response(JSON.stringify(body), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        )
      if (path.includes("/api/auth/me")) return ok(user)
      if (path.includes("/api/ingest/imports"))
        return ok({ items: [{ import_id: 6, source: "cli", status: "completed", started_at: "2026-06-01T08:00:00Z", finished_at: "2026-06-01T08:00:03Z", stats: null }] })
      if (path.includes("/api/ingest/import"))
        return Promise.resolve(
          new Response(JSON.stringify({ import_id: 7 }), {
            status: 201,
            headers: { "Content-Type": "application/json" },
          }),
        )
      if (path.includes("/api/ingest/report/7")) return ok(report)
      return Promise.resolve(
        new Response(JSON.stringify({ error: { code: "not_found", message: path } }), {
          status: 404,
          headers: { "Content-Type": "application/json" },
        }),
      )
    }),
  )
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <MemoryRouter>
          <IngestPage />
        </MemoryRouter>
      </I18nProvider>
    </QueryClientProvider>,
  )
}

beforeEach(() => useLanguageStore.setState({ language: "bs" }))
afterEach(() => vi.restoreAllMocks())

describe("Uvoz podataka (data-ingest-ui)", () => {
  it("uploading the 4 files POSTs the import and renders the report", async () => {
    const userEvent = (await import("@testing-library/user-event")).default
    const user = userEvent.setup()
    mockApi(adminUser)
    renderPage()

    for (const key of ["kupci", "artikli", "fakture", "stavke"]) {
      const input = await screen.findByTestId(`file-${key}`)
      await user.upload(input as HTMLInputElement, new File([`${key};x`], `${key}.csv`, { type: "text/csv" }))
    }
    await user.click(screen.getByTestId("import-submit"))

    await waitFor(() => {
      const post = vi
        .mocked(fetch)
        .mock.calls.find(
          ([url, init]) =>
            String(url).includes("/api/ingest/import") &&
            (init as RequestInit | undefined)?.method === "POST",
        )
      expect(post).toBeDefined()
      expect((post![1] as RequestInit).body).toBeInstanceOf(FormData)
    })

    // The report renders, including the code-swap candidate.
    await waitFor(() => expect(screen.getByTestId("quality-report")).toBeInTheDocument())
    expect(screen.getByTestId("quality-code_swap_candidates")).toHaveTextContent("A1")
  })

  it("lists past imports in the history", async () => {
    mockApi(adminUser)
    renderPage()
    await waitFor(() => expect(screen.getByTestId("data-table")).toHaveTextContent("cli"))
  })

  it("a non-admin sees a forbidden state", async () => {
    mockApi(ownerUser)
    renderPage()
    await waitFor(() => expect(screen.getByTestId("empty-state")).toBeInTheDocument())
    expect(screen.queryByTestId("import-submit")).not.toBeInTheDocument()
  })
})
