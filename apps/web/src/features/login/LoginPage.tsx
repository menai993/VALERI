/**
 * LoginPage: e-mail + password → httpOnly session cookie (M8 D1).
 */
import { useState, type FormEvent } from "react"
import { useNavigate } from "react-router"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useLogin } from "@/lib/api/queries"
import { useT } from "@/lib/i18n"

export function LoginPage() {
  const t = useT()
  const navigate = useNavigate()
  const login = useLogin()
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    login.mutate(
      { email, password },
      {
        onSuccess: (response) => {
          // Reps land on their task queue; everyone else on the dashboard.
          navigate(response.user.role === "sales_rep" ? "/zadaci" : "/", { replace: true })
        },
      },
    )
  }

  return (
    <main className="flex min-h-svh items-center justify-center bg-bg p-6">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle className="text-[26px] font-semibold leading-tight">
            {t.app.name}
          </CardTitle>
          <CardDescription>{t.app.tagline}</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <Label htmlFor="email">{t.auth.email}</Label>
              <Input
                id="email"
                type="email"
                autoComplete="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                required
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="password">{t.auth.password}</Label>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
              />
            </div>

            {login.isError && (
              <p className="text-sm text-down" role="alert">
                {t.auth.error}
              </p>
            )}

            <Button type="submit" variant="primary" disabled={login.isPending}>
              {login.isPending ? t.app.loading : t.auth.submit}
            </Button>
          </form>
        </CardContent>
      </Card>
    </main>
  )
}
