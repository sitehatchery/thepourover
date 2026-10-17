import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { useSearchParams } from 'react-router-dom'
import { apiGet, downloadCsv, query } from '../api/client'
import type { Page, Person, SegmentSummary } from '../api/types'
import DataTable, { TablePlaceholder, type Column } from '../components/DataTable'
import Pagination from '../components/Pagination'
import SegmentPicker from '../components/SegmentPicker'
import { formatDate, formatNumber, getToday, shortDate } from '../lib/format'
import './TablePage.css'

const PAGE_SIZE = 40
const FILTER_KEYS = ['email', 'app_user_id', 'status', 'acquisition_source', 'signup_from', 'signup_to'] as const
type Filters = Record<(typeof FILTER_KEYS)[number], string>
type Changes = Record<string, string | string[] | null>

const COLUMNS: Column<Person>[] = [
  { key: 'email', label: 'Email', sortable: true, render: (p) => <span className="cell-email">{p.email}</span> },
  { key: 'signup_date', label: 'Signup date', sortable: true, render: (p) => formatDate(p.signup_date) },
  {
    key: 'status',
    label: 'Status',
    sortable: true,
    render: (p) => p.status && <span className={`pill pill-${p.status}`}>{p.status === 'active' ? 'Active' : 'Unsubscribed'}</span>,
  },
  { key: 'acquisition_source', label: 'Acquisition source', sortable: true, render: (p) => p.acquisition_source },
  { key: 'last_open_date', label: 'Last open', sortable: true, render: (p) => formatDate(p.last_open_date) },
  { key: 'app_user_id', label: 'App user ID', sortable: true, render: (p) => <code>{p.app_user_id}</code> },
  { key: 'app_created_at', label: 'App created', sortable: true, render: (p) => formatDate(p.app_created_at) },
  {
    key: 'app_event_count',
    label: 'App events',
    sortable: true,
    align: 'right',
    render: (p) => (p.app_user_id ? formatNumber(p.app_event_count) : ''),
  },
  {
    key: 'web_event_count',
    label: 'Web events',
    sortable: true,
    align: 'right',
    render: (p) => (p.web_event_count ? formatNumber(p.web_event_count) : ''),
  },
  { key: 'last_seen', label: 'Last seen', sortable: true, render: (p) => formatDate(p.last_seen) },
  { key: 'first_utm_source', label: 'First source', sortable: true, render: (p) => p.first_utm_source },
]

function readFilters(params: URLSearchParams): Filters {
  return Object.fromEntries(FILTER_KEYS.map((k) => [k, params.get(k) ?? ''])) as Filters
}

type Result = { query: string; page?: Page<Person>; error?: string }

export default function SubscribersPage() {
  const [params, setParams] = useSearchParams()
  const [result, setResult] = useState<Result>({ query: '' })
  const [segments, setSegments] = useState<SegmentSummary[]>([])
  const [sources, setSources] = useState<string[]>([])
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState<string | null>(null)

  const sort = params.get('sort') ?? 'signup_date'
  const order = (params.get('order') ?? 'desc') as 'asc' | 'desc'
  const page = Number(params.get('page') ?? '1')
  const today = params.get('today') === 'true'
  const applied = params.toString()

  useEffect(() => {
    apiGet<SegmentSummary[]>('/segments?with_counts=false').then(setSegments).catch(() => setSegments([]))
    apiGet<{ fields: Record<string, { values?: string[] }> }>('/segments/schema')
      .then((schema) => setSources(schema.fields.acquisition_source?.values ?? []))
      .catch(() => setSources([]))
  }, [])

  const apiQuery = useMemo(() => {
    const current = new URLSearchParams(applied)
    return query({
      ...readFilters(current),
      today: current.get('today') === 'true',
      segment_id: current.getAll('segment_id'),
      sort: current.get('sort') ?? 'signup_date',
      order: current.get('order') ?? 'desc',
      page: current.get('page') ?? '1',
      page_size: PAGE_SIZE,
    })
  }, [applied])

  useEffect(() => {
    let stale = false
    apiGet<Page<Person>>(`/subscribers${apiQuery}`)
      .then((page) => !stale && setResult({ query: apiQuery, page }))
      .catch((err: Error) => !stale && setResult({ query: apiQuery, error: err.message }))
    return () => {
      stale = true
    }
  }, [apiQuery])

  // While a new query loads, keep showing the previous rows (dimmed) instead of flashing empty.
  const loading = result.query !== apiQuery
  const data = result.page

  function update(changes: Changes) {
    const next = new URLSearchParams(params)
    for (const [key, value] of Object.entries(changes)) {
      next.delete(key)
      if (Array.isArray(value)) value.forEach((v) => next.append(key, v))
      else if (value) next.set(key, value)
    }
    setParams(next)
  }

  function toggleSort(key: string) {
    const nextOrder = key === sort && order === 'desc' ? 'asc' : 'desc'
    update({ sort: key, order: nextOrder, page: null })
  }

  async function exportCsv() {
    setExporting(true)
    setExportError(null)
    try {
      const filters = query({ ...readFilters(params), today, segment_id: params.getAll('segment_id'), sort, order, format: 'csv' })
      await downloadCsv(`/subscribers${filters}`, 'subscribers.csv')
    } catch (err) {
      setExportError((err as Error).message)
    } finally {
      setExporting(false)
    }
  }

  const hasFilters = FILTER_KEYS.some((k) => params.get(k)) || today || params.getAll('segment_id').length > 0
  const isEmptyDatabase = data && data.total === 0 && !hasFilters
  const error = (!loading && result.error) || exportError

  return (
    <section className="table-page">
      <div className="page-head">
        <div>
          <h1>Subscribers</h1>
          <p className="page-sub">
            {data
              ? `${formatNumber(data.total)} ${hasFilters ? 'matching subscribers' : 'subscribers'}`
              : 'Newsletter subscribers with their app and website activity'}
          </p>
        </div>
        <div className="page-actions">
          <button className="btn" onClick={() => void exportCsv()} disabled={exporting || !data?.total}>
            {exporting ? 'Exporting…' : 'Export CSV'}
          </button>
        </div>
      </div>

      {/* Keyed by the applied filters, so the form resets whenever the URL changes (back button, links). */}
      <SubscriberFilters
        key={applied}
        params={params}
        today={today}
        hasFilters={hasFilters}
        segments={segments}
        sources={sources}
        onApply={(changes) => update({ ...changes, page: null })}
        onClear={() => setParams(new URLSearchParams())}
      />

      {error && (
        <p className="notice notice-error" role="alert">
          Couldn’t load subscribers: {error}
        </p>
      )}

      {isEmptyDatabase ? (
        <div className="empty-state">
          <TablePlaceholder />
          <p>No subscribers yet. Run an import to load subscribers, web events and app users from the shared data folder.</p>
        </div>
      ) : data && data.total === 0 ? (
        <p className="notice">No subscribers match these filters.</p>
      ) : data ? (
        <>
          <DataTable
            caption="Subscribers"
            columns={COLUMNS}
            rows={data.items}
            rowKey={(p) => p.profile_id}
            sort={sort}
            order={order}
            onSort={toggleSort}
            loading={loading}
          />
          <Pagination page={page} pageSize={PAGE_SIZE} total={data.total} onPage={(p) => update({ page: String(p) })} />
        </>
      ) : (
        !error && <TablePlaceholder />
      )}
    </section>
  )
}

type FilterProps = {
  params: URLSearchParams
  today: boolean
  hasFilters: boolean
  segments: SegmentSummary[]
  sources: string[]
  onApply: (changes: Changes) => void
  onClear: () => void
}

function SubscriberFilters({ params, today, hasFilters, segments, sources, onApply, onClear }: FilterProps) {
  const [draft, setDraft] = useState<Filters>(() => readFilters(params))
  const [draftSegments, setDraftSegments] = useState<string[]>(() => params.getAll('segment_id'))
  const set = (key: keyof Filters) => (value: string) => setDraft({ ...draft, [key]: value })
  const dateError = Boolean(draft.signup_from && draft.signup_to && draft.signup_from > draft.signup_to)

  function submit(event: FormEvent) {
    event.preventDefault()
    onApply({ ...draft, segment_id: draftSegments })
  }

  return (
    <form className="filter-bar" onSubmit={submit}>
      <label className="field">
        Email
        <input className="input" placeholder="Part of an email" value={draft.email} onChange={(e) => set('email')(e.target.value)} />
      </label>
      <label className="field">
        App user ID
        <input className="input" placeholder="u_…" value={draft.app_user_id} onChange={(e) => set('app_user_id')(e.target.value)} />
      </label>
      <label className="field">
        Status
        <select className="input" value={draft.status} onChange={(e) => set('status')(e.target.value)}>
          <option value="">Any</option>
          <option value="active">Active</option>
          <option value="unsubscribed">Unsubscribed</option>
        </select>
      </label>
      <label className="field">
        Source
        <select className="input" value={draft.acquisition_source} onChange={(e) => set('acquisition_source')(e.target.value)}>
          <option value="">Any</option>
          {sources.map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
      </label>
      <fieldset className="field date-range">
        <legend>Signed up</legend>
        <div className="date-inputs">
          <input
            className="input"
            type="date"
            aria-label="Signed up from"
            value={draft.signup_from}
            max={getToday()}
            onChange={(e) => set('signup_from')(e.target.value)}
          />
          <span aria-hidden="true">–</span>
          <input
            className="input"
            type="date"
            aria-label="Signed up to"
            value={draft.signup_to}
            max={getToday()}
            onChange={(e) => set('signup_to')(e.target.value)}
          />
        </div>
        {dateError && <span className="error-text">The start date must be on or before the end date</span>}
      </fieldset>
      <SegmentPicker segments={segments} selected={draftSegments} onChange={setDraftSegments} />

      <div className="filter-actions">
        <button
          type="button"
          className={today ? 'btn btn-active' : 'btn'}
          aria-pressed={today}
          onClick={() => onApply({ today: today ? null : 'true' })}
        >
          Signed up today <span className="btn-note">{shortDate(getToday())}</span>
        </button>
        <button type="submit" className="btn btn-primary" disabled={dateError}>
          Apply filters
        </button>
        {hasFilters && (
          <button type="button" className="btn btn-ghost" onClick={onClear}>
            Clear
          </button>
        )}
      </div>
    </form>
  )
}
