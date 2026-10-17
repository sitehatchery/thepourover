import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { apiGet, apiSend } from '../api/client'
import type { Page, Person } from '../api/types'
import EmailLink from '../components/EmailLink'
import { countOf, formatDate, formatNumber } from '../lib/format'
import './AssistantPage.css'

type Attachment =
  | { type: 'count'; count: number; percent_of_everyone: number; rules: string }
  | { type: 'people'; result_id: string; count: number; title: string }
  | { type: 'table'; title: string; definition?: string; columns: string[]; rows: (string | number)[][]; total: number }
  | { type: 'segment'; slug: string; name: string; count: number; rules: string }

type AuditStep =
  | { step: 'redacted'; detail: string }
  | { step: 'sent_to_model'; messages: { role: string; content?: string | null; tool_calls?: unknown }[] }
  | { step: 'tool'; name: string; arguments: string; result: unknown }
  | { step: 'answer'; content: string }

type Reply = { answer: string; attachments: Attachment[]; audit: AuditStep[]; redacted_question: boolean }
type Message = { role: 'user'; content: string } | { role: 'assistant'; content: string; reply?: Reply; error?: boolean }

const RANK_LABELS: Record<string, string> = {
  last_seen: 'last seen',
  last_open_date: 'last email open',
  web_event_count: 'website visits',
  web_active_days: 'days active on the website',
  app_event_count: 'app events',
  signup_date: 'signup date',
}

const SUGGESTIONS = [
  'How many Instagram signups went cold last month?',
  'Build me a list of our most engaged readers',
  'Which pages do new subscribers hit first?',
  'How engaged are our subscribers overall?',
  'Which acquisition source has the highest share of cold subscribers?',
]

export default function AssistantPage() {
  const [status, setStatus] = useState<{ configured: boolean; model: string } | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [question, setQuestion] = useState('')
  const [thinking, setThinking] = useState(false)
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    apiGet<{ configured: boolean; model: string }>('/assistant/status').then(setStatus).catch(() => setStatus(null))
  }, [])

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages, thinking])

  async function send(text: string) {
    const trimmed = text.trim()
    if (!trimmed || thinking) return
    const history = messages.map((m) => ({ role: m.role, content: m.content }))
    setMessages((m) => [...m, { role: 'user', content: trimmed }])
    setQuestion('')
    setThinking(true)
    try {
      const reply = await apiSend<Reply>('POST', '/assistant/ask', { question: trimmed, history })
      setMessages((m) => [...m, { role: 'assistant', content: reply.answer, reply }])
    } catch (err) {
      setMessages((m) => [...m, { role: 'assistant', content: (err as Error).message, error: true }])
    } finally {
      setThinking(false)
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault()
    void send(question)
  }

  const disabled = status !== null && !status.configured

  return (
    <section className="assistant">
      <div className="assistant-head">
        <div>
          <h1>Assistant</h1>
          <p className="page-sub">Ask about subscribers, website visits and app activity in plain English.</p>
        </div>
        <p className="privacy-note">
          <span className="lock" aria-hidden="true">●</span> The AI never sees personal data. It works only with counts,
          sources and pages; lists of people are loaded straight into your browser. Open “What the AI saw” under any
          answer to check.
        </p>
      </div>

      {disabled && (
        <p className="notice notice-error">
          The assistant isn't configured yet. Add <code>OPENAI_API_KEY=…</code> to <code>backend/.env</code> and restart the API.
        </p>
      )}

      <div className="chat" aria-live="polite">
        {messages.length === 0 && (
          <div className="chat-empty">
            <p>Try one of these:</p>
            <div className="suggestions">
              {SUGGESTIONS.map((s) => (
                <button key={s} className="suggestion" onClick={() => void send(s)} disabled={disabled || thinking}>
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m, i) =>
          m.role === 'user' ? (
            <div key={i} className="bubble user">
              {m.content}
            </div>
          ) : (
            <div key={i} className={m.error ? 'bubble bot error' : 'bubble bot'}>
              <p className="answer">{m.content}</p>
              {m.reply?.redacted_question && (
                <p className="redacted">An email or id in your question was removed before it reached the AI.</p>
              )}
              {m.reply?.attachments.map((a, j) => <AttachmentView key={j} attachment={a} />)}
              {m.reply && <AuditPanel steps={m.reply.audit} />}
            </div>
          ),
        )}
        {thinking && <div className="bubble bot thinking">Looking into it…</div>}
        <div ref={endRef} />
      </div>

      <form className="ask-bar" onSubmit={submit}>
        <input
          className="input"
          placeholder={disabled ? 'Assistant not configured' : 'Ask a question…'}
          aria-label="Ask the assistant"
          value={question}
          maxLength={2000}
          disabled={disabled}
          onChange={(e) => setQuestion(e.target.value)}
        />
        <button className="btn btn-primary" disabled={disabled || thinking || !question.trim()}>
          Ask
        </button>
      </form>
    </section>
  )
}

function AttachmentView({ attachment }: { attachment: Attachment }) {
  if (attachment.type === 'count') {
    return (
      <div className="att att-count">
        <span className="att-big">{countOf(attachment.count, 'person', 'people')}</span>
        <span className="att-note">
          {attachment.percent_of_everyone}% of everyone · {attachment.rules}
        </span>
      </div>
    )
  }
  if (attachment.type === 'segment') {
    return (
      <div className="att">
        Saved segment <Link to={`/segments/${attachment.slug}`}>{attachment.name}</Link> ·{' '}
        {countOf(attachment.count, 'person', 'people')}
      </div>
    )
  }
  if (attachment.type === 'table') {
    return (
      <div className="att">
        <p className="att-title">{attachment.title}</p>
        {attachment.definition && <p className="att-note att-definition">{attachment.definition}</p>}
        <div className="mini-table-wrap">
          <table className="mini-table">
            <thead>
              <tr>
                {attachment.columns.map((c) => (
                  <th key={c}>{c.replace(/_/g, ' ')}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {attachment.rows.map((row, i) => (
                <tr key={i}>
                  {row.map((cell, j) => (
                    <td key={j} className={typeof cell === 'number' ? 'num' : ''}>
                      {typeof cell === 'number' ? (attachment.columns[j].startsWith('percent') ? `${cell}%` : formatNumber(cell)) : cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    )
  }
  return <PeopleList attachment={attachment} />
}

function PeopleList({ attachment }: { attachment: Extract<Attachment, { type: 'people' }> }) {
  const [page, setPage] = useState<(Page<Person> & { rank_by: string | null }) | null>(null)
  const [saved, setSaved] = useState<{ slug: string; name: string } | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    apiGet<Page<Person> & { rank_by: string | null }>(`/assistant/results/${attachment.result_id}?page_size=10`)
      .then(setPage)
      .catch((err: Error) => setError(err.message))
  }, [attachment.result_id])

  async function save() {
    const name = window.prompt('Name for the new segment', attachment.title.slice(0, 60))
    if (!name) return
    try {
      setSaved(await apiSend<{ slug: string; name: string }>('POST', `/assistant/results/${attachment.result_id}/segment`, { name }))
    } catch (err) {
      setError((err as Error).message)
    }
  }

  return (
    <div className="att">
      <p className="att-title">
        {countOf(attachment.count, 'person', 'people')} · {attachment.title}
        <span className="att-local">Loaded in your browser, not shown to the AI</span>
      </p>
      {error && <p className="error-text">{error}</p>}
      {page && (
        <div className="mini-table-wrap">
          <table className="mini-table">
            <thead>
              <tr>
                <th>Email</th>
                <th>Source</th>
                <th>Last open</th>
                <th className="num">Web visits</th>
                <th className="num">Active days</th>
                <th className="num">App events</th>
              </tr>
            </thead>
            <tbody>
              {page.items.map((p) => (
                <tr key={p.profile_id}>
                  <td>
                    <EmailLink email={p.email} profileId={p.profile_id} />
                  </td>
                  <td>{p.acquisition_source}</td>
                  <td>{formatDate(p.last_open_date)}</td>
                  <td className="num">{formatNumber(p.web_event_count)}</td>
                  <td className="num">{formatNumber(p.web_active_days)}</td>
                  <td className="num">{formatNumber(p.app_event_count)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="att-actions">
        {saved ? (
          <Link to={`/segments/${saved.slug}`}>Saved as “{saved.name}” →</Link>
        ) : (
          <button type="button" className="btn" onClick={() => void save()}>
            Save as segment
          </button>
        )}
        {page && page.total > page.items.length && (
          <span className="att-note">
            Showing the first {page.items.length}
            {page.rank_by && `, ranked by ${RANK_LABELS[page.rank_by] ?? page.rank_by}`}
          </span>
        )}
      </div>
    </div>
  )
}

function AuditPanel({ steps }: { steps: AuditStep[] }) {
  const requests = steps.filter((s) => s.step === 'sent_to_model').length
  return (
    <details className="audit">
      <summary>What the AI saw ({countOf(requests, 'request')})</summary>
      <ol>
        {steps.map((s, i) => (
          <li key={i}>
            {s.step === 'redacted' && <p className="audit-label">Redacted: {s.detail}</p>}
            {s.step === 'sent_to_model' && (
              <>
                <p className="audit-label">Sent to the model ({countOf(s.messages.length, 'message')}, system prompt included)</p>
                <pre>{JSON.stringify(s.messages.slice(1), null, 2)}</pre>
              </>
            )}
            {s.step === 'tool' && (
              <>
                <p className="audit-label">
                  Tool <code>{s.name}</code> ran on the server; this result was sent back:
                </p>
                <pre>{JSON.stringify({ arguments: JSON.parse(s.arguments || '{}'), result: s.result }, null, 2)}</pre>
              </>
            )}
            {s.step === 'answer' && <p className="audit-label">Model answered.</p>}
          </li>
        ))}
      </ol>
    </details>
  )
}
