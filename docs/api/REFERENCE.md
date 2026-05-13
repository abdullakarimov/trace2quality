# API Reference - Trace2Quality

## Base URL

```
http://localhost:8000/api
```

## Authentication

Currently, single-user mode (no auth required). Future: JWT Bearer tokens.

## Response Format

All endpoints return JSON.

### Success Response

```json
{
  "status": "ok",
  "data": {}
}
```

### Error Response

```json
{
  "error": "Error message",
  "detail": "Detailed error description",
  "correlation_id": "uuid-for-tracking"
}
```

## Integrations

### List Integrations

```http
GET /integrations
```

**Response:**
```json
[
  {
    "type": "azure_devops",
    "is_configured": true,
    "status": "healthy",
    "last_tested": "2024-01-15T10:30:00Z"
  },
  {
    "type": "confluence",
    "is_configured": false,
    "status": "unconfigured"
  }
]
```

### Get Integration Status

```http
GET /integrations/{type}
```

**Parameters:**
- `type` (path): `azure_devops`, `confluence`, `jira`, or `gemini`

**Response:**
```json
{
  "type": "confluence",
  "status": "unconfigured",
  "is_configured": false,
  "error_message": null
}
```

### Update Integration Configuration

```http
PUT /integrations/{type}
```

**Parameters:**
- `type` (path): Integration provider type

**Request Body:**
```json
{
  "base_url": "https://yourdomain.atlassian.net/wiki",
  "email": "user@domain.com",
  "api_token": "your-api-token-here"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Configuration updated for confluence"
}
```

### Test Integration Connection

```http
POST /integrations/{type}/test
```

**Parameters:**
- `type` (path): Integration provider type

**Response (Success):**
```json
{
  "success": true,
  "error": null
}
```

**Response (Failure):**
```json
{
  "success": false,
  "error": "Invalid API token or email"
}
```

## Workflows

### List Available Workflows

```http
GET /workflows
```

**Response:**
```json
{
  "workflows": [
    {
      "key": "fetch_catalog",
      "name": "Fetch Catalog",
      "description": "Fetch and index content from external sources"
    },
    {
      "key": "generate_api_tests",
      "name": "Generate API Tests",
      "description": "Generate API test cases using Gemini"
    }
  ]
}
```

### Create Workflow Run

```http
POST /workflows/{workflow_key}/runs
```

**Parameters:**
- `workflow_key` (path): Workflow identifier (e.g., `fetch_catalog`)

**Request Body:**
```json
{
  "parameters": {
    "project": "MyProject",
    "space": "MYSPACE"
  },
  "dry_run": false,
  "force": false
}
```

**Response:**
```json
{
  "run_id": "uuid-string",
  "status": "queued",
  "workflow_key": "fetch_catalog",
  "created_at": "2024-01-15T10:30:00Z"
}
```

## Runs

### List Runs

```http
GET /runs?status=running&workflow_key=fetch_catalog&limit=50&offset=0
```

**Query Parameters:**
- `status` (optional): `queued`, `running`, `succeeded`, `failed`, `canceled`
- `workflow_key` (optional): Filter by workflow
- `limit` (optional): Results per page (default: 50)
- `offset` (optional): Pagination offset (default: 0)

**Response:**
```json
{
  "runs": [
    {
      "id": "uuid-string",
      "workflow_key": "fetch_catalog",
      "status": "succeeded",
      "created_at": "2024-01-15T10:00:00Z",
      "started_at": "2024-01-15T10:00:05Z",
      "completed_at": "2024-01-15T10:05:30Z"
    }
  ],
  "total": 100,
  "limit": 50,
  "offset": 0
}
```

### Get Run Details

```http
GET /runs/{run_id}
```

**Parameters:**
- `run_id` (path): Workflow run UUID

**Response:**
```json
{
  "id": "uuid-string",
  "workflow_key": "fetch_catalog",
  "status": "succeeded",
  "parameters": {
    "project": "MyProject",
    "space": "MYSPACE"
  },
  "dry_run": false,
  "created_at": "2024-01-15T10:00:00Z",
  "started_at": "2024-01-15T10:00:05Z",
  "completed_at": "2024-01-15T10:05:30Z",
  "duration_seconds": 325.0,
  "error_message": null
}
```

### Get Run Logs

```http
GET /runs/{run_id}/logs?limit=1000
```

**Parameters:**
- `run_id` (path): Workflow run UUID
- `limit` (query, optional): Maximum log lines (default: 1000)

**Response:**
```json
{
  "run_id": "uuid-string",
  "logs": [
    {
      "timestamp": "2024-01-15T10:00:05.123Z",
      "level": "INFO",
      "message": "Workflow fetch_catalog started"
    },
    {
      "timestamp": "2024-01-15T10:00:06.456Z",
      "level": "INFO",
      "message": "Fetching Confluence pages from space: MYSPACE"
    }
  ],
  "count": 42
}
```

## Artifacts

### List Run Artifacts

```http
GET /artifacts/run/{run_id}
```

**Parameters:**
- `run_id` (path): Workflow run UUID

**Response:**
```json
[
  {
    "id": "uuid-string",
    "run_id": "uuid-string",
    "filename": "test_cases_api.json",
    "content_type": "application/json",
    "size_bytes": 45632,
    "created_at": "2024-01-15T10:05:30Z",
    "download_url": "/api/artifacts/uuid-string/download"
  }
]
```

### Get Artifact Metadata

```http
GET /artifacts/{artifact_id}
```

**Parameters:**
- `artifact_id` (path): Artifact UUID

**Response:**
```json
{
  "id": "uuid-string",
  "run_id": "uuid-string",
  "filename": "test_cases_api.json",
  "content_type": "application/json",
  "size_bytes": 45632,
  "created_at": "2024-01-15T10:05:30Z",
  "download_url": "/api/artifacts/uuid-string/download"
}
```

### Download Artifact

```http
GET /artifacts/{artifact_id}/download
```

**Parameters:**
- `artifact_id` (path): Artifact UUID

**Response:** Binary file

## Health & Status

### Health Check

```http
GET /health
```

**Response:**
```json
{
  "status": "ok",
  "database": "ok",
  "redis": "ok",
  "integrations": {
    "azure_devops": "healthy",
    "confluence": "unconfigured",
    "jira": "unhealthy",
    "gemini": "healthy"
  }
}
```

### Application Status

```http
GET /status
```

**Response:**
```json
{
  "app": "Trace2Quality",
  "version": "0.1.0",
  "environment": "development",
  "debug": true
}
```

## Error Codes

| Code | Meaning |
|------|---------|
| 200 | OK - Request succeeded |
| 400 | Bad Request - Invalid parameters |
| 404 | Not Found - Resource not found |
| 500 | Internal Server Error - Unhandled exception |
| 503 | Service Unavailable - Redis or DB down |

## Rate Limiting

Not yet implemented. Future: per-endpoint limits.

## Versioning

API versioning via URL path is planned but not yet implemented.
Current API: v0.1.0 (subject to change)
