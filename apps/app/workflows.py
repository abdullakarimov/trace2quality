"""Workflow execution engine."""

import asyncio
import json
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from apps.app.config import get_settings
from apps.app.database import (
    ArtifactModel,
    IntegrationConfigModel,
    WorkflowRunLogModel,
    WorkflowRunModel,
    get_session_factory,
)
from packages.common import IntegrationType, SecretEncryption, get_logger
from packages.integrations import integration_registry
from packages.workflows import catalog, coverage, generation, reporting, triage

logger = get_logger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _load_config_from_record(record: IntegrationConfigModel) -> dict:
    enc = SecretEncryption(get_settings().app_encryption_key)
    try:
        return json.loads(enc.decrypt(record.config_encrypted).replace("'", '"'))
    except Exception:
        try:
            import ast

            return ast.literal_eval(enc.decrypt(record.config_encrypted))
        except Exception:
            return {}


def _resolve_integration_config(session, provider_type: IntegrationType) -> dict:
    record = (
        session.query(IntegrationConfigModel)
        .filter(IntegrationConfigModel.type == provider_type)
        .first()
    )
    loaded: dict = {}
    if record:
        loaded = _load_config_from_record(record) or {}

    settings = get_settings()
    if provider_type == IntegrationType.CONFLUENCE:
        if loaded:
            return {
                "base_url": loaded.get("base_url") or settings.confluence_base_url,
                "space": loaded.get("space") or settings.confluence_space,
                "email": loaded.get("email") or settings.confluence_email,
                "api_token": loaded.get("api_token") or settings.confluence_api_token,
            }
        return {
            "base_url": settings.confluence_base_url,
            "space": settings.confluence_space,
            "email": settings.confluence_email,
            "api_token": settings.confluence_api_token,
        }
    if provider_type == IntegrationType.AZURE_DEVOPS:
        org_url = str(loaded.get("org_url") or settings.azure_devops_org_url).rstrip("/")
        project = str(loaded.get("project") or settings.azure_devops_project).strip()
        pat = loaded.get("pat") or settings.azure_devops_pat

        settings_org = settings.azure_devops_org_url.rstrip("/")
        parsed = urlparse(org_url if "://" in org_url else f"https://{org_url}")
        settings_parsed = urlparse(settings_org if "://" in settings_org else f"https://{settings_org}") if settings_org else None

        # If org_url is just the host (no org segment), prefer configured settings org URL.
        if parsed.path.strip("/") == "" and settings_org:
            org_url = settings_org

        if (
            settings_org
            and parsed.netloc == settings_parsed.netloc
            and org_url.endswith(f"/{project}")
            and not settings_org.endswith(f"/{project}")
        ):
            # Repair common misconfiguration where org_url mistakenly contains project segment.
            org_url = settings_org

        return {
            "org_url": org_url,
            "project": project,
            "pat": pat,
        }
    if provider_type == IntegrationType.JIRA:
        if loaded:
            return {
                "base_url": loaded.get("base_url") or settings.jira_base_url,
                "email": loaded.get("email") or settings.jira_email,
                "api_token": loaded.get("api_token") or settings.jira_api_token,
            }
        return {
            "base_url": settings.jira_base_url,
            "email": settings.jira_email,
            "api_token": settings.jira_api_token,
        }
    if provider_type == IntegrationType.GEMINI:
        if loaded:
            return {
                "api_key": loaded.get("api_key") or settings.gemini_api_key,
                "model": loaded.get("model") or settings.gemini_model,
            }
        return {
            "api_key": settings.gemini_api_key,
            "model": settings.gemini_model,
        }
    return {}


def _write_artifact(run_id: str, filename: str, payload, content_type: str) -> tuple[str, int]:
    settings = get_settings()
    run_dir = Path(settings.artifact_storage_path) / "results" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    file_path = run_dir / filename

    if content_type == "application/json":
        data = json.dumps(payload, indent=2, ensure_ascii=True)
    else:
        data = str(payload)

    file_path.write_text(data, encoding="utf-8")
    rel_storage_path = str(Path("results") / run_id / filename)
    return rel_storage_path, len(data.encode("utf-8"))


def _persist_artifact(session, run_id: str, filename: str, payload, content_type: str = "application/json"):
    storage_path, size_bytes = _write_artifact(run_id, filename, payload, content_type)
    session.add(
        ArtifactModel(
            id=str(uuid4()),
            run_id=run_id,
            filename=filename,
            content_type=content_type,
            size_bytes=str(size_bytes),
            storage_path=storage_path,
        )
    )
    session.commit()


def enqueue_workflow(run_id: str, workflow_key: str) -> dict[str, str]:
    """Enqueue workflow through Celery when available, fallback to local background thread."""
    try:
        from apps.worker.celery_app import run_workflow as celery_run_workflow

        task = celery_run_workflow.delay(run_id, workflow_key)
        return {"queue": "celery", "task_id": str(task.id)}
    except Exception as exc:
        logger.warning(f"Celery enqueue failed, using local background execution: {str(exc)}")
        thread = threading.Thread(target=run_workflow, args=(run_id, workflow_key), daemon=True)
        thread.start()
        return {"queue": "local-thread", "task_id": thread.name}


def run_workflow(run_id: str, workflow_key: str):
    """Execute a workflow synchronously."""
    settings = get_settings()
    SessionLocal = get_session_factory(settings.database_url)
    session = SessionLocal()
    run = None

    def log_step(level: str, message: str, correlation_id: str | None = None):
        """Log to database and console."""
        log_entry = WorkflowRunLogModel(
            id=str(uuid4()),
            run_id=run_id,
            level=level,
            message=message,
            timestamp=_utc_now(),
            correlation_id=correlation_id,
        )
        session.add(log_entry)
        session.commit()
        
        # Also print to stderr so it appears in terminal
        timestamp = _utc_now().isoformat()
        prefix = f"[{timestamp}] [{workflow_key}] [{level}]"
        print(f"{prefix} {message}", file=sys.stderr, flush=True)

    try:
        run = session.query(WorkflowRunModel).filter(WorkflowRunModel.id == run_id).first()
        if not run:
            logger.error(f"Run not found: {run_id}")
            return

        correlation_id = str(run_id)

        run.status = "running"
        run.started_at = _utc_now()
        session.commit()

        log_step("INFO", f"Workflow {workflow_key} started", correlation_id=correlation_id)
        logger.info(f"Starting workflow: {workflow_key} (run_id={run_id})")

        # Parse parameters
        params = (
            run.parameters
            if isinstance(run.parameters, dict)
            else json.loads(run.parameters or "{}")
        )
        workflow_result = {}
        _persist_artifact(session, run_id, "parameters.json", params)

        # Execute workflow based on key
        if workflow_key == "fetch_confluence":
            log_step("INFO", "Fetching Confluence catalog")

            confluence_config = {
                "base_url": params.get("confluence_url", ""),
                "space": params.get("confluence_space", ""),
                "email": params.get("confluence_email", ""),
                "api_token": params.get("confluence_token", ""),
            }

            confluence_client = integration_registry.get_client(
                IntegrationType.CONFLUENCE, confluence_config
            )

            result = asyncio.run(
                catalog.fetch_confluence_catalog(
                    confluence_client,
                    space=confluence_config["space"],
                    labels=params.get("labels"),
                )
            )
            workflow_result = result
            log_step("INFO", f"Fetched {result.get('pages_fetched', 0)} pages", correlation_id=correlation_id)

        elif workflow_key == "fetch_jira":
            log_step("INFO", "Fetching Jira issues")

            jira_config = {
                "base_url": params.get("jira_url", ""),
                "email": params.get("jira_email", ""),
                "api_token": params.get("jira_token", ""),
            }

            jira_client = integration_registry.get_client(IntegrationType.JIRA, jira_config)

            result = asyncio.run(
                catalog.fetch_jira_issues(
                    jira_client,
                    jql=params.get("jql", ""),
                    project=params.get("project", ""),
                )
            )
            workflow_result = result
            log_step("INFO", f"Fetched {result.get('issues_fetched', 0)} issues", correlation_id=correlation_id)

        elif workflow_key == "fetch_azure":
            log_step("INFO", "Fetching Azure DevOps specs")

            azure_config = {
                "org_url": params.get("azure_org_url", ""),
                "project": params.get("azure_project", ""),
                "pat": params.get("azure_pat", ""),
            }

            azure_client = integration_registry.get_client(
                IntegrationType.AZURE_DEVOPS, azure_config
            )

            result = asyncio.run(
                catalog.fetch_azure_devops_specs(
                    azure_client,
                    project=azure_config["project"],
                )
            )
            workflow_result = result
            log_step("INFO", f"Fetched {result.get('plans_fetched', 0)} plans", correlation_id=correlation_id)

        elif workflow_key == "generate_tests":
            log_step("INFO", "Generating test cases")

            gemini_config = {
                "api_key": params.get("gemini_api_key", ""),
                "model": params.get("gemini_model", "gemini-2.0-flash"),
            }

            gemini_client = integration_registry.get_client(
                IntegrationType.GEMINI, gemini_config
            )

            if params.get("test_type") == "api":
                result = asyncio.run(
                    generation.generate_api_test_cases(
                        gemini_client,
                        spec=params.get("spec", ""),
                        project=params.get("project", ""),
                        suite=params.get("suite", ""),
                    )
                )
            else:
                result = asyncio.run(
                    generation.generate_ui_test_cases(
                        gemini_client,
                        user_story=params.get("user_story", ""),
                        project=params.get("project", ""),
                        suite=params.get("suite", ""),
                    )
                )

            workflow_result = result
            log_step("INFO", f"Generated {result.get('tests_generated', 0)} tests", correlation_id=correlation_id)

        elif workflow_key == "analyze_coverage":
            log_step("INFO", "Analyzing test coverage")

            gemini_config = {
                "api_key": params.get("gemini_api_key", ""),
                "model": params.get("gemini_model", "gemini-2.0-flash"),
            }

            gemini_client = integration_registry.get_client(
                IntegrationType.GEMINI, gemini_config
            )

            result = asyncio.run(
                generation.analyze_coverage(
                    gemini_client,
                    requirements=params.get("requirements", []),
                    tests=params.get("tests", []),
                )
            )
            workflow_result = result
            log_step("INFO", f"Coverage: {result.get('coverage_percentage', 0):.1f}%", correlation_id=correlation_id)

        elif workflow_key == "update_coverage":
            log_step("INFO", "Updating coverage pages", correlation_id=correlation_id)

            confluence_client = integration_registry.get_client(
                IntegrationType.CONFLUENCE,
                _resolve_integration_config(session, IntegrationType.CONFLUENCE),
            )
            azure_client = integration_registry.get_client(
                IntegrationType.AZURE_DEVOPS,
                _resolve_integration_config(session, IntegrationType.AZURE_DEVOPS),
            )
            jira_client = integration_registry.get_client(
                IntegrationType.JIRA,
                _resolve_integration_config(session, IntegrationType.JIRA),
            )
            gemini_client = integration_registry.get_client(
                IntegrationType.GEMINI,
                _resolve_integration_config(session, IntegrationType.GEMINI),
            )

            result = asyncio.run(
                coverage.run_update_coverage_pages_workflow(
                    confluence_client=confluence_client,
                    azure_client=azure_client,
                    jira_client=jira_client,
                    gemini_client=gemini_client,
                    mode=params.get("mode", "single"),
                    us_code=params.get("us_code"),
                    apply=bool(params.get("apply", False)),
                    force=bool(params.get("force", False)),
                    batch_delay_seconds=int(params.get("batch_delay_seconds", 3)),
                    max_items=params.get("max_items"),
                    fail_fast=bool(params.get("fail_fast", False)),
                    include_debug_artifacts=bool(params.get("include_debug_artifacts", True)),
                    use_cached_azure_snapshot=bool(params.get("use_cached_azure_snapshot", False)),
                    preview_run_id=params.get("preview_run_id") or None,
                    correlation_id=correlation_id,
                    log_fn=lambda level, message: log_step(level, message, correlation_id=correlation_id),
                )
            )
            workflow_result = result
            log_step("INFO", "Coverage pages updated", correlation_id=correlation_id)

        elif workflow_key == "triage_bugs":
            log_step("INFO", "Triaging bug tickets", correlation_id=correlation_id)

            jira_client = integration_registry.get_client(
                IntegrationType.JIRA,
                _resolve_integration_config(session, IntegrationType.JIRA),
            )
            confluence_client = integration_registry.get_client(
                IntegrationType.CONFLUENCE,
                _resolve_integration_config(session, IntegrationType.CONFLUENCE),
            )
            gemini_client = integration_registry.get_client(
                IntegrationType.GEMINI,
                _resolve_integration_config(session, IntegrationType.GEMINI),
            )

            result = asyncio.run(
                triage.run_triage_bugs_workflow(
                    jira_client=jira_client,
                    confluence_client=confluence_client,
                    gemini_client=gemini_client,
                    jql=params.get("jql", triage.DEFAULT_BUG_JQL),
                    max_results=int(params.get("max_results", 50)),
                    apply=bool(params.get("apply", False)),
                    add_comment=bool(params.get("add_comment", False)),
                    severity_field_id=str(params.get("severity_field_id", triage.DEFAULT_SEVERITY_FIELD_ID)),
                    impact_field_id=str(params.get("impact_field_id", triage.DEFAULT_IMPACT_FIELD_ID)),
                    target_status=str(params.get("target_status", triage.DEFAULT_TARGET_STATUS)),
                    batch_delay_seconds=int(params.get("batch_delay_seconds", 10)),
                    correlation_id=correlation_id,
                    log_fn=lambda level, message: log_step(level, message, correlation_id=correlation_id),
                )
            )
            workflow_result = result
            triage_summary = result.get("summary", {})
            log_step(
                "INFO",
                f"Triage complete: triaged={triage_summary.get('bugs_triaged', 0)}"
                f"/{triage_summary.get('bugs_fetched', 0)}",
                correlation_id=correlation_id,
            )

        elif workflow_key == "generate_from_confluence":
            log_step("INFO", "Generating test cases from Confluence", correlation_id=correlation_id)

            confluence_client = integration_registry.get_client(
                IntegrationType.CONFLUENCE,
                _resolve_integration_config(session, IntegrationType.CONFLUENCE),
            )
            azure_client = integration_registry.get_client(
                IntegrationType.AZURE_DEVOPS,
                _resolve_integration_config(session, IntegrationType.AZURE_DEVOPS),
            )
            gemini_client = integration_registry.get_client(
                IntegrationType.GEMINI,
                _resolve_integration_config(session, IntegrationType.GEMINI),
            )

            result = asyncio.run(
                generation.run_generate_from_confluence_workflow(
                    confluence_client=confluence_client,
                    gemini_client=gemini_client,
                    azure_client=azure_client,
                    epic_page_id=str(params.get("epic_page_id", "")),
                    test_plan_id=str(params.get("test_plan_id", "")),
                    api_docs_folder_id=str(params.get("api_docs_folder_id", "")),
                    api_keyword=str(params.get("api_keyword", "API")),
                    single_us_id=params.get("single_us_id") or None,
                    resume_from=params.get("resume_from") or None,
                    force=bool(params.get("force", False)),
                    dry_run=bool(params.get("dry_run", False)),
                    gemini_delay_seconds=int(params.get("gemini_delay_seconds", 10)),
                    log_fn=lambda level, message: log_step(level, message, correlation_id=correlation_id),
                )
            )
            workflow_result = result
            log_step(
                "INFO",
                f"generate_from_confluence complete: "
                f"created={result.get('tests_created', 0)} across {result.get('us_processed', 0)} US(s)",
                correlation_id=correlation_id,
            )

        else:
            log_step("WARNING", f"Unknown workflow: {workflow_key}", correlation_id=correlation_id)
            run.status = "failed"
            run.error_message = f"Unknown workflow: {workflow_key}"
            session.commit()
            return

        if workflow_result:
            _persist_artifact(session, run_id, "workflow_result.json", workflow_result)
            if workflow_key == "update_coverage":
                _persist_artifact(session, run_id, "run_summary.json", workflow_result.get("summary", {}))
                _persist_artifact(session, run_id, "per_item_results.json", workflow_result.get("per_item_results", []))
                _persist_artifact(
                    session,
                    run_id,
                    "generated_pages_preview.json",
                    workflow_result.get("generated_pages_preview", []),
                )
                if workflow_result.get("errors"):
                    _persist_artifact(session, run_id, "errors.json", workflow_result.get("errors", []))
            elif workflow_key == "triage_bugs":
                _persist_artifact(session, run_id, "triage_summary.json", workflow_result.get("summary", {}))
                _persist_artifact(session, run_id, "per_issue_results.json", workflow_result.get("per_issue_results", []))
            elif workflow_key == "generate_from_confluence":
                _persist_artifact(session, run_id, "per_us_results.json", workflow_result.get("per_us_results", []))

        run.status = "succeeded"
        run.completed_at = _utc_now()
        session.commit()

        log_step("INFO", f"Workflow {workflow_key} completed successfully", correlation_id=correlation_id)
        logger.info(f"Workflow completed: {workflow_key} (run_id={run_id})")

    except Exception as e:
        logger.error(
            f"Workflow execution failed: {str(e)}", extra={"run_id": run_id}
        )
        if run:
            log_step("ERROR", f"Workflow failed: {str(e)}")
            run.status = "failed"
            run.error_message = str(e)
            run.completed_at = _utc_now()
            session.commit()
    finally:
        session.close()
