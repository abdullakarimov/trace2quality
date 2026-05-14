"""Workflow API endpoints"""

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from apps.app.config import get_settings
from apps.app.database import ArtifactModel, WorkflowRunModel, get_session_factory
from apps.app.workflows import _resolve_integration_config, enqueue_workflow
from packages.common import (
    IntegrationType,
    TriageBugTicketsRunRequest,
    UpdateCoverageRunRequest,
    WorkflowRunCreate,
    WorkflowType,
    get_logger,
)
from packages.integrations import integration_registry
from packages.workflows import triage as triage_workflow

logger = get_logger(__name__)

router = APIRouter()

HIDDEN_WEBAPP_WORKFLOW_KEYS = {
    "fetch_catalog",
    "generate_api_tests",
    "generate_ui_tests",
    "associate_automation",
    "generate_report",
}


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
        if workflow.value in HIDDEN_WEBAPP_WORKFLOW_KEYS:
            continue
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


@router.post("/triage-bugs/runs")
async def create_triage_bugs_run(
    payload: TriageBugTicketsRunRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """Create a triage_bugs run via stable JSON API contract.

    When `apply` is False (default) the workflow runs in dry-run mode: it
    evaluates every bug and reports what it would do but makes no changes to Jira.
    Set `apply: true` to actually update severity/impact fields, transition issues,
    and add triage comments.
    """
    correlation_id = getattr(request.state, "correlation_id", None)

    run_id = str(uuid4())
    accepted_params = payload.model_dump()

    run = WorkflowRunModel(
        id=run_id,
        workflow_key="triage_bugs",
        parameters=accepted_params,
        dry_run="0" if payload.apply else "1",
        status="queued",
    )
    db.add(run)
    db.commit()

    queue_info = enqueue_workflow(run_id, "triage_bugs")

    logger.info(
        "Created triage_bugs run",
        correlation_id=correlation_id,
        extra={"run_id": run_id, "apply": payload.apply, "max_results": payload.max_results},
    )

    return {
        "run_id": run_id,
        "workflow_key": "triage_bugs",
        "status": "queued",
        "accepted_parameters": accepted_params,
        "queue": queue_info.get("queue"),
        "task_id": queue_info.get("task_id"),
        "created_at": datetime.utcnow().isoformat(),
    }


# ── Selective apply for dry-run triage results ────────────────────────────────

class _ApplyIssuesRequest(BaseModel):
    run_id: str
    issue_keys: list[str] | None = None  # None / empty = apply all real-bug rows


@router.post("/triage-bugs/apply-issues")
async def apply_triage_issues(
    payload: _ApplyIssuesRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """Apply triage results (severity/impact/priority/transition/comment) to specific Jira issues
    from an existing dry-run.  If ``issue_keys`` is omitted every row where
    ``is_real_bug=true`` is applied.
    """
    # ── 1. Validate the source run ────────────────────────────────────────────
    run = db.query(WorkflowRunModel).filter(WorkflowRunModel.id == payload.run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail=f"Run not found: {payload.run_id}")
    if run.workflow_key != "triage_bugs":
        raise HTTPException(status_code=400, detail="Run is not a triage_bugs run")

    # ── 2. Load per_issue_results artifact ────────────────────────────────────
    artifact = (
        db.query(ArtifactModel)
        .filter(ArtifactModel.run_id == payload.run_id, ArtifactModel.filename == "per_issue_results.json")
        .first()
    )
    if not artifact:
        raise HTTPException(status_code=404, detail="per_issue_results.json artifact not found for this run")

    settings = get_settings()
    artifact_path = Path(settings.artifact_storage_path) / artifact.storage_path
    if not artifact_path.exists():
        raise HTTPException(status_code=404, detail="Artifact file missing from storage")

    per_issue_results: list[dict] = json.loads(artifact_path.read_text(encoding="utf-8"))

    # ── 3. Filter to requested issues ─────────────────────────────────────────
    requested_keys: set[str] = set(payload.issue_keys or [])
    rows_to_apply = [
        row for row in per_issue_results
        if row.get("is_real_bug")
        and (not requested_keys or str(row.get("key")) in requested_keys)
    ]

    if not rows_to_apply:
        return {"applied": [], "skipped": [], "errors": [], "message": "No matching real-bug rows to apply"}

    # ── 4. Recover workflow parameters from the source run ────────────────────
    params: dict = (
        run.parameters if isinstance(run.parameters, dict)
        else json.loads(run.parameters or "{}")
    )
    severity_field_id = str(params.get("severity_field_id") or triage_workflow.DEFAULT_SEVERITY_FIELD_ID)
    impact_field_id = str(params.get("impact_field_id") or triage_workflow.DEFAULT_IMPACT_FIELD_ID)
    target_status = str(params.get("target_status") or triage_workflow.DEFAULT_TARGET_STATUS)

    # ── 5. Build Jira client ───────────────────────────────────────────────────
    jira_client = integration_registry.get_client(
        IntegrationType.JIRA, _resolve_integration_config(db, IntegrationType.JIRA)
    )

    # ── 6. Apply each issue ───────────────────────────────────────────────────
    applied: list[str] = []
    skipped: list[str] = []
    errors: list[dict] = []

    async def _apply_one(row: dict) -> None:
        key = str(row.get("key") or "")
        severity = str(row.get("severity") or "Major")
        impact = str(row.get("impact") or "Moderate / Limited")
        priority = str(row.get("priority") or "Medium")
        reasoning = str(row.get("reasoning") or "")

        try:
            await jira_client.update_issue(
                key,
                {
                    "fields": {
                        severity_field_id: {"value": severity},
                        impact_field_id: {"value": impact},
                        "priority": {"name": priority},
                    }
                },
            )
            await jira_client.transition_issue(key, target_status)
            comment_text = (
                f"Triaged by automated system:\n"
                f"- Severity: {severity}\n"
                f"- Impact: {impact}\n"
                f"- Priority: {priority}\n"
                f"- Reason: {reasoning}"
            )
            await jira_client.add_comment(key, comment_text)
            applied.append(key)
        except Exception as exc:
            errors.append({"key": key, "error": str(exc)})

    try:
        await asyncio.gather(*[_apply_one(row) for row in rows_to_apply])
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Apply failed: {exc}")

    not_real = [
        str(row.get("key")) for row in per_issue_results
        if not row.get("is_real_bug") and (not requested_keys or str(row.get("key")) in requested_keys)
    ]
    skipped.extend(not_real)

    return {
        "applied": applied,
        "skipped": skipped,
        "errors": errors,
        "applied_count": len(applied),
        "error_count": len(errors),
    }
