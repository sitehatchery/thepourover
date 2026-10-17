import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { apiGet } from '../api/client'
import type { Person, Segment } from '../api/types'
import DataTable from '../components/DataTable'
import ListHeader from '../components/ListHeader'
import ListStates from '../components/ListStates'
import Pagination from '../components/Pagination'
import { PERSON_COLUMNS } from '../components/personColumns'
import { PAGE_SIZE, useListQuery } from '../lib/useListQuery'
import './SegmentEditorPage.css'
import './TablePage.css'

const NO_FILTERS: readonly string[] = []

export default function SegmentMembersPage() {
  const { slug = '' } = useParams()
  const [segment, setSegment] = useState<Segment | null>(null)
  const [error, setError] = useState<string | null>(null)
  const list = useListQuery<Person>({ endpoint: `/segments/${slug}/members`, filterKeys: NO_FILTERS, defaultSort: 'last_seen' })

  useEffect(() => {
    apiGet<Segment>(`/segments/${slug}`)
      .then(setSegment)
      .catch((err: Error) => setError(err.message))
  }, [slug])

  return (
    <section className="table-page">
      <p className="crumb">
        <Link to="/segments">Segments</Link> /
      </p>
      <ListHeader
        title={segment?.name ?? 'Segment'}
        description=""
        total={list.data?.total}
        hasFilters={false}
        noun="person"
        plural="people"
        onExport={() => list.exportCsv(`segment_${slug}.csv`)}
      >
        <Link className="btn" to={`/segments/${slug}/edit`}>
          Edit rules
        </Link>
      </ListHeader>

      {error && <p className="notice notice-error">{error}</p>}

      {segment && (
        <div className="segment-detail">
          <p className="segment-rule">{segment.summary}</p>
          {segment.description && <p className="segment-desc">{segment.description}</p>}
          <p className="segment-uses">
            Use as a filter on{' '}
            <Link to={`/subscribers?segment_id=${slug}`}>Subscribers</Link>,{' '}
            <Link to={`/web-events?segment_id=${slug}`}>Web Events</Link> or{' '}
            <Link to={`/app-events?segment_id=${slug}`}>App Events</Link>.
          </p>
        </div>
      )}

      <ListStates
        data={list.data}
        error={list.error}
        hasFilters={false}
        noun="people"
        emptyMessage="No one matches these rules right now. Membership updates live as new data arrives."
      >
        {(data) => (
          <>
            <DataTable
              caption={`Members of ${segment?.name ?? 'segment'}`}
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
