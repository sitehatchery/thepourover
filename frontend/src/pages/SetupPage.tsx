import { useEffect, useRef, useState } from 'react'
import { apiGet, apiSend, downloadCsv } from '../api/client'
import type { ImportRun } from '../api/types'
import { countOf, formatNumber } from '../lib/format'
import './SetupPage.css'
import './TablePage.css'

type Source = { kind: string; folder: string; available: boolean; files: { name: string; size_bytes: number }[] }

const ENTITY_LABELS: Record<string, string> = { subscribers: 'Subscribers', app_users: 'App users', web_events: 'Web events' }

function fileSize(bytes: number): string {
  return bytes > 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`
}

function when(iso: string): string {
  const date = new Date(`${iso}Z`)
  return date.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
}

export default function SetupPage() {
  const [source, setSource] = useState<Source | null>(null)
  const [runs, setRuns] = useState<ImportRun[]>([])
  const [latest, setLatest] = useState<ImportRun | null>(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [reload, setReload] = useState(0)
  const confirmRef = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    apiGet<Source>('/import/source').then(setSource).catch((err: Error) => setError(err.message))
    apiGet<ImportRun[]>('/import/runs?limit=8').then(setRuns).catch(() => setRuns([]))
  }, [reload])

  async function runImport() {
    confirmRef.current?.close()
    setRunning(true)
    setError(null)
    try {
      setLatest(await apiSend<ImportRun>('POST', '/import'))
      setReload((n) => n + 1)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setRunning(false)
    }
  }

  async function downloadReport() {
    try {
      await downloadCsv('/import/report', 'import_errors.csv')
    } catch (err) {
      setError((err as Error).message)
    }
  }

  return (
    <section className="table-page">
      <div className="page-head">
        <div>
          <h1>Setup</h1>
          <p className="page-sub">Load subscriber, website and app data into the CDP</p>
        </div>
      </div>

      <div className="setup-grid">
        <div className="setup-card">
          <h2>Load data</h2>
          <p>
            Imports every CSV in the drop folder. Files are recognised by their column headings, checked row by row,
            cleaned (emails trimmed and lower-cased, sources mapped) and de-duplicated before anything is saved. Rows
            that can't be fixed are skipped and listed in a downloadable error report.
          </p>
          <ul className="setup-facts">
            <li>
              <strong>Replaces</strong> subscribers, app users, web events and app events (including events received
              through the webhook).
            </li>
            <li>
              <strong>Keeps</strong> segments, acquisition sources and sign-ins.
            </li>
            <li>Everything is checked first and saved in one step, so a failed import leaves the current data untouched.</li>
          </ul>

          <div className="source-box">
            <p className="source-title">
              Drop folder <code>{source?.folder ?? '…'}</code>
            </p>
            {source && !source.available && <p className="error-text">The drop folder can't be found on the server.</p>}
            {source && source.available && (
              <ul className="file-list">
                {source.files.map((f) => (
                  <li key={f.name}>
                    <span>{f.name}</span>
                    <span className="file-size">{fileSize(f.size_bytes)}</span>
                  </li>
                ))}
                {source.files.length === 0 && <li className="muted">No files waiting.</li>}
              </ul>
            )}
          </div>

          <button
            className="btn btn-primary load-btn"
            disabled={running || !source?.available || !source.files.length}
            onClick={() => confirmRef.current?.showModal()}
          >
            {running ? 'Importing…' : '[Load Data]'}
          </button>
          {error && (
            <p className="notice notice-error" role="alert">
              {error}
            </p>
          )}
        </div>

        <div className="setup-card" aria-live="polite">
          <h2>Result</h2>
          {running && <p className="muted">Reading, validating and loading the files…</p>}
          {!running && !latest && <p className="muted">Run an import to see what was loaded, fixed and rejected.</p>}
          {!running && latest && <RunResult run={latest} onDownload={() => void downloadReport()} />}
        </div>
      </div>

      {runs.length > 0 && (
        <div className="setup-card">
          <h2>Import history</h2>
          <div className="mini-table-wrap">
            <table className="history-table">
              <thead>
                <tr>
                  <th>When</th>
                  <th>Source</th>
                  <th>Status</th>
                  <th>Summary</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <tr key={run.import_run_id}>
                    <td>{when(run.started_at)}</td>
                    <td>{run.source}</td>
                    <td>
                      <span className={run.status === 'succeeded' ? 'pill pill-active' : 'pill pill-unsubscribed'}>{run.status}</span>
                    </td>
                    <td className="history-message">{run.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <dialog ref={confirmRef} className="confirm-dialog" aria-labelledby="confirm-title">
        <h2 id="confirm-title">Replace the current data?</h2>
        <p>
          This replaces all subscribers, app users, web events and app events with what's in the drop folder. App events
          sent through the webhook since the last import will be removed. Segments are kept.
        </p>
        <div className="confirm-actions">
          <button className="btn" onClick={() => confirmRef.current?.close()} autoFocus>
            Cancel
          </button>
          <button className="btn btn-primary" onClick={() => void runImport()}>
            Yes, load data
          </button>
        </div>
      </dialog>
    </section>
  )
}

function RunResult({ run, onDownload }: { run: ImportRun; onDownload: () => void }) {
  const files = Object.entries(run.file_stats)
  const rejected = files.reduce((sum, [, s]) => sum + s.rejected, 0)
  return (
    <div className="run-result">
      <p className={run.status === 'succeeded' ? 'result-line ok' : 'result-line failed'}>
        {run.status === 'succeeded' ? 'Import complete.' : 'Import failed.'} {run.message}
      </p>
      {files.length > 0 && (
        <div className="mini-table-wrap">
          <table className="history-table">
            <thead>
              <tr>
                <th>File</th>
                <th className="num">Read</th>
                <th className="num">Loaded</th>
                <th className="num">Duplicates merged</th>
                <th className="num">Fixed</th>
                <th className="num">Rejected</th>
              </tr>
            </thead>
            <tbody>
              {files.map(([name, s]) => (
                <tr key={name}>
                  <td>
                    {name}
                    <span className="file-size"> · {ENTITY_LABELS[s.entity] ?? s.entity}</span>
                  </td>
                  <td className="num">{formatNumber(s.read)}</td>
                  <td className="num">{formatNumber(s.loaded)}</td>
                  <td className="num">{formatNumber(s.duplicates_merged)}</td>
                  <td className="num">{formatNumber(s.fixed)}</td>
                  <td className={s.rejected ? 'num rejected' : 'num'}>{formatNumber(s.rejected)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {run.has_error_report && (
        <p className="report-line">
          {rejected ? `${countOf(rejected, 'row')} couldn't be imported.` : 'Some rows were fixed or flagged.'}{' '}
          <button type="button" className="link-btn" onClick={onDownload}>
            Download the error report
          </button>{' '}
          to see each one and why.
        </p>
      )}
    </div>
  )
}
