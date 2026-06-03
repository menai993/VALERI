/**
 * DataTable (ui-design §5): the generic dense table — header row in micro caps,
 * hairline dividers, right-aligned tabular numerics, badge cells.
 */
import type { ReactNode } from "react"

import { cn } from "@/lib/utils"

export interface Column<T> {
  key: string
  header: string
  align?: "left" | "right"
  render: (row: T) => ReactNode
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  footer,
}: {
  columns: Column<T>[]
  rows: T[]
  rowKey: (row: T) => string | number
  footer?: ReactNode
}) {
  return (
    <div className="w-full overflow-x-auto" data-testid="data-table">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b">
            {columns.map((column) => (
              <th
                key={column.key}
                className={cn(
                  "pb-2 text-xs font-medium text-text-3",
                  column.align === "right" ? "text-right" : "text-left",
                )}
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={rowKey(row)} className="border-b border-border last:border-0">
              {columns.map((column) => (
                <td
                  key={column.key}
                  className={cn(
                    "py-3",
                    column.align === "right" ? "tnum text-right" : "text-left",
                  )}
                >
                  {column.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {footer && <div className="pt-3">{footer}</div>}
    </div>
  )
}
