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
.venv\Scripts\python -m app.cli init-db          # migrations + reference data
.venv\Scripts\python -m app.cli import           # load data/sample/*.csv
.venv\Scripts\python -m app.cli create-api-key local-dev   # prints a key once
.venv\Scripts\python -m uvicorn app.main:app --port 8000

# Front end (second terminal)
cd frontend
npm install
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

## Sample data result

| File | Read | Loaded | Fixed | Rejected | Duplicates merged |
|---|---|---|---|---|---|
| subscribers.csv | 2,995 | 2,900 | 85 | 10 | 85 |
| app_users.csv | 930 | 930 | 94 | 0 | 0 |
| web_events.csv | 10,000 | 10,000 | 212 | 0 | 0 |

900 of 930 app users link to a subscriber; 8,441 of 10,000 web events are attributed to a person (7,041 through `visitor_id` backfill).
