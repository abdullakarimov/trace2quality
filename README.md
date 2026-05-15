# Trace2Quality (t2q)

Enterprise QA automation and traceability platform. Trace2Quality connects requirements, tests, and execution artifacts across Azure DevOps, Confluence, Jira, and AI-powered test generation via Google Gemini.

## What is Trace2Quality?

t2q orchestrates enterprise QA workflows through a web UI and REST API:

- **Catalog Management** — Fetch and index specs, user stories, and docs from Confluence and Jira
- **Test Generation** — AI-powered (Gemini) generation of API and UI test cases
- **Coverage Tracking** — Link tests to requirements, fetch full Azure DevOps test steps, update coverage metrics in Confluence
- **Bug Triage** — AI-powered Jira bug assessment with dry-run preview and one-click apply (transition, priority, custom fields; optional comment)
- **CSV Fixer** — Fix broken Azure DevOps Test Plan CSV files for import (browser-based, no ADO connection required)
- **Scheduling & Webhooks** — Schedule recurring workflows or trigger them via GitHub/Jira/Confluence events
- **Workflow Composition** — Chain multiple workflows into a single orchestrated execution

## Architecture

```
trace2quality/
├── apps/
│   └── app/              # FastAPI web server + UI
├── packages/
│   ├── workflows/        # Domain logic (catalog, generation, coverage, triage, reporting)
│   ├── integrations/     # External API clients (Azure DevOps, Confluence, Jira, Gemini)
│   └── common/           # Shared models, utilities, logging
├── infra/
│   ├── docker/           # Dockerfiles
│   └── migrations/       # Alembic database migrations
├── docs/                 # API reference, design, and operations guides
└── scripts/              # Demo and data migration utilities
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI + SQLAlchemy + Pydantic |
| Database | SQLite (dev), PostgreSQL (production) |
| Frontend | Server-rendered Jinja2 + HTMX |
| Gemini | google-genai SDK + 10s rate limiting |
| Testing | pytest + pytest-asyncio |
| External APIs | Azure DevOps REST, Confluence Cloud, Jira Cloud, Google Gemini |

> **No external dependencies required.** The app runs on Python venv + SQLite only.
> Docker Compose is provided as optional convenience for fresh-machine setup only.

---

## Quick Start (native — recommended)

### Prerequisites

- Python 3.11+

### 1. Clone and set up

```bash
git clone https://github.com/abdullakarimov/trace2quality.git
cd trace2quality
make setup          # creates venv, installs deps, copies .env.example → .env
```

Edit `.env` and fill in your tokens (see **Getting API Tokens** below).

### 2. Run migrations and start

```bash
make migrate        # creates/upgrades SQLite database
make dev            # starts FastAPI app
```

That's it. Open http://localhost:8000.

| URL | Purpose |
|-----|---------|
| http://localhost:8000 | Web UI |
| http://localhost:8000/docs | Swagger API docs |
| http://localhost:8000/redoc | ReDoc API docs |

### Stopping

Press `Ctrl-C` in the `make dev` terminal, or run:

```bash
scripts/dev/stop.sh
```

---

## Optional: Docker Compose

Docker is **not required** for local development. If you prefer containers:

```bash
# Build and start
docker-compose up -d

# Run migrations inside container
docker-compose exec app alembic upgrade head

# Stop
docker-compose down
```

---

## Getting API Tokens

Trace2Quality requires one token per integration you want to use. Configure them in `.env`.

### Azure DevOps — Personal Access Token (PAT)

A PAT authenticates against the Azure DevOps REST API to read test plans and create/update test cases.

1. Sign in to [dev.azure.com](https://dev.azure.com) and open your organisation.
2. Click your profile avatar (top-right) → **Personal access tokens**.
3. Click **New Token**.
4. Set a name (e.g. `trace2quality`), choose an expiry, and select the **Scopes**:
   - **Work Items**: Read & Write
   - **Test Management**: Read & Write
5. Click **Create** and copy the token — it is only shown once.
6. Add to `.env`:
   ```env
   AZURE_DEVOPS_ORG_URL=https://dev.azure.com/your-org
   AZURE_DEVOPS_PROJECT=YourProjectName
   AZURE_DEVOPS_PAT=<paste token here>
   ```

> **Docs**: [Azure DevOps PAT documentation](https://learn.microsoft.com/en-us/azure/devops/organizations/accounts/use-personal-access-tokens-to-authenticate)

---

### Confluence Cloud — API Token

Used to read and write Confluence pages (requirements catalog, coverage reports).

1. Go to [id.atlassian.com/manage-profile/security/api-tokens](https://id.atlassian.com/manage-profile/security/api-tokens).
2. Click **Create API token**.
3. Give it a label (e.g. `trace2quality`) and click **Create**.
4. Copy the token — it is only shown once.
5. Add to `.env`:
   ```env
   CONFLUENCE_BASE_URL=https://your-domain.atlassian.net/wiki
   CONFLUENCE_SPACE=YOURSPACE
   CONFLUENCE_EMAIL=your.email@domain.com
   CONFLUENCE_API_TOKEN=<paste token here>
   ```

> The app authenticates using **Basic Auth** (`email:token` base-64 encoded), which is the standard for Confluence Cloud REST API.

> **Docs**: [Atlassian API tokens](https://support.atlassian.com/atlassian-account/docs/manage-api-tokens-for-your-atlassian-account/)

---

### Jira Cloud — API Token

Used to query issues and update tickets (bug triage, QA tasks).

1. Use the **same API token** generated for Confluence above — Atlassian tokens are account-wide and work for both Confluence and Jira.
2. Add to `.env`:
   ```env
   JIRA_BASE_URL=https://your-domain.atlassian.net
   JIRA_EMAIL=your.email@domain.com
   JIRA_API_TOKEN=<same Atlassian token>
   ```

> **Docs**: [Jira Cloud REST API authentication](https://developer.atlassian.com/cloud/jira/platform/basic-auth-for-rest-apis/)

---

### Google Gemini — API Key

Used for AI-powered test case generation and coverage analysis.

1. Go to [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey).
2. Click **Create API key** and select a Google Cloud project (or create one).
3. Copy the generated key.
4. Add to `.env`:
   ```env
   GEMINI_API_KEY=<paste key here>
   GEMINI_MODEL=gemini-pro
   ```

> **Free tier**: Google AI Studio offers a free quota sufficient for development use. For production workloads, use a billed project via [Google Cloud Vertex AI](https://cloud.google.com/vertex-ai/docs/generative-ai/model-reference/gemini).

> **Docs**: [Google AI Studio API keys](https://ai.google.dev/gemini-api/docs/api-key)

---

### Encryption Key

All integration tokens are encrypted at rest using Fernet symmetric encryption. Generate a strong key:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

```env
APP_ENCRYPTION_KEY=<output from above>
APP_SECRET_KEY=<another strong random string>
```

> **Never commit your `.env` file.** It is excluded by `.gitignore`.

---

## Configuration Reference

| Variable | Required | Description |
|----------|----------|-------------|
| `APP_ENV` | No | `development` or `production` (default: `development`) |
| `APP_ENCRYPTION_KEY` | **Yes** | Fernet key for encrypting stored tokens |
| `APP_SECRET_KEY` | **Yes** | Secret for session signing |
| `DATABASE_URL` | No | SQLite path or PostgreSQL URL |
| `AZURE_DEVOPS_ORG_URL` | For Azure | `https://dev.azure.com/your-org` |
| `AZURE_DEVOPS_PROJECT` | For Azure | Project name |
| `AZURE_DEVOPS_PAT` | For Azure | Personal Access Token |
| `CONFLUENCE_BASE_URL` | For Confluence | `https://your-domain.atlassian.net/wiki` |
| `CONFLUENCE_SPACE` | For Confluence | Space key (e.g. `QA`) |
| `CONFLUENCE_EMAIL` | For Confluence | Your Atlassian account email |
| `CONFLUENCE_API_TOKEN` | For Confluence | Atlassian API token |
| `JIRA_BASE_URL` | For Jira | `https://your-domain.atlassian.net` |
| `JIRA_EMAIL` | For Jira | Your Atlassian account email |
| `JIRA_API_TOKEN` | For Jira | Atlassian API token (same as Confluence) |
| `GEMINI_API_KEY` | For AI features | Google AI Studio API key |
| `GEMINI_MODEL` | No | Model name (default: `gemini-2.0-flash`) |

---

## Running Workflows

### Via Web UI

1. Open http://localhost:8000
2. Navigate to **Workflows** and trigger a run
3. Monitor progress under **Runs**
4. Use **Dashboard → CSV Fixer** to repair malformed Azure DevOps Test Plan CSV files before import

### Via API

```bash
# Trigger a workflow
curl -X POST http://localhost:8000/api/workflows/fetch_confluence/runs \
  -H "Content-Type: application/json" \
  -d '{"parameters": {"space": "QA", "labels": ["requirements"]}}'

# Triage bugs (dry run — no Jira changes)
curl -X POST http://localhost:8000/api/workflows/triage-bugs/runs \
  -H "Content-Type: application/json" \
  -d '{"jql": "project = MYPROJ AND issuetype = Bug AND status = Open", "max_results": 50, "apply": false}'

# Apply triage results to all real bugs from a run
curl -X POST http://localhost:8000/api/workflows/triage-bugs/apply-issues \
  -H "Content-Type: application/json" \
  -d '{"run_id": "<run_id>", "issue_keys": null}'

# Apply triage results and also add triage comments
curl -X POST http://localhost:8000/api/workflows/triage-bugs/apply-issues \
   -H "Content-Type: application/json" \
   -d '{"run_id": "<run_id>", "issue_keys": null, "add_comment": true}'

# Apply triage results to a single issue
curl -X POST http://localhost:8000/api/workflows/triage-bugs/apply-issues \
  -H "Content-Type: application/json" \
  -d '{"run_id": "<run_id>", "issue_keys": ["MYPROJ-123"]}'

# Check run status
curl http://localhost:8000/api/runs/{run_id}

# List recent runs
curl http://localhost:8000/api/runs
```

---

## Triage Bug Tickets Workflow

The triage workflow fetches Jira bugs via JQL, locates the associated Confluence user-story specification page for each issue, and uses Google Gemini to assess each bug against the spec.

**UI:** `http://localhost:8000/ui/workflows/triage_bugs/run`

### How it works

1. **Fetch bugs** — Query Jira using any JQL expression (e.g. `project = PROJ AND issuetype = Bug AND status = Open`).
2. **Find spec page** — For each bug, the workflow extracts the linked user story identifier (e.g. `US-11.1.2`) and searches Confluence using a two-strategy approach:
   - Quoted-phrase CQL (`title ~ "\"US-11.1.2\""`) for exact segment matching.
   - Broad fallback with Python regex filtering when the exact query returns nothing.
   - When multiple pages match, the shortest non-API-suffixed title is preferred as the most generic spec page.
3. **AI assessment** — Gemini reads the spec and the bug description and returns:
   - `is_real_bug` — whether the bug is a genuine defect given the spec.
   - `severity` — `Critical` / `Major` / `Minor`.
   - `impact` — `Extensive / Widespread` / `Significant / Large` / `Moderate / Limited` / `Minor / Localized`.
   - `priority` — `Highest` / `High` / `Medium` / `Low` / `Lowest`.
   - `reasoning` — free-text explanation.
4. **Dry-run preview** — Results are shown in a table. No Jira changes are made until you explicitly apply.
5. **Apply** — After reviewing the dry-run table, apply changes issue-by-issue using the per-row **Apply** button, or apply all real bugs at once with **Apply All**. Each apply call:
   - Transitions the issue to the configured target status.
   - Sets `priority`, `severity` (custom field), and `impact` (custom field).
   - Optionally adds a triage comment with Gemini reasoning only when explicitly enabled.

### Parameters

| Field | Required | Description |
|-------|----------|-------------|
| JQL | Yes | Jira Query Language filter for bugs to triage |
| Max Results | No | Cap on number of issues fetched (default: 50) |
| Apply | No | `true` to apply changes immediately; `false` (default) for dry-run |
| Add Comment | No | `true` to add Jira triage comments (default: `false`) |
| Target Status | No | Jira status to transition issues to after triage (e.g. `In Progress`) |
| Severity Field ID | No | Jira custom field ID for severity (e.g. `customfield_10200`) |
| Impact Field ID | No | Jira custom field ID for impact (e.g. `customfield_10201`) |
| Batch Delay (s) | No | Seconds to wait between Gemini calls to stay within rate limits (default: 10) |

---

## CSV Fixer

The CSV Fixer tool repairs Azure DevOps Test Plan CSV files that fail to import due to formatting issues. It runs entirely in the browser — no ADO connection is needed.

**Access:** Dashboard → CSV Fixer, or navigate to `http://localhost:8000/ui/csv-fixer` directly.

**What it fixes:**

- Legacy 9-column CSVs → 10-column Azure DevOps schema (inserts empty `Priority` column)
- Test Case rows with embedded step data → splits into a TC header row + step row
- Step rows that carry `Area Path` / `Assigned To` / `State` instead of the parent TC row — borrows them up
- Tab-collapsed metadata cells where multiple fields were merged into one
- Missing `Priority` / `Area Path` / `Assigned To` / `State` on test case rows — carry-forward from last seen values
- Existing `ID` values — stripped so imported items are created fresh
- Embedded newlines inside cell values — replaced with `\n` or a space (configurable)
- Wrong column count — maps to the expected 10-column shape
- Blank/empty separator rows — dropped

**Parameters:**

| Field | Required | Description |
|-------|----------|-------------|
| CSV Files | Yes | One or more `.csv` files to fix |
| Assigned To | No | Default assignee used when rows have no assignee (e.g. `Doe John <john.doe@corp.com>`) |
| Embedded Newlines | No | How to handle newlines inside cells: `\n` (default), space, or keep as-is |

**Output:** Single file → `<name>_fixed.csv` download. Multiple files → `fixed_csvs.zip` archive.

---

## Coverage Workflow — Azure DevOps Notes

When fetching test cases from Azure DevOps, the coverage workflow:

- Retrieves **full work item details** for each test case, including the `Microsoft.VSTS.TCM.Steps` XML field, and parses it into structured `{action, expected}` step pairs (HTML tags are stripped).
- Classifies test suites as **API** or **UI** by comparing the **Test Plan ID** numerically — not by suite name. Adjust `API_PLAN_ID` in `packages/workflows/coverage/__init__.py` to match your project's plan IDs.

---

## Development

```bash
make setup          # first-time setup
make dev            # start app + worker
make test           # run test suite
make test-coverage  # tests with HTML coverage report
make lint           # ruff + mypy
make format         # black + isort
make migrate        # apply Alembic migrations
make clean          # clear caches
```

Create a new migration after model changes:

```bash
PYTHONPATH=$(pwd) venv/bin/alembic -c infra/migrations/alembic.ini \
  revision --autogenerate -m "describe change"
```

---

## Security Notes

- All credentials stored encrypted (Fernet AES-128) — never in plain text
- Tokens are masked in all log output
- `.env` is excluded from version control
- Rotate any token from the UI without restarting the server
- Use PostgreSQL + a secrets manager (e.g. AWS Secrets Manager, Vault) in production

---

## License

MIT
