"""Workflow API endpoints"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from apps.app.database import WorkflowRunModel, get_session_factory
from apps.app.config import get_settings
from packages.common import WorkflowRunCreate, WorkflowType, get_logger

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


@router.get("")
async def list_workflows() -> dict:
    """List available workflows"""
    workflows = []
    for workflow in WorkflowType:
        workflows.append({
            "key": workflow.value,
            "name": workflow.value.replace("_", " ").title(),
            "description": f"Workflow: {workflow.value}",
        })
    return {"workflows": workflows}


@router.post("/{workflow_key}/runs")
async def create_run(
    workflow_key: str, run_config: WorkflowRunCreate, request: Request, db: Session = Depends(get_db)
) -> dict:
    """Trigger a workflow execution"""
    correlation_id = getattr(request.state, "correlation_id", None)

    try:
        workflow_type = WorkflowType(workflow_key)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown workflow: {workflow_key}")

    # Create run record
    from uuid import uuid4
    from datetime import datetime

    run_id = str(uuid4())
    run = WorkflowRunModel(
        id=run_id,
        workflow_key=workflow_key,
        parameters=run_config.parameters,
        dry_run="1" if run_config.dry_run else "0",
        status="queued",
    )
    db.add(run)
    db.commit()

    logger.info(
        f"Created workflow run: {workflow_key}",
        correlation_id=correlation_id,
        extra={"run_id": run_id, "dry_run": run_config.dry_run},
    )

    # TODO: Queue job in Celery
    # celery_app.send_task(f"tasks.run_workflow", args=[run_id, workflow_key])

    return {
        "run_id": run_id,
        "status": "queued",
        "workflow_key": workflow_key,
        "created_at": datetime.utcnow().isoformat(),
    }
