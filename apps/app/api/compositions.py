"""Workflow composition API endpoints"""

from typing import Optional
from fastapi import APIRouter, HTTPException
from datetime import datetime

from packages.workflows.composition import (
    WorkflowCompositionType,
    WorkflowComposition,
    ComposedWorkflowExecution,
    create_sequential_composition,
    create_parallel_composition,
    create_chained_composition,
    create_full_qa_cycle_composition,
    create_quality_gate_composition,
)
from packages.common import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/compositions", tags=["compositions"])

# In-memory storage for demo (replace with database in production)
_compositions: dict[str, WorkflowComposition] = {}
_executions: dict[str, ComposedWorkflowExecution] = {}


@router.post("/")
async def create_workflow_composition(
    name: str,
    composition_type: str,
    workflows: list[dict]
):
    """Create a new workflow composition"""
    try:
        if composition_type.lower() not in [t.value for t in WorkflowCompositionType]:
            raise ValueError(f"Invalid composition type: {composition_type}")
        
        comp_type = WorkflowCompositionType(composition_type.lower())
        
        composition = WorkflowComposition(
            composition_id="",
            name=name,
            composition_type=comp_type,
            workflows=workflows
        )
        
        # Generate ID
        import uuid
        composition.composition_id = str(uuid.uuid4())
        
        valid, error = composition.validate()
        if not valid:
            raise ValueError(error)
        
        _compositions[composition.composition_id] = composition
        logger.info(f"Created composition: {composition.composition_id}")
        
        return {
            "composition_id": composition.composition_id,
            "name": name,
            "composition_type": composition_type,
            "workflows_count": len(workflows),
            "created_at": composition.created_at
        }
    except Exception as e:
        logger.error(f"Error creating composition: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/")
async def list_compositions():
    """List all workflow compositions"""
    compositions = list(_compositions.values())
    
    return {
        "compositions": [c.to_dict() for c in compositions],
        "total": len(compositions)
    }


@router.get("/{composition_id}")
async def get_composition(composition_id: str):
    """Get composition details"""
    composition = _compositions.get(composition_id)
    if not composition:
        raise HTTPException(status_code=404, detail=f"Composition not found: {composition_id}")
    
    return composition.to_dict()


@router.post("/templates/qa-cycle")
async def create_qa_cycle_template(project: str):
    """Create a full QA cycle composition (template)"""
    try:
        composition = create_full_qa_cycle_composition(project)
        _compositions[composition.composition_id] = composition
        
        logger.info(f"Created QA cycle template: {composition.composition_id}")
        return {
            "composition_id": composition.composition_id,
            "name": composition.name,
            "composition_type": composition.composition_type.value,
            "workflows": [w["workflow_key"] for w in composition.workflows],
            "created_at": composition.created_at
        }
    except Exception as e:
        logger.error(f"Error creating QA cycle template: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/templates/quality-gate")
async def create_quality_gate_template(project: str):
    """Create a quality gate composition (template)"""
    try:
        composition = create_quality_gate_composition(project)
        _compositions[composition.composition_id] = composition
        
        logger.info(f"Created quality gate template: {composition.composition_id}")
        return {
            "composition_id": composition.composition_id,
            "name": composition.name,
            "composition_type": composition.composition_type.value,
            "workflows": [w["workflow_key"] for w in composition.workflows],
            "created_at": composition.created_at
        }
    except Exception as e:
        logger.error(f"Error creating quality gate template: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{composition_id}/execute")
async def execute_composition(composition_id: str):
    """Execute a workflow composition"""
    composition = _compositions.get(composition_id)
    if not composition:
        raise HTTPException(status_code=404, detail=f"Composition not found: {composition_id}")
    
    try:
        import uuid
        execution_id = str(uuid.uuid4())
        
        execution = ComposedWorkflowExecution(
            execution_id=execution_id,
            composition_id=composition_id,
            composition_type=composition.composition_type
        )
        
        _executions[execution_id] = execution
        
        logger.info(f"Started composition execution: {execution_id}")
        
        # In a real implementation, this would submit workflows to Celery
        # based on composition_type (sequential, parallel, chained, conditional)
        
        return {
            "execution_id": execution_id,
            "composition_id": composition_id,
            "composition_type": composition.composition_type.value,
            "status": "queued",
            "started_at": execution.started_at
        }
    except Exception as e:
        logger.error(f"Error executing composition: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/executions/{execution_id}")
async def get_execution_status(execution_id: str):
    """Get execution status and results"""
    execution = _executions.get(execution_id)
    if not execution:
        raise HTTPException(status_code=404, detail=f"Execution not found: {execution_id}")
    
    return execution.to_dict()


@router.get("/{composition_id}/executions")
async def list_executions(composition_id: str, limit: int = 10):
    """List execution history for a composition"""
    composition = _compositions.get(composition_id)
    if not composition:
        raise HTTPException(status_code=404, detail=f"Composition not found: {composition_id}")
    
    executions = [
        e for e in _executions.values()
        if e.composition_id == composition_id
    ]
    
    # Sort by started_at descending
    executions = sorted(
        executions,
        key=lambda e: e.started_at,
        reverse=True
    )[:limit]
    
    return {
        "composition_id": composition_id,
        "executions": [e.to_dict() for e in executions],
        "total": len(executions)
    }


@router.get("/executions")
async def list_all_executions(limit: int = 100):
    """List recent composition executions"""
    executions = sorted(
        _executions.values(),
        key=lambda e: e.started_at,
        reverse=True
    )[:limit]
    
    return {
        "executions": [e.to_dict() for e in executions],
        "total": len(_executions),
        "recent_count": len(executions),
        "success_count": sum(1 for e in executions if e.status == "succeeded"),
        "failed_count": sum(1 for e in executions if e.status == "failed")
    }


__all__ = ["router"]
