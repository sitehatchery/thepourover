import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { apiGet, apiSend, downloadCsv } from '../api/client'
import type { ImportRun } from '../api/types'
import { countOf, formatNumber } from '../lib/format'
import './SetupPage.css'
import './TablePage.css'

type LocalSource = { kind: string; folder: string; available: boolean; files: { name: string; size_bytes: number }[] }
type DriveStatus = {
  configured: boolean
  connected: boolean
  account_email: string | null
  folder_name: string | null
  files: { name: string; mime_type: string; size_bytes: number | null }[]
  error: string | null
}
type SourceChoice = 'google_drive' | 'local'

const ENTITY_LABELS: Record<string, string> = { subscribers: 'Subscribers', app_users: 'App users', web_events: 'Web events' }
const SOURCE_LABELS: Record<string, string> = { google_drive: 'Google Drive', local: 'Data folder' }

function fileSize(bytes: number | null): string {
  if (bytes === null) return 'Google Sheet'
  return bytes > 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`
}

function when(iso: string): string {
  const date = new Date(`${iso}Z`)
  return date.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })
}

export default function SetupPage() {
  const [params, setParams] = useSearchParams()
  const [local, setLocal] = useState<LocalSource | null>(null)
  const [drive, setDrive] = useState<DriveStatus | null>(null)
  const [choice, setChoice] = useState<SourceChoice | null>(null)
  const [runs, setRuns] = useState<ImportRun[]>([])
  const [latest, setLatest] = useState<ImportRun | null>(null)
  const [running, setRunning] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [reload, setReload] = useState(0)
  const confirmRef = useRef<HTMLDialogElement>(null)

  // Coming back from Google: show the outcome once, then tidy the URL.
  const [flash] = useState(() =>
    params.get('google') === 'connected'
      ? { ok: true, text: 'Google Drive is connected.' }
      : params.get('google') === 'error'
        ? { ok: false, text: params.get('message') ?? 'Google sign-in failed.' }
        : null,
  )
  useEffect(() => {
    if (params.has('google')) setParams({}, { replace: true })
  }, [params, setParams])

  useEffect(() => {
    apiGet<LocalSource>('/import/source').then(setLocal).catch((err: Error) => setError(err.message))
    apiGet<DriveStatus>('/integrations/google/status').then(setDrive).catch(() => setDrive(null))
    apiGet<ImportRun[]>('/import/runs?limit=8').then(setRuns).catch(() => setRuns([]))
  }, [reload])

  // Default to Drive once it's connected, otherwise the data folder.
  const source: SourceChoice = choice ?? (drive?.connected ? 'google_drive' : 'local')
  const files = source === 'google_drive' ? (drive?.files ?? []) : (local?.files ?? [])
  const sourceReady = source === 'google_drive' ? Boolean(drive?.connected && !drive.error) : Boolean(local?.available)

  async function connectDrive() {
    setBusy(true)
    setError(null)
    try {
      const { url } = await apiSend<{ url: string }>('POST', '/integrations/google/start', { return_to: window.location.origin })
      window.location.assign(url)
    } catch (err) {
      setError((err as Error).message)
      setBusy(false)
    }
  }

  async function disconnectDrive() {
    if (!window.confirm('Disconnect Google Drive? Imports will use the data folder until you reconnect.')) return
    setBusy(true)
    try {
      await apiSend('POST', '/integrations/google/disconnect')
      setChoice(null)
      setReload((n) => n + 1)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function runImport() {
    confirmRef.current?.close()
    setRunning(true)
    setError(null)
    try {
      setLatest(await apiSend<ImportRun>('POST', `/import?source=${source}`))
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

      {flash && <p className={flash.ok ? 'notice notice-ok' : 'notice notice-error'}>{flash.text}</p>}

      <div className="setup-grid">
        <div className="setup-card">
          <h2>Load data</h2>
          <p>
            Imports every CSV in the chosen source. Files are recognized by their column headings, checked row by row,
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

          <fieldset className="source-choice">
            <legend>Import from</legend>

            <label className={source === 'google_drive' ? 'source-option selected' : 'source-option'}>
              <input type="radio" name="source" checked={source === 'google_drive'} onChange={() => setChoice('google_drive')} />
              <span className="source-option-body">
                <span className="source-option-title">Google Drive</span>
                {drive && !drive.configured && <span className="muted">Not configured on the server (Google OAuth client missing).</span>}
                {drive?.configured && !drive.connected && <span className="muted">Not connected yet.</span>}
                {drive?.connected && (
                  <span className="muted">
                    Connected as {drive.account_email ?? 'your Google account'}
                    {drive.folder_name && (
                      <>
                        {' '}
                        · folder <code>{drive.folder_name}</code>
                      </>
                    )}
                  </span>
                )}
                {drive?.error && <span className="error-text">{drive.error}</span>}
                {drive?.configured && (
                  <span className="source-actions">
                    <button type="button" className="btn" disabled={busy} onClick={() => void connectDrive()}>
                      {drive.connected ? 'Reconnect' : 'Connect Google Drive'}
                    </button>
                    {drive.connected && (
                      <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => void disconnectDrive()}>
                        Disconnect
                      </button>
                    )}
                  </span>
                )}
              </span>
            </label>

            <label className={source === 'local' ? 'source-option selected' : 'source-option'}>
              <input type="radio" name="source" checked={source === 'local'} onChange={() => setChoice('local')} />
              <span className="source-option-body">
                <span className="source-option-title">Data folder on the server</span>
                <span className="muted">
                  <code>{local?.folder ?? '…'}</code>
                  {local && !local.available && ' (not found)'}
                </span>
              </span>
            </label>
          </fieldset>

          {sourceReady && (
            <div className="source-box">
              <p className="source-title">Files waiting in {SOURCE_LABELS[source]}</p>
              <ul className="file-list">
                {files.map((f) => (
                  <li key={f.name}>
                    <span>{f.name}</span>
                    <span className="file-size">{fileSize(f.size_bytes)}</span>
                  </li>
                ))}
                {files.length === 0 && <li className="muted">No files waiting.</li>}
              </ul>
            </div>
          )}

          <button
            className="btn btn-primary load-btn"
            disabled={running || !sourceReady || !files.length}
            onClick={() => confirmRef.current?.showModal()}
          >
            {running ? 'Importing…' : 'Load Data'}
          </button>
          {error && (
            <p className="notice notice-error" role="alert">
              {error}
            </p>
          )}
        </div>

        <div className={latest || running ? 'setup-card' : 'setup-card is-idle'} aria-live="polite">
          <h2>Import result</h2>
          {running && <p className="muted">Reading, validating and loading the files…</p>}
          {!running && !latest && <p className="muted">Load Data to see what was loaded, fixed and rejected.</p>}
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
                    <td>{SOURCE_LABELS[run.source] ?? run.source}</td>
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
          This replaces all subscribers, app users, web events and app events with what's in the chosen source. App events
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
