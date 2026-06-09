/**
 * Odobrenja (P1): the owner's approval queue — the missing front door for the
 * M7 approval workflow. Pending first; nothing customer-facing happens without
 * a decision here (principle 10).
 */
import { useState } from "react"

import { Card } from "@/components/ui/card"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useToast } from "@/components/ui/toast"
import { CardSkeleton, EmptyState, ErrorState } from "@/components/widgets/CardState"
import { ApprovalCard } from "@/components/widgets/ApprovalCard"
import { useApprovalDecision, useApprovals } from "@/lib/api/queries"
import type { Approval } from "@/lib/api/types"
import { useT } from "@/lib/i18n"

export function ApprovalsPage() {
  const t = useT()
  const toast = useToast()
  const [tab, setTab] = useState<"pending" | "all">("pending")
  const { data, isLoading, isError, refetch } = useApprovals(
    tab === "pending" ? "pending_approval" : undefined,
  )
  const decide = useApprovalDecision()

  function decideWith(decision: "approved" | "rejected" | "deferred") {
    return (item: Approval) =>
      decide.mutate(
        { approvalId: item.id, decision },
        {
          onSuccess: () => {
            const message =
              decision === "approved"
                ? t.approvals.toast_approved
                : decision === "rejected"
                  ? t.approvals.toast_rejected
                  : t.approvals.toast_deferred
            toast(message)
          },
        },
      )
  }

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-[26px] font-semibold leading-tight text-text">
          {t.approvals.title}
        </h1>
        <p className="text-sm text-text-2">{t.approvals.subtitle}</p>
      </div>

      <Tabs value={tab} onValueChange={(value) => setTab(value as "pending" | "all")}>
        <TabsList>
          <TabsTrigger value="pending">{t.approvals.pending}</TabsTrigger>
          <TabsTrigger value="all">{t.approvals.decided}</TabsTrigger>
        </TabsList>
      </Tabs>

      <Card className="flex flex-col gap-4 p-5">
        {isError && <ErrorState onRetry={() => refetch()} />}
        {isLoading && <CardSkeleton rows={5} />}
        {data && data.items.length === 0 && <EmptyState message={t.approvals.empty} />}
        {data?.items.map((item) => (
          <ApprovalCard
            key={item.id}
            item={item}
            deciding={decide.isPending}
            onApprove={decideWith("approved")}
            onReject={decideWith("rejected")}
            onDefer={decideWith("deferred")}
          />
        ))}
      </Card>
    </div>
  )
}
