# Trace2Quality (t2q)

Enterprise QA automation and traceability platform. Trace2Quality connects requirements, tests, and execution artifacts across Azure DevOps, Confluence, Jira, and AI-powered test generation via Google Gemini.

## What is Trace2Quality?

t2q orchestrates enterprise QA workflows through a web UI and REST API:

- **Catalog Management** — Fetch and index specs, user stories, and docs from Confluence and Jira
- **Test Generation** — AI-powered (Gemini) generation of API and UI test cases
- **Coverage Tracking** — Link tests to requirements, update coverage metrics in Confluence
- **Bug Triage** — Classify defects and surface automation gaps
- **Scheduling & Webhooks** — Schedule recurring workflows or trigger them via GitHub/Jira/Confluence events
- **Workflow Composition** — Chain multiple workflows into a single orchestrated execution

## Architecture

```
trace2quality/
├── apps/
│   ├── app/              # FastAPI web server + UI
│   └── worker/           # Celery job worker
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
| Task Queue | Celery + Redis |
| Database | SQLite (dev), PostgreSQL (production) |
| Frontend | Server-rendered Jinja2 |
| Containers | Docker Compose |
| Testing | pytest + pytest-asyncio |
| External APIs | Azure DevOps REST, Confluence Cloud, Jira Cloud, Google Gemini |

---

## Quick Start

### Prerequisites

- Docker & Docker Compose
- Python 3.11+

### 1. Clone and configure

```bash
git clone https://github.com/abdullakarimov/trace2quality.git
cd trace2quality
cp .env.example .env
# Fill in your tokens — see "Getting API Tokens" below
```

### 2. Start services

```bash
docker-compose up -d
```

### 3. Run migrations

```bash
docker-compose exec app alembic upgrade head
```

### 4. Open the app

| URL | Purpose |
|-----|---------|
| http://localhost:8000 | Web UI |
| http://localhost:8000/docs | Swagger API docs |
| http://localhost:8000/redoc | ReDoc API docs |

### Manual Setup (without Docker)

```bash
python -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
export PYTHONPATH=$(pwd)

# Terminal 1: Redis
redis-server

# Terminal 2: FastAPI app
uvicorn apps.app.main:app --reload --port 8000

# Terminal 3: Celery worker
celery -A apps.worker.celery_app worker --loglevel=info
```

---

## Getting API Tokens

Trace2Quality requires one token per integration you want to use. Configure them in `.env` or via **Settings → Integrations** in the UI.

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
| `REDIS_URL` | No | Redis broker URL (default: `redis://localhost:6379/0`) |
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
| `GEMINI_MODEL` | No | Model name (default: `gemini-pro`) |

---

## Running Workflows

### Via Web UI

1. Open http://localhost:8000
2. Go to **Settings → Integrations** and configure your tokens
3. Click **Test Connection** to validate each integration
4. Navigate to **Workflows** and trigger a run
5. Monitor progress under **Runs**
6. Download outputs from **Data Explorer**

### Via API

```bash
# Trigger a workflow
curl -X POST http://localhost:8000/api/workflows/fetch_confluence/runs \
  -H "Content-Type: application/json" \
  -d '{"parameters": {"space": "QA", "labels": ["requirements"]}}'

# Check run status
curl http://localhost:8000/api/runs/{run_id}

# List recent runs
curl http://localhost:8000/api/runs
```

---

## Development

```bash
# Format
black apps packages

# Lint
ruff check apps packages --fix

# Type checking
mypy apps packages

# Run tests
pytest tests/ -v --cov

# Create a new DB migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head
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
