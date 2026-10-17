import { useState, type ReactNode } from 'react'
import { countOf } from '../lib/format'

type Props = {
  title: string
  description: string
  total: number | undefined
  hasFilters: boolean
  /** Singular noun, e.g. "web event". */
  noun: string
  /** Plural when it isn't just noun + "s", e.g. "people". */
  plural?: string
  onExport: () => Promise<void>
  children?: ReactNode
}

/** Page title, live count and the Export CSV button shared by the table pages. */
export default function ListHeader({ title, description, total, hasFilters, noun, plural, onExport, children }: Props) {
  const [exporting, setExporting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function exportCsv() {
    setExporting(true)
    setError(null)
    try {
      await onExport()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setExporting(false)
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{title}</h1>
          <p className="page-sub">
            {total === undefined ? description : countOf(total, hasFilters ? `matching ${noun}` : noun, plural && (hasFilters ? `matching ${plural}` : plural))}
          </p>
        </div>
        <div className="page-actions">
          {children}
          <button className="btn" onClick={() => void exportCsv()} disabled={exporting || !total}>
            {exporting ? 'Exporting…' : 'Export CSV'}
          </button>
        </div>
      </div>
      {error && (
        <p className="notice notice-error" role="alert">
          Export failed: {error}
        </p>
      )}
    </>
  )
}
