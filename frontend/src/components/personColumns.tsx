import { Link } from 'react-router-dom'
import type { Person } from '../api/types'
import type { Column } from './DataTable'
import EmailLink from './EmailLink'
import { formatDate, formatNumber } from '../lib/format'

/** Columns for tables of people: the Subscribers table and segment member lists. */
export const PERSON_COLUMNS: Column<Person>[] = [
  { key: 'email', label: 'Email', sortable: true, render: (p) => <EmailLink email={p.email} profileId={p.profile_id} /> },
  { key: 'signup_date', label: 'Signup date', sortable: true, render: (p) => formatDate(p.signup_date) },
  {
    key: 'status',
    label: 'Status',
    sortable: true,
    render: (p) =>
      p.status ? (
        <span className={`pill pill-${p.status}`}>{p.status === 'active' ? 'Active' : 'Unsubscribed'}</span>
      ) : (
        !p.is_subscriber && <span className="pill pill-neutral">App only</span>
      ),
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
    render: (p) =>
      p.app_user_id && (
        <Link className="count-link" to={`/app-events?profile_id=${p.profile_id}`}>
          {formatNumber(p.app_event_count)}
        </Link>
      ),
  },
  {
    key: 'web_event_count',
    label: 'Web events',
    sortable: true,
    align: 'right',
    render: (p) =>
      p.web_event_count > 0 && (
        <Link className="count-link" to={`/web-events?profile_id=${p.profile_id}`}>
          {formatNumber(p.web_event_count)}
        </Link>
      ),
  },
  { key: 'last_seen', label: 'Last seen', sortable: true, render: (p) => formatDate(p.last_seen) },
  { key: 'first_utm_source', label: 'First source', sortable: true, render: (p) => p.first_utm_source },
]
