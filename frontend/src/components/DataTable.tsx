import type { ReactNode } from 'react'
import './DataTable.css'

export type Column<T> = {
  key: string
  label: string
  sortable?: boolean
  align?: 'left' | 'right'
  render: (row: T) => ReactNode
}

type Props<T> = {
  columns: Column<T>[]
  rows: T[]
  rowKey: (row: T) => string
  sort: string
  order: 'asc' | 'desc'
  onSort: (key: string) => void
  caption: string
  loading?: boolean
}

export default function DataTable<T>({ columns, rows, rowKey, sort, order, onSort, caption, loading }: Props<T>) {
  return (
    <div className={loading ? 'table-wrap is-loading' : 'table-wrap'} aria-busy={loading}>
      <table className="data-table">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>
            {columns.map((column) => {
              const active = column.key === sort
              const ariaSort = active ? (order === 'asc' ? 'ascending' : 'descending') : undefined
              return (
                <th key={column.key} scope="col" aria-sort={ariaSort} className={column.align === 'right' ? 'num' : ''}>
                  {column.sortable ? (
                    <button className={active ? 'sort-btn active' : 'sort-btn'} onClick={() => onSort(column.key)}>
                      {column.label}
                      <span className="sort-arrow" aria-hidden="true">
                        {active ? (order === 'asc' ? '↑' : '↓') : '↕'}
                      </span>
                    </button>
                  ) : (
                    column.label
                  )}
                </th>
              )
            })}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={rowKey(row)}>
              {columns.map((column) => (
                <td key={column.key} className={column.align === 'right' ? 'num' : ''}>
                  {column.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Light gray table shown before any data exists. */
export function TablePlaceholder({ columns = 6, rows = 7 }: { columns?: number; rows?: number }) {
  return (
    <div className="table-placeholder" aria-hidden="true">
      {Array.from({ length: rows }, (_, r) => (
        <div className="placeholder-row" key={r}>
          {Array.from({ length: columns }, (_, c) => (
            <span key={c} className="placeholder-cell" style={{ width: `${55 + ((r * 7 + c * 13) % 40)}%` }} />
          ))}
        </div>
      ))}
    </div>
  )
}
