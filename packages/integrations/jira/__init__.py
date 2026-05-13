"""Jira integration client"""

from typing import Any, Optional

import httpx

from packages.common import IntegrationConnectionStatus, IntegrationType, get_logger
from packages.integrations import IntegrationClient

logger = get_logger(__name__)


class JiraClient(IntegrationClient):
    """Jira Cloud API client"""

    provider_type = IntegrationType.JIRA

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self.base_url = config.get("base_url", "https://yourdomain.atlassian.net")
        self.email = config.get("email", "")
        self.api_token = config.get("api_token", "")

    async def test_connection(self) -> tuple[bool, Optional[str]]:
        """Test connection to Jira"""
        if not self.api_token or not self.email:
            return False, "API token or email not configured"

        try:
            async with httpx.AsyncClient() as client:
                auth = (self.email, self.api_token)
                response = await client.get(
                    f"{self.base_url}/rest/api/3/myself",
                    auth=auth,
                    timeout=10,
                )
                if response.status_code == 200:
                    return True, None
                elif response.status_code == 401:
                    return False, "Invalid API token or email"
                else:
                    return False, f"HTTP {response.status_code}: {response.text}"
        except httpx.TimeoutException:
            return False, "Connection timeout"
        except Exception as e:
            return False, str(e)

    async def get_health_status(self) -> IntegrationConnectionStatus:
        """Get current health status"""
        if not self.api_token or not self.email:
            return IntegrationConnectionStatus.UNCONFIGURED

        success, _ = await self.test_connection()
        return (
            IntegrationConnectionStatus.HEALTHY
            if success
            else IntegrationConnectionStatus.UNHEALTHY
        )

    async def fetch_issues(self, jql: str) -> list[dict[str, Any]]:
        """Fetch issues using JQL query"""
        try:
            async with httpx.AsyncClient() as client:
                auth = (self.email, self.api_token)
                response = await client.get(
                    f"{self.base_url}/rest/api/3/search",
                    auth=auth,
                    params={"jql": jql, "maxResults": 100},
                    timeout=30,
                )
                if response.status_code == 200:
                    data = response.json()
                    return data.get("issues", [])
                else:
                    logger.error(f"Failed to fetch issues: {response.text}")
                    return []
        except Exception as e:
            logger.error(f"Error fetching issues: {str(e)}")
            return []

    async def create_issue(self, issue_data: dict[str, Any]) -> dict[str, Any]:
        """Create a new issue"""
        try:
            async with httpx.AsyncClient() as client:
                auth = (self.email, self.api_token)
                response = await client.post(
                    f"{self.base_url}/rest/api/3/issue",
                    auth=auth,
                    json=issue_data,
                    timeout=30,
                )
                if response.status_code in (201, 200):
                    data = response.json()
                    return {"success": True, "issue_key": data.get("key"), "issue_id": data.get("id")}
                else:
                    return {"success": False, "error": response.text}
        except Exception as e:
            logger.error(f"Error creating issue: {str(e)}")
            return {"success": False, "error": str(e)}

    async def update_issue(self, issue_key: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Update an issue"""
        try:
            async with httpx.AsyncClient() as client:
                auth = (self.email, self.api_token)
                response = await client.put(
                    f"{self.base_url}/rest/api/3/issue/{issue_key}",
                    auth=auth,
                    json=updates,
                    timeout=30,
                )
                if response.status_code in (204, 200):
                    return {"success": True, "issue_key": issue_key}
                else:
                    return {"success": False, "error": response.text}
        except Exception as e:
            logger.error(f"Error updating issue {issue_key}: {str(e)}")
            return {"success": False, "error": str(e)}

    async def fetch_qa_tasks(self) -> list[dict[str, Any]]:
        """Fetch QA tasks (issues labeled as QA tasks)"""
        jql = 'labels = "QA" AND type = "Task"'
        return await self.fetch_issues(jql)


__all__ = ["JiraClient"]
