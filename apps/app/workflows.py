"""Workflow execution engine (synchronous, no Celery)"""

import asyncio
import json
from datetime import datetime
from uuid import uuid4

from apps.app.config import get_settings
from apps.app.database import (
    ArtifactModel,
    WorkflowRunLogModel,
    WorkflowRunModel,
    get_session_factory,
)
from packages.common import get_logger
from packages.integrations import integration_registry
from packages.workflows import catalog, coverage, generation, reporting, triage

logger = get_logger(__name__)


def run_workflow(run_id: str, workflow_key: str):
    """Execute a workflow synchronously"""
    settings = get_settings()
    SessionLocal = get_session_factory(settings.database_url)
    session = SessionLocal()

    def log_step(level: str, message: str):
        """Log a workflow step"""
        log_entry = WorkflowRunLogModel(
            id=str(uuid4()),
            run_id=run_id,
            level=level,
            message=message,
            timestamp=datetime.utcnow(),
        )
        session.add(log_entry)
        session.commit()

    try:
        run = (
            session.query(WorkflowRunModel)
            .filter(WorkflowRunModel.id == run_id)
            .first()
        )
        if not run:
            logger.error(f"Run not found: {run_id}")
            return

        run.status = "running"
        run.started_at = datetime.utcnow()
        session.commit()

        log_step("INFO", f"Workflow {workflow_key} started")
        logger.info(f"Starting workflow: {workflow_key} (run_id={run_id})")

        # Parse parameters
        params = (
            run.parameters
            if isinstance(run.parameters, dict)
            else json.loads(run.parameters or "{}")
        )
        workflow_result = {}

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
                "confluence", confluence_config
            )

            result = asyncio.run(
                catalog.fetch_confluence_catalog(
                    confluence_client,
                    space=confluence_config["space"],
                    labels=params.get("labels"),
                )
            )
            workflow_result = result
            log_step("INFO", f"Fetched {result.get('pages_fetched', 0)} pages")

        elif workflow_key == "fetch_jira":
            log_step("INFO", "Fetching Jira issues")

            jira_config = {
                "base_url": params.get("jira_url", ""),
                "email": params.get("jira_email", ""),
                "api_token": params.get("jira_token", ""),
            }

            jira_client = integration_registry.get_client("jira", jira_config)

            result = asyncio.run(
                catalog.fetch_jira_issues(
                    jira_client,
                    jql=params.get("jql", ""),
                    project=params.get("project", ""),
                )
            )
            workflow_result = result
            log_step("INFO", f"Fetched {result.get('issues_fetched', 0)} issues")

        elif workflow_key == "fetch_azure":
            log_step("INFO", "Fetching Azure DevOps specs")

            azure_config = {
                "org_url": params.get("azure_org_url", ""),
                "project": params.get("azure_project", ""),
                "pat": params.get("azure_pat", ""),
            }

            azure_client = integration_registry.get_client(
                "azure_devops", azure_config
            )

            result = asyncio.run(
                catalog.fetch_azure_devops_specs(
                    azure_client,
                    project=azure_config["project"],
                )
            )
            workflow_result = result
            log_step("INFO", f"Fetched {result.get('plans_fetched', 0)} plans")

        elif workflow_key == "generate_tests":
            log_step("INFO", "Generating test cases")

            gemini_config = {
                "api_key": params.get("gemini_api_key", ""),
                "model": params.get("gemini_model", "gemini-2.0-flash"),
            }

            gemini_client = integration_registry.get_client(
                "gemini", gemini_config
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
            log_step("INFO", f"Generated {result.get('tests_generated', 0)} tests")

        elif workflow_key == "analyze_coverage":
            log_step("INFO", "Analyzing test coverage")

            gemini_config = {
                "api_key": params.get("gemini_api_key", ""),
                "model": params.get("gemini_model", "gemini-2.0-flash"),
            }

            gemini_client = integration_registry.get_client(
                "gemini", gemini_config
            )

            result = asyncio.run(
                generation.analyze_coverage(
                    gemini_client,
                    requirements=params.get("requirements", []),
                    tests=params.get("tests", []),
                )
            )
            workflow_result = result
            log_step(
                "INFO", f"Coverage: {result.get('coverage_percentage', 0):.1f}%"
            )

        elif workflow_key == "update_coverage":
            log_step("INFO", "Updating coverage pages")

            confluence_config = {
                "base_url": params.get("confluence_url", ""),
                "space": params.get("confluence_space", ""),
                "email": params.get("confluence_email", ""),
                "api_token": params.get("confluence_token", ""),
            }

            confluence_client = integration_registry.get_client(
                "confluence", confluence_config
            )

            result = asyncio.run(
                coverage.update_coverage_pages(
                    confluence_client,
                    project=params.get("project", ""),
                    test_results=params.get("test_results", {}),
                )
            )
            workflow_result = result
            log_step("INFO", "Coverage pages updated")

        else:
            log_step("WARNING", f"Unknown workflow: {workflow_key}")
            run.status = "failed"
            run.error_message = f"Unknown workflow: {workflow_key}"
            session.commit()
            return

        # Store result as artifact
        if workflow_result:
            artifact = ArtifactModel(
                id=str(uuid4()),
                run_id=run_id,
                filename="workflow_result.json",
                content_type="application/json",
                size_bytes=len(json.dumps(workflow_result)),
                storage_path=f"results/{run_id}/workflow_result.json",
            )
            session.add(artifact)
            session.commit()

        run.status = "succeeded"
        run.completed_at = datetime.utcnow()
        session.commit()

        log_step("INFO", f"Workflow {workflow_key} completed successfully")
        logger.info(f"Workflow completed: {workflow_key} (run_id={run_id})")

    except Exception as e:
        logger.error(
            f"Workflow execution failed: {str(e)}", extra={"run_id": run_id}
        )
        log_step("ERROR", f"Workflow failed: {str(e)}")
        run.status = "failed"
        run.error_message = str(e)
        run.completed_at = datetime.utcnow()
        session.commit()
    finally:
        session.close()
