/** M12: the live LLM routing tab — tiers, role→tier mapping, escalation, and the
 * masking lock. Admin edits a role's tier → PATCH; non-admins see read-only badges. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { SettingsPage } from "@/features/settings/SettingsPage"
import { I18nProvider } from "@/lib/i18n"
import type { LlmSettings, User } from "@/lib/api/types"
import { useLanguageStore } from "@/store/ui"

// ── fixtures ──────────────────────────────────────────────────────────────────

const adminUser: User = {
  id: 2,
  name: "Administrator",
  email: "admin@ultrahigijena.ba",
  role: "admin",
  sales_rep_id: null,
  preferred_language: "bs",
  created_at: "2026-01-01T00:00:00Z",
}

const ownerUser: User = { ...adminUser, id: 1, name: "Vlasnik", role: "owner" }

const llmSettings: LlmSettings = {
  provider: "anthropic (hosted Claude via LiteLLM)",
  tiers: {
    tier1: { alias: "tier1", description: "Claude Haiku — brzi/jeftini sloj" },
    tier2: { alias: "tier2", description: "Claude Sonnet — jaki sloj" },
    tier2_strong: { alias: "tier2_strong", description: "Claude Opus — najjači sloj" },
  },
  role_tiers: {
    narration: "tier1",
    intent: "tier1",
    simple_qa: "tier1",
    over_suppression_audit: "tier2",
  },
  escalation_confidence_threshold: 0.6,
  cascade_enabled: true,
  cascade_max_escalations: 1,
  masking: "locked_on",
}

// ── helpers ───────────────────────────────────────────────────────────────────

function mockApi(user: User, settings: LlmSettings) {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string | URL | Request, init?: RequestInit) => {
      const path = typeof url === "string" ? url : url instanceof URL ? url.pathname : url.url
      const respond = (body: unknown) =>
        Promise.resolve(
          new Response(JSON.stringify(body), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        )

      if (path.includes("/api/auth/me")) return respond(user)
      if (path.includes("/api/settings/llm")) {
        if (init?.method === "PATCH") {
          const patch = JSON.parse(String(init.body))
          return respond({ ...settings, ...patch })
        }
        return respond(settings)
      }
      if (path.includes("/api/settings/rule-config")) return respond({ items: [] })
      if (path.includes("/api/settings/users")) return respond({ items: [] })
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

async function openLlmTab(user: ReturnType<typeof import("@testing-library/user-event").default.setup>) {
  await waitFor(() => expect(screen.getByText("AI model")).toBeInTheDocument())
  await user.click(screen.getByText("AI model"))
}

beforeEach(() => {
  useLanguageStore.setState({ language: "bs" })
})

afterEach(() => {
  vi.restoreAllMocks()
})

// ── tests ─────────────────────────────────────────────────────────────────────

describe("Settings → AI model (M12)", () => {
  it("renders tiers, role routing, escalation and the masking lock", async () => {
    const userEvent = (await import("@testing-library/user-event")).default
    const user = userEvent.setup()
    mockApi(adminUser, llmSettings)
    renderSettings()
    await openLlmTab(user)

    // Tiers (read-only infra config).
    await waitFor(() => expect(screen.getByTestId("llm-tiers")).toBeInTheDocument())
    const tiers = screen.getByTestId("llm-tiers")
    expect(tiers).toHaveTextContent("Tier 1 — Haiku (brzi)")
    expect(tiers).toHaveTextContent("Tier 2 — Sonnet (jaki)")
    expect(tiers).toHaveTextContent("Tier 2+ — Opus (najjači)")

    // Role routing with localized role names.
    const routing = screen.getByTestId("llm-role-tiers")
    expect(routing).toHaveTextContent("Naracija zadataka")
    expect(routing).toHaveTextContent("Provjera potisnutih signala")

    // Escalation + cascade values come from the API.
    expect(screen.getByTestId("escalation-threshold")).toHaveTextContent("0.6")
    expect(screen.getByTestId("cascade-state")).toHaveTextContent("Uključena")

    // The masking lock is always shown and never an input.
    const lock = screen.getByTestId("masking-locked")
    expect(lock).toHaveTextContent("PII maskiranje: uvijek uključeno")
    expect(lock.querySelector("input")).toBeNull()
  })

  it("admin changes a role's tier → PATCH /api/settings/llm", async () => {
    const userEvent = (await import("@testing-library/user-event")).default
    const user = userEvent.setup()
    mockApi(adminUser, llmSettings)
    renderSettings()
    await openLlmTab(user)

    await waitFor(() =>
      expect(screen.getByTestId("role-tier-select-over_suppression_audit")).toBeInTheDocument(),
    )

    // Open the Radix select and pick the strongest tier (the Sonnet→Opus swap).
    await user.click(screen.getByTestId("role-tier-select-over_suppression_audit"))
    const option = await screen.findByRole("option", { name: "Tier 2+ — Opus (najjači)" })
    await user.click(option)

    await waitFor(() => {
      const fetchMock = vi.mocked(fetch)
      const patchCall = fetchMock.mock.calls.find(
        ([url, init]) =>
          String(url).includes("/api/settings/llm") &&
          (init as RequestInit | undefined)?.method === "PATCH",
      )
      expect(patchCall).toBeDefined()
      const body = JSON.parse(String((patchCall![1] as RequestInit).body))
      expect(body.role_tiers.over_suppression_audit).toBe("tier2_strong")
    })
  })

  it("non-admin (owner) sees read-only tier badges, no selects", async () => {
    const userEvent = (await import("@testing-library/user-event")).default
    const user = userEvent.setup()
    mockApi(ownerUser, llmSettings)
    renderSettings()
    await openLlmTab(user)

    await waitFor(() => expect(screen.getByTestId("llm-role-tiers")).toBeInTheDocument())
    expect(screen.queryByTestId("role-tier-select-narration")).not.toBeInTheDocument()
    // The tier is still visible, as a badge.
    const rows = screen.getAllByTestId("role-tier-row")
    expect(rows.length).toBeGreaterThan(0)
  })
})
