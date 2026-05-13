# Architecture - Trace2Quality (t2q)

## System Overview

Trace2Quality is a distributed QA automation platform built with modern Python web technologies. It orchestrates workflows across multiple external systems (Azure DevOps, Confluence, Jira, Gemini) while maintaining a persistent database of configurations, runs, and artifacts.

### High-Level Components

```
┌─────────────────────────────────────────────────────────────────┐
│                         Web Browser                              │
└───────────────┬─────────────────────────────────────────────────┘
                │ HTTP/REST
┌───────────────▼─────────────────────────────────────────────────┐
│                     FastAPI Application                          │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────┐   │
│  │  Server-Rendered │  │  REST API        │  │  WebSocket   │   │
│  │  UI (Jinja2)     │  │  (JSON)          │  │  (Optional)  │   │
│  └──────────────────┘  └──────────────────┘  └──────────────┘   │
└──────┬────────────────────────────────────┬──────────────┬──────┘
       │                                    │              │
       ├─ SQLAlchemy ORM                    │              │
       ├─ Request routing                   │              │
       └─ Session management                │              │
                                             │              │
┌────────────────────────────────────────────▼──────────────▼─────┐
│                   Job Queue (Celery)                             │
│  ┌──────────────────┐  ┌──────────────────┐                    │
│  │  Task Broker     │  │  Result Backend  │                    │
│  │  (Redis)         │  │  (Redis)         │                    │
│  └──────────────────┘  └──────────────────┘                    │
└────────┬──────────────────────────────────────────────────────┘
         │ Async job execution
┌────────▼──────────────────────────────────────────────────────┐
│              Celery Worker(s)                                  │
│  ┌────────────────────────────────────────────────────────┐   │
│  │  Workflow Execution Engine                            │   │
│  │  - Catalog fetching                                   │   │
│  │  - Test generation                                    │   │
│  │  - Coverage updates                                   │   │
│  │  - Triage and reporting                               │   │
│  └────────────────────────────────────────────────────────┘   │
└──────┬─────┬───────────┬──────────┬─────────────────────────────┘
       │     │           │          │
       │     │           │          └─ Confluence API
       │     │           └────────────── Jira API
       │     └────────────────────────── Azure DevOps API
       └──────────────────────────────── Gemini API

┌─────────────────────────────────────────────────────────────────┐
│                       Data Persistence                           │
│  ┌──────────────────┐  ┌──────────────────┐                    │
│  │  SQLite/Postgres │  │  File Storage    │                    │
│  │  (Configurations,│  │  (Artifacts,     │                    │
│  │   Run history,   │  │   Datasets)      │                    │
│  │   Logs)          │  │                  │                    │
│  └──────────────────┘  └──────────────────┘                    │
└─────────────────────────────────────────────────────────────────┘
```

## Layer Breakdown

### 1. Frontend Layer
- **Technology**: Jinja2 templates + HTMX + Alpine.js
- **Responsibilities**:
  - Server-rendered HTML pages for dashboard, settings, workflows, runs
  - Integration configuration forms (with secure token input)
  - Live job monitoring (via polling, WebSocket future)
  - Data browsing and artifact download
- **No** heavy JavaScript framework (no React/Vue)
- **Benefits**: Fast page loads, minimal client state, server-side logic co-located

### 2. API Layer (FastAPI)
- **Technology**: FastAPI + Pydantic + SQLAlchemy
- **Responsibilities**:
  - RESTful endpoints for programmatic access
  - Request validation and serialization
  - Authentication and authorization (future: JWT)
  - CORS and middleware setup
  - Integration health checks and connection testing
- **Key routes**:
  - `/api/integrations/*` - Provider configuration and testing
  - `/api/workflows/*` - Workflow management and execution
  - `/api/runs/*` - Run history and logs
  - `/api/artifacts/*` - Generated output files

### 3. Workflow Layer (Business Logic)
- **Location**: `packages/workflows/`
- **Modules**:
  - `catalog/` - Data ingestion and indexing
  - `generation/` - AI-powered test case creation
  - `coverage/` - Coverage tracking and metrics
  - `triage/` - Bug classification
  - `reporting/` - Results aggregation and traceability
- **Design**:
  - Pure functions/services (dependency-injected clients)
  - No coupling to HTTP or UI frameworks
  - Independently testable and reusable
  - Async-ready for scalability

### 4. Integration Layer
- **Location**: `packages/integrations/`
- **Providers**:
  - `azure_devops/` - Azure DevOps REST API client
  - `confluence/` - Confluence Cloud API client
  - `jira/` - Jira Cloud API client
  - `gemini/` - Google Gemini API client
- **Pattern**:
  - Abstract base class `IntegrationClient` with common interface
  - Registry pattern for dynamic client instantiation
  - Token/PAT-based authentication (no cURL replay)
  - Retry and error handling logic
  - Mask secrets in logs

### 5. Job Queue Layer (Celery + Redis)
- **Technology**: Celery + Redis
- **Responsibilities**:
  - Asynchronous task execution
  - Distributed job processing (multi-worker capable)
  - Task persistence and retry logic
  - Job status tracking
  - Result caching
- **Workflow**:
  1. User triggers workflow via REST API or UI
  2. FastAPI creates run record in database
  3. Celery task is enqueued
  4. Worker picks up task and executes workflow
  5. Run status is updated; logs are persisted
  6. UI polls for updates (or WebSocket in future)

### 6. Data Persistence Layer
- **Database**: SQLite (dev), PostgreSQL (production)
- **Models**:
  - `IntegrationConfigModel` - Encrypted provider credentials
  - `WorkflowRunModel` - Run metadata and status
  - `WorkflowRunLogModel` - Timestamped execution logs
  - `ArtifactModel` - Generated output metadata
  - `DatasetSnapshotModel` - Cached external data
  - `UserPreferenceModel` - Future: multi-tenant settings
- **File Storage**:
  - `data/artifacts/` - Generated test cases, reports, exports
  - `data/cache/` - Cached provider data, intermediate results

## Data Flow

### Workflow Execution Flow

```
1. User Action
   └─> Click "Run Workflow" on UI
       └─> POST /api/workflows/{key}/runs
   
2. API Handler
   └─> Create WorkflowRunModel (status=queued)
       └─> Send Celery task
       └─> Return run_id to user
   
3. Async Processing
   └─> Worker receives task
       └─> Update status to "running"
       └─> Log correlation_id
       └─> Call workflow service
           ├─> Fetch integration configs from DB
           ├─> Instantiate integration clients
           ├─> Execute workflow logic
           └─> Persist run logs
       └─> Update status (succeeded/failed)
       └─> Store artifacts
   
4. User Monitoring
   └─> Poll GET /api/runs/{id}
       └─> Return run status, duration
   └─> Poll GET /api/runs/{id}/logs
       └─> Stream or return timestamped log lines
   └─> Get GET /api/runs/{id}/artifacts
       └─> Download output files
```

### Integration Configuration Flow

```
1. Settings Page
   └─> GET /ui/integrations
       └─> Render form for each provider (Azure, Confluence, Jira, Gemini)
   
2. User Input
   └─> Fill in credentials (PAT, API token, API key)
       └─> POST /api/integrations/{type}
           └─> Encrypt credentials with APP_ENCRYPTION_KEY
           └─> Store in IntegrationConfigModel
   
3. Connection Test
   └─> Click "Test Connection"
       └─> POST /api/integrations/{type}/test
           └─> Decrypt credentials
           └─> Instantiate integration client
           └─> Call test_connection()
           └─> Update status in DB (healthy/unhealthy)
           └─> Return result to user
```

## Security Considerations

### Secret Management
- **Encryption Key**: `APP_ENCRYPTION_KEY` environment variable
- **Storage**: Encrypted at-rest in database
- **Transmission**: HTTPS only (in production)
- **Logging**: Secrets masked/redacted; only last N chars visible if accidentally logged
- **Rotation**: Update via settings without restart

### Authentication (Future)
- OAuth 2.0 / OpenID Connect
- JWT tokens
- Role-based access control (RBAC)
- Currently: single-user mode (no auth required)

### Integration Security
- No raw cURL replay or browser cookie injection
- Token validation on connection test
- Scope checking for each provider
- Retry logic with exponential backoff (defensive against rate limits)

## Scaling Considerations

### Horizontal Scaling
- **App**: Multiple FastAPI workers (Gunicorn/Uvicorn)
- **Worker**: Multiple Celery workers (auto-scaling)
- **Database**: PostgreSQL for production (replicate if needed)
- **Cache**: Redis cluster for high availability

### Vertical Scaling
- **Celery Configuration**:
  - Worker prefetch multiplier: configurable
  - Task time limits: prevents hung jobs
  - Auto-retry on transient failures
- **Database Connection Pooling**: SQLAlchemy connection pool sizing

### Monitoring & Observability
- Structured logging (JSON in production, text in dev)
- Correlation IDs for request/job tracing
- Celery Flower for job monitoring (optional, in-container)
- Health check endpoint for load balancers

## Testing Strategy

### Unit Tests
- Workflow services (mocked integration clients)
- Data models and validators
- Utility functions (encryption, logging)

### Integration Tests
- With mocked HTTP responses (responses library)
- Database operations (test DB)
- Celery task execution

### UI Tests (Future)
- Critical pages (dashboard, run detail)
- Integration form submission and validation

### E2E Tests
- Docker Compose stack
- Smoke tests for happy path
- Pre-deployment validation

## Future Enhancements

1. **Real-Time Updates**: WebSocket for live log streaming
2. **Multi-Tenancy**: Organizations, teams, RBAC
3. **Webhook Sync**: Auto-sync from providers
4. **AI-Powered Insights**: Coverage gaps, test recommendations
5. **Cloud Deployments**: Kubernetes, serverless function integrations
6. **Plugin System**: Allow custom workflow modules and integrations
