"""Integration settings API endpoints"""

import ast
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from apps.app.database import IntegrationConfigModel, get_session_factory
from apps.app.config import get_settings
from packages.common import (
    ErrorResponse,
    IntegrationConfig,
    IntegrationConnectionStatus,
    IntegrationType,
    SecretEncryption,
    get_logger,
)
from packages.integrations import integration_registry

logger = get_logger(__name__)

router = APIRouter()


class DeleteTestCasesRequest(BaseModel):
    """Request body for deleting Azure DevOps test cases."""

    case_ids: list[str]
    org_url: Optional[str] = None
    project: Optional[str] = None
    pat: Optional[str] = None
    test_plan_id: Optional[str] = None


class ReassignTestCasesRequest(BaseModel):
    """Request body for re-assigning Azure DevOps test cases."""

    case_ids: list[str]
    assigned_to: str
    org_url: Optional[str] = None
    project: Optional[str] = None
    pat: Optional[str] = None


class AzureDevOpsOrphanTestCasesRequest(BaseModel):
    """Request body for Azure DevOps orphan Test Case discovery."""

    org_url: Optional[str] = None
    project: Optional[str] = None
    pat: Optional[str] = None
    test_plan_id: Optional[str] = None


def get_db(request: Request) -> Session:
    """Get database session"""
    settings = get_settings()
    SessionLocal = get_session_factory(settings.database_url)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _load_integration_config(config_record: IntegrationConfigModel) -> dict:
    """Decrypt and deserialize provider config from storage."""
    enc = SecretEncryption(get_settings().app_encryption_key)
    try:
        return ast.literal_eval(enc.decrypt(config_record.config_encrypted))
    except Exception:
        return {}


def _resolve_azure_devops_config(
    db: Session,
) -> tuple[dict, str]:
    """Resolve Azure DevOps config from the database or application settings."""
    return _resolve_azure_devops_config_with_overrides(db)


def _resolve_azure_devops_config_with_overrides(
    db: Session,
    org_url: Optional[str] = None,
    project: Optional[str] = None,
    pat: Optional[str] = None,
) -> tuple[dict, str]:
    """Resolve Azure DevOps config from explicit overrides, DB, or settings."""
    if org_url and project and pat:
        return (
            {
                "org_url": org_url,
                "project": project,
                "pat": pat,
            },
            "explicit",
        )

    config_record = db.query(IntegrationConfigModel).filter(
        IntegrationConfigModel.type == IntegrationType.AZURE_DEVOPS
    ).first()

    if config_record:
        config_data = _load_integration_config(config_record)
        if config_data:
            return config_data, "database"

    settings = get_settings()
    if settings.azure_devops_pat:
        return (
            {
                "org_url": settings.azure_devops_org_url,
                "project": settings.azure_devops_project,
                "pat": settings.azure_devops_pat,
            },
            "settings",
        )

    return {}, "missing"


@router.get("")
async def list_integrations(
    request: Request, db: Session = Depends(get_db)
) -> list[IntegrationConfig]:
    """List all configured integrations"""
    correlation_id = getattr(request.state, "correlation_id", None)

    configs = db.query(IntegrationConfigModel).all()
    result = []

    for config in configs:
        result.append(
            IntegrationConfig(
                type=config.type,
                is_configured=config.status != "unconfigured",
                status=IntegrationConnectionStatus(config.status),
                last_tested=config.last_tested,
                error_message=config.error_message,
            )
        )

    logger.info(f"Listed {len(result)} integration configs", correlation_id=correlation_id)
    return result


@router.post("/{integration_type}/test")
async def test_connection(
    integration_type: str, request: Request, db: Session = Depends(get_db)
) -> dict:
    """Test connection to an integration provider"""
    correlation_id = getattr(request.state, "correlation_id", None)

    try:
        provider_type = IntegrationType(integration_type)
    except ValueError:
        logger.warning(f"Invalid integration type: {integration_type}", correlation_id=correlation_id)
        raise HTTPException(status_code=400, detail=f"Invalid integration type: {integration_type}")

    config_record = db.query(IntegrationConfigModel).filter(
        IntegrationConfigModel.type == provider_type
    ).first()

    if not config_record:
        logger.warning(
            f"Integration config not found: {integration_type}", correlation_id=correlation_id
        )
        return {"success": False, "error": "Integration not configured"}

    # Decrypt and reconstruct config
    config_data = _load_integration_config(config_record)

    try:
        client = integration_registry.get_client(provider_type, config_data)
        success, error = await client.test_connection()

        # Update status in database
        config_record.status = "healthy" if success else "unhealthy"
        config_record.error_message = error
        from datetime import datetime
        config_record.last_tested = datetime.utcnow()
        db.commit()

        logger.info(
            f"Tested connection for {integration_type}: success={success}",
            correlation_id=correlation_id,
        )
        return {"success": success, "error": error}
    except Exception as e:
        logger.error(
            f"Failed to test connection for {integration_type}: {str(e)}",
            correlation_id=correlation_id,
        )
        raise HTTPException(status_code=500, detail=f"Failed to test connection: {str(e)}")


@router.put("/{integration_type}")
async def update_integration(
    integration_type: str, config: dict, request: Request, db: Session = Depends(get_db)
) -> dict:
    """Update integration configuration"""
    correlation_id = getattr(request.state, "correlation_id", None)

    try:
        provider_type = IntegrationType(integration_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid integration type: {integration_type}")

    enc = SecretEncryption(get_settings().app_encryption_key)

    config_record = db.query(IntegrationConfigModel).filter(
        IntegrationConfigModel.type == provider_type
    ).first()

    if not config_record:
        from uuid import uuid4
        config_record = IntegrationConfigModel(
            id=str(uuid4()),
            type=provider_type,
            status="unconfigured",
        )
        db.add(config_record)

    config_record.config_encrypted = enc.encrypt(str(config))
    config_record.status = "unconfigured"
    config_record.error_message = None

    db.commit()

    logger.info(f"Updated integration config: {integration_type}", correlation_id=correlation_id)
    return {"success": True, "message": f"Configuration updated for {integration_type}"}


@router.get("/{integration_type}")
async def get_integration(
    integration_type: str, request: Request, db: Session = Depends(get_db)
) -> dict:
    """Get integration configuration status (no secrets)"""
    correlation_id = getattr(request.state, "correlation_id", None)

    try:
        provider_type = IntegrationType(integration_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid integration type: {integration_type}")

    config_record = db.query(IntegrationConfigModel).filter(
        IntegrationConfigModel.type == provider_type
    ).first()

    if not config_record:
        return {
            "type": integration_type,
            "status": "unconfigured",
            "is_configured": False,
        }

    return {
        "type": integration_type,
        "status": config_record.status,
        "is_configured": config_record.status != "unconfigured",
        "last_tested": config_record.last_tested,
        "error_message": config_record.error_message,
    }


@router.get("/azure_devops/orphan-test-cases")
async def list_azure_devops_orphan_test_cases(
    request: Request,
    db: Session = Depends(get_db),
    org_url: Optional[str] = Query(None),
    project: Optional[str] = Query(None),
    pat: Optional[str] = Query(None),
    test_plan_id: Optional[str] = Query(None),
) -> dict:
    """List Azure DevOps Test Case work items that are not in any test suite."""
    correlation_id = getattr(request.state, "correlation_id", None)

    config_data, source = _resolve_azure_devops_config_with_overrides(
        db,
        org_url=org_url,
        project=project,
        pat=pat,
    )
    if not config_data:
        raise HTTPException(status_code=404, detail="Azure DevOps integration not configured")

    client = integration_registry.get_client(IntegrationType.AZURE_DEVOPS, config_data)

    result = await client.list_orphan_test_cases(test_plan_id=test_plan_id)
    if not result.get("success"):
        raise HTTPException(
            status_code=500,
            detail=result.get("error", "Failed to list orphan test cases"),
        )

    orphans = result.get("orphan_test_cases", [])
    logger.info(
        f"Found {len(orphans)} orphan Azure DevOps test cases",
        correlation_id=correlation_id,
    )
    return {
        "success": True,
        "source": source,
        "test_plan_id": test_plan_id,
        "count": len(orphans),
        "items": orphans,
        "summary": {
            "total_test_cases": result.get("total_test_cases", 0),
            "linked_test_cases": result.get("linked_test_cases", 0),
            "orphan_test_cases": len(orphans),
        },
    }


@router.delete("/azure_devops/orphan-test-cases")
async def delete_azure_devops_orphan_test_cases(
    payload: DeleteTestCasesRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """Delete selected Azure DevOps Test Case work items."""
    correlation_id = getattr(request.state, "correlation_id", None)

    if not payload.case_ids:
        raise HTTPException(status_code=400, detail="case_ids cannot be empty")

    config_data, source = _resolve_azure_devops_config_with_overrides(
        db,
        org_url=payload.org_url,
        project=payload.project,
        pat=payload.pat,
    )
    if not config_data:
        raise HTTPException(status_code=404, detail="Azure DevOps integration not configured")

    client = integration_registry.get_client(IntegrationType.AZURE_DEVOPS, config_data)

    result = await client.delete_test_cases(payload.case_ids)
    logger.info(
        "Deleted Azure DevOps test cases",
        correlation_id=correlation_id,
        extra={
            "requested_count": len(payload.case_ids),
            "deleted_count": result.get("deleted_count", 0),
            "failed_count": result.get("failed_count", 0),
        },
    )

    if not result.get("success") and not result.get("deleted"):
        http_status = result.get("http_status")
        error_msg = result.get("error", "Failed to delete test cases")
        if http_status == 403:
            raise HTTPException(
                status_code=403,
                detail=f"Azure DevOps permission denied: {error_msg}. Ensure your PAT has 'Delete test artifacts' permission.",
            )
        elif http_status == 401:
            raise HTTPException(status_code=401, detail="Azure DevOps authentication failed. Check your PAT.")
        raise HTTPException(status_code=500, detail=error_msg)

    result["source"] = source
    result["test_plan_id"] = payload.test_plan_id
    return result


@router.patch("/azure_devops/orphan-test-cases/reassign")
async def reassign_azure_devops_orphan_test_cases(
    payload: ReassignTestCasesRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """Re-assign selected Azure DevOps Test Case work items to a different user."""
    correlation_id = getattr(request.state, "correlation_id", None)

    if not payload.case_ids:
        raise HTTPException(status_code=400, detail="case_ids cannot be empty")
    if not payload.assigned_to or not payload.assigned_to.strip():
        raise HTTPException(status_code=400, detail="assigned_to cannot be empty")

    config_data, source = _resolve_azure_devops_config_with_overrides(
        db,
        org_url=payload.org_url,
        project=payload.project,
        pat=payload.pat,
    )
    if not config_data:
        raise HTTPException(status_code=404, detail="Azure DevOps integration not configured")

    client = integration_registry.get_client(IntegrationType.AZURE_DEVOPS, config_data)

    result = await client.reassign_test_cases(payload.case_ids, payload.assigned_to.strip())
    logger.info(
        "Reassigned Azure DevOps test cases",
        correlation_id=correlation_id,
        extra={
            "requested_count": len(payload.case_ids),
            "updated_count": result.get("updated_count", 0),
            "failed_count": result.get("failed_count", 0),
            "assigned_to": payload.assigned_to,
        },
    )

    if not result.get("success") and not result.get("updated"):
        http_status = result.get("http_status")
        error_msg = result.get("error", "Failed to re-assign test cases")
        if http_status == 403:
            raise HTTPException(
                status_code=403,
                detail=f"Azure DevOps permission denied: {error_msg}. Ensure your PAT has work item write permission.",
            )
        elif http_status == 401:
            raise HTTPException(status_code=401, detail="Azure DevOps authentication failed. Check your PAT.")
        raise HTTPException(status_code=500, detail=error_msg)

    result["source"] = source
    return result
