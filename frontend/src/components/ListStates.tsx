import type { ReactNode } from 'react'
import type { Page } from '../api/types'
import { TablePlaceholder } from './DataTable'

type Props<T> = {
  data: Page<T> | undefined
  error: string | undefined
  hasFilters: boolean
  noun: string
  emptyMessage: ReactNode
  children: (data: Page<T>) => ReactNode
}

/** The error, empty, no-match and first-load states every table page shares. */
export default function ListStates<T>({ data, error, hasFilters, noun, emptyMessage, children }: Props<T>) {
  return (
    <>
      {error && (
        <p className="notice notice-error" role="alert">
          Couldn’t load {noun}: {error}
        </p>
      )}
      {data && data.total === 0 && !hasFilters ? (
        <div className="empty-state">
          <TablePlaceholder />
          <p>{emptyMessage}</p>
        </div>
      ) : data && data.total === 0 ? (
        <p className="notice">No {noun} match these filters.</p>
      ) : data ? (
        children(data)
      ) : (
        !error && <TablePlaceholder />
      )}
    </>
  )
}
