/**
 * RelationshipMap (CI2, §6): a small ego graph of a customer's CONFIRMED links.
 *
 * An inline SVG (no graph library) places the focus customer at the centre with
 * its linked customers around it; below, a legend lists each edge with its type,
 * source and confidence (the evidence). Confirmed edges only — the API filters.
 */
import { Card } from "@/components/ui/card"
import { useKbGraph } from "@/lib/api/queries"
import type { GraphEdge, GraphNode } from "@/lib/api/types"
import { useT } from "@/lib/i18n"

const W = 320
const H = 240
const CX = W / 2
const CY = H / 2
const R = 86

function nodePositions(nodes: GraphNode[], focusId: number): Map<number, [number, number]> {
  const positions = new Map<number, [number, number]>()
  positions.set(focusId, [CX, CY])
  const others = nodes.filter((n) => n.customer_id !== focusId)
  others.forEach((node, index) => {
    const angle = (2 * Math.PI * index) / Math.max(others.length, 1) - Math.PI / 2
    positions.set(node.customer_id, [CX + R * Math.cos(angle), CY + R * Math.sin(angle)])
  })
  return positions
}

export function RelationshipMap({ customerId }: { customerId: number }) {
  const t = useT()
  const { data } = useKbGraph(customerId)

  if (!data || data.edges.length === 0) return null

  const names = new Map<number, string | null>(data.nodes.map((n) => [n.customer_id, n.name]))
  const positions = nodePositions(data.nodes, customerId)
  const relLabel = (rt: string) => t.kb.rel[rt as keyof typeof t.kb.rel] ?? rt

  return (
    <Card className="flex flex-col gap-2 p-5" data-testid="relationship-map">
      <h3 className="text-[15px] font-semibold text-text">{t.kb.map_title}</h3>

      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={t.kb.map_title}>
        {data.edges.map((edge: GraphEdge, index) => {
          const a = positions.get(edge.from)
          const b = positions.get(edge.to)
          if (!a || !b) return null
          return (
            <line
              key={index}
              x1={a[0]}
              y1={a[1]}
              x2={b[0]}
              y2={b[1]}
              className="stroke-border"
              strokeWidth={1.5}
            />
          )
        })}
        {data.nodes.map((node) => {
          const pos = positions.get(node.customer_id)
          if (!pos) return null
          const isFocus = node.customer_id === customerId
          return (
            <g key={node.customer_id}>
              <circle
                cx={pos[0]}
                cy={pos[1]}
                r={isFocus ? 9 : 6}
                className={isFocus ? "fill-primary" : "fill-primary-soft stroke-primary"}
              />
              <text
                x={pos[0]}
                y={pos[1] - 12}
                textAnchor="middle"
                className="fill-text-2 text-[10px]"
              >
                {node.name ?? `#${node.customer_id}`}
              </text>
            </g>
          )
        })}
      </svg>

      {/* Evidence legend: each edge labeled with type + source + confidence. */}
      <div className="flex flex-col gap-1">
        {data.edges.map((edge, index) => (
          <div key={index} className="text-xs text-text-3" data-testid="graph-edge">
            {names.get(edge.from) ?? `#${edge.from}`} · {relLabel(edge.rel_type)} →{" "}
            {names.get(edge.to) ?? `#${edge.to}`} ·{" "}
            <span className="tnum">
              {t.confidence.label}: {edge.confidence}
            </span>{" "}
            · {t.kb.source[edge.source]}
          </div>
        ))}
      </div>
    </Card>
  )
}
