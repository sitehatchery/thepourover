import { useEffect, useState } from 'react'
import { apiGet } from '../api/client'
import type { SegmentSummary } from '../api/types'

type Schema = { fields: Record<string, { values?: string[] }> }

export type Lookups = {
  segments: SegmentSummary[]
  sources: string[]
  utmSources: string[]
  pages: string[]
}

const EMPTY: Lookups = { segments: [], sources: [], utmSources: [], pages: [] }
let cache: Promise<Lookups> | null = null

function load(): Promise<Lookups> {
  cache ??= Promise.all([apiGet<SegmentSummary[]>('/segments?with_counts=false'), apiGet<Schema>('/segments/schema')])
    .then(([segments, schema]) => ({
      segments,
      sources: schema.fields.acquisition_source?.values ?? [],
      utmSources: schema.fields.first_utm_source?.values ?? [],
      pages: schema.fields.page_visited?.values ?? [],
    }))
    .catch(() => {
      cache = null
      return EMPTY
    })
  return cache
}

/** Dropdown options for filters (segments, sources, pages), fetched once per page load. */
export function useLookups(): Lookups {
  const [lookups, setLookups] = useState<Lookups>(EMPTY)
  useEffect(() => {
    let active = true
    load().then((value) => active && setLookups(value))
    return () => {
      active = false
    }
  }, [])
  return lookups
}
