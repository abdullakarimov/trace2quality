"""Trace2Quality Common Models and Types"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class IntegrationType(str, Enum):
    """Supported integration providers"""
    AZURE_DEVOPS = "azure_devops"
    CONFLUENCE = "confluence"
    JIRA = "jira"
    GEMINI = "gemini"


class WorkflowType(str, Enum):
    """Workflow identifiers"""
    FETCH_CATALOG = "fetch_catalog"
    GENERATE_API_TESTS = "generate_api_tests"
    GENERATE_UI_TESTS = "generate_ui_tests"
    UPDATE_COVERAGE = "update_coverage"
    TRIAGE_BUGS = "triage_bugs"
    ASSOCIATE_AUTOMATION = "associate_automation"
    GENERATE_REPORT = "generate_report"


class RunStatus(str, Enum):
    """Workflow run status lifecycle"""
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


class IntegrationConnectionStatus(str, Enum):
    """Connection health status"""
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    UNCONFIGURED = "unconfigured"


# === Schemas for API ===


class IntegrationConfig(BaseModel):
    """Integration provider configuration"""
    type: IntegrationType
    org_url: Optional[str] = None
    space: Optional[str] = None
    email: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    is_configured: bool = False
    status: IntegrationConnectionStatus = IntegrationConnectionStatus.UNCONFIGURED
    last_tested: Optional[datetime] = None
    error_message: Optional[str] = None

    class Config:
        use_enum_values = True


class WorkflowParameter(BaseModel):
    """Parameters for a workflow execution"""
    key: str
    value: Any
    required: bool = False


class WorkflowRunCreate(BaseModel):
    """Request to create a workflow run"""
    workflow_key: WorkflowType
    parameters: dict[str, Any] = Field(default_factory=dict)
    dry_run: bool = False
    force: bool = False


class WorkflowRunResponse(BaseModel):
    """Workflow run response"""
    id: str
    workflow_key: WorkflowType
    status: RunStatus
    parameters: dict[str, Any]
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    log_lines: int = 0
    error_message: Optional[str] = None

    class Config:
        use_enum_values = True


class ArtifactResponse(BaseModel):
    """Artifact metadata"""
    id: str
    run_id: str
    filename: str
    content_type: str
    size_bytes: int
    created_at: datetime
    download_url: str


class HealthCheckResponse(BaseModel):
    """System health status"""
    status: str  # "ok" or "degraded"
    database: str  # "ok" or "error"
    redis: str  # "ok" or "error"
    integrations: dict[str, str]  # integration_name -> status


class ErrorResponse(BaseModel):
    """Standard error response"""
    error: str
    detail: Optional[str] = None
    correlation_id: Optional[str] = None
