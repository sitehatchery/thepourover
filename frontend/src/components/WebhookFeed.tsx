import { useEffect, useRef, useState } from 'react'
import { apiGet } from '../api/client'
import type { WebhookCall } from '../api/types'
import './WebhookFeed.css'

const POLL_MS = 4000
const KEEP = 25

const OUTCOME_LABEL: Record<WebhookCall['outcome'], string> = {
  stored: 'Stored',
  duplicate: 'Duplicate',
  rejected: 'Rejected',
}

/**
 * Every call to the webhook as it arrives, from outside or from the form above, with the steps it took.
 * Polls for newer calls while the panel is open and the tab is visible.
 */
export default function WebhookFeed({ onNewEvents, refreshKey }: { onNewEvents: () => void; refreshKey: number }) {
  const [calls, setCalls] = useState<WebhookCall[] | null>(null)
  const [paused, setPaused] = useState(false)
  const [open, setOpen] = useState<number | null>(null)
  const [failed, setFailed] = useState(false)
  const latest = useRef(0)
  const onNew = useRef(onNewEvents)

  useEffect(() => {
    onNew.current = onNewEvents
  }, [onNewEvents])

  useEffect(() => {
    if (paused) return
    let stopped = false

    async function poll() {
      if (document.visibilityState !== 'visible') return
      try {
        const fresh = await apiGet<WebhookCall[]>(`/webhook_calls?after=${latest.current}&limit=${KEEP}`)
        if (stopped) return
        setFailed(false)
        if (latest.current > 0 && fresh.some((c) => c.channel === 'webhook' && c.outcome === 'stored')) onNew.current()
        if (fresh.length) latest.current = fresh[0].webhook_call_id
        setCalls((current) => [...fresh, ...(current ?? [])].slice(0, KEEP))
      } catch {
        if (!stopped) setFailed(true)
      }
    }

    void poll()
    const timer = window.setInterval(() => void poll(), POLL_MS)
    return () => {
      stopped = true
      window.clearInterval(timer)
    }
  }, [paused, refreshKey])

  return (
    <section className="feed" aria-labelledby="feed-title">
      <header className="feed-head">
        <div>
          <h2 id="feed-title">
            <span className={paused ? 'feed-dot paused' : 'feed-dot'} aria-hidden="true" />
            Live webhook feed
          </h2>
          <p>
            Every call to <code>POST /webhooks/app</code>, including rejected ones. Rejected calls keep the reason, never the
            payload.
          </p>
        </div>
        <button type="button" className="btn" aria-pressed={paused} onClick={() => setPaused((p) => !p)}>
          {paused ? 'Resume' : 'Pause'}
        </button>
      </header>

      {failed && <p className="feed-note">Couldn't reach the feed. Retrying…</p>}
      {calls && calls.length === 0 && <p className="feed-note">No webhook calls yet. Send one with the form above, or from outside with a signed request.</p>}

      {calls && calls.length > 0 && (
        <ol className="feed-list">
          {calls.map((call) => {
            const expanded = open === call.webhook_call_id
            return (
              <li key={call.webhook_call_id} className={`feed-item ${call.outcome}`}>
                <button
                  type="button"
                  className="feed-row"
                  aria-expanded={expanded}
                  onClick={() => setOpen(expanded ? null : call.webhook_call_id)}
                >
                  <time className="feed-time" dateTime={call.received_at}>
                    {new Date(`${call.received_at}Z`).toLocaleTimeString()}
                  </time>
                  <span className={`pill feed-outcome ${call.outcome}`}>
                    {OUTCOME_LABEL[call.outcome]} <span className="feed-status">{call.http_status}</span>
                  </span>
                  <span className="feed-summary">
                    {call.event ? (
                      <>
                        <code>{call.event}</code> <code>{call.event_id}</code>
                        <span className="feed-user">{call.app_user_id ? <code>{call.app_user_id}</code> : 'anonymous'}</span>
                      </>
                    ) : (
                      <span className="feed-reason">{call.steps[call.steps.length - 1]}</span>
                    )}
                  </span>
                  <span className="feed-meta">
                    {call.channel === 'app' ? 'App Events form' : 'Webhook'} · {call.duration_ms} ms
                  </span>
                </button>
                {expanded && (
                  <ol className="steps feed-steps">
                    {call.steps.map((step, i) => (
                      <li key={i}>{step}</li>
                    ))}
                  </ol>
                )}
              </li>
            )
          })}
        </ol>
      )}
    </section>
  )
}
