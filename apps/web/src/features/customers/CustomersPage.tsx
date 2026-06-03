/**
 * Kupci (frontend-spec §5): list/search with risk badges; rows link to the 360 detail.
 */
import { useState } from "react"
import { Search } from "lucide-react"
import { Link } from "react-router"

import { Card } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { CardSkeleton, EmptyState, ErrorState } from "@/components/widgets/CardState"
import { DataTable, type Column } from "@/components/widgets/DataTable"
import { RiskBadge } from "@/components/widgets/RiskBadge"
import { useCustomers } from "@/lib/api/queries"
import type { CustomerRow } from "@/lib/api/types"
import { formatDate, formatMoney } from "@/lib/format"
import { useT } from "@/lib/i18n"

export function CustomersPage() {
  const t = useT()
  const [query, setQuery] = useState("")
  const { data, isLoading, isError, refetch } = useCustomers(query ? { query } : {})

  const columns: Column<CustomerRow>[] = [
    {
      key: "name",
      header: t.customers.name,
      render: (row) => (
        <Link
          to={`/kupci/${row.id}`}
          className="font-medium text-text hover:text-primary hover:underline"
        >
          {row.name}
        </Link>
      ),
    },
    {
      key: "segment",
      header: t.customers.segment,
      render: (row) => <span className="text-text-2">{row.segment ?? "—"}</span>,
    },
    {
      key: "turnover",
      header: t.customers.turnover,
      align: "right",
      render: (row) => formatMoney(row.turnover_60d),
    },
    {
      key: "last_order",
      header: t.customers.last_order,
      align: "right",
      render: (row) => formatDate(row.last_order_date),
    },
    {
      key: "risk",
      header: t.customers.risk,
      align: "right",
      render: (row) => (row.risk_band ? <RiskBadge band={row.risk_band} /> : <span>—</span>),
    },
  ]

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-[26px] font-semibold leading-tight text-text">
          {t.customers.title}
        </h1>
        <p className="text-sm text-text-2">{t.customers.subtitle}</p>
      </div>

      <Card className="flex flex-col gap-4 p-5">
        <div className="relative max-w-sm">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-3" />
          <Input
            className="pl-9"
            placeholder={t.customers.search}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>

        {isLoading && <CardSkeleton rows={8} />}
        {isError && <ErrorState onRetry={() => refetch()} />}
        {data && data.items.length === 0 && <EmptyState message={t.customers.empty} />}
        {data && data.items.length > 0 && (
          <DataTable columns={columns} rows={data.items} rowKey={(row) => row.id} />
        )}
      </Card>
    </div>
  )
}
