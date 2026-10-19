import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { apiGet, downloadCsv, query } from '../api/client'
import type { Page } from '../api/types'

export const PAGE_SIZE = 40

/** Keys the page's own UI owns; anything else in the URL (e.g. ?profile= for the dialog) is ignored. */
type Options = {
  endpoint: string
  filterKeys: readonly string[]
  defaultSort: string
  /** Bump to refetch without changing the URL, e.g. after sending an event. */
  refreshKey?: number
}

export type Changes = Record<string, string | string[] | null>

/** True when a filter form's values differ from what's applied in the URL (so Apply would change something). */
export function differsFromApplied(values: Record<string, string | string[] | boolean>, params: URLSearchParams): boolean {
  return Object.entries(values).some(([key, value]) => {
    if (Array.isArray(value)) return [...value].sort().join('\n') !== [...params.getAll(key)].sort().join('\n')
    if (typeof value === 'boolean') return value !== (params.get(key) === 'true')
    return value.trim() !== (params.get(key) ?? '').trim()
  })
}
type Result<T> = { query: string; page?: Page<T>; error?: string }

/**
 * State for a filterable, sortable, paged table kept entirely in the URL, so views can be bookmarked,
 * shared and navigated with the back button.
 */
export function useListQuery<T>({ endpoint, filterKeys, defaultSort, refreshKey = 0 }: Options) {
  const [params, setParams] = useSearchParams()
  const [result, setResult] = useState<Result<T>>({ query: '' })

  const sort = params.get('sort') ?? defaultSort
  const order = (params.get('order') ?? 'desc') as 'asc' | 'desc'
  const page = Number(params.get('page') ?? '1')

  const listParams = useMemo(() => {
    const values: Record<string, string | string[] | boolean> = {}
    for (const key of filterKeys) values[key] = key === 'segment_id' ? params.getAll(key) : (params.get(key) ?? '')
    return values
  }, [params, filterKeys])

  const filterString = query(listParams)
  const apiQuery = `${filterString}${filterString ? '&' : '?'}${new URLSearchParams({
    sort,
    order,
    page: String(page),
    page_size: String(PAGE_SIZE),
  })}`
  const requestKey = `${apiQuery}#${refreshKey}`

  useEffect(() => {
    let stale = false
    apiGet<Page<T>>(`${endpoint}${apiQuery}`)
      .then((data) => !stale && setResult({ query: requestKey, page: data }))
      .catch((err: Error) => !stale && setResult({ query: requestKey, error: err.message }))
    return () => {
      stale = true
    }
  }, [endpoint, apiQuery, requestKey])

  function update(changes: Changes) {
    const next = new URLSearchParams(params)
    for (const [key, value] of Object.entries(changes)) {
      next.delete(key)
      if (Array.isArray(value)) value.forEach((v) => next.append(key, v))
      else if (value) next.set(key, value)
    }
    setParams(next)
  }

  function clear() {
    const next = new URLSearchParams()
    const profile = params.get('profile')
    if (profile) next.set('profile', profile)
    setParams(next)
  }

  const hasFilters = filterKeys.some((k) => params.getAll(k).some(Boolean))

  return {
    params,
    sort,
    order,
    page,
    data: result.page,
    loading: result.query !== requestKey,
    error: result.query === requestKey ? result.error : undefined,
    hasFilters,
    /** URL-shaped key of the applied filters; use as a React key to reset filter forms. */
    appliedKey: filterString,
    update,
    clear,
    toggleSort: (key: string) =>
      update({ sort: key, order: key === sort && order === 'desc' ? 'asc' : 'desc', page: null }),
    setPage: (p: number) => update({ page: p > 1 ? String(p) : null }),
    applyFilters: (changes: Changes) => update({ ...changes, page: null }),
    exportCsv: (fallbackName: string) =>
      downloadCsv(`${endpoint}${filterString}${filterString ? '&' : '?'}${new URLSearchParams({ sort, order, format: 'csv' })}`, fallbackName),
  }
}
