/**
 * Prilike (frontend-spec §5, C-CRM1): the opportunity pipeline — weighted-value
 * header + kanban (stage columns) + a DataTable + the "Nova prilika" create form.
 *
 * User-entered pipeline data (no AI envelope); all figures are SQL-computed and
 * passed through as exact strings. RBAC is enforced server-side.
 */
import { useState } from "react"

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
import { CardSkeleton, EmptyState, ErrorState } from "@/components/widgets/CardState"
import { DataTable, type Column } from "@/components/widgets/DataTable"
import { OpportunityCard } from "@/components/widgets/OpportunityCard"
import { ApiRequestError } from "@/lib/api/client"
import { useCreateOpportunity, useCustomers, usePipeline } from "@/lib/api/queries"
import type { Opportunity, OppStage } from "@/lib/api/types"
import { formatMoney, formatPercent } from "@/lib/format"
import { useT } from "@/lib/i18n"

const STAGES: OppStage[] = ["lead", "qualified", "proposal", "negotiation", "won", "lost"]

function NewOpportunityDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const t = useT()
  const customers = useCustomers()
  const create = useCreateOpportunity()
  const [customerId, setCustomerId] = useState<string>("")
  const [title, setTitle] = useState("")
  const [value, setValue] = useState("")
  const [stage, setStage] = useState<OppStage>("lead")

  function submit() {
    if (!customerId || title.trim().length < 2) return
    create.mutate(
      {
        customer_id: Number(customerId),
        title: title.trim(),
        value: value ? Number(value) : undefined,
        stage,
      },
      {
        onSuccess: () => {
          setTitle("")
          setValue("")
          setCustomerId("")
          setStage("lead")
          onClose()
        },
      },
    )
  }

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent data-testid="new-opportunity-dialog">
        <DialogHeader>
          <DialogTitle>{t.opportunities.new_title}</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <Label>{t.opportunities.customer}</Label>
            <Select value={customerId} onValueChange={setCustomerId}>
              <SelectTrigger data-testid="opp-customer-select">
                <SelectValue placeholder={t.opportunities.customer} />
              </SelectTrigger>
              <SelectContent>
                {customers.data?.items.map((customer) => (
                  <SelectItem key={customer.id} value={String(customer.id)}>
                    {customer.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="opp-title">{t.opportunities.opp_title}</Label>
            <Input id="opp-title" value={title} onChange={(e) => setTitle(e.target.value)} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="opp-value">{t.opportunities.value}</Label>
            <Input
              id="opp-value"
              type="number"
              value={value}
              onChange={(e) => setValue(e.target.value)}
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label>{t.opportunities.stage_label}</Label>
            <Select value={stage} onValueChange={(s) => setStage(s as OppStage)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {STAGES.map((s) => (
                  <SelectItem key={s} value={s}>
                    {t.opportunities.stages[s]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
        <DialogFooter>
          <Button variant="default" onClick={onClose}>
            {t.opportunities.cancel}
          </Button>
          <Button
            variant="primary"
            onClick={submit}
            disabled={create.isPending || !customerId || title.trim().length < 2}
            data-testid="submit-opportunity"
          >
            {t.opportunities.create}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export function OpportunitiesPage() {
  const t = useT()
  const { data, isLoading, isError, error, refetch } = usePipeline()
  const [dialogOpen, setDialogOpen] = useState(false)

  const allOpportunities: Opportunity[] = data
    ? data.stages.flatMap((column) => column.opportunities)
    : []

  const tableColumns: Column<Opportunity>[] = [
    {
      key: "title",
      header: t.opportunities.opp_title,
      render: (row) => <span className="font-medium text-text">{row.title}</span>,
    },
    {
      key: "customer",
      header: t.opportunities.customer,
      render: (row) => <span className="text-text-2">{row.customer_name ?? "—"}</span>,
    },
    {
      key: "stage",
      header: t.opportunities.stage_label,
      render: (row) => <span className="text-text-2">{t.opportunities.stages[row.stage]}</span>,
    },
    {
      key: "value",
      header: t.opportunities.value,
      align: "right",
      render: (row) => (row.value ? formatMoney(row.value) : "—"),
    },
    {
      key: "weighted",
      header: t.opportunities.weighted_value,
      align: "right",
      render: (row) => (row.weighted_value ? formatMoney(row.weighted_value) : "—"),
    },
  ]

  return (
    <div className="flex flex-col gap-4">
      {/* header + Nova prilika */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-[26px] font-semibold leading-tight text-text">
            {t.opportunities.title}
          </h1>
          <p className="text-sm text-text-2">{t.opportunities.subtitle}</p>
        </div>
        <Button variant="primary" onClick={() => setDialogOpen(true)} data-testid="open-new-opp">
          {t.opportunities.new}
        </Button>
      </div>

      {isLoading && <CardSkeleton rows={6} />}
      {isError &&
        (error instanceof ApiRequestError && error.status === 403 ? (
          <EmptyState message={t.app.forbidden} />
        ) : (
          <ErrorState onRetry={() => refetch()} />
        ))}

      {data && (
        <>
          {/* weighted value + conversion + open count */}
          <div
            className="grid gap-4"
            style={{ gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))" }}
          >
            <Card className="flex flex-col gap-1 p-4">
              <span className="text-sm text-text-2">{t.opportunities.weighted_value}</span>
              <span className="tnum text-[24px] font-bold text-text" data-testid="weighted-value">
                {formatMoney(data.total_weighted_value)}
              </span>
            </Card>
            <Card className="flex flex-col gap-1 p-4">
              <span className="text-sm text-text-2">{t.opportunities.conversion}</span>
              <span className="tnum text-[24px] font-bold text-text" data-testid="conversion-rate">
                {formatPercent(Number(data.conversion_rate) * 100)}
              </span>
            </Card>
            <Card className="flex flex-col gap-1 p-4">
              <span className="text-sm text-text-2">{t.opportunities.open_count}</span>
              <span className="tnum text-[24px] font-bold text-text">{data.open_count}</span>
            </Card>
          </div>

          {/* kanban by stage */}
          {allOpportunities.length === 0 ? (
            <Card className="p-5">
              <EmptyState message={t.opportunities.empty} />
            </Card>
          ) : (
            <div className="grid gap-3 lg:grid-cols-6" data-testid="kanban">
              {data.stages.map((column) => (
                <div
                  key={column.stage}
                  className="flex flex-col gap-2"
                  data-testid="kanban-column"
                >
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-semibold text-text">
                      {t.opportunities.stages[column.stage]}
                    </span>
                    <span className="tnum text-xs text-text-3">{column.count}</span>
                  </div>
                  {column.opportunities.map((opportunity) => (
                    <OpportunityCard key={opportunity.id} opportunity={opportunity} />
                  ))}
                </div>
              ))}
            </div>
          )}

          {/* table */}
          {allOpportunities.length > 0 && (
            <Card className="flex flex-col gap-3 p-5">
              <h2 className="text-[17px] font-semibold text-text">{t.opportunities.table_title}</h2>
              <DataTable columns={tableColumns} rows={allOpportunities} rowKey={(row) => row.id} />
            </Card>
          )}
        </>
      )}

      <NewOpportunityDialog open={dialogOpen} onClose={() => setDialogOpen(false)} />
    </div>
  )
}
