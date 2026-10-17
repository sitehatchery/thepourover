import { useEffect, useId, useState, type FormEvent, type ReactNode } from 'react'
import { apiGet, apiSend, ApiError } from '../api/client'
import { getToday } from '../lib/format'
import './AppEventSender.css'

const EVENTS = ['app_open', 'read_story', 'link_click', 'login'] as const
const PROPERTY_KEYS = ['story', 'link', 'other'] as const
const ID_PATTERN = /^[A-Za-z0-9_-]+$/

type Property = { key: (typeof PROPERTY_KEYS)[number]; customKey: string; value: string }
type Result = {
  status: 'stored' | 'duplicate'
  event_id: string
  app_user_id: string | null
  attached_events: number
  placeholder_created: boolean
  steps: string[]
}

const randomId = (prefix: string) => `${prefix}_${crypto.getRandomValues(new Uint32Array(1))[0].toString(16).padStart(8, '0').slice(0, 6)}`

function nowOnToday(): string {
  const time = new Date().toISOString().slice(11, 19)
  return `${getToday()}T${time}`
}

/** Sends an event through the real webhook (signed on the server), then shows each processing step. */
export default function AppEventSender({ onSent }: { onSent: () => void }) {
  const [eventId, setEventId] = useState(() => randomId('evt'))
  const [event, setEvent] = useState<(typeof EVENTS)[number]>('app_open')
  const [userId, setUserId] = useState('')
  const [deviceId, setDeviceId] = useState(() => randomId('d'))
  const [timestamp, setTimestamp] = useState(nowOnToday)
  const [properties, setProperties] = useState<Property[]>([])
  const [sending, setSending] = useState(false)
  const [result, setResult] = useState<Result | null>(null)
  const [error, setError] = useState<string | null>(null)

  const problems = [
    !ID_PATTERN.test(eventId) && 'Event ID can use letters, numbers, _ and - only.',
    userId && !ID_PATTERN.test(userId) && 'User ID can use letters, numbers, _ and - only.',
    !ID_PATTERN.test(deviceId) && 'Device ID is required (letters, numbers, _ and -).',
    !timestamp && 'Timestamp is required.',
    properties.some((p) => !p.value.trim() || (p.key === 'other' && !p.customKey.trim())) && 'Fill in or remove empty property rows.',
  ].filter(Boolean) as string[]

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (problems.length) return
    setSending(true)
    setError(null)
    try {
      const props = Object.fromEntries(properties.map((p) => [p.key === 'other' ? p.customKey.trim() : p.key, p.value.trim()]))
      const response = await apiSend<Result>('POST', '/app_events/send', {
        event_id: eventId,
        event,
        user_id: userId.trim() || null,
        device_id: deviceId.trim(),
        timestamp: `${timestamp.length === 16 ? `${timestamp}:00` : timestamp}Z`,
        properties: props,
      })
      setResult(response)
      setEventId(randomId('evt')) // ready for the next event; re-type the old id to demo duplicates
      onSent()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'The event could not be sent.')
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="sender">
      <form className="sender-form" onSubmit={submit} noValidate>
        <div className="sender-head">
          <h2>Send an app event</h2>
          <p>Goes through the live webhook: signed, verified, de-duplicated and stitched exactly like an event from the app.</p>
        </div>

        <div className="sender-grid">
          <label className="field">
            Event ID
            <span className="input-with-btn">
              <input className="input" value={eventId} onChange={(e) => setEventId(e.target.value)} required />
              <button type="button" className="btn btn-ghost" onClick={() => setEventId(randomId('evt'))} title="New event ID">
                ↻
              </button>
            </span>
          </label>
          <label className="field">
            Event
            <select className="input" value={event} onChange={(e) => setEvent(e.target.value as (typeof EVENTS)[number])}>
              {EVENTS.map((name) => (
                <option key={name}>{name}</option>
              ))}
            </select>
          </label>
          <SuggestInput label="User ID" hint="Empty = not logged in" field="user_id" value={userId} onChange={setUserId} />
          <SuggestInput
            label="Device ID"
            field="device_id"
            value={deviceId}
            onChange={setDeviceId}
            extra={
              <button type="button" className="btn btn-ghost" onClick={() => setDeviceId(randomId('d'))} title="New device">
                ↻
              </button>
            }
          />
          <label className="field">
            Timestamp (UTC)
            <input className="input" type="datetime-local" step={1} value={timestamp} onChange={(e) => setTimestamp(e.target.value)} />
          </label>
        </div>

        <fieldset className="properties">
          <legend>Properties</legend>
          {properties.map((p, i) => (
            <div className="property-row" key={i}>
              <select
                className="input"
                aria-label="Property type"
                value={p.key}
                onChange={(e) => setProperties(properties.map((q, j) => (j === i ? { ...q, key: e.target.value as Property['key'] } : q)))}
              >
                {PROPERTY_KEYS.map((k) => (
                  <option key={k}>{k}</option>
                ))}
              </select>
              {p.key === 'other' && (
                <input
                  className="input"
                  aria-label="Property name"
                  placeholder="name"
                  value={p.customKey}
                  onChange={(e) => setProperties(properties.map((q, j) => (j === i ? { ...q, customKey: e.target.value } : q)))}
                />
              )}
              <input
                className="input"
                aria-label="Property value"
                placeholder="supreme-court-ruling-explained"
                value={p.value}
                onChange={(e) => setProperties(properties.map((q, j) => (j === i ? { ...q, value: e.target.value } : q)))}
              />
              <button
                type="button"
                className="btn btn-ghost"
                aria-label="Remove property"
                onClick={() => setProperties(properties.filter((_, j) => j !== i))}
              >
                ×
              </button>
            </div>
          ))}
          <button
            type="button"
            className="btn"
            onClick={() => setProperties([...properties, { key: 'story', customKey: '', value: '' }])}
          >
            + Add property
          </button>
        </fieldset>

        {problems.length > 0 && <p className="error-text">{problems[0]}</p>}
        {error && (
          <p className="error-text" role="alert">
            {error}
          </p>
        )}

        <div className="sender-actions">
          <button className="btn btn-primary" disabled={sending || problems.length > 0}>
            {sending ? 'Sending…' : 'Send through webhook'}
          </button>
          <button type="button" className="btn btn-ghost" onClick={() => setTimestamp(nowOnToday())}>
            Reset time to now
          </button>
        </div>
      </form>

      <aside className="sender-result" aria-live="polite">
        <h3>Webhook result</h3>
        {result ? (
          <>
            <p className={result.status === 'duplicate' ? 'result-status dup' : 'result-status ok'}>
              {result.status === 'duplicate' ? 'Duplicate: nothing changed' : 'Stored'} <code>{result.event_id}</code>
            </p>
            <ol className="steps">
              {result.steps.map((step, i) => (
                <li key={i}>{step}</li>
              ))}
            </ol>
          </>
        ) : (
          <p className="muted">
            Each step the webhook takes will show here. Try an event with no user ID, then a <code>login</code> from the
            same device: the earlier event attaches to the user.
          </p>
        )}
      </aside>
    </div>
  )
}

type SuggestProps = {
  label: string
  hint?: string
  field: 'user_id' | 'device_id'
  value: string
  onChange: (value: string) => void
  extra?: ReactNode
}

function SuggestInput({ label, hint, field, value, onChange, extra }: SuggestProps) {
  const listId = useId()
  const [options, setOptions] = useState<string[]>([])

  useEffect(() => {
    const timer = setTimeout(() => {
      apiGet<string[]>(`/app_events/suggest?field=${field}&q=${encodeURIComponent(value)}`)
        .then(setOptions)
        .catch(() => setOptions([]))
    }, 200)
    return () => clearTimeout(timer)
  }, [field, value])

  return (
    <label className="field">
      {label}
      {hint && <span className="field-hint">{hint}</span>}
      <span className="input-with-btn">
        <input className="input" list={listId} value={value} onChange={(e) => onChange(e.target.value)} autoComplete="off" />
        {extra}
      </span>
      <datalist id={listId}>
        {options.map((o) => (
          <option key={o} value={o} />
        ))}
      </datalist>
    </label>
  )
}
