/**
 * Typed fetch wrapper (frontend-spec §6).
 *
 * - credentials: 'include' — the session is an httpOnly cookie (M8 D1);
 *   JavaScript never sees the token and nothing touches localStorage.
 * - Mutations echo the (non-HttpOnly) valeri_csrf cookie in X-CSRF-Token —
 *   the double-submit half of the P2 CSRF gate.
 * - Error envelopes ({error: {code, message}}) become ApiRequestError.
 * - 401 responses flag the session as expired (the AuthGuard redirects).
 */

export class ApiRequestError extends Error {
  status: number
  code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.name = "ApiRequestError"
    this.status = status
    this.code = code
  }
}

const MUTATING_METHODS = ["POST", "PUT", "PATCH", "DELETE"]

function csrfToken(): string | null {
  if (typeof document === "undefined") return null
  const match = document.cookie.match(/(?:^|;\s*)valeri_csrf=([^;]+)/)
  return match ? decodeURIComponent(match[1]) : null
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  // FormData sets its own multipart boundary Content-Type — never force JSON for it.
  const isFormData = typeof FormData !== "undefined" && init?.body instanceof FormData
  const baseHeaders: Record<string, string> = isFormData
    ? {}
    : { "Content-Type": "application/json" }
  const method = (init?.method ?? "GET").toUpperCase()
  if (MUTATING_METHODS.includes(method)) {
    const token = csrfToken()
    if (token) baseHeaders["X-CSRF-Token"] = token
  }
  const response = await fetch(path, {
    credentials: "include",
    headers: { ...baseHeaders, ...init?.headers },
    ...init,
  })

  if (response.status === 204) return undefined as T

  let body: unknown
  try {
    body = await response.json()
  } catch {
    body = null
  }

  if (!response.ok) {
    const envelope = body as { error?: { code?: string; message?: string } } | null
    throw new ApiRequestError(
      response.status,
      envelope?.error?.code ?? String(response.status),
      envelope?.error?.message ?? response.statusText,
    )
  }
  return body as T
}

export const api = {
  get: <T>(path: string, params?: Record<string, string | number | undefined>) => {
    const query = params
      ? "?" +
        new URLSearchParams(
          Object.entries(params)
            .filter(([, value]) => value !== undefined && value !== "")
            .map(([key, value]) => [key, String(value)]),
        ).toString()
      : ""
    return request<T>(`${path}${query}`)
  },
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body !== undefined ? JSON.stringify(body) : undefined }),
  patch: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(body) }),
  // Multipart upload: let the browser set the boundary Content-Type (don't send JSON).
  upload: <T>(path: string, form: FormData) =>
    request<T>(path, { method: "POST", body: form, headers: {} }),
}
