# Operations Guide - Trace2Quality

## Local Development Setup

### Prerequisites

- Docker & Docker Compose (or Python 3.11+ + Redis separately)
- Make (optional, for shortcuts)
- Git

### Quick Start (Docker)

```bash
# 1. Clone and navigate
cd /Users/abdulla/stuff/t2q

# 2. Copy environment
cp .env.example .env

# 3. Edit .env with your integration tokens
# vim .env

# 4. Start services
docker-compose up -d

# 5. Initialize database
docker-compose exec app alembic upgrade head

# 6. Open in browser
# http://localhost:8000/ui
```

### Manual Python Setup

```bash
# 1. Create virtual environment
python -m venv venv
source venv/bin/activate

# 2. Install dependencies
pip install -e ".[dev]"

# 3. Set up environment
export PYTHONPATH=/Users/abdulla/stuff/t2q
export $(cat .env | xargs)

# 4. Start Redis separately
redis-server

# 5. In terminal 1: FastAPI app
cd apps/app
uvicorn main:app --reload

# 6. In terminal 2: Celery worker
cd apps/worker
celery -A celery_app worker --loglevel=info
```

## Configuration

### Required Environment Variables

```bash
APP_ENCRYPTION_KEY=<strong-random-key-generate-with-python>
REDIS_URL=redis://localhost:6379/0
DATABASE_URL=sqlite:///./data/trace2quality.db
```

Generate a strong encryption key:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### Provider Configuration

Get tokens from each provider:

1. **Azure DevOps**
   - Go to https://dev.azure.com/{org}/_usersSettings/tokens
   - Create PAT with "Test management (read & write)" scope
   - Note: organization URL and project name

2. **Confluence Cloud**
   - Go to https://id.atlassian.com/manage-profile/security/api-tokens
   - Create API token
   - Note: base URL and space key

3. **Jira Cloud**
   - Go to https://id.atlassian.com/manage-profile/security/api-tokens
   - Create API token
   - Note: base URL and project key

4. **Google Gemini**
   - Go to https://makersuite.google.com/app/apikey
   - Create API key
   - Select model (e.g., `gemini-pro`)

## Running Workflows

### Via Web UI

1. Navigate to http://localhost:8000/ui
2. Go to **Integrations** tab
3. Configure each provider with tokens
4. Test connections
5. Go to **Workflows** tab
6. Select a workflow and click "Run"
7. Monitor execution in **Runs** tab

### Via REST API

```bash
# Trigger a workflow
curl -X POST http://localhost:8000/api/workflows/fetch_catalog/runs \
  -H "Content-Type: application/json" \
  -d '{
    "parameters": {
      "space": "YOURSPACE"
    },
    "dry_run": false
  }'

# Get run status
curl http://localhost:8000/api/runs/{run_id}

# Get logs
curl http://localhost:8000/api/runs/{run_id}/logs

# Download artifacts
curl http://localhost:8000/api/artifacts/{artifact_id}/download > output.json
```

### Via CLI (Future)

```bash
# Once CLI is implemented
python -m apps.worker.cli run-workflow --workflow fetch_catalog --dry-run
```

## Database Management

### Migrations

```bash
# Create a new migration
alembic revision --autogenerate -m "Add new field"

# Apply all pending migrations
alembic upgrade head

# Rollback one migration
alembic downgrade -1

# Show migration history
alembic history
```

### Backing Up Data

```bash
# SQLite
cp data/trace2quality.db data/trace2quality.db.backup.$(date +%s)

# PostgreSQL
pg_dump trace2quality > backup.sql
```

## Monitoring & Debugging

### Logs

```bash
# Docker Compose
docker-compose logs -f app
docker-compose logs -f worker
docker-compose logs -f redis

# Manual Python
# Logs appear in console

# Log levels
LOG_LEVEL=DEBUG  # Verbose
LOG_LEVEL=INFO   # Normal
LOG_LEVEL=ERROR  # Errors only
```

### Celery Monitoring (Optional)

```bash
# Install Flower (optional dashboard)
pip install flower

# Run Flower
celery -A apps.worker.celery_app flower

# Open http://localhost:5555
```

### Health Checks

```bash
# System health
curl http://localhost:8000/api/health

# Application status
curl http://localhost:8000/api/status

# Integration health
curl http://localhost:8000/api/integrations
```

## Troubleshooting

### "Connection refused" to Redis

**Cause**: Redis not running  
**Fix**: Start Redis (`docker-compose up redis` or `redis-server`)

### "Database is locked" (SQLite)

**Cause**: Multiple processes accessing SQLite simultaneously  
**Fix**: Use PostgreSQL for production, or ensure only one process at a time

### Integration test fails with 401

**Cause**: Invalid token or expired credentials  
**Fix**: Regenerate token from provider and update via UI

### Celery worker not picking up tasks

**Cause**: Worker not running or Redis connection issue  
**Fix**: Check Redis is running (`redis-cli ping`), restart worker

### High memory usage

**Cause**: Celery worker prefetch too high  
**Fix**: Adjust `worker_prefetch_multiplier` in `apps/worker/celery_app.py`

## Performance Tuning

### For High Volume Workflows

```python
# In apps/worker/celery_app.py
celery_app.conf.update(
    worker_prefetch_multiplier=4,      # Increase for more throughput
    worker_max_tasks_per_child=1000,   # Recycle workers to prevent memory leak
    task_time_limit=30 * 60,           # 30 min hard limit
)
```

### Database Connection Pooling

```python
# In apps/app/database.py
from sqlalchemy import create_engine
engine = create_engine(
    database_url,
    pool_size=20,
    max_overflow=40,
    pool_pre_ping=True,  # Verify connections are valid
)
```

### Caching External Data

- Workflow results are cached in `data/cache/`
- Cache TTL configurable per workflow
- Manual cache clear: `rm -rf data/cache/*`

## Production Deployment

### Prerequisites

- PostgreSQL 12+
- Redis 6+
- Python 3.11+
- SSL/TLS certificates

### Configuration

```bash
# Production .env
APP_ENV=production
APP_DEBUG=false
DATABASE_URL=postgresql://user:pass@db-host:5432/trace2quality
REDIS_URL=redis://redis-host:6379/0
APP_ENCRYPTION_KEY=<generate-strong-key>
APP_SECRET_KEY=<generate-strong-key>
```

### Deployment Options

1. **Docker Swarm**: Use docker-compose.yml with scale directive
2. **Kubernetes**: Convert docker-compose to Helm charts
3. **Cloud**: Deploy to AWS (ECS), Azure (Container Instances), GCP (Cloud Run)

### Scaling Workers

```bash
# Docker Compose: scale workers
docker-compose up -d --scale worker=3

# Kubernetes: scale replicas
kubectl scale deployment t2q-worker --replicas=3
```

## Backup & Recovery

### Regular Backups

```bash
#!/bin/bash
# backup.sh
BACKUP_DIR="./backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

mkdir -p $BACKUP_DIR

# Database
docker-compose exec -T db pg_dump trace2quality > $BACKUP_DIR/db_$TIMESTAMP.sql

# Files
tar -czf $BACKUP_DIR/artifacts_$TIMESTAMP.tar.gz data/artifacts/
tar -czf $BACKUP_DIR/cache_$TIMESTAMP.tar.gz data/cache/

echo "Backup complete: $BACKUP_DIR/"
```

### Recovery

```bash
# Restore database
psql trace2quality < backups/db_20240115_120000.sql

# Restore artifacts
tar -xzf backups/artifacts_20240115_120000.tar.gz

# Restart services
docker-compose restart app worker
```

## Support & Reporting Issues

- **Bugs**: Report via GitHub Issues
- **Questions**: Check FAQ or documentation
- **Security**: Report privately to security@trace2quality.local

---

**Last Updated**: May 2024  
**Version**: 0.1.0-alpha
