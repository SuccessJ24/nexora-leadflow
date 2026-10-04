# NEXORA AI — NEXORA LeadFlow

### Human-guided lead qualification and sales operations for B2B marketing agencies

NEXORA LeadFlow turns inbound business inquiries into structured, prioritized sales work. It combines AI-assisted lead understanding with deterministic qualification rules, CRM and Slack adapters, response drafts, and an explicit human approval step before any outbound email.

## Architecture and workflow

```text
Inbound Lead → AI Analysis → Deterministic Qualification → CRM Sync → Slack Alert
             → Response Draft → Human Approval → Email → Workflow/Audit Events
```

The workflow is backed by PostgreSQL. Lead intake and analysis are recorded with workflow events. Optional integrations can be disabled or run through local mock providers during development.

## Key Capabilities

- Validated lead intake through the dashboard or API.
- Structured AI analysis with confidence, service fit, intent, urgency, missing information, and a suggested next action.
- Deterministic qualification rules control final lead classification and review routing.
- Persistent lead, analysis, follow-up, and workflow-event records in PostgreSQL.
- Optional HubSpot CRM synchronization and Slack sales/review notifications.
- Response drafts, human decisions, and an **Approve & Send** email workflow.
- Mock AI, HubSpot, Slack, and email providers for local development without external API calls.
- Per-analysis duplicate-send protection, safe integration status, and event history in the dashboard.

## Tech Stack

- Python, FastAPI, Pydantic, and SQLAlchemy
- PostgreSQL and Alembic migrations
- OpenAI structured analysis adapter and deterministic local mock AI provider
- Provider adapters for HubSpot, Slack incoming webhooks, and Resend
- Jinja2 dashboard with browser-side JavaScript
- Docker Compose and pytest

## Why This Architecture

- **LLM reasoning and structured analysis:** AI interprets an inbound request and returns data validated against the application schema.
- **Deterministic business rules:** Qualification and review routing are controlled by application rules, so the model’s suggested classification does not control final routing by itself.
- **PostgreSQL persistence:** Leads, analyses, follow-ups, and workflow events survive application restarts and can be migrated through Alembic.
- **External integrations and adapters:** HubSpot, Slack, and email are isolated behind provider interfaces. Mock providers support development and tests; integration failures are recorded without silently discarding an accepted lead.
- **Human approval and control:** The response draft remains unsent until a reviewer explicitly approves it. Approval and send results are recorded in workflow history.

## Security & Human Control

- Keep API keys, tokens, webhook URLs, and sender configuration in environment variables or a deployment secret manager.
- Do not commit `.env`; it is excluded by `.gitignore` and `.dockerignore`. `.env.example` contains placeholders only.
- AI analysis, CRM synchronization, and Slack notification do not send external email. A human must use **Approve & Send** before the email provider is called.
- Reject and Request Information do not send email. Duplicate approvals for an already-sent analysis draft do not send a second email.
- Workflow/audit events record key processing, reviewer, and integration outcomes without storing provider credentials or the full email body.
- Integration failures are logged with safe categories and recorded as events. Lead intake remains available when optional CRM or Slack integrations fail; an email send failure is returned safely and can be retried.
- The health endpoint reports provider mode/configuration only. It does not perform external connectivity checks or claim that configured credentials are reachable.

## Screenshots

> **Dashboard overview:** screenshot placeholder — add a dashboard capture here when available.

> **Lead detail and approval workflow:** screenshot placeholder — add a lead-detail capture here when available.

## Quick Start

### Local development

Use `MOCK_AI=true` for no-credit development. The `.env.example` file sets this mode and leaves provider credentials blank; no OpenAI key is required. Mock AI, HubSpot, Slack, and email providers make no external requests.

1. Copy `.env.example` to `.env` if `.env` does not already exist. Preserve your existing `.env` if you already have one.
2. Install Python 3.11 or newer and the project dependencies.
3. Start PostgreSQL, apply migrations, and run the API:

```powershell
docker compose up -d db
python -m pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

The dashboard is at `http://localhost:8000`, the generated API documentation is at `/docs`, and health/status is at `/api/health`.

### Docker Compose

The app container waits for PostgreSQL’s health check, applies `alembic upgrade head`, and then starts Uvicorn. Compose reads the app environment from `.env` and configures the container’s database URL to use the `db` service.

```powershell
docker compose up --build
docker compose ps
docker compose down
```

`docker compose down` stops and removes the Compose containers and network. The named PostgreSQL data volume is retained unless explicitly removed.

### Windows PowerShell setup

From the project folder, after installing Python 3.11 or newer:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# Keep MOCK_AI=true for local development; no OpenAI key is needed.
# Keep DATABASE_URL pointed at localhost when using the local Compose database.
docker compose up -d db
alembic upgrade head
uvicorn app.main:app --reload
```

To run the whole stack in containers instead, use `docker compose up --build` from the project folder.

## Configuration

Set configuration in `.env` for local development or through deployment secrets in hosted environments. Never paste credentials into source files or commit them.

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | SQLAlchemy database connection. Local Compose development uses PostgreSQL on `localhost`; the app container receives a URL pointing to `db`. |
| `OPENAI_API_KEY` | Credential for live AI analysis when `MOCK_AI=false`. Leave blank in mock mode. |
| `OPENAI_MODEL` | OpenAI model used by the live provider; the example is `gpt-4o-mini`. |
| `MOCK_AI` | Selects deterministic local AI analysis when `true`; `.env.example` sets `true`. |
| `HUBSPOT_ENABLED` | Enables the HubSpot adapter. Defaults to `false`. |
| `HUBSPOT_ACCESS_TOKEN` | HubSpot credential required by the enabled live adapter. |
| `SLACK_ENABLED` | Enables Slack notifications. Defaults to `false`. |
| `SLACK_WEBHOOK_URL` | Webhook URL required by the enabled live Slack adapter. |
| `RESEND_ENABLED` | Enables live email configuration. Defaults to `false`. |
| `RESEND_API_KEY` | Resend credential used only by the configured production adapter. |
| `RESEND_FROM_EMAIL` | Verified sender address/name used for Resend email. |
| `INTEGRATION_TIMEOUT_SECONDS` | Timeout for external integration requests; example value is `5`. |
| `AI_CONFIDENCE_THRESHOLD` | Confidence threshold used by deterministic review routing; example value is `0.65`. |
| `HIGH_VALUE_BUDGET_MONTHLY` | Monthly budget threshold used by qualification/review rules; example value is `25000`. |
| `CORS_ORIGINS` | Comma-separated allowed browser origins; example value is `http://localhost:8000`. |
| `APP_ENV` | Application environment. Live Resend requires `production` (or `prod`). |

When `MOCK_AI=true`, enabled HubSpot and Slack integrations select their mock adapters, and email uses Mock Email. With `MOCK_AI=false`, enabled HubSpot and Slack require credentials to use their live adapters. Resend is selected only when `APP_ENV=production`, `MOCK_AI=false`, `RESEND_ENABLED=true`, and both Resend settings are present. In non-production with live AI mode, email remains disabled. Missing OpenAI configuration in live AI mode causes the lead to be saved without a classification and records an error/review event.

## Integrations and email approval

HubSpot upserts qualified leads and records CRM outcomes. Slack can notify the sales team about qualified leads, required human review, or integration errors. Both integrations are disabled by default and can be exercised locally with `MOCK_AI=true` and their respective `*_ENABLED=true` setting, without credentials or HTTP requests.

The email body uses the existing response draft; the application does not generate a second AI response for sending. A reviewer explicitly approves the draft through `POST /api/leads/{id}/approve` or the dashboard’s **Approve & Send** action. A successful send is recorded for that analysis; a repeated request returns an already-sent status. Failed sends record a safe failure event and may be retried. For live Resend, set `APP_ENV=production`, `MOCK_AI=false`, `RESEND_ENABLED=true`, `RESEND_API_KEY`, and `RESEND_FROM_EMAIL` through deployment secrets. The configured sender must be accepted by the Resend account before live delivery.

## API Endpoints

- `POST /api/leads` — validate and submit a lead.
- `GET /api/leads` — list recent leads.
- `GET /api/leads/{id}` — retrieve lead detail and workflow events.
- `POST /api/leads/{id}/reanalyze` — run and persist a new analysis.
- `POST /api/leads/{id}/review` — approve, reject, request information, or reclassify a decision without sending email.
- `POST /api/leads/{id}/approve` — record explicit approval and attempt to send the existing draft.
- `GET /api/dashboard/summary` — retrieve dashboard metrics.
- `GET /api/health` — check database availability and safe provider modes/configuration.
- `/docs` — FastAPI-generated OpenAPI documentation.

## Testing

Run the suite from the project folder:

```powershell
pytest
```

Tests use an in-memory SQLite database and mock or stub all external providers. They do not call OpenAI, HubSpot, Slack, or Resend. The suite covers lead validation and qualification, workflow persistence, reanalysis and dashboard APIs, integrations and their failure handling, approval/rejection/request-information behavior, duplicate-send protection, and email retry behavior.

## Migrations

Apply the current migration:

```powershell
alembic upgrade head
```

After changing SQLAlchemy models, generate a candidate migration, review it, and then apply it:

```powershell
alembic revision --autogenerate -m "describe change"
alembic upgrade head
```

The Docker app startup also runs `alembic upgrade head` before starting the web server. Do not use destructive migration commands against a database containing data you need to keep.

The optional demo seed can be run after migrations with `python -m scripts.seed_demo`. It is idempotent by its demo email address. Keep `MOCK_AI=true` for a no-credit analysis.

## Production Deployment

Before deployment, configure managed PostgreSQL, production secret storage, TLS, restricted `CORS_ORIGINS`, backups, monitoring, and an operational migration process. Set `APP_ENV=production`; provide OpenAI credentials only if using live AI analysis. Enable HubSpot or Slack only after setting their credentials. Enable Resend only after configuring its API key and accepted sender. Health reports configuration state, not external reachability. Review provider permissions, retry behavior, privacy/retention requirements, and operational alerting before sending real customer data to external services.

The Compose database credentials are local-development values only; do not reuse them in a hosted production environment. Never commit `.env` or real integration secrets.
