/**
 * Postavke (frontend-spec §5): detection thresholds (rule_config), users (admin),
 * and the LLM info panel (masking shown as locked-on).
 */
import { Lock } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { CardSkeleton, EmptyState, ErrorState } from "@/components/widgets/CardState"
import { DataTable, type Column } from "@/components/widgets/DataTable"
import { ApiRequestError } from "@/lib/api/client"
import { useMe, useRuleConfig, useUsers } from "@/lib/api/queries"
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

function LlmTab() {
  const t = useT()
  return (
    <Card className="flex flex-col gap-4 p-5">
      <p className="text-sm text-text-2">{t.settings.llm_info}</p>
      <div className="flex items-center gap-2 rounded-md bg-surface-2 p-3 text-sm text-text-2">
        <Lock className="h-4 w-4 text-up" />
        {t.settings.llm_masking}
      </div>
    </Card>
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
          <LlmTab />
        </TabsContent>
      </Tabs>
    </div>
  )
}
