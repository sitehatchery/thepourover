import { useState, type FormEvent } from 'react'
import type { AppEventRow } from '../api/types'
import AppEventSender from '../components/AppEventSender'
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
import { PAGE_SIZE, useListQuery, type Changes } from '../lib/useListQuery'
import './TablePage.css'

const EVENTS = ['app_open', 'read_story', 'link_click', 'login']
const FILTER_KEYS = ['date_from', 'date_to', 'today', 'event', 'user_id', 'anonymous', 'email', 'segment_id', 'profile_id'] as const

const COLUMNS: Column<AppEventRow>[] = [
  { key: 'event_id', label: 'Event ID', render: (e) => <code>{e.event_id}</code> },
  { key: 'event', label: 'Event', sortable: true, render: (e) => <span className="pill pill-neutral">{e.event}</span> },
  { key: 'email', label: 'Email', sortable: true, render: (e) => <EmailLink email={e.email} profileId={e.profile_id} fallback="" /> },
  {
    key: 'user_id',
    label: 'User ID',
    sortable: true,
    render: (e) => (e.user_id ? <code>{e.user_id}</code> : <span className="cell-muted">anonymous</span>),
  },
  { key: 'device_id', label: 'Device ID', render: (e) => <code>{e.device_id}</code> },
  {
    key: 'timestamp',
    label: 'Timestamp',
    sortable: true,
    render: (e) => (
      <>
        {formatDate(e.timestamp)} <span className="cell-time">{e.timestamp.slice(11, 19)}</span>
      </>
    ),
  },
  { key: 'properties', label: 'Properties', render: (e) => e.properties },
]

export default function AppEventsPage() {
  const [refreshKey, setRefreshKey] = useState(0)
  const list = useListQuery<AppEventRow>({ endpoint: '/app_events', filterKeys: FILTER_KEYS, defaultSort: 'timestamp', refreshKey })
  const lookups = useLookups()
  const profileId = list.params.get('profile_id')

  return (
    <section className="table-page">
      <ListHeader
        title="App Events"
        description="Events from the mobile app, received live through the webhook"
        total={list.data?.total}
        hasFilters={list.hasFilters}
        noun="app event"
        onExport={() => list.exportCsv('app_events.csv')}
      />

      <AppEventSender onSent={() => setRefreshKey((k) => k + 1)} />

      <AppEventFilters
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
        noun="app events"
        emptyMessage="No app events yet. They arrive through the webhook; send one with the form above."
      >
        {(data) => (
          <>
            <DataTable
              caption="App events"
              columns={COLUMNS}
              rows={data.items}
              rowKey={(e) => e.event_id}
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

function AppEventFilters({ params, hasFilters, lookups, onApply, onClear }: FilterProps) {
  const read = (key: string) => params.get(key) ?? ''
  const [event, setEvent] = useState(read('event'))
  const [userId, setUserId] = useState(read('user_id'))
  const [anonymous, setAnonymous] = useState(params.get('anonymous') === 'true')
  const [email, setEmail] = useState(read('email'))
  const [from, setFrom] = useState(read('date_from'))
  const [to, setTo] = useState(read('date_to'))
  const [segments, setSegments] = useState(params.getAll('segment_id'))
  const today = params.get('today') === 'true'

  function submit(e: FormEvent) {
    e.preventDefault()
    onApply({
      event,
      user_id: anonymous ? null : userId,
      anonymous: anonymous ? 'true' : null,
      email,
      date_from: from,
      date_to: to,
      segment_id: segments,
    })
  }

  return (
    <form className="filter-bar" onSubmit={submit}>
      <label className="field">
        Event
        <select className="input" value={event} onChange={(e) => setEvent(e.target.value)}>
          <option value="">Any</option>
          {EVENTS.map((name) => (
            <option key={name}>{name}</option>
          ))}
        </select>
      </label>
      <label className="field">
        User ID
        <input
          className="input"
          placeholder="u_…"
          value={userId}
          disabled={anonymous}
          onChange={(e) => setUserId(e.target.value)}
        />
      </label>
      <label className="field checkbox-field">
        <span>
          <input type="checkbox" checked={anonymous} onChange={(e) => setAnonymous(e.target.checked)} /> Anonymous only
        </span>
        <span className="field-hint">Device not logged in yet</span>
      </label>
      <label className="field">
        Email
        <input className="input" placeholder="Part of an email" value={email} onChange={(e) => setEmail(e.target.value)} />
      </label>
      <DateRange legend="Happened" from={from} to={to} onChange={(f, t) => (setFrom(f), setTo(t))} />
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
        <button type="submit" className="btn btn-primary" disabled={dateRangeInvalid(from, to)}>
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
