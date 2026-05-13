"""Catalog workflow module for fetching and indexing content"""

from typing import Any, Optional
from datetime import datetime

from packages.common import get_logger

logger = get_logger(__name__)


async def fetch_confluence_catalog(
    confluence_client, space: str, labels: Optional[list[str]] = None
) -> dict[str, Any]:
    """Fetch Confluence pages and index them"""
    logger.info(f"Fetching Confluence catalog from space: {space}")

    try:
        items = []
        
        # If labels provided, fetch pages by each label
        if labels:
            for label in labels:
                pages = await confluence_client.fetch_pages_by_label(label)
                for page in pages:
                    page_id = page.get("id")
                    title = page.get("title", "")
                    content = await confluence_client.fetch_page_content(page_id)
                    
                    items.append({
                        "id": page_id,
                        "type": "confluence_page",
                        "title": title,
                        "source_url": page.get("_links", {}).get("self", ""),
                        "labels": [label],
                        "content_preview": content[:500] if content else "",
                        "last_modified": page.get("version", {}).get("when", ""),
                    })
        
        return {
            "source": "confluence",
            "space": space,
            "pages_fetched": len(items),
            "indexed_count": len(items),
            "items": items,
            "timestamp": datetime.utcnow().isoformat(),
            "status": "success" if items else "no_results",
        }
    except Exception as e:
        logger.error(f"Error fetching Confluence catalog: {str(e)}")
        return {
            "source": "confluence",
            "space": space,
            "pages_fetched": 0,
            "indexed_count": 0,
            "items": [],
            "error": str(e),
            "status": "failed",
        }


async def fetch_jira_issues(
    jira_client, jql: str, project: str
) -> dict[str, Any]:
    """Fetch Jira issues and catalog them"""
    logger.info(f"Fetching Jira issues with JQL: {jql}")

    try:
        issues = await jira_client.fetch_issues(jql)
        
        items = []
        for issue in issues:
            items.append({
                "id": issue.get("key"),
                "type": issue.get("fields", {}).get("issuetype", {}).get("name", ""),
                "title": issue.get("fields", {}).get("summary", ""),
                "description": issue.get("fields", {}).get("description", "")[:500],
                "status": issue.get("fields", {}).get("status", {}).get("name", ""),
                "priority": issue.get("fields", {}).get("priority", {}).get("name", ""),
                "assignee": issue.get("fields", {}).get("assignee", {}).get("displayName", ""),
                "url": issue.get("self", ""),
                "created": issue.get("fields", {}).get("created", ""),
            })
        
        return {
            "source": "jira",
            "project": project,
            "issues_fetched": len(items),
            "indexed_count": len(items),
            "items": items,
            "timestamp": datetime.utcnow().isoformat(),
            "status": "success" if items else "no_results",
        }
    except Exception as e:
        logger.error(f"Error fetching Jira issues: {str(e)}")
        return {
            "source": "jira",
            "project": project,
            "issues_fetched": 0,
            "indexed_count": 0,
            "items": [],
            "error": str(e),
            "status": "failed",
        }


async def fetch_azure_devops_specs(
    azure_client, project: str
) -> dict[str, Any]:
    """Fetch Azure DevOps test plans and specifications"""
    logger.info(f"Fetching Azure DevOps specs from project: {project}")

    try:
        plans = await azure_client.fetch_test_plans()
        
        items = []
        for plan in plans:
            plan_id = plan.get("id")
            suites = await azure_client.fetch_test_cases(plan_id)
            
            for suite in suites:
                items.append({
                    "id": suite.get("id"),
                    "type": "test_suite",
                    "name": suite.get("name", ""),
                    "plan_id": plan_id,
                    "plan_name": plan.get("name", ""),
                    "test_count": suite.get("testCaseCount", 0),
                    "parent_suite": suite.get("parentSuite", {}).get("id", ""),
                    "url": suite.get("url", ""),
                })
        
        return {
            "source": "azure_devops",
            "project": project,
            "plans_fetched": len(items),
            "indexed_count": len(items),
            "items": items,
            "timestamp": datetime.utcnow().isoformat(),
            "status": "success" if items else "no_results",
        }
    except Exception as e:
        logger.error(f"Error fetching Azure DevOps specs: {str(e)}")
        return {
            "source": "azure_devops",
            "project": project,
            "plans_fetched": 0,
            "indexed_count": 0,
            "items": [],
            "error": str(e),
            "status": "failed",
        }


__all__ = [
    "fetch_confluence_catalog",
    "fetch_jira_issues",
    "fetch_azure_devops_specs",
]
