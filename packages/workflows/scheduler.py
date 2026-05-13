"""Workflow scheduling and triggers"""

from typing import Any, Optional
from datetime import datetime, timedelta
from enum import Enum
import json

from packages.common import get_logger

logger = get_logger(__name__)


class ScheduleFrequency(str, Enum):
    """Workflow schedule frequency options"""
    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    ONCE = "once"


class WorkflowSchedule:
    """Represents a scheduled workflow execution"""

    def __init__(
        self,
        schedule_id: str,
        workflow_key: str,
        frequency: ScheduleFrequency,
        parameters: dict[str, Any],
        start_time: Optional[str] = None,
        active: bool = True
    ):
        self.schedule_id = schedule_id
        self.workflow_key = workflow_key
        self.frequency = frequency
        self.parameters = parameters
        self.start_time = start_time or datetime.utcnow().isoformat()
        self.active = active
        self.last_run: Optional[str] = None
        self.next_run: Optional[str] = self._calculate_next_run()
        self.run_count = 0
        self.failure_count = 0

    def _calculate_next_run(self) -> str:
        """Calculate next execution time based on frequency"""
        start = datetime.fromisoformat(self.start_time) if isinstance(self.start_time, str) else self.start_time
        
        if self.frequency == ScheduleFrequency.HOURLY:
            next_run = start + timedelta(hours=1)
        elif self.frequency == ScheduleFrequency.DAILY:
            next_run = start + timedelta(days=1)
        elif self.frequency == ScheduleFrequency.WEEKLY:
            next_run = start + timedelta(weeks=1)
        elif self.frequency == ScheduleFrequency.MONTHLY:
            # Simple month approximation
            next_run = start + timedelta(days=30)
        else:  # ONCE
            next_run = start
        
        return next_run.isoformat()

    def is_due(self) -> bool:
        """Check if workflow is due to run"""
        if not self.active:
            return False
        
        if self.frequency == ScheduleFrequency.ONCE and self.last_run:
            return False
        
        next_run_time = datetime.fromisoformat(self.next_run)
        return datetime.utcnow() >= next_run_time

    def mark_executed(self, success: bool = True):
        """Mark workflow as executed"""
        self.last_run = datetime.utcnow().isoformat()
        self.run_count += 1
        
        if not success:
            self.failure_count += 1
        
        if self.frequency != ScheduleFrequency.ONCE:
            self.next_run = self._calculate_next_run()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation"""
        return {
            "schedule_id": self.schedule_id,
            "workflow_key": self.workflow_key,
            "frequency": self.frequency.value,
            "parameters": self.parameters,
            "start_time": self.start_time,
            "active": self.active,
            "last_run": self.last_run,
            "next_run": self.next_run,
            "run_count": self.run_count,
            "failure_count": self.failure_count,
        }


class WebhookEvent:
    """Represents a webhook event for workflow triggering"""

    def __init__(
        self,
        event_type: str,
        workflow_key: str,
        trigger_data: dict[str, Any],
        event_id: Optional[str] = None
    ):
        self.event_id = event_id or self._generate_id()
        self.event_type = event_type
        self.workflow_key = workflow_key
        self.trigger_data = trigger_data
        self.created_at = datetime.utcnow().isoformat()
        self.processed = False

    @staticmethod
    def _generate_id() -> str:
        """Generate unique event ID"""
        import uuid
        return str(uuid.uuid4())

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation"""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "workflow_key": self.workflow_key,
            "trigger_data": self.trigger_data,
            "created_at": self.created_at,
            "processed": self.processed,
        }


def create_schedule(
    workflow_key: str,
    frequency: str,
    parameters: dict[str, Any],
    start_time: Optional[str] = None
) -> WorkflowSchedule:
    """Create a new workflow schedule"""
    import uuid
    
    schedule_id = str(uuid.uuid4())
    freq = ScheduleFrequency(frequency.lower())
    
    schedule = WorkflowSchedule(
        schedule_id=schedule_id,
        workflow_key=workflow_key,
        frequency=freq,
        parameters=parameters,
        start_time=start_time or datetime.utcnow().isoformat(),
        active=True
    )
    
    logger.info(f"Created schedule {schedule_id} for workflow {workflow_key}")
    return schedule


def create_webhook_event(
    event_type: str,
    workflow_key: str,
    trigger_data: dict[str, Any]
) -> WebhookEvent:
    """Create a webhook event"""
    event = WebhookEvent(
        event_type=event_type,
        workflow_key=workflow_key,
        trigger_data=trigger_data
    )
    
    logger.info(f"Created webhook event {event.event_id} for workflow {workflow_key}")
    return event


def filter_schedules_due_now(schedules: list[WorkflowSchedule]) -> list[WorkflowSchedule]:
    """Filter schedules that are due to run"""
    due_schedules = []
    
    for schedule in schedules:
        if schedule.is_due():
            due_schedules.append(schedule)
            logger.debug(f"Schedule {schedule.schedule_id} is due for execution")
    
    return due_schedules


__all__ = [
    "ScheduleFrequency",
    "WorkflowSchedule",
    "WebhookEvent",
    "create_schedule",
    "create_webhook_event",
    "filter_schedules_due_now",
]
