/**
 * Postavke (frontend-spec §5): detection thresholds (rule_config), users (admin),
 * and the live LLM routing panel (M12 — tiers, role→tier mapping, escalation;
 * masking shown as locked-on, never configurable).
 */
import { Lock } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { CardSkeleton, EmptyState, ErrorState } from "@/components/widgets/CardState"
import { DataTable, type Column } from "@/components/widgets/DataTable"
import { ApiRequestError } from "@/lib/api/client"
import {
  useLlmSettings,
  useMe,
  usePatchLlmSettings,
  useRuleConfig,
  useUsers,
} from "@/lib/api/queries"
import type { RuleConfigEntry, User } from "@/lib/api/types"
import { useT } from "@/lib/i18n"

function ThresholdsTab() {
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
      render: (row) => <span className="text-text-2">{row.param}</span>,
    },
    {
      key: "value",
      header: t.settings.threshold_value,
      align: "right",
      render: (row) => <span className="tnum font-medium">{JSON.stringify(row.value)}</span>,
    },
  ]

  return (
    <Card className="p-5">
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

function UsersTab() {
  const t = useT()
  const { data, isLoading, isError, error, refetch } = useUsers()

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
      align: "right",
      render: (row) => <Badge>{t.settings.roles[row.role]}</Badge>,
    },
  ]

  return (
    <Card className="p-5">
      {data && (
        <DataTable columns={columns} rows={data.items} rowKey={(row) => row.id} />
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
          {isAdmin && <TabsTrigger value="users">{t.settings.tab_users}</TabsTrigger>}
          <TabsTrigger value="llm">{t.settings.tab_llm}</TabsTrigger>
        </TabsList>

        <TabsContent value="thresholds">
          <ThresholdsTab />
        </TabsContent>
        {isAdmin && (
          <TabsContent value="users">
            <UsersTab />
          </TabsContent>
        )}
        <TabsContent value="llm">
          <LlmTab isAdmin={isAdmin} />
        </TabsContent>
      </Tabs>
    </div>
  )
}
