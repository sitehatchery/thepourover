type Props = {
  page: number
  pageSize: number
  total: number
  onPage: (page: number) => void
}

/** Hidden when everything fits on one page. */
export default function Pagination({ page, pageSize, total, onPage }: Props) {
  const pages = Math.ceil(total / pageSize)
  if (total <= pageSize) return null
  const first = (page - 1) * pageSize + 1
  const last = Math.min(page * pageSize, total)

  return (
    <nav className="pagination" aria-label="Pages">
      <span className="pagination-range">
        {first.toLocaleString()}–{last.toLocaleString()} of {total.toLocaleString()}
      </span>
      <button className="btn" disabled={page <= 1} onClick={() => onPage(1)} aria-label="First page">
        «
      </button>
      <button className="btn" disabled={page <= 1} onClick={() => onPage(page - 1)}>
        Previous
      </button>
      <span className="pagination-page">
        Page {page} of {pages.toLocaleString()}
      </span>
      <button className="btn" disabled={page >= pages} onClick={() => onPage(page + 1)}>
        Next
      </button>
      <button className="btn" disabled={page >= pages} onClick={() => onPage(pages)} aria-label="Last page">
        »
      </button>
    </nav>
  )
}
