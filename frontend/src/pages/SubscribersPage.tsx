import { useState, type FormEvent } from 'react'
import type { Person } from '../api/types'
import DataTable from '../components/DataTable'
import DateRange from '../components/DateRange'
import ListHeader from '../components/ListHeader'
import ListStates from '../components/ListStates'
import Pagination from '../components/Pagination'
import SegmentPicker from '../components/SegmentPicker'
import { PERSON_COLUMNS } from '../components/personColumns'
import { dateRangeInvalid, getToday, shortDate } from '../lib/format'
import { useLookups, type Lookups } from '../lib/useLookups'
import { PAGE_SIZE, differsFromApplied, useListQuery, type Changes } from '../lib/useListQuery'
import './TablePage.css'

const FILTER_KEYS = ['email', 'app_user_id', 'status', 'acquisition_source', 'signup_from', 'signup_to', 'today', 'segment_id'] as const

export default function SubscribersPage() {
  const list = useListQuery<Person>({ endpoint: '/subscribers', filterKeys: FILTER_KEYS, defaultSort: 'signup_date' })
  const lookups = useLookups()

  return (
    <section className="table-page">
      <ListHeader
        title="Subscribers"
        description="Newsletter subscribers with their app and website activity"
        total={list.data?.total}
        hasFilters={list.hasFilters}
        noun="subscriber"
        onExport={() => list.exportCsv('subscribers.csv')}
      />

      {/* Keyed by the applied filters, so the form resets whenever the URL changes (back button, links). */}
      <SubscriberFilters
        key={list.appliedKey}
        params={list.params}
        hasFilters={list.hasFilters}
        lookups={lookups}
        onApply={list.applyFilters}
        onClear={list.clear}
      />

      <ListStates
        data={list.data}
        error={list.error}
        hasFilters={list.hasFilters}
        noun="subscribers"
        emptyMessage="No subscribers yet. Run an import to load subscribers, web events and app users from the shared data folder."
      >
        {(data) => (
          <>
            <DataTable
              caption="Subscribers"
              columns={PERSON_COLUMNS}
              rows={data.items}
              rowKey={(p) => p.profile_id}
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

function SubscriberFilters({ params, hasFilters, lookups, onApply, onClear }: FilterProps) {
  const read = (key: string) => params.get(key) ?? ''
  const [email, setEmail] = useState(read('email'))
  const [appUserId, setAppUserId] = useState(read('app_user_id'))
  const [status, setStatus] = useState(read('status'))
  const [source, setSource] = useState(read('acquisition_source'))
  const [from, setFrom] = useState(read('signup_from'))
  const [to, setTo] = useState(read('signup_to'))
  const [segments, setSegments] = useState(params.getAll('segment_id'))
  const today = params.get('today') === 'true'
  const changed = differsFromApplied(
    { email, app_user_id: appUserId, status, acquisition_source: source, signup_from: from, signup_to: to, segment_id: segments },
    params,
  )

  function submit(event: FormEvent) {
    event.preventDefault()
    onApply({
      email,
      app_user_id: appUserId,
      status,
      acquisition_source: source,
      signup_from: from,
      signup_to: to,
      segment_id: segments,
    })
  }

  return (
    <form className="filter-bar" onSubmit={submit}>
      <label className="field">
        Email
        <input className="input" placeholder="Part of an email" value={email} onChange={(e) => setEmail(e.target.value)} />
      </label>
      <label className="field">
        App user ID
        <input className="input" placeholder="u_…" value={appUserId} onChange={(e) => setAppUserId(e.target.value)} />
      </label>
      <label className="field">
        Status
        <select className="input" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">Any</option>
          <option value="active">Active</option>
          <option value="unsubscribed">Unsubscribed</option>
        </select>
      </label>
      <label className="field">
        Source
        <select className="input" value={source} onChange={(e) => setSource(e.target.value)}>
          <option value="">Any</option>
          {lookups.sources.map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
      </label>
      <DateRange legend="Signed up" from={from} to={to} onChange={(f, t) => (setFrom(f), setTo(t))} />
      <SegmentPicker segments={lookups.segments} selected={segments} onChange={setSegments} />

      <div className="filter-actions">
        <button
          type="button"
          className={today ? 'btn btn-active' : 'btn'}
          aria-pressed={today}
          onClick={() => onApply({ today: today ? null : 'true' })}
        >
          Signed up today <span className="btn-note">{shortDate(getToday())}</span>
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
