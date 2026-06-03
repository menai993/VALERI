/**
 * Artikli (frontend-spec §5): the lost-article view (MVP centerpiece) + catalog.
 */
import { useState } from "react"
import { Search } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { CardSkeleton, EmptyState, ErrorState } from "@/components/widgets/CardState"
import { ConfidenceLabel } from "@/components/widgets/ConfidenceLabel"
import { DataTable, type Column } from "@/components/widgets/DataTable"
import { EvidenceExpander } from "@/components/widgets/EvidenceExpander"
import { RegisterChip } from "@/components/widgets/RegisterChip"
import { useArticles, useLostArticles } from "@/lib/api/queries"
import type { ArticleRow, LostArticleRow } from "@/lib/api/types"
import { formatDate } from "@/lib/format"
import { useT } from "@/lib/i18n"

function LostArticlesTab() {
  const t = useT()
  const { data, isLoading, isError, refetch } = useLostArticles()

  const columns: Column<LostArticleRow>[] = [
    {
      key: "article",
      header: t.dashboard.lost_articles.article,
      render: (row) => (
        <div className="flex flex-col gap-1">
          <div className="flex items-center gap-2">
            <RegisterChip register={row.register} />
            <span className="font-medium text-text">{row.article_name}</span>
          </div>
          <span className="text-xs text-text-3">{row.article_code}</span>
          <ConfidenceLabel band={row.conf_band} />
          <EvidenceExpander evidence={row.evidence} />
        </div>
      ),
    },
    {
      key: "customer",
      header: t.dashboard.lost_articles.customer,
      render: (row) => (
        <div className="flex flex-col">
          <span className="text-text-2">{row.customer_name}</span>
          <span className="text-xs text-text-3">{row.segment}</span>
        </div>
      ),
    },
    {
      key: "last_seen",
      header: t.dashboard.lost_articles.last_seen,
      align: "right",
      render: (row) => formatDate(row.last_seen),
    },
    {
      key: "gap",
      header: t.dashboard.lost_articles.gap,
      align: "right",
      render: (row) => row.gap_days ?? "—",
    },
  ]

  return (
    <Card className="p-5">
      {isLoading && <CardSkeleton rows={6} />}
      {isError && <ErrorState onRetry={() => refetch()} />}
      {data && data.items.length === 0 && <EmptyState />}
      {data && data.items.length > 0 && (
        <DataTable columns={columns} rows={data.items} rowKey={(row) => row.signal_id} />
      )}
    </Card>
  )
}

function CatalogTab() {
  const t = useT()
  const [query, setQuery] = useState("")
  const { data, isLoading, isError, refetch } = useArticles(query || undefined)

  const columns: Column<ArticleRow>[] = [
    { key: "code", header: t.articles.code, render: (row) => <span className="tnum">{row.code}</span> },
    {
      key: "name",
      header: t.articles.name,
      render: (row) => <span className="font-medium text-text">{row.name}</span>,
    },
    {
      key: "category",
      header: t.articles.category,
      render: (row) => <span className="text-text-2">{row.category_name ?? "—"}</span>,
    },
    {
      key: "active",
      header: t.articles.active,
      align: "right",
      render: (row) => <Badge>{row.active ? "✓" : "✗"}</Badge>,
    },
  ]

  return (
    <Card className="flex flex-col gap-4 p-5">
      <div className="relative max-w-sm">
        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-text-3" />
        <Input
          className="pl-9"
          placeholder={t.articles.search}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>
      {isLoading && <CardSkeleton rows={6} />}
      {isError && <ErrorState onRetry={() => refetch()} />}
      {data && data.items.length === 0 && <EmptyState message={t.articles.empty} />}
      {data && data.items.length > 0 && (
        <DataTable columns={columns} rows={data.items} rowKey={(row) => row.id} />
      )}
    </Card>
  )
}

export function ArticlesPage() {
  const t = useT()
  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-[26px] font-semibold leading-tight text-text">{t.articles.title}</h1>
        <p className="text-sm text-text-2">{t.articles.subtitle}</p>
      </div>

      <Tabs defaultValue="lost">
        <TabsList>
          <TabsTrigger value="lost">{t.articles.tab_lost}</TabsTrigger>
          <TabsTrigger value="catalog">{t.articles.tab_catalog}</TabsTrigger>
        </TabsList>
        <TabsContent value="lost">
          <LostArticlesTab />
        </TabsContent>
        <TabsContent value="catalog">
          <CatalogTab />
        </TabsContent>
      </Tabs>
    </div>
  )
}
