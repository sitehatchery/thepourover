# The Pour Over: Mini CDP

A small customer data platform that brings newsletter subscribers, website visits and app activity into one place for the Growth team. Built as a take-home assessment for The Pour Over.

> Work in progress. This README grows with the project; the full version (architecture, data rules, webhook, PII handling, security) is tracked in Jira TPO-222.

## Stack

- **Back end:** Python 3.12, FastAPI, SQLAlchemy, Alembic, SQLite
- **Front end:** React + TypeScript (Vite)
- **Local:** WAMP/Apache at `https://cdp.local`; **production:** Nginx

## Run it locally

```bash
# Back end
cd backend
py -3.12 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env                           # then fill in CDP_JWT_SECRET and CDP_WEBHOOK_SECRETS
.venv\Scripts\python -m app.cli init-db          # migrations + reference data
.venv\Scripts\python -m app.cli import           # load data/sample/*.csv
.venv\Scripts\python -m app.cli create-user growth          # UI login (prompts for a password)
.venv\Scripts\python -m app.cli create-api-key local-dev    # API key for scripts; printed once
.venv\Scripts\python -m uvicorn app.main:app --port 8000

# Front end (second terminal)
cd frontend
npm install        # in PowerShell, use npm.cmd if script execution is disabled
npm run dev        # http://localhost:5173, proxies /app to the API
```

API docs: http://127.0.0.1:8000/app/docs

Settings come from environment variables or `backend/.env` (see `backend/.env.example`). "Today" is fixed at **2026-09-28**, per the brief.

For `https://cdp.local` through WAMP, see `deploy/apache/cdp.local.conf`.

## Tests

```bash
cd backend
.venv\Scripts\python -m pytest
```

## Data rules (so far)

- **Email normalization:** one function, `normalize_email()` in `backend/app/rules.py` (trim + lowercase + format check). Every module that reads an email calls it.
- **Subscriber dedupe:** group by normalized email; keep the row with the latest `last_open_date`, then latest `signup_date`, then the later row; blank fields are filled from the other rows. In the sample, all 85 duplicates differ only by email case or whitespace.
- **Linking:** app users join subscribers on normalized email. Web events without an email inherit the email of the same `visitor_id`'s identified event (skipped if a visitor has more than one email), then join subscribers on email.
- **Rejected rows** (blank rows, invalid emails, bad required dates) are skipped and listed in a downloadable error report; good rows still load. The import validates everything first and replaces data in one transaction.

## Authentication

- **UI users** sign in at `POST /app/auth/login` and get a 15-minute access token plus a refresh token (also set as an httpOnly, SameSite=strict cookie). Each refresh token works once: `POST /app/auth/refresh` returns a new pair, and reusing an old refresh token revokes the whole chain. Passwords are hashed with Argon2id; login is rate limited.
- **API keys** (`cdp_...`) are for scripts and other systems. They're stored as SHA-256 hashes, can be rotated (the old key keeps working for 24 hours) and revoked: `python -m app.cli list-api-keys | rotate-api-key <id> | revoke-api-key <id>`.
- Every API endpoint except `/app/health` and the webhook takes `Authorization: Bearer <access token or API key>`.

## App events webhook

`POST /app/webhooks/app`, with `POST /webhooks/app` (the path in the brief) as an alias for the same handler.

Requests are signed like Stripe's: HMAC-SHA256 over `{timestamp}.{raw body}` with the shared secret, sent as `X-CDP-Timestamp` and `X-CDP-Signature: sha256=<hex>`. Requests older than 5 minutes are refused (replay protection), comparison is constant-time, the secret can be rotated (`CDP_WEBHOOK_SECRETS` accepts several), and the endpoint is rate limited.

```python
import hashlib, hmac, json, time, urllib.request
body = json.dumps({"event_id": "evt_9f3a1c", "event": "read_story", "user_id": "u_2b6447a3",
                   "device_id": "d_4b21e8", "timestamp": "2026-09-28T14:22:05Z",
                   "properties": {"story": "supreme-court-ruling-explained"}}).encode()
ts = str(int(time.time()))
sig = hmac.new(SECRET.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()
urllib.request.urlopen(urllib.request.Request("https://cdp.local/webhooks/app", data=body, headers={
    "Content-Type": "application/json", "X-CDP-Timestamp": ts, "X-CDP-Signature": f"sha256={sig}"}))
```

How events are handled:

- **Duplicates:** `event_id` is the primary key. A repeat returns 200 with `"status": "duplicate"` and changes nothing.
- **Out of order:** events are stored with their own timestamp (plus `received_at`); every read sorts by event time.
- **Login stitching:** an anonymous event belongs to the *next* identified event from the same device. When a login (or any event with a `user_id`) arrives, the device's anonymous events since its previous identified event are attached to that user. An anonymous event that arrives late takes the user of the device's next identified event. An anonymous event *after* a login stays anonymous: the brief says `user_id` is present on every event after login, so a null means the device logged out.
- **Unknown `user_id`:** never dropped. A placeholder app user is created so the person shows up in lookup and segments; a later import that includes the user completes it.
- **No restart needed:** events are written straight to the database that every page and segment reads.
- The response lists each processing step (received, verified, stored or duplicate, user resolved, events attached).

Edge cases this doesn't cover: two people sharing one device without logging out between them, and a device that's reinstalled (new `device_id`) before logging in.

## Segments

A segment is a saved definition, evaluated live against the database every time it's used, so a new webhook event can change membership immediately.

```json
{"match": "all", "filters": [
  {"field": "acquisition_source", "operator": "equals", "value": "Instagram"},
  {"field": "last_open_date", "operator": "not_within_last_days", "value": 30}
]}
```

- **People:** segments select people: every subscriber (`s_<id>`), plus app users who never subscribed (`u_<id>`, including webhook placeholders). Each person has computed fields: app account, app/web activity counts, active days, first web source, last seen.
- **Schema:** `GET /app/segments/schema` lists every field, its operators and its allowed values (sources, pages and event types come from the data). The builder UI and the AI assistant use the same schema, and there is no email or other personal field in it.
- **Safety:** definitions are validated against the schema, and field names map to an allow-list. Every value is a bound SQL parameter.
- **Relative dates** count back from the configured today. "Not within the last N days" includes people with no date at all (e.g. never opened).
- **Built-in catalog:** 22 segments are seeded by `init-db`, including the brief's "Instagram signups not opened in 30 days" (229 people in the sample). Seeding only adds missing segments, so edits are kept.
- **Endpoints:** `GET/POST /app/segments`, `GET/PUT/DELETE /app/segments/{id or slug}`, `/members` (paged or `format=csv`), `/count`, and `POST /app/segments/preview`. `segment_id` (repeatable) filters `/app/subscribers`, `/app/app_events` and `/app/web_events`.

## Sample data result

| File | Read | Loaded | Fixed | Rejected | Duplicates merged |
|---|---|---|---|---|---|
| subscribers.csv | 2,995 | 2,900 | 85 | 10 | 85 |
| app_users.csv | 930 | 930 | 94 | 0 | 0 |
| web_events.csv | 10,000 | 10,000 | 212 | 0 | 0 |

900 of 930 app users link to a subscriber; 8,441 of 10,000 web events are attributed to a person (7,041 through `visitor_id` backfill).
