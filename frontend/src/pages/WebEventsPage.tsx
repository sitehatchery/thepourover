import { useState, type FormEvent } from 'react'
import type { WebEventRow } from '../api/types'
import DataTable, { type Column } from '../components/DataTable'
import DateRange from '../components/DateRange'
import EmailLink from '../components/EmailLink'
import ListHeader from '../components/ListHeader'
import ListStates from '../components/ListStates'
import Pagination from '../components/Pagination'
import PersonFilterTag from '../components/PersonFilterTag'
import SegmentPicker from '../components/SegmentPicker'
import { dateRangeInvalid, formatDate, getToday, shortDate } from '../lib/format'
import { useLookups, type Lookups } from '../lib/useLookups'
import { PAGE_SIZE, differsFromApplied, useListQuery, type Changes } from '../lib/useListQuery'
import './TablePage.css'

const FILTER_KEYS = ['date_from', 'date_to', 'today', 'utm_source', 'email', 'page_path', 'segment_id', 'profile_id'] as const

const COLUMNS: Column<WebEventRow>[] = [
  {
    key: 'email',
    label: 'Email',
    sortable: true,
    render: (e) => (
      <>
        <EmailLink email={e.email} profileId={e.profile_id} />
        {e.email_backfilled && (
          <span className="cell-hint" title={`No email on this visit; matched through visitor ${e.visitor_id}`}>
            via visitor
          </span>
        )}
      </>
    ),
  },
  { key: 'visitor_id', label: 'Visitor ID', render: (e) => <code>{e.visitor_id}</code> },
  { key: 'page', label: 'Page', sortable: true, render: (e) => e.page },
  {
    key: 'timestamp',
    label: 'Timestamp (UTC)',
    sortable: true,
    render: (e) => (
      <>
        {formatDate(e.timestamp)} <span className="cell-time">{e.timestamp.slice(11, 19)}</span>
      </>
    ),
  },
  { key: 'utm_source', label: 'UTM source', sortable: true, render: (e) => e.utm_source },
]

export default function WebEventsPage() {
  const list = useListQuery<WebEventRow>({ endpoint: '/web_events', filterKeys: FILTER_KEYS, defaultSort: 'timestamp' })
  const lookups = useLookups()
  const profileId = list.params.get('profile_id')

  return (
    <section className="table-page">
      <ListHeader
        title="Web Events"
        description="Website visits, linked to subscribers by email and visitor ID"
        total={list.data?.total}
        hasFilters={list.hasFilters}
        noun="web event"
        onExport={() => list.exportCsv('web_events.csv')}
      />

      <WebEventFilters
        key={list.appliedKey}
        params={list.params}
        hasFilters={list.hasFilters}
        lookups={lookups}
        onApply={list.applyFilters}
        onClear={list.clear}
      />
      {profileId && <PersonFilterTag profileId={profileId} onRemove={() => list.applyFilters({ profile_id: null })} />}

      <ListStates
        data={list.data}
        error={list.error}
        hasFilters={list.hasFilters}
        noun="web events"
        emptyMessage="No web events yet. Run an import to load them."
      >
        {(data) => (
          <>
            <DataTable
              caption="Web events"
              columns={COLUMNS}
              rows={data.items}
              rowKey={(e) => String(e.web_event_id)}
              sort={list.sort}
              order={list.order}
              onSort={list.toggleSort}
              loading={list.loading}
            />
            <Pagination page={list.page} pageSize={PAGE_SIZE} total={data.total} onPage={list.setPage} />
          </>
        )}
      </ListStates>
    </section>
  )
}

type FilterProps = {
  params: URLSearchParams
  hasFilters: boolean
  lookups: Lookups
  onApply: (changes: Changes) => void
  onClear: () => void
}

function WebEventFilters({ params, hasFilters, lookups, onApply, onClear }: FilterProps) {
  const read = (key: string) => params.get(key) ?? ''
  const [email, setEmail] = useState(read('email'))
  const [utm, setUtm] = useState(read('utm_source'))
  const [page, setPage] = useState(read('page_path'))
  const [from, setFrom] = useState(read('date_from'))
  const [to, setTo] = useState(read('date_to'))
  const [segments, setSegments] = useState(params.getAll('segment_id'))
  const today = params.get('today') === 'true'
  const changed = differsFromApplied({ email, utm_source: utm, page_path: page, date_from: from, date_to: to, segment_id: segments }, params)

  function submit(event: FormEvent) {
    event.preventDefault()
    onApply({ email, utm_source: utm, page_path: page, date_from: from, date_to: to, segment_id: segments })
  }

  return (
    <form className="filter-bar" onSubmit={submit}>
      <label className="field">
        Email
        <input className="input" placeholder="Part of an email" value={email} onChange={(e) => setEmail(e.target.value)} />
      </label>
      <label className="field">
        UTM source
        <select className="input" value={utm} onChange={(e) => setUtm(e.target.value)}>
          <option value="">Any</option>
          {lookups.utmSources.map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
      </label>
      <label className="field">
        Page
        <select className="input" value={page} onChange={(e) => setPage(e.target.value)}>
          <option value="">Any</option>
          {lookups.pages.map((p) => (
            <option key={p}>{p}</option>
          ))}
        </select>
      </label>
      <DateRange legend="Visited" from={from} to={to} onChange={(f, t) => (setFrom(f), setTo(t))} />
      <SegmentPicker segments={lookups.segments} selected={segments} onChange={setSegments} />

      <div className="filter-actions">
        <button
          type="button"
          className={today ? 'btn btn-active' : 'btn'}
          aria-pressed={today}
          onClick={() => onApply({ today: today ? null : 'true' })}
        >
          Today <span className="btn-note">{shortDate(getToday())}</span>
        </button>
        <button type="submit" className="btn btn-primary" disabled={!changed || dateRangeInvalid(from, to)}>
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
