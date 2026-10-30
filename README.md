# SHA LeadFlow AI

SHA LeadFlow AI is a functional, free-tier, cloud-ready lead-management CRM for **SHA Interface Interiors**. It captures enquiries, scores them deterministically (0–100), tracks follow-ups, imports CSV lists, deduplicates leads, and works even when free AI is unavailable.

**Deployment status: NOT deployed.** This README prepares the application for free deployment on Render + Supabase, but no cloud deployment has been performed and no real AI API calls have been made. All AI tests use fakes/mocked HTTP responses.

## What the app does

| Feature | Description |
|---|---|
| Leads | Create, edit, search, filter, sort, paginate, and view lead details |
| Scoring | Deterministic 0–100 score (budget 25, readiness 25, urgency 20, scope 15, area 15). AI never controls the score |
| Follow-ups | Due-date tasks with dashboard reminders, message drafts, and activity history |
| CSV import | Server-side validation, duplicate detection, transactional import, size/row limits |
| Duplicate detection | Normalizes phone/email before comparing; database unique constraints |
| Status changes | New → Contacted → Qualified → Proposal Sent → Won → Lost with activity log |
| AI insight | Optional free Gemini or Groq summary/draft with deterministic fallback |
| Dashboard | Totals, source breakdown, pipeline counts, high-priority leads, overdue/due-today counts, win rate |
| Auth | Session-based single administrator with CSRF protection and rate limiting |

## Tech stack

- Python 3.11+ (developed/tested on Python 3.13.14)
- Flask, Flask-SQLAlchemy, Flask-Migrate, Flask-WTF, python-dotenv
- PostgreSQL in production (Supabase); SQLite only as a local fallback
- Jinja2 templates, vanilla JavaScript, plain CSS (no Tailwind, Bootstrap, or external assets)
- Gunicorn for production, pytest for tests
- Gemini REST and Groq OpenAI-compatible endpoint via plain `requests` (no SDKs)

**Not used:** Ollama/local LLMs, paid OpenAI/Anthropic APIs, paid infrastructure, paid dependencies, background workers, real email/WhatsApp sending.

## Requirements

Python 3.11 or newer and `pip`. Install the pinned dependencies:

```powershell
pip install -r requirements.txt
```

Pinned dependencies resolve cleanly in the existing environment, including `tzdata`.

## Local setup (Windows PowerShell)

From `E:\sha interiors`:

```powershell
# 1. Create a virtual environment (Python 3.11+). Use py -3.13 if available, otherwise python.
py -3.13 -m venv .venv

# 2. Activate it
.\.venv\Scripts\Activate.ps1

# 3. Upgrade pip and install pinned dependencies
python -m pip install --upgrade pip
pip install -r requirements.txt

# 4. Copy the example environment file and edit it
Copy-Item .env.example .env
notepad .env
```

### Environment variables

Copy `.env.example` to `.env` and replace every placeholder. Never commit `.env`; it is gitignored.

| Variable | Purpose | Example / guidance |
|---|---|---|
| `APP_ENV` | `development` locally, `production` on Render | `development` |
| `FLASK_APP` | WSGI entry point | `wsgi:app` |
| `SECRET_KEY` | Session signing secret — must be random and ≥32 chars in production | `python -c "import secrets; print(secrets.token_hex(32))"` |
| `DATABASE_URL` | Local SQLite fallback. Production requires PostgreSQL | `sqlite:///instance/sha_leadflow.db` |
| `TRUST_PROXY` | `1` behind a trusted reverse proxy such as Render | `0` locally, `1` on Render |
| `SESSION_COOKIE_SECURE` | `1` so cookies are HTTPS-only in production | `0` locally, `1` on Render |
| `LOG_LEVEL` | Application log level | `INFO` |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | First administrator credentials for `flask create-admin` / bootstrap | Set real values; remove password after first deploy |
| `AI_PROVIDER` | `gemini`, `groq`, or `none`. No automatic provider switching | `gemini` |
| `GEMINI_API_KEY` | Free Google AI Studio key | Obtain from Google AI Studio |
| `GEMINI_MODEL` | Explicit model ID from environment | `gemini-3.5-flash-lite` |
| `GEMINI_THINKING_LEVEL` | Gemini 3.x thinking level | `minimal` |
| `GROQ_API_KEY` / `GROQ_MODEL` | Optional Groq adapter only when `AI_PROVIDER=groq` | Leave empty to disable |
| `AI_TIMEOUT_SECONDS` / `AI_MAX_RETRIES` | AI call timeout and limited retries | `15`, `2` |
| `AI_RATE_LIMIT_PER_MINUTE` / `LEAD_RATE_LIMIT_PER_MINUTE` / `LOGIN_RATE_LIMIT_PER_MINUTE` | Per-process rate limits | `10`, `20`, `10` |
| `SERVICE_AREAS` | Comma-separated service-area list for scoring | Bangalore localities |
| `HIGH_PRIORITY_THRESHOLD` | Deterministic score at which leads are high priority | `80` |
| `SCORING_CONFIG_JSON` | Optional JSON override of all five scoring weights (must sum to 100) | See `.env.example` |
| `MAX_CSV_BYTES` / `MAX_CSV_ROWS` | CSV upload guards | `2097152`, `1000` |

Generate a secret locally:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

### Initialize the database and create an admin

```powershell
# Apply migrations
flask --app wsgi db upgrade

# Create the administrator (prompts if ADMIN_EMAIL/ADMIN_PASSWORD are not set)
flask --app wsgi create-admin
```

Optionally seed fictional demo data:

```powershell
flask --app wsgi seed-demo
```

All seeded records use `example.com` addresses and `90000000xx` phone numbers.

### Run locally

```powershell
flask --app wsgi run --host 127.0.0.1 --port 5000
```

Then open `http://127.0.0.1:5000/` and sign in with the administrator account you created.

## Lead scoring (deterministic)

Scores are computed by rules in `app/config.py` and `app/services/scoring.py`. The AI provider is deliberately **not** involved.

| Factor | Weight | What it measures |
|---|---:|---|
| Budget fit | 25 | Budget band alignment |
| Readiness & intent | 25 | Requirements detail, intent keywords, timeline/budget shared |
| Urgency | 20 | Expected start date proximity and urgency keywords |
| Project scope fit | 15 | Project type tier |
| Service area fit | 15 | Locality in configured service areas |

Weights sum to 100 and are configurable via `SCORING_CONFIG_JSON` or by editing `app/config.py`. After changing scoring configuration, run:

```powershell
flask --app wsgi recalc-scores
```

Priority bands (deterministic):

| Band | Score | Label |
|---|---:|---|
| Hot | 80–100 | High priority |
| Warm | 60–79 | Developing |
| Nurture | 0–59 | Early stage |

High-priority threshold defaults to 80 (`HIGH_PRIORITY_THRESHOLD`).

## AI providers, privacy, and fallback

- **Gemini** is the explicit primary provider. Configure `AI_PROVIDER=gemini`, `GEMINI_API_KEY`, and `GEMINI_MODEL`.
- **Groq** is used only when explicitly configured with `AI_PROVIDER=groq`, `GROQ_API_KEY`, and `GROQ_MODEL`. There is **no automatic provider switching** and **no paid-provider fallback**.
- Provider-specific model IDs come from environment variables only; nothing is hardcoded.
- Prompts exclude name, phone, and email. Only project facts and the untrusted brief are sent.
- If AI is unavailable, over quota, or returns invalid output, a clearly-labelled deterministic fallback summary/draft is used. The CRM remains fully usable.
- Google AI Studio free-tier inputs may be used to improve products; do not send sensitive personal data beyond the project brief.
- Current free-tier example model IDs: `gemini-3.5-flash-lite` (Gemini) and `openai/gpt-oss-120b` (Groq). Verify availability and limits in Google AI Studio / Groq before changing.

AI usage logs record provider, model, status, latency, token counts, and failure reason — never contact details.

## Security

- Secrets from environment variables only; `.env.example` contains placeholders, no real secrets
- Production refuses to start with a weak or placeholder `SECRET_KEY` (<32 chars or known placeholder)
- Production requires `DATABASE_URL` pointing to PostgreSQL; SQLite is local-development-only
- CSRF protection on all state-changing forms (`WTF_CSRF_TIME_LIMIT` = 7200 seconds)
- Session cookies: `HttpOnly`, `SameSite=Lax`, secure in production
- `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy: same-origin`, CSP, HSTS when secure cookies are on
- Hard 6 MB request cap; CSV upload capped by `MAX_CSV_BYTES` / `MAX_CSV_ROWS`
- In-process, per-process rate limiter (not distributed; not shared across Gunicorn workers)
- Safe error handling: no exception details exposed publicly
- Same-site relative redirects only

## Automated tests

Run the suite:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

### Actual test results

```
68 passed in 13.20s
```

Tests cover lead creation, duplicates, scoring, status updates, CSV import, dashboard calculations, AI failure fallback with mocked providers, authentication, CSRF, rate limiting, and production config enforcement. AI tests use fakes/mocked responses; no real API key is required.

## Free deployment: Render + Supabase

This section documents exact next steps. It does **not** claim deployment succeeded; verify each step yourself.

### 1. Create a Supabase PostgreSQL database (free)

1. Sign in to Supabase and create a new free project.
2. Free tier: 500 MB database, 2 active free projects, paused after 1 week of inactivity, no automatic backups.
3. In **Database > Settings > Connection string**, use **Session mode** pooler (`port 5432`), e.g.:
   ```
   postgresql://postgres.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require
   ```
4. URL-encode any special characters in the password.
5. Supabase free projects have no automatic backups; export regularly with `supabase db dump` or `pg_dump` and keep off-site copies.

### 2. Create the Render web service (free)

1. Push this repository to a Git provider (GitHub/GitLab/Bitbucket).
2. In Render, create a new **Web Service** from the repository, or sync `render.yaml`.
3. Use the Python runtime, free plan (0.1 CPU / 512 MB RAM).
4. Build command: `pip install -r requirements.txt`
5. Start command: `sh start.sh`
6. Health check path: `/healthz`
7. Free web services spin down after 15 minutes of inactivity and spin back up on the next request.

### 3. Set Render environment variables

Set these in the Render dashboard (do not hardcode secrets):

| Variable | Value |
|---|---|
| `APP_ENV` | `production` |
| `SECRET_KEY` | Strong random value ≥32 characters (`generateValue: true` in `render.yaml`) |
| `DATABASE_URL` | Supabase session-pooler PostgreSQL connection string |
| `TRUST_PROXY` | `1` |
| `SESSION_COOKIE_SECURE` | `1` |
| `AI_PROVIDER` | `gemini` (or `groq`, or `none`) |
| `GEMINI_API_KEY` | Your Google AI Studio key |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` |
| `GEMINI_THINKING_LEVEL` | `minimal` |
| `ADMIN_EMAIL` | Your admin email |
| `ADMIN_PASSWORD` | Strong unique password ≥10 characters |
| `LOG_LEVEL` | `INFO` |
| `WEB_WORKERS` | `2` |
| `WEB_THREADS` | `4` |

`render.yaml` marks `DATABASE_URL`, `GEMINI_API_KEY`, `ADMIN_EMAIL`, and `ADMIN_PASSWORD` as `sync: false`, so Render prompts for them rather than storing them in the blueprint.

### 4. First deploy

1. `start.sh` runs `flask --app wsgi db upgrade` (idempotent migrations) on every start.
2. If `ADMIN_EMAIL` and `ADMIN_PASSWORD` are set, `bootstrap-admin` creates the administrator once.
3. Gunicorn starts serving `wsgi:app`.
4. Open the Render service URL and sign in.

`flask db upgrade` runs on every Render start (including after spin-up), so migrations are safe and repeatable. Remove `ADMIN_PASSWORD` from Render environment variables after the first successful deploy if you prefer to manage admin access via `flask create-admin --force` locally against the production database.

### 5. Free-tier limitations to accept

- Render free web service spins down after 15 minutes idle; first request after spin-down is slow (cold start).
- One Render free web service; 750 instance hours per month.
- Supabase free database pauses after 1 week of inactivity; resume from the Supabase dashboard.
- Supabase free tier has no automatic backups; schedule your own `pg_dump` exports.
- The in-process rate limiter is per-process and not shared across Gunicorn workers.
- Free AI tiers have rate and quota limits; when exceeded, the app falls back to deterministic summaries/drafts.
- Render free services do not include a shell for one-off commands; run `flask` CLI locally against Supabase with `DATABASE_URL` set when needed.

## Project structure

```
E:\sha interiors\
├── README.md
├── requirements.txt          # Pinned dependencies
├── .env.example              # Placeholder-only environment template (copy to .env)
├── .gitignore
├── Procfile                  # web: sh start.sh
├── start.sh                  # Migrations + bootstrap + Gunicorn (LF endings)
├── render.yaml               # Render blueprint
├── wsgi.py                   # WSGI entry point
├── pytest.ini
├── app/
│   ├── __init__.py           # App factory, auth gate, security headers, health, errors, CLI
│   ├── config.py             # Environment config; production secret/DB enforcement
│   ├── cli.py                # create-admin, bootstrap-admin, recalc-scores, init-db, seed-demo
│   ├── models.py             # Lead, FollowUp, User, Activity
│   ├── extensions.py         # db, migrate, csrf
│   ├── ratelimit.py          # In-process rate limiter
│   ├── utils.py              # Date, currency, formatting helpers
│   ├── routes/
│   │   ├── auth.py           # Login/logout, rate-limited
│   │   ├── dashboard.py      # Dashboard aggregates
│   │   ├── followups.py      # Follow-up list/create/complete/reopen/draft
│   │   ├── health.py         # /healthz
│   │   └── leads.py          # Lead CRUD, status, CSV, AI qualify
│   ├── services/
│   │   ├── validation.py     # Server-side lead/follow-up validation + normalization
│   │   ├── scoring.py        # Deterministic 0–100 scoring
│   │   ├── leads.py          # Lead CRUD, duplicates, activity, CSV import
│   │   ├── followups.py      # Follow-up tasks and drafts
│   │   ├── dashboard.py      # Database aggregates
│   │   └── ai/
│   │       ├── service.py    # AI orchestration, validation, logging, fallbacks
│   │       ├── base.py       # Common provider interface + retries
│   │       ├── gemini.py     # Gemini REST adapter
│   │       └── groq.py       # Optional Groq adapter
│   ├── static/css/app.css    # Plain responsive CSS
│   ├── static/js/app.js      # Vanilla JavaScript
│   ├── static/img/favicon.svg
│   └── templates/            # Jinja2 templates
├── migrations/
│   ├── alembic.ini
│   ├── env.py
│   └── versions/
│       └── 6671fb75fa2c_initial_schema.py
└── tests/
    ├── conftest.py
    ├── test_ai.py
    ├── test_auth.py
    ├── test_csv_import.py
    ├── test_dashboard.py
    ├── test_followups.py
    ├── test_leads.py
    ├── test_scoring.py
    └── test_security.py
```

## Verification checklist

Before considering the app ready for production use:

- [ ] `pip install -r requirements.txt` resolves all pins (including `tzdata`)
- [ ] `flask --app wsgi db upgrade` succeeds against a real PostgreSQL database
- [ ] `flask --app wsgi create-admin` creates the administrator
- [ ] `flask --app wsgi seed-demo` inserts fictional demo data (local SQLite only)
- [ ] `pytest` passes (last result: **68 passed**)
- [ ] `/healthz` returns `{"status":"ok","database":"ok",...}`
- [ ] Production config rejects SQLite and weak/placeholder `SECRET_KEY`
- [ ] Login, lead create/edit, status change, CSV import, follow-ups, and AI fallback all work
- [ ] `.env` contains real values and is not committed

## What this repository does not claim

- No deployment has occurred. Render/Supabase production behavior has not been verified.
- No live Gemini/Groq API calls have been made; AI behavior against real free-tier endpoints is untested.
- Do not treat "free-tier ready" as a guarantee of uptime, quota, or continued free availability; provider limits can change.
