"""Trace2Quality Common Models and Types"""

from datetime import datetime
from enum import Enum
import re
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator


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
    workflow_key: Optional[WorkflowType] = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    dry_run: bool = False
    force: bool = False


class UpdateCoverageRunRequest(BaseModel):
    """Request payload for update_coverage_pages workflow."""

    mode: Literal["single", "all_mapped", "all_missing"]
    us_code: Optional[str] = None
    apply: bool = False
    force: bool = False
    batch_delay_seconds: int = Field(default=3, ge=0, le=30)
    max_items: Optional[int] = None
    fail_fast: bool = False
    include_debug_artifacts: bool = True
    use_cached_azure_snapshot: bool = False
    preview_run_id: Optional[str] = None

    @model_validator(mode="after")
    def validate_mode_us_code(self):
        """Validate mode/us_code constraints and max_items semantics."""
        us_pattern = r"^US-[0-9]+(\.[0-9]+)*$"

        if self.mode == "single" and not self.preview_run_id:
            if not self.us_code:
                raise ValueError("us_code is required when mode=single")
            if not re.match(us_pattern, self.us_code):
                raise ValueError(
                    "us_code must match pattern ^US-[0-9]+(\\.[0-9]+)*$"
                )
        elif self.mode != "single":
            if self.us_code:
                raise ValueError("us_code is only allowed when mode=single")

        if self.max_items is not None and self.max_items <= 0:
            raise ValueError("max_items must be > 0 when provided")

        return self


class TriageBugTicketsRunRequest(BaseModel):
    """Request payload for triage_bugs workflow."""

    jql: str = Field(
        default='issuetype in ("BE BUG", "Mobile bug", Bug, "FE bug") AND status = Backlog',
        description="JQL query selecting bug issues to triage",
    )
    max_results: int = Field(default=50, ge=1, le=500, description="Maximum bugs to process")
    apply: bool = Field(default=False, description="When False, runs in dry-run mode without modifying Jira")
    add_comment: bool = Field(
        default=False,
        description="When True and apply=True, add triage reasoning comments to Jira issues",
    )
    severity_field_id: str = Field(
        default="customfield_10865", description="Jira custom field ID for Severity"
    )
    impact_field_id: str = Field(
        default="customfield_10004", description="Jira custom field ID for Impact"
    )
    target_status: str = Field(
        default="Triage", description="Jira status name to transition confirmed bugs into"
    )
    batch_delay_seconds: int = Field(
        default=10, ge=0, le=60, description="Seconds to wait between Gemini API calls"
    )


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
