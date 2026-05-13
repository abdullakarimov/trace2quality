# Trace2Quality (t2q)

Enterprise QA automation and traceability platform. Trace2Quality connects requirements, tests, and execution artifacts across Azure DevOps, Confluence, Jira, and AI-powered test generation.

**Previous name:** spec2test  
**Current name:** Trace2Quality (t2q)  
**Status:** Phase 1 - Foundation (🚧 under development)

## What is Trace2Quality?

t2q is a web application that orchestrates enterprise QA workflows:

- **Catalog Management**: Fetch and index API specs, user stories, and documentation from Confluence and Jira
- **Test Generation**: AI-powered (Gemini) generation of API and UI test cases
- **Coverage Tracking**: Link tests to requirements, update coverage metrics in Confluence
- **Bug Triage**: Intelligent categorization and automation linking of QA defects
- **Run History & Artifacts**: Persistent storage of workflow executions, logs, and outputs

## Architecture

```
trace2quality/
├── apps/
│   ├── app/              # FastAPI web server + UI
│   └── worker/           # Celery job worker
├── packages/
│   ├── workflows/        # Domain logic (catalog, generation, coverage, triage, reporting)
│   ├── integrations/     # External API clients (Azure DevOps, Confluence, Jira, Gemini)
│   └── common/           # Shared models, utilities, constants
├── infra/
│   ├── docker/           # Dockerfiles & Docker Compose
│   └── migrations/       # Alembic database migrations
├── docs/
│   ├── architecture/     # Technical design docs
│   ├── api/              # API reference
│   └── operations/       # Deployment & ops guides
└── scripts/
    ├── dev/              # Development utilities
    └── data_migration/   # Legacy data import tools
```

## Tech Stack

- **Backend**: FastAPI + SQLAlchemy + Pydantic
- **Task Queue**: Celery + Redis
- **Database**: SQLite (dev), PostgreSQL (production)
- **Frontend**: Server-rendered Jinja2 + HTMX + Alpine.js
- **Containerization**: Docker Compose
- **Testing**: pytest + pytest-asyncio
- **External APIs**: Azure DevOps REST, Confluence Cloud, Jira Cloud, Google Gemini

## Quick Start (Local Development)

### Prerequisites

- Docker & Docker Compose
- Python 3.11+
- Make (optional, but recommended)

### Setup

1. **Clone and initialize**
   ```bash
   cd /Users/abdulla/stuff/t2q
   cp .env.example .env
   # Edit .env with your API tokens
   ```

2. **Start services**
   ```bash
   docker-compose up -d
   ```

3. **Run migrations**
   ```bash
   docker-compose exec app alembic upgrade head
   ```

4. **Open app**
   - Web UI: http://localhost:8000
   - Celery Flower (job monitoring): http://localhost:5555 (optional, needs separate container)

### Manual Python Setup (if not using Docker)

```bash
python -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
export PYTHONPATH=/Users/abdulla/stuff/t2q

# Start Redis separately
redis-server

# In one terminal: app
cd apps/app
uvicorn main:app --reload

# In another terminal: worker
cd apps/worker
celery -A celery_app worker --loglevel=info
```

## Configuration

Create `.env` from `.env.example`:

```env
# Required
APP_ENCRYPTION_KEY=<strong-random-key>
REDIS_URL=redis://localhost:6379/0
DATABASE_URL=sqlite:///./data/trace2quality.db

# Integrations (get tokens from each provider)
AZURE_DEVOPS_PAT=<your-pat>
CONFLUENCE_API_TOKEN=<your-token>
JIRA_API_TOKEN=<your-token>
GEMINI_API_KEY=<your-key>
```

## Running Workflows

### Web UI (Recommended)

1. Go to http://localhost:8000
2. Configure integrations: **Settings → Integrations**
3. Run workflows: **Workflows** tab
4. View runs: **Runs** tab
5. Explore data: **Data Explorer** tab

### CLI (Optional)

```bash
# Check current fixtures (after running)
python -m apps.worker.cli run-workflow --workflow fetch-catalog --dry-run

# Run workflow
python -m apps.worker.cli run-workflow --workflow generate-api-tests --project MyProject
```

## Project Phases

### Phase 1: Foundation ✅ (In Progress)
- Monorepo scaffolding
- Integration settings & encrypted secrets
- Job framework & run persistence
- Basic workflow execution

### Phase 2: Core Workflows (Next)
- Catalog fetch from Confluence/Jira
- API/UI test case generation with Gemini
- Coverage page updates

### Phase 3: Advanced Workflows
- Bug triage and classification
- Automation association from test runs
- Progress reports and metrics

### Phase 4: Hardening
- Comprehensive test suite
- Observability & logging
- Migration tools for legacy data
- Complete documentation

## Key Features (When Implemented)

- 🔐 **Secure Credentials**: Encrypted token storage, no copy-paste cURL commands
- 📦 **Modular Workflows**: Independent, testable, reusable services
- 🔄 **Job Orchestration**: Queued execution, retry logic, idempotent operations
- 📊 **Run History**: Persistent logs, artifacts, and metrics
- 🌐 **Multi-Tenant Ready**: Single-user initially, extensible for organizations
- 🔌 **Provider Abstractions**: Easy to add new integrations (AWS, GCP, GitHub, etc.)
- 📲 **Real-Time Updates**: WebSocket support for live job status (future)

## Security Considerations

- All secrets encrypted at application level using `APP_ENCRYPTION_KEY`
- Never logs full tokens or sensitive data
- PAT/API token validation on connection test
- Rotate credentials without server restart
- Default to SQLite (no network exposure); PostgreSQL optional for production

## Development

### Code Style

```bash
# Format
black apps packages

# Lint
ruff check apps packages --fix

# Type checking
mypy apps packages

# Sort imports
isort apps packages
```

### Testing

```bash
pytest apps packages -v --cov
```

### Database Migrations

```bash
# Create new migration
alembic revision --autogenerate -m "Add new table"

# Apply migrations
alembic upgrade head

# Rollback
alembic downgrade -1
```

## API Documentation

FastAPI auto-generates OpenAPI docs at:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

Key endpoints:
- `POST /api/integrations/{type}/test` - Test connection to provider
- `GET /api/integrations` - List configured integrations
- `POST /api/workflows/{workflow_key}/runs` - Trigger workflow
- `GET /api/runs` - List all runs
- `GET /api/runs/{id}` - Get run details and logs

## Known Gaps & Next Steps

1. **WebSocket Live Updates**: Currently uses polling; WebSocket would improve UX
2. **Data Migration**: Need scripts to import legacy `data/` and `output/` artifacts
3. **OAuth Support**: Jira/Confluence/Azure DevOps OAuth (PAT/API token priority now)
4. **Multi-Tenancy**: Initial single-user, but schema ready for organizations
5. **Webhook Sync**: Real-time syncs from providers (currently manual trigger)
6. **Test Coverage**: Core workflows need 80%+ test coverage

## Migration from spec2test

Old project structure → New project structure:

| Old | New |
|-----|-----|
| `test_generators/` | `packages/workflows/` |
| `test_generators/fetch/` | `packages/workflows/catalog/` |
| `test_generators/generate/` | `packages/workflows/generation/` |
| `integrations/` (implicit) | `packages/integrations/` |
| One-off scripts | Workflow modules + UI |
| cURL replay auth | Token-based auth (PAT, API keys) |
| `data/` outputs | Persisted run artifacts + database |

## Support & Contributing

For issues, ideas, or contributions, open a GitHub issue or pull request.

## License

MIT

---

**Last Updated**: May 2026  
**Version**: 0.1.0-alpha  
**Project Lead**: Trace2Quality Team
