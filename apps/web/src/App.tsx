/**
 * VALERI web app root: providers + router (frontend-spec §3).
 *
 * QueryClient → Theme → I18n → Router. No localStorage anywhere; the session
 * lives in an httpOnly cookie and UI state lives in Zustand (in-memory).
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { RouterProvider } from "react-router"

import { ThemeProvider } from "@/app/ThemeProvider"
import { I18nProvider } from "@/lib/i18n"
import { router } from "@/routes"

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 30 * 1000,
    },
  },
})

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <I18nProvider>
          <RouterProvider router={router} />
        </I18nProvider>
      </ThemeProvider>
    </QueryClientProvider>
  )
}

export default App
