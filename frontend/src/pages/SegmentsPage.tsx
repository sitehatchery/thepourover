import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiGet, apiSend } from '../api/client'
import type { Segment } from '../api/types'
import { TablePlaceholder } from '../components/DataTable'
import { countOf } from '../lib/format'
import './SegmentsPage.css'
import './TablePage.css'

const GROUPS: { key: Segment['group']; label: string; blurb: string }[] = [
  { key: 'subscriber', label: 'Subscribers', blurb: 'Newsletter signups, sources and email engagement' },
  { key: 'app_users', label: 'App users', blurb: 'App accounts and in-app activity' },
  { key: 'web_events', label: 'Website visitors', blurb: 'Linked visits to thepourover.org' },
]

export default function SegmentsPage() {
  const [segments, setSegments] = useState<Segment[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [reload, setReload] = useState(0)

  useEffect(() => {
    apiGet<Segment[]>('/segments')
      .then(setSegments)
      .catch((err: Error) => setError(err.message))
  }, [reload])

  async function remove(segment: Segment) {
    if (!window.confirm(`Delete the segment “${segment.name}”? This can't be undone.`)) return
    try {
      await apiSend('DELETE', `/segments/${segment.slug}`)
      setReload((n) => n + 1)
    } catch (err) {
      setError((err as Error).message)
    }
  }

  return (
    <section className="table-page">
      <div className="page-head">
        <div>
          <h1>Segments</h1>
          <p className="page-sub">Saved groups of people, recalculated live every time you use them</p>
        </div>
        <div className="page-actions">
          <Link className="btn btn-primary" to="/segments/new">
            + New segment
          </Link>
        </div>
      </div>

      {error && (
        <p className="notice notice-error" role="alert">
          {error}
        </p>
      )}
      {!segments && !error && <TablePlaceholder />}

      {segments &&
        GROUPS.map((group) => {
          const items = segments.filter((s) => s.group === group.key)
          if (!items.length) return null
          return (
            <section key={group.key} className="segment-group">
              <div className="segment-group-head">
                <h2>{group.label}</h2>
                <p>{group.blurb}</p>
              </div>
              <ul className="segment-cards">
                {items.map((s) => (
                  <li key={s.slug} className="segment-card">
                    <div className="segment-card-top">
                      <Link to={`/segments/${s.slug}`} className="segment-name">
                        {s.name}
                      </Link>
                      <span className="segment-count">{countOf(s.member_count ?? 0, 'person', 'people')}</span>
                    </div>
                    <p className="segment-summary">{s.summary}</p>
                    {s.description && <p className="segment-desc">{s.description}</p>}
                    <div className="segment-actions">
                      <Link to={`/segments/${s.slug}`}>View members</Link>
                      <Link to={`/subscribers?segment_id=${s.slug}`}>Filter subscribers</Link>
                      <Link to={`/segments/${s.slug}/edit`}>Edit</Link>
                      <button type="button" className="link-btn danger" onClick={() => void remove(s)}>
                        Delete
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          )
        })}
    </section>
  )
}
