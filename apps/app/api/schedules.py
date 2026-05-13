"""Workflow scheduling API endpoints"""

from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from datetime import datetime

from packages.workflows.scheduler import (
    ScheduleFrequency,
    WorkflowSchedule,
    create_schedule,
    filter_schedules_due_now,
)
from packages.common import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/schedules", tags=["schedules"])

# In-memory storage for demo (replace with database in production)
_schedules: dict[str, WorkflowSchedule] = {}


@router.post("/")
async def create_workflow_schedule(
    workflow_key: str,
    frequency: str,
    parameters: dict = None,
    start_time: Optional[str] = None
):
    """Create a new workflow schedule"""
    try:
        if frequency.lower() not in [f.value for f in ScheduleFrequency]:
            raise ValueError(f"Invalid frequency: {frequency}")
        
        schedule = create_schedule(
            workflow_key=workflow_key,
            frequency=frequency,
            parameters=parameters or {},
            start_time=start_time
        )
        
        _schedules[schedule.schedule_id] = schedule
        
        logger.info(f"Created schedule: {schedule.schedule_id}")
        return {
            "schedule_id": schedule.schedule_id,
            "workflow_key": workflow_key,
            "frequency": frequency,
            "next_run": schedule.next_run,
            "created_at": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Error creating schedule: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/")
async def list_schedules(active_only: bool = Query(False)):
    """List all workflow schedules"""
    try:
        schedules = list(_schedules.values())
        
        if active_only:
            schedules = [s for s in schedules if s.active]
        
        return {
            "schedules": [s.to_dict() for s in schedules],
            "total": len(schedules),
            "active_count": sum(1 for s in schedules if s.active)
        }
    except Exception as e:
        logger.error(f"Error listing schedules: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{schedule_id}")
async def get_schedule(schedule_id: str):
    """Get schedule details"""
    schedule = _schedules.get(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail=f"Schedule not found: {schedule_id}")
    
    return schedule.to_dict()


@router.put("/{schedule_id}")
async def update_schedule(
    schedule_id: str,
    active: Optional[bool] = None,
    parameters: Optional[dict] = None
):
    """Update a schedule"""
    schedule = _schedules.get(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail=f"Schedule not found: {schedule_id}")
    
    if active is not None:
        schedule.active = active
    
    if parameters is not None:
        schedule.parameters = parameters
    
    logger.info(f"Updated schedule: {schedule_id}")
    return schedule.to_dict()


@router.delete("/{schedule_id}")
async def delete_schedule(schedule_id: str):
    """Delete a schedule"""
    if schedule_id not in _schedules:
        raise HTTPException(status_code=404, detail=f"Schedule not found: {schedule_id}")
    
    del _schedules[schedule_id]
    logger.info(f"Deleted schedule: {schedule_id}")
    return {"status": "deleted", "schedule_id": schedule_id}


@router.get("/{schedule_id}/runs")
async def get_schedule_run_history(schedule_id: str, limit: int = Query(10)):
    """Get execution history for a schedule"""
    schedule = _schedules.get(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail=f"Schedule not found: {schedule_id}")
    
    return {
        "schedule_id": schedule_id,
        "workflow_key": schedule.workflow_key,
        "run_count": schedule.run_count,
        "failure_count": schedule.failure_count,
        "last_run": schedule.last_run,
        "next_run": schedule.next_run if schedule.active else None,
        "success_rate": ((schedule.run_count - schedule.failure_count) / schedule.run_count * 100) if schedule.run_count > 0 else 0.0
    }


__all__ = ["router"]
