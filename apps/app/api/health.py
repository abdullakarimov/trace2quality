"""Health and system status API endpoints"""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from redis import Redis

from apps.app.config import get_settings
from apps.app.database import get_session_factory
from packages.common import get_logger

logger = get_logger(__name__)

router = APIRouter()


def get_db(request: Request) -> Session:
    """Get database session"""
    settings = get_settings()
    SessionLocal = get_session_factory(settings.database_url)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@router.get("/health")
async def health_check(db: Session = Depends(get_db)) -> dict:
    """System health status"""
    settings = get_settings()
    health_status = {
        "status": "ok",
        "database": "error",
        "redis": "error",
        "integrations": {},
    }

    # Check database
    try:
        from sqlalchemy import text
        db.execute(text("SELECT 1"))
        health_status["database"] = "ok"
    except Exception as e:
        logger.error(f"Database health check failed: {str(e)}")
        health_status["status"] = "degraded"

    # Check Redis
    try:
        redis_client = Redis.from_url(settings.redis_url)
        redis_client.ping()
        health_status["redis"] = "ok"
    except Exception as e:
        logger.error(f"Redis health check failed: {str(e)}")
        health_status["status"] = "degraded"

    # Check integrations (basic status from DB)
    from apps.app.database import IntegrationConfigModel
    integrations = db.query(IntegrationConfigModel).all()
    for integration in integrations:
        health_status["integrations"][integration.type.value] = integration.status

    return health_status


@router.get("/status")
async def status() -> dict:
    """Application status and version"""
    settings = get_settings()
    return {
        "app": "Trace2Quality",
        "version": "0.1.0",
        "environment": settings.app_env,
        "debug": settings.app_debug,
    }
