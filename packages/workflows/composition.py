"""Workflow composition and chaining"""

from typing import Any, Callable, Optional
from datetime import datetime
from enum import Enum

from packages.common import get_logger

logger = get_logger(__name__)


class WorkflowCompositionType(str, Enum):
    """Types of workflow composition"""
    SEQUENTIAL = "sequential"      # Run workflows one after another
    PARALLEL = "parallel"          # Run workflows in parallel
    CONDITIONAL = "conditional"    # Run based on conditions
    CHAINED = "chained"           # Pass output of one as input to next


class WorkflowComposition:
    """Compose multiple workflows into a single execution unit"""

    def __init__(
        self,
        composition_id: str,
        name: str,
        composition_type: WorkflowCompositionType,
        workflows: list[dict[str, Any]]
    ):
        self.composition_id = composition_id
        self.name = name
        self.composition_type = composition_type
        self.workflows = workflows
        self.created_at = datetime.utcnow().isoformat()

    def validate(self) -> tuple[bool, Optional[str]]:
        """Validate composition configuration"""
        if not self.workflows:
            return False, "At least one workflow required"
        
        for i, workflow in enumerate(self.workflows):
            if "workflow_key" not in workflow:
                return False, f"Workflow {i} missing workflow_key"
            
            if "parameters" not in workflow:
                workflow["parameters"] = {}
        
        return True, None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation"""
        return {
            "composition_id": self.composition_id,
            "name": self.name,
            "composition_type": self.composition_type.value,
            "workflows": self.workflows,
            "created_at": self.created_at,
        }


class ComposedWorkflowExecution:
    """Tracks execution of a composed workflow"""

    def __init__(
        self,
        execution_id: str,
        composition_id: str,
        composition_type: WorkflowCompositionType
    ):
        self.execution_id = execution_id
        self.composition_id = composition_id
        self.composition_type = composition_type
        self.started_at = datetime.utcnow().isoformat()
        self.completed_at: Optional[str] = None
        self.status = "running"  # running, succeeded, failed, partial
        self.workflow_results: list[dict[str, Any]] = []
        self.error_message: Optional[str] = None

    def add_result(
        self,
        workflow_key: str,
        run_id: str,
        status: str,
        output: dict[str, Any]
    ):
        """Add result from executed workflow"""
        self.workflow_results.append({
            "workflow_key": workflow_key,
            "run_id": run_id,
            "status": status,
            "output": output,
            "timestamp": datetime.utcnow().isoformat(),
        })

    def mark_complete(self, status: str, error_message: Optional[str] = None):
        """Mark execution as complete"""
        self.completed_at = datetime.utcnow().isoformat()
        self.status = status
        self.error_message = error_message
        logger.info(f"Composition execution {self.execution_id} completed with status {status}")

    def get_duration(self) -> float:
        """Get execution duration in seconds"""
        if not self.completed_at:
            return 0.0
        
        start = datetime.fromisoformat(self.started_at)
        end = datetime.fromisoformat(self.completed_at)
        return (end - start).total_seconds()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation"""
        return {
            "execution_id": self.execution_id,
            "composition_id": self.composition_id,
            "composition_type": self.composition_type.value,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "status": self.status,
            "duration_seconds": self.get_duration(),
            "workflow_results": self.workflow_results,
            "error_message": self.error_message,
        }


def create_composition(
    name: str,
    composition_type: str,
    workflows: list[dict[str, Any]]
) -> WorkflowComposition:
    """Create a new workflow composition"""
    import uuid
    
    composition_id = str(uuid.uuid4())
    comp_type = WorkflowCompositionType(composition_type.lower())
    
    composition = WorkflowComposition(
        composition_id=composition_id,
        name=name,
        composition_type=comp_type,
        workflows=workflows
    )
    
    valid, error = composition.validate()
    if not valid:
        raise ValueError(f"Invalid composition: {error}")
    
    logger.info(f"Created composition {composition_id}: {name}")
    return composition


def create_sequential_composition(
    name: str,
    workflow_configs: list[dict[str, Any]]
) -> WorkflowComposition:
    """Create a sequential composition (workflows run one after another)"""
    return create_composition(name, "sequential", workflow_configs)


def create_parallel_composition(
    name: str,
    workflow_configs: list[dict[str, Any]]
) -> WorkflowComposition:
    """Create a parallel composition (workflows run concurrently)"""
    return create_composition(name, "parallel", workflow_configs)


def create_chained_composition(
    name: str,
    workflow_configs: list[dict[str, Any]]
) -> WorkflowComposition:
    """Create a chained composition (output of one feeds into next)"""
    return create_composition(name, "chained", workflow_configs)


def create_conditional_composition(
    name: str,
    workflow_configs: list[dict[str, Any]],
    conditions: dict[str, str]
) -> WorkflowComposition:
    """Create a conditional composition (workflows run based on conditions)"""
    for config, condition in zip(workflow_configs, conditions.values()):
        config["condition"] = condition
    
    return create_composition(name, "conditional", workflow_configs)


# Example compositions
def create_full_qa_cycle_composition(project: str) -> WorkflowComposition:
    """Create a full QA cycle: fetch specs → generate tests → run tests → report"""
    workflows = [
        {
            "workflow_key": "fetch_confluence",
            "order": 1,
            "parameters": {
                "confluence_space": project,
                "labels": ["requirements", "qa-ready"]
            }
        },
        {
            "workflow_key": "generate_tests",
            "order": 2,
            "parameters": {
                "project": project,
                "test_type": "api"
            }
        },
        {
            "workflow_key": "analyze_coverage",
            "order": 3,
            "parameters": {
                "project": project
            }
        },
        {
            "workflow_key": "update_coverage",
            "order": 4,
            "parameters": {
                "project": project
            }
        }
    ]
    
    return create_sequential_composition(f"Full QA Cycle - {project}", workflows)


def create_quality_gate_composition(project: str) -> WorkflowComposition:
    """Create quality gate: triage bugs → classify gaps → generate report"""
    workflows = [
        {
            "workflow_key": "triage_bugs",
            "order": 1,
            "parameters": {
                "project": project,
                "query": f'project="{project}" AND type=Bug AND resolution=Unresolved'
            }
        },
        {
            "workflow_key": "analyze_coverage",
            "order": 2,
            "parameters": {
                "project": project
            }
        },
        {
            "workflow_key": "generate_report",
            "order": 3,
            "parameters": {
                "project": project
            }
        }
    ]
    
    return create_sequential_composition(f"Quality Gate - {project}", workflows)


__all__ = [
    "WorkflowCompositionType",
    "WorkflowComposition",
    "ComposedWorkflowExecution",
    "create_composition",
    "create_sequential_composition",
    "create_parallel_composition",
    "create_chained_composition",
    "create_conditional_composition",
    "create_full_qa_cycle_composition",
    "create_quality_gate_composition",
]
