import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { apiGet } from '../api/client'
import type { AppEventRow, Page, Profile, WebEventRow } from '../api/types'
import { countOf, formatDate, formatNumber } from '../lib/format'
import './ActivityDialog.css'

const ROWS = 10

/** The subscriber activity view. Open when the URL has ?profile=<id>, from any page. */
export default function ActivityDialog() {
  const [params, setParams] = useSearchParams()
  const profileId = params.get('profile')
  const dialogRef = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    if (profileId && !dialog.open) dialog.showModal()
    if (!profileId && dialog.open) dialog.close()
  }, [profileId])

  function close() {
    const next = new URLSearchParams(params)
    next.delete('profile')
    setParams(next)
  }

  return (
    <dialog
      ref={dialogRef}
      className="activity-dialog"
      aria-labelledby="activity-title"
      onClose={() => profileId && close()}
      onClick={(e) => e.target === dialogRef.current && close()}
    >
      {profileId && <ProfileView key={profileId} profileId={profileId} onClose={close} />}
    </dialog>
  )
}

function ProfileView({ profileId, onClose }: { profileId: string; onClose: () => void }) {
  const [profile, setProfile] = useState<Profile | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    apiGet<Profile>(`/profiles/${encodeURIComponent(profileId)}`)
      .then(setProfile)
      .catch((err: Error) => setError(err.message))
  }, [profileId])

  return (
    <div className="activity">
      <header className="activity-head">
        <div>
          <p className="activity-kicker">Subscriber activity</p>
          <h2 id="activity-title">{profile ? (profile.email ?? profile.profile_id) : error ? 'Not found' : 'Loading…'}</h2>
          {profile && (
            <div className="badges">
              {profile.is_subscriber ? (
                <span className={`pill pill-${profile.status}`}>{profile.status === 'active' ? 'Active subscriber' : 'Unsubscribed'}</span>
              ) : (
                <span className="pill pill-neutral">App user, not subscribed</span>
              )}
              {profile.is_placeholder && (
                <span className="pill pill-warn" title="Created when the webhook received an unknown user_id">
                  Placeholder from webhook
                </span>
              )}
            </div>
          )}
        </div>
        <button className="btn btn-ghost close-btn" onClick={onClose} aria-label="Close" autoFocus>
          ×
        </button>
      </header>

      {error && <p className="notice notice-error">{error === 'Profile not found' ? 'This person no longer exists. They may have been removed by a new import.' : error}</p>}

      {profile && (
        <>
          <dl className="stats">
            <Stat label="Web events" value={formatNumber(profile.web_event_count)} note={countOf(profile.web_active_days, 'active day')} />
            <Stat label="App events" value={formatNumber(profile.app_event_count)} note={profile.app_user_id ? 'Has the app' : 'No app account'} />
            <Stat label="Last seen" value={formatDate(profile.last_seen) || '—'} note="Web or app" />
            <Stat label="First source" value={profile.first_utm_source ?? '—'} note="Oldest tagged visit" />
          </dl>

          <div className="activity-grid">
            <section>
              <h3>Newsletter</h3>
              {profile.newsletter ? (
                <dl className="facts">
                  <Fact label="Email" value={profile.newsletter.email} />
                  <Fact label="Signed up" value={formatDate(profile.newsletter.signup_date)} />
                  <Fact label="Source" value={profile.newsletter.acquisition_source} />
                  <Fact label="Last open" value={formatDate(profile.newsletter.last_open_date) || 'Never opened'} />
                </dl>
              ) : (
                <p className="muted">Not a newsletter subscriber.</p>
              )}
            </section>

            <section>
              <h3>App</h3>
              {profile.app_accounts.length ? (
                <dl className="facts">
                  {profile.app_accounts.map((a) => (
                    <Fact key={a.app_user_id} label="User ID" value={<code>{a.app_user_id}</code>} />
                  ))}
                  <Fact label="Created" value={formatDate(profile.app_accounts[0].created_at)} />
                  <Fact label="Devices" value={profile.device_ids.length ? profile.device_ids.map((d) => <code key={d}>{d} </code>) : 'None seen yet'} />
                  <Fact label="Last active" value={formatDate(profile.last_app_activity)} />
                </dl>
              ) : (
                <p className="muted">No app account.</p>
              )}
            </section>

            <section className="span-2">
              <h3>Segments</h3>
              {profile.segments.length ? (
                <ul className="tags">
                  {profile.segments.map((s) => (
                    <li key={s.slug}>
                      <Link className="tag tag-link" to={`/subscribers?segment_id=${s.slug}`}>
                        {s.name}
                      </Link>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="muted">Not in any saved segment.</p>
              )}
            </section>
          </div>

          <EventTable<WebEventRow>
            title="Site visits"
            path={`/profiles/${profile.profile_id}/web_events`}
            allLink={profile.web_event_count ? `/web-events?profile_id=${profile.profile_id}` : null}
            empty="No linked website visits."
            columns={['Page', 'When', 'Source']}
            row={(e) => [
              <span key="p">{e.page}</span>,
              <span key="t">
                {formatDate(e.timestamp)} <span className="time">{e.timestamp.slice(11, 16)}</span>
                {e.email_backfilled && (
                  <span className="hint" title={`Matched through visitor ${e.visitor_id}`}>
                    {' '}
                    · via visitor
                  </span>
                )}
              </span>,
              <span key="s">{e.utm_source}</span>,
            ]}
            rowKey={(e) => String(e.web_event_id)}
          />

          <EventTable<AppEventRow>
            title="App activity"
            path={`/profiles/${profile.profile_id}/app_events`}
            allLink={profile.app_event_count ? `/app-events?profile_id=${profile.profile_id}` : null}
            empty={profile.app_user_id ? 'No app events yet.' : 'No app account.'}
            columns={['Event', 'When', 'Device', 'Details']}
            row={(e) => [
              <span key="e" className="event-name">{e.event.replace('_', ' ')}</span>,
              <span key="t">
                {formatDate(e.timestamp)} <span className="time">{e.timestamp.slice(11, 16)}</span>
              </span>,
              <code key="d">{e.device_id}</code>,
              <span key="p">{e.properties}</span>,
            ]}
            rowKey={(e) => e.event_id}
          />

          {profile.is_subscriber && profile.email && (
            <p className="activity-footer">
              <Link to={`/subscribers?email=${encodeURIComponent(profile.email)}`}>Show in the Subscribers table →</Link>
            </p>
          )}
        </>
      )}
    </div>
  )
}

function Stat({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <div className="stat">
      <dt>{label}</dt>
      <dd>
        <span className="stat-value">{value}</span>
        <span className="stat-note">{note}</span>
      </dd>
    </div>
  )
}

function Fact({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="fact">
      <dt>{label}</dt>
      <dd>{value || '—'}</dd>
    </div>
  )
}

type EventTableProps<T> = {
  title: string
  path: string
  allLink: string | null
  empty: string
  columns: string[]
  row: (item: T) => ReactNode[]
  rowKey: (item: T) => string
}

function EventTable<T>({ title, path, allLink, empty, columns, row, rowKey }: EventTableProps<T>) {
  const [page, setPage] = useState(1)
  const [data, setData] = useState<Page<T> | null>(null)

  useEffect(() => {
    apiGet<Page<T>>(`${path}?page=${page}&page_size=${ROWS}`).then(setData).catch(() => setData(null))
  }, [path, page])

  const pages = data ? Math.ceil(data.total / ROWS) : 0
  return (
    <section className="event-section">
      <div className="event-section-head">
        <h3>
          {title} {data && <span className="count">{formatNumber(data.total)}</span>}
        </h3>
        {allLink && <Link to={allLink}>Open full table →</Link>}
      </div>
      {data && data.total === 0 ? (
        <p className="muted">{empty}</p>
      ) : (
        <div className="mini-table-wrap">
          <table className="mini-table">
            <thead>
              <tr>
                {columns.map((c) => (
                  <th key={c}>{c}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data?.items.map((item) => (
                <tr key={rowKey(item)}>
                  {row(item).map((cell, i) => (
                    <td key={i}>{cell}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {pages > 1 && (
        <div className="mini-pager">
          <button className="btn" disabled={page <= 1} onClick={() => setPage(page - 1)}>
            Newer
          </button>
          <span>
            {page} / {pages}
          </span>
          <button className="btn" disabled={page >= pages} onClick={() => setPage(page + 1)}>
            Older
          </button>
        </div>
      )}
    </section>
  )
}
