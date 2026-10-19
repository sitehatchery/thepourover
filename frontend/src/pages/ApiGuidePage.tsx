import { useEffect, useState, type ReactNode } from 'react'
import { apiGet } from '../api/client'
import './ApiGuidePage.css'

type FieldSpec = {
  type: string
  label: string
  description: string
  operators: string[]
  values?: string[]
  supports_within_last_days?: boolean
}
type SegmentSchema = { today: string; match: string[]; fields: Record<string, FieldSpec> }

const SECTIONS = [
  ['start', 'Getting started'],
  ['api-keys', 'API keys'],
  ['tokens', 'Sign-in tokens'],
  ['webhook', 'Sending app events'],
  ['segments', 'Segment definitions'],
  ['errors', 'Errors and limits'],
] as const

/** A getting-started guide for the API. The segment field reference is loaded from the server, so it can't drift. */
export default function ApiGuidePage() {
  const base = window.location.origin
  const [schema, setSchema] = useState<SegmentSchema | null>(null)

  useEffect(() => {
    apiGet<SegmentSchema>('/segments/schema')
      .then(setSchema)
      .catch(() => undefined)
  }, [])

  return (
    <section className="guide">
      <header className="guide-head">
        <h1>API guide</h1>
        <p>
          How other systems talk to the Mini CDP. Every endpoint, with its parameters and response shapes, is in the{' '}
          <a href="/app/docs" target="_blank" rel="noopener">
            interactive API reference
          </a>{' '}
          (generated from the code).
        </p>
      </header>

      <div className="guide-layout">
        <nav className="guide-toc" aria-label="On this page">
          {SECTIONS.map(([id, label]) => (
            <a key={id} href={`#${id}`}>
              {label}
            </a>
          ))}
        </nav>

        <div className="guide-body">
          <GuideSection id="start" title="Getting started">
            <p>
              The API lives under <code>{base}/app/</code> and speaks JSON. Every endpoint except the webhook and{' '}
              <code>/app/health</code> needs one of two credentials, sent as a bearer token:
            </p>
            <ul>
              <li>
                <strong>An API key</strong> (starts with <code>cdp_</code>) for servers and scripts. It doesn't expire unless
                rotated or revoked.
              </li>
              <li>
                <strong>An access token</strong> from signing in, for people. It lasts 15 minutes and is renewed with a refresh
                token.
              </li>
            </ul>
            <p>
              The app event webhook doesn't take either: each request is signed with a shared secret instead (see{' '}
              <a href="#webhook">Sending app events</a>).
            </p>
          </GuideSection>

          <GuideSection id="api-keys" title="API keys">
            <p>
              An admin creates keys in the{' '}
              <a href="/app/admin/api-client/list" target="_blank" rel="noopener">
                admin console
              </a>{' '}
              (API keys, then New) or on the server with <code>python -m app.cli create-api-key "Partner name"</code>. The key
              is shown once; only a hash of it is stored. <strong>Rotate</strong> issues a replacement and keeps the old key
              working for 24 hours so callers can switch over. <strong>Revoke</strong> stops a key at once.
            </p>
            <Code
              samples={{
                curl: `curl "${base}/app/subscribers?status=active&page_size=5" \\
  -H "Authorization: Bearer $CDP_API_KEY"`,
                Python: `import os
import requests

response = requests.get(
    "${base}/app/subscribers",
    params={"status": "active", "page_size": 5},
    headers={"Authorization": f"Bearer {os.environ['CDP_API_KEY']}"},
    timeout=30,
)
response.raise_for_status()
for subscriber in response.json()["items"]:
    print(subscriber["email"], subscriber["signup_date"])`,
              }}
            />
            <p>
              List endpoints take <code>page</code>, <code>page_size</code> (up to 200), <code>sort</code> and{' '}
              <code>order</code>, plus their own filters. Add <code>format=csv</code> to get every matching row as a CSV file
              instead of a page of JSON.
            </p>
          </GuideSection>

          <GuideSection id="tokens" title="Sign-in tokens">
            <p>
              <code>POST /app/auth/login</code> returns a short-lived <code>access_token</code> and a single-use{' '}
              <code>refresh_token</code>. Before the access token runs out, swap the refresh token for a new pair at{' '}
              <code>POST /app/auth/refresh</code>. Each refresh token works once; reusing an old one ends that whole sign-in,
              which protects against a stolen token. <code>POST /app/auth/logout</code> ends it on purpose. (The web app does
              the same with an httpOnly cookie, so scripts never see its tokens.)
            </p>
            <Code
              samples={{
                curl: `# Sign in
curl -X POST "${base}/app/auth/login" -H "Content-Type: application/json" \\
  -d '{"username": "growth", "password": "…"}'
# → {"access_token": "eyJ…", "token_type": "bearer", "expires_in": 900, "refresh_token": "…"}

# Call the API
curl "${base}/app/segments" -H "Authorization: Bearer $ACCESS_TOKEN"

# Renew (the old refresh token stops working)
curl -X POST "${base}/app/auth/refresh" -H "Content-Type: application/json" \\
  -d "{\\"refresh_token\\": \\"$REFRESH_TOKEN\\"}"`,
              }}
            />
          </GuideSection>

          <GuideSection id="webhook" title="Sending app events">
            <p>
              The mobile app's backend posts each event to <code>POST {base}/webhooks/app</code> (also available at{' '}
              <code>/app/webhooks/app</code>). Sign the request with the shared webhook secret: take the current Unix time in
              seconds, compute an HMAC-SHA256 of <code>{'{timestamp}.{raw body}'}</code>, and send both as headers. Requests
              more than 5 minutes old are refused, so a captured request can't be replayed.
            </p>
            <table className="guide-table">
              <tbody>
                <tr>
                  <th scope="row">
                    <code>X-CDP-Timestamp</code>
                  </th>
                  <td>Unix time in seconds, e.g. <code>1790604300</code></td>
                </tr>
                <tr>
                  <th scope="row">
                    <code>X-CDP-Signature</code>
                  </th>
                  <td>
                    <code>sha256=</code> followed by the hex HMAC
                  </td>
                </tr>
              </tbody>
            </table>
            <Code
              samples={{
                curl: `BODY='{"event_id":"evt_1001","event":"login","user_id":"u_2b6447a3","device_id":"d_42","timestamp":"2026-09-28T14:05:00Z","properties":{}}'
TS=$(date +%s)
SIG=$(printf '%s.%s' "$TS" "$BODY" | openssl dgst -sha256 -hmac "$CDP_WEBHOOK_SECRET" -hex | sed 's/^.* //')

curl -X POST "${base}/webhooks/app" \\
  -H "Content-Type: application/json" \\
  -H "X-CDP-Timestamp: $TS" \\
  -H "X-CDP-Signature: sha256=$SIG" \\
  --data-raw "$BODY"`,
                Python: `import hashlib, hmac, json, os, time
import requests

event = {
    "event_id": "evt_1001",
    "event": "login",
    "user_id": "u_2b6447a3",
    "device_id": "d_42",
    "timestamp": "2026-09-28T14:05:00Z",
    "properties": {},
}
body = json.dumps(event).encode()  # sign exactly the bytes you send
ts = str(int(time.time()))
digest = hmac.new(os.environ["CDP_WEBHOOK_SECRET"].encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()

response = requests.post(
    "${base}/webhooks/app",
    data=body,
    headers={"Content-Type": "application/json", "X-CDP-Timestamp": ts, "X-CDP-Signature": f"sha256={digest}"},
    timeout=10,
)
print(response.status_code, response.json())`,
                Node: `import crypto from 'node:crypto'

const body = JSON.stringify({
  event_id: 'evt_1001',
  event: 'login',
  user_id: 'u_2b6447a3',
  device_id: 'd_42',
  timestamp: '2026-09-28T14:05:00Z',
  properties: {},
})
const ts = Math.floor(Date.now() / 1000).toString()
const digest = crypto.createHmac('sha256', process.env.CDP_WEBHOOK_SECRET).update(\`\${ts}.\${body}\`).digest('hex')

const response = await fetch('${base}/webhooks/app', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json', 'X-CDP-Timestamp': ts, 'X-CDP-Signature': \`sha256=\${digest}\` },
  body,
})
console.log(response.status, await response.json())`,
              }}
            />
            <p>What the webhook does with each event:</p>
            <ul>
              <li>
                <strong>Duplicates</strong>: an <code>event_id</code> it already has returns <code>200</code> with{' '}
                <code>"status": "duplicate"</code> and changes nothing, so retrying is always safe.
              </li>
              <li>
                <strong>Out of order</strong>: events are placed by their own <code>timestamp</code>, not by when they arrive.
              </li>
              <li>
                <strong>Anonymous, then login</strong>: an event with no <code>user_id</code> belongs to the next identified
                event from the same device. Earlier anonymous events attach when the login arrives, and a late anonymous event
                attaches to the login that already came after it.
              </li>
              <li>
                <strong>Unknown user_id</strong>: a placeholder profile is created, and a later import fills it in.
              </li>
            </ul>
            <p>
              The response lists each step taken. Every call, including rejected ones, appears in the live feed on the App
              Events page.
            </p>
          </GuideSection>

          <GuideSection id="segments" title="Segment definitions">
            <p>
              A segment is a saved definition: whether people must match <code>all</code> or <code>any</code> of its filters,
              and the filters themselves. Create one with <code>POST /app/segments</code>, check its size first with{' '}
              <code>POST /app/segments/preview</code>, and list its people with{' '}
              <code>GET /app/segments/{'{slug}'}/members</code>.
            </p>
            <Code
              samples={{
                JSON: `{
  "name": "Engaged Instagram readers",
  "description": "Came from Instagram, opened recently and read a story in the app this month",
  "group": "subscriber",
  "definition": {
    "match": "all",
    "filters": [
      { "field": "acquisition_source", "operator": "equals", "value": "Instagram" },
      { "field": "last_open_date", "operator": "within_last_days", "value": 14 },
      { "field": "app_event_type", "operator": "includes", "value": "read_story", "within_last_days": 30 }
    ]
  }
}`,
              }}
            />
            <p>
              The fields below come straight from <code>GET /app/segments/schema</code>, which the segment builder and the AI
              assistant use too. Dates are relative to {schema ? <strong>{schema.today}</strong> : 'the server’s “today”'}.
            </p>
            {schema ? (
              <div className="guide-table-wrap">
                <table className="guide-table guide-fields">
                  <thead>
                    <tr>
                      <th scope="col">Field</th>
                      <th scope="col">Type</th>
                      <th scope="col">Operators</th>
                      <th scope="col">Meaning</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(schema.fields).map(([name, spec]) => (
                      <tr key={name}>
                        <th scope="row">
                          <code>{name}</code>
                        </th>
                        <td>{spec.type}</td>
                        <td>
                          {spec.operators.map((op) => (
                            <code key={op} className="guide-op">
                              {op}
                            </code>
                          ))}
                        </td>
                        <td>
                          {spec.description || spec.label}
                          {spec.values && spec.values.length > 0 && (
                            <span className="guide-values">
                              Values: {spec.values.slice(0, 8).join(', ')}
                              {spec.values.length > 8 && ` and ${spec.values.length - 8} more`}
                            </span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="guide-muted">Loading the field list…</p>
            )}
          </GuideSection>

          <GuideSection id="errors" title="Errors and limits">
            <p>
              Errors return JSON with a <code>detail</code> field. Every response has an <code>X-Request-ID</code> header;
              quote it when reporting a problem.
            </p>
            <div className="guide-table-wrap">
              <table className="guide-table">
                <thead>
                  <tr>
                    <th scope="col">Status</th>
                    <th scope="col">Meaning</th>
                  </tr>
                </thead>
                <tbody>
                  {ERRORS.map(([code, meaning]) => (
                    <tr key={code}>
                      <th scope="row">
                        <code>{code}</code>
                      </th>
                      <td>{meaning}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p>
              Rate limits are per client IP: <strong>10 sign-in attempts a minute</strong> and{' '}
              <strong>600 webhook calls a minute</strong>. Over the limit, the API answers <code>429</code> with a{' '}
              <code>Retry-After</code> header in seconds.
            </p>
          </GuideSection>
        </div>
      </div>
    </section>
  )
}

const ERRORS: [string, string][] = [
  ['400', 'The input is wrong: a bad filter, date range or segment definition. Webhook payload errors list each field.'],
  ['401', 'Missing or expired credentials, or a webhook signature that doesn’t match.'],
  ['404', 'No such subscriber, profile, segment or event.'],
  ['409', 'Conflicts with existing data, such as a segment name already in use.'],
  ['413', 'The webhook body is over 16 KB.'],
  ['422', 'The request doesn’t match the endpoint’s schema; detail lists what and where.'],
  ['429', 'Rate limited; wait for Retry-After seconds.'],
  ['500', 'Our fault. The response includes a request_id to quote.'],
  ['503', 'A dependency isn’t set up or reachable (OpenAI for the assistant, Google for Drive imports).'],
]

function GuideSection({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section id={id} className="guide-section" aria-labelledby={`${id}-title`}>
      <h2 id={`${id}-title`}>{title}</h2>
      {children}
    </section>
  )
}

/** Code samples in one or more languages, with tabs and a copy button. */
export function Code({ samples }: { samples: Record<string, string> }) {
  const languages = Object.keys(samples)
  const [language, setLanguage] = useState(languages[0])
  const [copied, setCopied] = useState(false)

  function copy() {
    void navigator.clipboard?.writeText(samples[language]).then(() => {
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    })
  }

  return (
    <div className="code">
      <div className="code-bar">
        <div role="tablist" aria-label="Language">
          {languages.map((name) => (
            <button
              key={name}
              type="button"
              role="tab"
              aria-selected={name === language}
              className={name === language ? 'code-tab active' : 'code-tab'}
              onClick={() => setLanguage(name)}
            >
              {name}
            </button>
          ))}
        </div>
        <button type="button" className="code-copy" onClick={copy}>
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <pre>
        <code>{samples[language]}</code>
      </pre>
    </div>
  )
}
