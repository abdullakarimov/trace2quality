"""Workflow API endpoints"""

from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from apps.app.database import WorkflowRunModel, get_session_factory
from apps.app.config import get_settings
from apps.app.workflows import enqueue_workflow
from packages.common import (
    UpdateCoverageRunRequest,
    WorkflowRunCreate,
    WorkflowType,
    get_logger,
)

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
        WorkflowType(workflow_key)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown workflow: {workflow_key}")

    # Create run record
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

    queue_info = enqueue_workflow(run_id, workflow_key)

    return {
        "run_id": run_id,
        "status": "queued",
        "workflow_key": workflow_key,
        "queue": queue_info.get("queue"),
        "task_id": queue_info.get("task_id"),
        "created_at": datetime.utcnow().isoformat(),
    }


@router.post("/update-coverage-pages/runs")
async def create_update_coverage_run(
    payload: UpdateCoverageRunRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """Create update_coverage run via stable JSON API contract."""
    correlation_id = getattr(request.state, "correlation_id", None)

    run_id = str(uuid4())
    accepted_params = payload.model_dump()

    run = WorkflowRunModel(
        id=run_id,
        workflow_key="update_coverage",
        parameters=accepted_params,
        dry_run="0" if payload.apply else "1",
        status="queued",
    )
    db.add(run)
    db.commit()

    queue_info = enqueue_workflow(run_id, "update_coverage")

    logger.info(
        "Created update_coverage run",
        correlation_id=correlation_id,
        extra={"run_id": run_id, "mode": payload.mode},
    )

    return {
        "run_id": run_id,
        "workflow_key": "update_coverage",
        "status": "queued",
        "accepted_parameters": accepted_params,
        "queue": queue_info.get("queue"),
        "task_id": queue_info.get("task_id"),
        "created_at": datetime.utcnow().isoformat(),
    }
