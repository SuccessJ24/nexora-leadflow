# NEXORA LeadFlow — Product Case Study

## Project overview

NEXORA LeadFlow is a human-guided lead qualification and sales operations application for B2B marketing agencies. It takes a public inquiry through structured analysis, deterministic qualification, reviewer follow-up, and an auditable next step.

This is a portfolio project, not a client case study. The examples and screenshots use synthetic lead data. No client results, customer testimonials, or performance metrics are claimed.

**Live experience:** [Public inquiry form](https://nexora-leadflow.onrender.com/request) · [Read-only demo](https://nexora-leadflow.onrender.com/demo) · [Team sign-in](https://nexora-leadflow.onrender.com/signin)

## The product problem

Agency teams receive inquiries with different levels of fit, urgency, budget detail, and readiness. A useful workflow needs to organize those signals quickly while preserving review when information is missing or the next step could affect a prospect.

LeadFlow is designed around that workflow. A visitor can submit an inquiry without creating an account. The private team workspace stores the lead, presents its analysis and qualification, and gives a reviewer control over follow-up.

## Core workflow

```text
Public inquiry
  → Structured AI analysis
  → Deterministic qualification and routing
  → CRM / Slack adapter outcomes
  → Response draft
  → Human review and decision
  → Approved email send (when configured)
  → Workflow and audit events
```

The model supplies structured analysis. Application rules determine the final qualification and human-review route. The response draft is not sent automatically; a signed-in reviewer must approve it.

## Example use cases

### 1. Prioritize a complete, high-fit inquiry

A synthetic B2B lead with a stated budget, service needs, and near-term timeline is analyzed for service fit, intent, urgency, and confidence. Deterministic rules use those signals to assign the final route and recommended next action.

![Synthetic HOT lead analysis](screenshots/lead-detail-hot.jpg)

### 2. Route incomplete information to human review

When an inquiry lacks useful company, industry, budget, or timeline information, the workflow records what is missing and routes it for human review instead of filling gaps with invented facts.

![Synthetic lead routed to human review](screenshots/lead-detail-review.jpg)

### 3. Review a response before sending

LeadFlow prepares a draft using the inquiry details. A reviewer can request information, reclassify, reject, or approve the draft. The screenshot shows the message in a **Not sent** state; the project does not claim it was delivered.

![Response draft with human approval controls](screenshots/approval-workflow.jpg)

### 4. Monitor the team queue and workflow

The dashboard summarizes the lead queue, qualification categories, human-review workload, and follow-ups. Lead details include analysis confidence and workflow-event history.

![Synthetic dashboard overview](screenshots/dashboard-overview.jpg)

## Product walkthrough

The short GIF sequences the saved dashboard and lead-detail screenshots. It is an edited walkthrough, not a continuous recording.

![LeadFlow walkthrough GIF](screenshots/leadflow-demo.gif)

## Architecture and control boundaries

| Concern | Responsibility |
| --- | --- |
| AI provider | Produces schema-validated analysis; mock mode runs locally without OpenAI or Gemini calls. |
| Qualification rules | Decide final HOT/WARM/NURTURE/UNQUALIFIED routing and review requirements deterministically. |
| PostgreSQL + Alembic | Persist leads, analyses, follow-ups, and workflow events with versioned migrations. |
| Integration adapters | Isolate HubSpot CRM, Slack notifications, and Resend email from the lead workflow. |
| Human reviewer | Controls reclassification, rejection, information requests, and email approval. |
| Workflow events | Provide a record of processing, analysis, review, and integration outcomes. |

Integration credentials are not included in this repository. The portfolio deployment uses mock AI and has no live provider secrets configured; configure integrations through Render secrets if needed. Email remains behind explicit human approval.

## Public and private experiences

- **Public inquiry:** [nexora-leadflow.onrender.com/request](https://nexora-leadflow.onrender.com/request), no account required; contact consent is required.
- **Public product preview:** [nexora-leadflow.onrender.com/demo](https://nexora-leadflow.onrender.com/demo), read-only synthetic records.
- **Private workspace:** [nexora-leadflow.onrender.com/signin](https://nexora-leadflow.onrender.com/signin), protected by owner credentials configured in Render.

The live Render deployment uses its free web service and free PostgreSQL database. Free services can spin down while idle, and the database expires after 30 days without backups. Treat the instance as a portfolio demonstration and use synthetic test inquiries, not as a durable destination for customer data. See [Render's free-tier limits](https://render.com/docs/free).

## Technology

FastAPI, Pydantic, SQLAlchemy, PostgreSQL, Alembic, Jinja2, Docker, pytest, and provider adapters for OpenAI, Gemini, HubSpot, Slack, and Resend.

## Verification snapshot

- Local test suite: **66 passed** on October 9, 2026.
- Render deployment: marked **Deploy succeeded | Live** on October 9, 2026; the Alembic migration completed and the health endpoint returned HTTP 200.
- Browser inspection: the hosted sign-in page and public inquiry page loaded successfully.
- No live inquiry was submitted during deployment verification. The screenshots above are synthetic local captures, not screenshots of live customer data.

See the [README](README.md) for setup, configuration, endpoints, testing, migrations, and deployment details.
