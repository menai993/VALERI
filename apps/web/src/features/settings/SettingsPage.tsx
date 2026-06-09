/**
 * Postavke (frontend-spec §5): detection thresholds (rule_config), users (admin),
 * and the live LLM routing panel (M12 — tiers, role→tier mapping, escalation;
 * masking shown as locked-on, never configurable).
 */
import { useState } from "react"
import { Lock, Pencil, Plus } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { CardSkeleton, EmptyState, ErrorState } from "@/components/widgets/CardState"
import { DataMetricsPanel } from "@/components/widgets/DataMetricsPanel"
import { DataTable, type Column } from "@/components/widgets/DataTable"
import { ApiRequestError } from "@/lib/api/client"
import {
  useCreateUser,
  useLlmSettings,
  useMe,
  usePatchLlmSettings,
  usePatchRuleConfig,
  useRuleConfig,
  useUpdateUser,
  useUsers,
} from "@/lib/api/queries"
import type { Role, RuleConfigEntry, User, UserCreate, UserUpdate } from "@/lib/api/types"
import { useT } from "@/lib/i18n"

const ROLES: Role[] = ["owner", "admin", "finance", "sales_rep"]

/** A rule_config value ↔ editable text. Numbers/bools/strings show raw; objects as JSON. */
function displayValue(value: unknown): string {
  return typeof value === "object" && value !== null ? JSON.stringify(value) : String(value)
}
function parseValue(raw: string): unknown {
  try {
    return JSON.parse(raw)
  } catch {
    return raw // a bare word like "summer" stays a string
  }
}

function ThresholdValueCell({ row, editable }: { row: RuleConfigEntry; editable: boolean }) {
  const t = useT()
  const patch = usePatchRuleConfig()
  const [draft, setDraft] = useState(() => displayValue(row.value))

  if (!editable) {
    return <span className="tnum font-medium">{displayValue(row.value)}</span>
  }

  const dirty = draft !== displayValue(row.value)
  return (
    <div className="flex items-center justify-end gap-2">
      <Input
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        className="tnum h-8 w-40 text-right"
        aria-label={`${row.rule}.${row.param}`}
        data-testid={`threshold-input-${row.rule}.${row.param}`}
      />
      <Button
        size="sm"
        variant="primary"
        disabled={!dirty || patch.isPending}
        onClick={() =>
          patch.mutate([{ rule: row.rule, param: row.param, value: parseValue(draft) }])
        }
        data-testid={`threshold-save-${row.rule}.${row.param}`}
      >
        {t.settings.save}
      </Button>
    </div>
  )
}

function ThresholdsTab({ isAdmin }: { isAdmin: boolean }) {
  const t = useT()
  const { data, isLoading, isError, error, refetch } = useRuleConfig()

  if (isLoading) return <CardSkeleton rows={8} />
  if (isError) {
    if (error instanceof ApiRequestError && error.status === 403) {
      return <EmptyState message={t.app.forbidden} />
    }
    return <ErrorState onRetry={() => refetch()} />
  }

  const columns: Column<RuleConfigEntry>[] = [
    {
      key: "rule",
      header: t.settings.threshold_rule,
      render: (row) => (
        <span className="font-medium text-text">
          {t.rules[row.rule as keyof typeof t.rules] ?? row.rule}
        </span>
      ),
    },
    {
      key: "param",
      header: t.settings.threshold_param,
      render: (row) => (
        <div className="flex flex-col">
          <span className="text-text">{t.settings.param_desc[row.param] ?? row.param}</span>
          <span className="font-mono text-xs text-text-3">{row.param}</span>
        </div>
      ),
    },
    {
      key: "value",
      header: t.settings.threshold_value,
      align: "right",
      render: (row) => (
        <ThresholdValueCell row={row} editable={isAdmin} />
      ),
    },
  ]

  return (
    <Card className="p-5">
      {isAdmin && <p className="mb-3 text-sm text-text-2">{t.settings.threshold_hint}</p>}
      {data && data.items.length === 0 && <EmptyState />}
      {data && data.items.length > 0 && (
        <DataTable
          columns={columns}
          rows={data.items}
          rowKey={(row) => `${row.rule}.${row.param}`}
        />
      )}
    </Card>
  )
}

function UserDialog({
  mode,
  user,
  open,
  onOpenChange,
}: {
  mode: "add" | "edit"
  user?: User
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const t = useT()
  const createUser = useCreateUser()
  const updateUser = useUpdateUser()

  const [name, setName] = useState(user?.name ?? "")
  const [email, setEmail] = useState(user?.email ?? "")
  const [role, setRole] = useState<Role>(user?.role ?? "sales_rep")
  const [password, setPassword] = useState("")

  const pending = createUser.isPending || updateUser.isPending
  const failed = createUser.isError || updateUser.isError

  const submit = () => {
    if (mode === "add") {
      const body: UserCreate = { name, email, role, password }
      createUser.mutate(body, { onSuccess: () => onOpenChange(false) })
    } else if (user) {
      const body: UserUpdate = { name, role }
      if (password) body.password = password
      updateUser.mutate({ id: user.id, body }, { onSuccess: () => onOpenChange(false) })
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{mode === "add" ? t.settings.users_add : t.settings.users_edit}</DialogTitle>
        </DialogHeader>

        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="user-name">{t.settings.users_name}</Label>
            <Input id="user-name" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="user-email">{t.settings.users_email}</Label>
            <Input
              id="user-email"
              type="email"
              value={email}
              disabled={mode === "edit"}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="user-role">{t.settings.users_role}</Label>
            <Select value={role} onValueChange={(value) => setRole(value as Role)}>
              <SelectTrigger id="user-role" data-testid="user-role-select">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {ROLES.map((r) => (
                  <SelectItem key={r} value={r}>
                    {t.settings.roles[r]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="user-password">
              {mode === "add" ? t.settings.users_password : t.settings.users_password_optional}
            </Label>
            <Input
              id="user-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          {failed && <p className="text-sm text-down">{t.settings.users_error}</p>}
        </div>

        <DialogFooter>
          <Button variant="default" onClick={() => onOpenChange(false)}>
            {t.settings.users_cancel}
          </Button>
          <Button variant="primary" disabled={pending} onClick={submit} data-testid="user-save">
            {t.settings.save}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function UsersTab({ isAdmin }: { isAdmin: boolean }) {
  const t = useT()
  const { data, isLoading, isError, error, refetch } = useUsers()
  const [dialog, setDialog] = useState<{ mode: "add" | "edit"; user?: User } | null>(null)

  if (isLoading) return <CardSkeleton rows={5} />
  if (isError) {
    if (error instanceof ApiRequestError && error.status === 403) {
      return <EmptyState message={t.app.forbidden} />
    }
    return <ErrorState onRetry={() => refetch()} />
  }

  const columns: Column<User>[] = [
    {
      key: "name",
      header: t.settings.users_name,
      render: (row) => <span className="font-medium text-text">{row.name}</span>,
    },
    {
      key: "email",
      header: t.settings.users_email,
      render: (row) => <span className="text-text-2">{row.email}</span>,
    },
    {
      key: "role",
      header: t.settings.users_role,
      render: (row) => <Badge>{t.settings.roles[row.role]}</Badge>,
    },
    {
      key: "actions",
      header: "",
      align: "right",
      render: (row) =>
        isAdmin ? (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => setDialog({ mode: "edit", user: row })}
            data-testid={`user-edit-${row.id}`}
          >
            <Pencil className="h-3.5 w-3.5" />
            {t.settings.users_edit}
          </Button>
        ) : null,
    },
  ]

  return (
    <Card className="flex flex-col gap-3 p-5">
      {isAdmin && (
        <div className="flex justify-end">
          <Button variant="primary" onClick={() => setDialog({ mode: "add" })} data-testid="user-add">
            <Plus className="h-4 w-4" />
            {t.settings.users_add}
          </Button>
        </div>
      )}
      {data && <DataTable columns={columns} rows={data.items} rowKey={(row) => row.id} />}
      {dialog && (
        <UserDialog
          mode={dialog.mode}
          user={dialog.user}
          open={true}
          onOpenChange={(open) => !open && setDialog(null)}
        />
      )}
    </Card>
  )
}

function LlmTab({ isAdmin }: { isAdmin: boolean }) {
  const t = useT()
  const { data, isLoading, isError, error, refetch } = useLlmSettings()
  const patchSettings = usePatchLlmSettings()

  if (isLoading) return <CardSkeleton rows={8} />
  if (isError) {
    if (error instanceof ApiRequestError && error.status === 403) {
      return <EmptyState message={t.app.forbidden} />
    }
    return <ErrorState onRetry={() => refetch()} />
  }
  if (!data) return null

  const tierLabel = (tier: string) =>
    t.settings.llm.tiers[tier as keyof typeof t.settings.llm.tiers] ?? tier
  const roleLabel = (role: string) =>
    t.settings.llm.roles[role as keyof typeof t.settings.llm.roles] ?? role

  return (
    <div className="flex flex-col gap-4">
      {/* Provider + the masking lock (principle 6 — displayed, never configurable). */}
      <Card className="flex flex-col gap-4 p-5">
        <p className="text-sm text-text-2">{t.settings.llm_info}</p>
        <div
          className="flex items-center gap-2 rounded-md bg-surface-2 p-3 text-sm text-text-2"
          data-testid="masking-locked"
        >
          <Lock className="h-4 w-4 text-up" />
          {t.settings.llm_masking}
        </div>
      </Card>

      {/* Tiers — the alias→Claude-model mapping is infra config, shown read-only. */}
      <Card className="flex flex-col gap-3 p-5" data-testid="llm-tiers">
        <h2 className="text-[17px] font-semibold text-text">{t.settings.llm.tiers_title}</h2>
        {Object.entries(data.tiers).map(([tier, info]) => (
          <div
            key={tier}
            className="flex flex-wrap items-center justify-between gap-2 border-b pb-2 last:border-b-0"
          >
            <span className="text-sm font-medium text-text">{tierLabel(tier)}</span>
            <div className="flex items-center gap-2">
              <Badge variant="outline">{info.alias}</Badge>
              <span className="text-xs text-text-3">{info.description}</span>
            </div>
          </div>
        ))}
      </Card>

      {/* Role → tier routing (admin-editable; every change is a logged decision server-side). */}
      <Card className="flex flex-col gap-3 p-5" data-testid="llm-role-tiers">
        <h2 className="text-[17px] font-semibold text-text">{t.settings.llm.routing_title}</h2>
        {Object.entries(data.role_tiers).map(([role, tier]) => (
          <div
            key={role}
            className="flex flex-wrap items-center justify-between gap-3 border-b pb-2 last:border-b-0"
            data-testid="role-tier-row"
          >
            <span className="text-sm text-text">{roleLabel(role)}</span>
            {isAdmin ? (
              <Select
                value={tier}
                onValueChange={(value) =>
                  patchSettings.mutate({ role_tiers: { ...data.role_tiers, [role]: value } })
                }
              >
                <SelectTrigger className="w-56" data-testid={`role-tier-select-${role}`}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {Object.keys(data.tiers).map((tierKey) => (
                    <SelectItem key={tierKey} value={tierKey}>
                      {tierLabel(tierKey)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : (
              <Badge>{tierLabel(tier)}</Badge>
            )}
          </div>
        ))}

        <div className="flex flex-wrap items-center justify-between gap-3 pt-2">
          <span className="text-sm text-text-2">{t.settings.llm.escalation}</span>
          <span className="tnum text-sm font-medium text-text" data-testid="escalation-threshold">
            {data.escalation_confidence_threshold}
          </span>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="text-sm text-text-2">{t.settings.llm.cascade}</span>
          <Badge data-testid="cascade-state">
            {data.cascade_enabled ? t.settings.llm.cascade_on : t.settings.llm.cascade_off}
          </Badge>
        </div>
      </Card>
    </div>
  )
}

export function SettingsPage() {
  const t = useT()
  const { data: user } = useMe()
  const isAdmin = user?.role === "admin"

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-[26px] font-semibold leading-tight text-text">
          {t.settings.title}
        </h1>
        <p className="text-sm text-text-2">{t.settings.subtitle}</p>
      </div>

      <Tabs defaultValue="thresholds">
        <TabsList>
          <TabsTrigger value="thresholds">{t.settings.tab_thresholds}</TabsTrigger>
          {isAdmin && <TabsTrigger value="data">{t.settings.tab_data}</TabsTrigger>}
          {isAdmin && <TabsTrigger value="users">{t.settings.tab_users}</TabsTrigger>}
          <TabsTrigger value="llm">{t.settings.tab_llm}</TabsTrigger>
        </TabsList>

        <TabsContent value="thresholds">
          <ThresholdsTab isAdmin={isAdmin} />
        </TabsContent>
        {isAdmin && (
          <TabsContent value="data">
            <DataMetricsPanel />
          </TabsContent>
        )}
        {isAdmin && (
          <TabsContent value="users">
            <UsersTab isAdmin={isAdmin} />
          </TabsContent>
        )}
        <TabsContent value="llm">
          <LlmTab isAdmin={isAdmin} />
        </TabsContent>
      </Tabs>
    </div>
  )
}
