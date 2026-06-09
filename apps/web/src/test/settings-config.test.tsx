/** Admin-configurable Postavke: editing a detection threshold (PATCH rule-config)
 * and adding a user (POST users). Both are admin-only. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { SettingsPage } from "@/features/settings/SettingsPage"
import { I18nProvider } from "@/lib/i18n"
import type { User } from "@/lib/api/types"
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

const ruleConfig = {
  items: [{ rule: "customer_decline", param: "drop_pct", value: 0.3, updated_by: null, updated_at: null }],
}

function mockApi() {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string | URL | Request) => {
      const path = typeof url === "string" ? url : url instanceof URL ? url.pathname : url.url
      const ok = (body: unknown) =>
        Promise.resolve(
          new Response(JSON.stringify(body), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        )
      if (path.includes("/api/auth/me")) return ok(adminUser)
      if (path.includes("/api/settings/rule-config")) return ok(ruleConfig)
      if (path.includes("/api/settings/users")) return ok({ items: [] })
      if (path.includes("/api/admin/metrics/status")) return ok({})
      return Promise.resolve(
        new Response(JSON.stringify({ error: { code: "not_found", message: path } }), {
          status: 404,
          headers: { "Content-Type": "application/json" },
        }),
      )
    }),
  )
}

function renderSettings() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <I18nProvider>
        <MemoryRouter>
          <SettingsPage />
        </MemoryRouter>
      </I18nProvider>
    </QueryClientProvider>,
  )
}

beforeEach(() => useLanguageStore.setState({ language: "bs" }))
afterEach(() => vi.restoreAllMocks())

describe("Postavke — admin configuration", () => {
  it("admin edits a threshold → PATCH /api/settings/rule-config", async () => {
    const userEvent = (await import("@testing-library/user-event")).default
    const user = userEvent.setup()
    mockApi()
    renderSettings()

    const input = await screen.findByTestId("threshold-input-customer_decline.drop_pct")
    await user.clear(input)
    await user.type(input, "0.5")
    await user.click(screen.getByTestId("threshold-save-customer_decline.drop_pct"))

    await waitFor(() => {
      const patch = vi
        .mocked(fetch)
        .mock.calls.find(
          ([url, init]) =>
            String(url).includes("/api/settings/rule-config") &&
            (init as RequestInit | undefined)?.method === "PATCH",
        )
      expect(patch).toBeDefined()
      const body = JSON.parse(String((patch![1] as RequestInit).body))
      expect(body.changes[0]).toMatchObject({ rule: "customer_decline", param: "drop_pct", value: 0.5 })
    })
  })

  it("admin adds a user → POST /api/settings/users", async () => {
    const userEvent = (await import("@testing-library/user-event")).default
    const user = userEvent.setup()
    mockApi()
    renderSettings()

    await waitFor(() => expect(screen.getByText("Korisnici")).toBeInTheDocument())
    await user.click(screen.getByText("Korisnici"))
    await user.click(await screen.findByTestId("user-add"))

    await user.type(screen.getByLabelText("Ime"), "Novi Korisnik")
    await user.type(screen.getByLabelText("E-mail"), "novi@ultrahigijena.ba")
    await user.type(screen.getByLabelText("Lozinka"), "lozinka123")
    await user.click(screen.getByTestId("user-save"))

    await waitFor(() => {
      const post = vi
        .mocked(fetch)
        .mock.calls.find(
          ([url, init]) =>
            String(url).includes("/api/settings/users") &&
            (init as RequestInit | undefined)?.method === "POST",
        )
      expect(post).toBeDefined()
      const body = JSON.parse(String((post![1] as RequestInit).body))
      expect(body).toMatchObject({ name: "Novi Korisnik", email: "novi@ultrahigijena.ba", role: "sales_rep" })
    })
  })
})
