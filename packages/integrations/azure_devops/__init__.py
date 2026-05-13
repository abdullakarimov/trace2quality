"""Azure DevOps integration client"""

from typing import Any, Optional

import httpx

from packages.common import IntegrationConnectionStatus, IntegrationType, get_logger
from packages.integrations import IntegrationClient

logger = get_logger(__name__)


class AzureDevOpsClient(IntegrationClient):
    """Azure DevOps REST API client"""

    provider_type = IntegrationType.AZURE_DEVOPS

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self.org_url = config.get("org_url", "https://dev.azure.com/yourorg")
        self.project = config.get("project", "YourProject")
        self.pat = config.get("pat", "")
        self.base_url = f"{self.org_url}/_apis"

    async def test_connection(self) -> tuple[bool, Optional[str]]:
        """Test connection to Azure DevOps"""
        if not self.pat:
            return False, "PAT (Personal Access Token) not configured"

        try:
            async with httpx.AsyncClient() as client:
                auth = ("", self.pat)  # PAT is passed as password
                response = await client.get(
                    f"{self.base_url}/projects/{self.project}?api-version=7.1",
                    auth=auth,
                    timeout=10,
                )
                if response.status_code == 200:
                    return True, None
                elif response.status_code == 401:
                    return False, "Invalid PAT or unauthorized"
                else:
                    return False, f"HTTP {response.status_code}: {response.text}"
        except httpx.TimeoutException:
            return False, "Connection timeout"
        except Exception as e:
            return False, str(e)

    async def get_health_status(self) -> IntegrationConnectionStatus:
        """Get current health status"""
        if not self.pat:
            return IntegrationConnectionStatus.UNCONFIGURED

        success, _ = await self.test_connection()
        return (
            IntegrationConnectionStatus.HEALTHY
            if success
            else IntegrationConnectionStatus.UNHEALTHY
        )

    async def fetch_test_plans(self) -> list[dict[str, Any]]:
        """Fetch test plans from project"""
        try:
            async with httpx.AsyncClient() as client:
                auth = ("", self.pat)
                response = await client.get(
                    f"{self.base_url}/testplan/plans?api-version=7.1",
                    auth=auth,
                    timeout=30,
                )
                if response.status_code == 200:
                    data = response.json()
                    return data.get("value", [])
                else:
                    logger.error(f"Failed to fetch test plans: {response.text}")
                    return []
        except Exception as e:
            logger.error(f"Error fetching test plans: {str(e)}")
            return []

    async def fetch_test_cases(self, plan_id: str) -> list[dict[str, Any]]:
        """Fetch test cases from a plan"""
        try:
            async with httpx.AsyncClient() as client:
                auth = ("", self.pat)
                response = await client.get(
                    f"{self.base_url}/testplan/Plans({plan_id})/suites?api-version=7.1",
                    auth=auth,
                    timeout=30,
                )
                if response.status_code == 200:
                    data = response.json()
                    return data.get("value", [])
                else:
                    logger.error(f"Failed to fetch test cases: {response.text}")
                    return []
        except Exception as e:
            logger.error(f"Error fetching test cases: {str(e)}")
            return []

    async def create_test_case(self, test_case_data: dict[str, Any]) -> dict[str, Any]:
        """Create a test case"""
        try:
            async with httpx.AsyncClient() as client:
                auth = ("", self.pat)
                response = await client.post(
                    f"{self.base_url}/test/cases?api-version=7.1",
                    auth=auth,
                    json=test_case_data,
                    timeout=30,
                )
                if response.status_code in (200, 201):
                    data = response.json()
                    return {"success": True, "case_id": data.get("id"), "url": data.get("url", "")}
                else:
                    return {"success": False, "error": response.text}
        except Exception as e:
            logger.error(f"Error creating test case: {str(e)}")
            return {"success": False, "error": str(e)}

    async def update_test_case(self, case_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Update a test case"""
        try:
            async with httpx.AsyncClient() as client:
                auth = ("", self.pat)
                response = await client.patch(
                    f"{self.base_url}/test/cases/{case_id}?api-version=7.1",
                    auth=auth,
                    json=updates,
                    timeout=30,
                )
                if response.status_code in (200, 204):
                    return {"success": True, "case_id": case_id}
                else:
                    return {"success": False, "error": response.text}
        except Exception as e:
            logger.error(f"Error updating test case {case_id}: {str(e)}")
            return {"success": False, "error": str(e)}


__all__ = ["AzureDevOpsClient"]
