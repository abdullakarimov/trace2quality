"""Azure DevOps integration client"""

import re
import xml.etree.ElementTree as ET
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
        self.org_url = str(config.get("org_url", "")).rstrip("/")
        self.project = config.get("project", "YourProject")
        self.pat = config.get("pat", "")
        self.base_url = f"{self.org_url}/_apis"
        self.project_base_url = f"{self.org_url}/{self.project}/_apis"

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
                    f"{self.project_base_url}/testplan/plans?api-version=7.1",
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
                    f"{self.project_base_url}/test/Plans/{plan_id}/suites?api-version=5.0",
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

    async def fetch_suites(self, plan_id: str) -> list[dict[str, Any]]:
        """Fetch suites for a test plan."""
        return await self.fetch_test_cases(plan_id)

    async def fetch_test_cases_for_suite(self, plan_id: str, suite_id: str) -> list[dict[str, Any]]:
        """Fetch test cases linked to a suite."""
        try:
            async with httpx.AsyncClient() as client:
                auth = ("", self.pat)
                response = await client.get(
                    f"{self.project_base_url}/testplan/Plans/{plan_id}/Suites/{suite_id}/TestCase?api-version=7.1",
                    auth=auth,
                    timeout=30,
                )
                if response.status_code == 200:
                    data = response.json()
                    return data.get("value", [])
                logger.error(f"Failed to fetch suite test cases: {response.text}")
                return []
        except Exception as e:
            logger.error(f"Error fetching suite test cases: {str(e)}")
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

    async def list_orphan_test_cases(self, test_plan_id: Optional[str] = None) -> dict[str, Any]:
        """List Test Case work items that are not assigned to any test suite."""
        try:
            all_case_details = await self._fetch_all_test_case_work_items()
            if not all_case_details:
                return {
                    "success": True,
                    "total_test_cases": 0,
                    "linked_test_cases": 0,
                    "orphan_test_cases": [],
                    "test_plan_id": test_plan_id,
                }

            linked_ids = await self._fetch_test_case_ids_in_suites(test_plan_id=test_plan_id)

            orphan_test_cases = [
                case
                for case in all_case_details
                if str(case.get("id", "")) not in linked_ids
            ]

            return {
                "success": True,
                "total_test_cases": len(all_case_details),
                "linked_test_cases": len(linked_ids),
                "orphan_test_cases": orphan_test_cases,
                "test_plan_id": test_plan_id,
            }
        except Exception as e:
            logger.error(f"Error listing orphan test cases: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "total_test_cases": 0,
                "linked_test_cases": 0,
                "orphan_test_cases": [],
                "test_plan_id": test_plan_id,
            }

    async def delete_test_cases(self, case_ids: list[str]) -> dict[str, Any]:
        """Delete Test Case work items by ID."""
        if not case_ids:
            return {"success": False, "error": "No test case IDs provided", "deleted": [], "failed": []}

        deleted: list[str] = []
        failed: list[dict[str, str]] = []

        try:
            async with httpx.AsyncClient() as client:
                auth = ("", self.pat)
                for case_id in case_ids:
                    response = await client.delete(
                        f"{self.project_base_url}/test/testcases/{case_id}?api-version=7.1-preview.1",
                        auth=auth,
                        timeout=30,
                    )
                    if response.status_code in (200, 202, 204):
                        deleted.append(case_id)
                    else:
                        try:
                            err_body = response.json()
                            err_msg = err_body.get("message", response.text)
                        except Exception:
                            err_msg = response.text
                        failed.append({
                            "id": case_id,
                            "status": response.status_code,
                            "error": err_msg,
                        })
                        # On 403/401 stop early — all items will fail for the same reason
                        if response.status_code in (401, 403):
                            logger.warning(f"Permission denied deleting test case {case_id}: {err_msg}")
                            break

            first_failure = failed[0] if failed else None
            first_status = first_failure.get("status") if first_failure else None
            return {
                "success": len(failed) == 0,
                "deleted": deleted,
                "failed": failed,
                "deleted_count": len(deleted),
                "failed_count": len(failed),
                "http_status": first_status,
                "error": first_failure.get("error") if first_failure and not deleted else None,
            }
        except Exception as e:
            logger.error(f"Error deleting test cases: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "deleted": deleted,
                "failed": failed,
                "deleted_count": len(deleted),
                "failed_count": len(failed),
            }

    async def reassign_test_cases(self, case_ids: list[str], assigned_to: str) -> dict[str, Any]:
        """Re-assign Test Case work items to a different user by email/display name."""
        if not case_ids:
            return {"success": False, "error": "No test case IDs provided", "updated": [], "failed": []}
        if not assigned_to:
            return {"success": False, "error": "assigned_to cannot be empty", "updated": [], "failed": []}

        updated: list[str] = []
        failed: list[dict[str, Any]] = []

        patch_body = [
            {
                "op": "add",
                "path": "/fields/System.AssignedTo",
                "value": assigned_to,
            }
        ]

        try:
            async with httpx.AsyncClient() as client:
                auth = ("", self.pat)
                for case_id in case_ids:
                    response = await client.patch(
                        f"{self.project_base_url}/wit/workitems/{case_id}?api-version=7.1",
                        auth=auth,
                        headers={"Content-Type": "application/json-patch+json"},
                        json=patch_body,
                        timeout=30,
                    )
                    if response.status_code in (200, 201):
                        updated.append(case_id)
                    else:
                        try:
                            err_body = response.json()
                            err_msg = err_body.get("message", response.text)
                        except Exception:
                            err_msg = response.text
                        failed.append({
                            "id": case_id,
                            "status": response.status_code,
                            "error": err_msg,
                        })
                        if response.status_code in (401, 403):
                            logger.warning(f"Permission denied reassigning test case {case_id}: {err_msg}")
                            break

            first_failure = failed[0] if failed else None
            first_status = first_failure.get("status") if first_failure else None
            return {
                "success": len(failed) == 0,
                "updated": updated,
                "failed": failed,
                "updated_count": len(updated),
                "failed_count": len(failed),
                "http_status": first_status,
                "error": first_failure.get("error") if first_failure and not updated else None,
            }
        except Exception as e:
            logger.error(f"Error reassigning test cases: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "updated": updated,
                "failed": failed,
                "updated_count": len(updated),
                "failed_count": len(failed),
            }

    async def _fetch_all_test_case_work_items(self) -> list[dict[str, Any]]:
        """Fetch all Test Case work items in the configured project."""
        wiql_query = {
            "query": (
                "SELECT [System.Id], [System.Title], [System.State] "
                "FROM WorkItems "
                "WHERE [System.TeamProject] = @project "
                "AND [System.WorkItemType] = 'Test Case'"
            )
        }

        async with httpx.AsyncClient() as client:
            auth = ("", self.pat)
            wiql_response = await client.post(
                f"{self.project_base_url}/wit/wiql?api-version=7.1",
                auth=auth,
                json=wiql_query,
                timeout=30,
            )
            if wiql_response.status_code != 200:
                logger.error(
                    f"Failed to query Test Case work items: {wiql_response.text}"
                )
                return []

            work_item_refs = wiql_response.json().get("workItems", [])
            all_ids = [str(item.get("id")) for item in work_item_refs if item.get("id")]
            if not all_ids:
                return []

            fields = [
                "System.Id",
                "System.Title",
                "System.State",
                "System.AreaPath",
                "System.IterationPath",
            ]

            detailed_items: list[dict[str, Any]] = []
            for i in range(0, len(all_ids), 200):
                chunk = all_ids[i : i + 200]
                response = await client.get(
                    f"{self.base_url}/wit/workitems",
                    auth=auth,
                    params={
                        "ids": ",".join(chunk),
                        "fields": ",".join(fields),
                        "api-version": "7.1",
                    },
                    timeout=30,
                )
                if response.status_code != 200:
                    logger.error(f"Failed to fetch Test Case details: {response.text}")
                    continue

                for item in response.json().get("value", []):
                    item_fields = item.get("fields", {})
                    detailed_items.append(
                        {
                            "id": str(item.get("id", "")),
                            "title": item_fields.get("System.Title", ""),
                            "state": item_fields.get("System.State", ""),
                            "area_path": item_fields.get("System.AreaPath", ""),
                            "iteration_path": item_fields.get("System.IterationPath", ""),
                            "url": item.get("url", ""),
                        }
                    )

            return detailed_items

    async def _fetch_test_case_ids_in_suites(self, test_plan_id: Optional[str] = None) -> set[str]:
        """Fetch IDs of Test Cases that are assigned to suites in all plans."""
        linked_ids: set[str] = set()

        async with httpx.AsyncClient() as client:
            auth = ("", self.pat)

            if test_plan_id:
                plans = [{"id": test_plan_id}]
            else:
                plans_response = await client.get(
                    f"{self.project_base_url}/testplan/plans?api-version=7.1",
                    auth=auth,
                    timeout=30,
                )
                if plans_response.status_code != 200:
                    logger.error(
                        "Failed to fetch test plans while resolving orphan test cases: "
                        f"{plans_response.text}"
                    )
                    return linked_ids

                plans = plans_response.json().get("value", [])

            for plan in plans:
                plan_id = plan.get("id")
                if not plan_id:
                    continue

                suites_response = await client.get(
                    f"{self.project_base_url}/test/Plans/{plan_id}/suites?api-version=5.0",
                    auth=auth,
                    timeout=30,
                )
                if suites_response.status_code != 200:
                    logger.warning(
                        f"Failed to fetch suites for plan {plan_id}: {suites_response.text}"
                    )
                    continue

                suites = suites_response.json().get("value", [])
                for suite in suites:
                    suite_id = suite.get("id")
                    if not suite_id:
                        continue

                    test_cases_response = await client.get(
                        f"{self.project_base_url}/test/Plans/{plan_id}/Suites/{suite_id}/testcases"
                        f"?api-version=7.1",
                        auth=auth,
                        timeout=30,
                    )
                    if test_cases_response.status_code != 200:
                        logger.warning(
                            "Failed to fetch test cases for "
                            f"plan {plan_id} suite {suite_id}: {test_cases_response.text}"
                        )
                        continue

                    for test_case in test_cases_response.json().get("value", []):
                        case_ref = test_case.get("testCase") or {}
                        case_id = case_ref.get("id")
                        if case_id:
                            linked_ids.add(str(case_id))

        return linked_ids

    @staticmethod
    def _parse_steps_xml(steps_xml: str) -> list[dict[str, str]]:
        """Parse the Microsoft.VSTS.TCM.Steps XML field into a list of {action, expected} dicts."""
        if not steps_xml:
            return []
        try:
            root = ET.fromstring(steps_xml)
        except ET.ParseError:
            return []
        steps: list[dict[str, str]] = []
        for step_el in root.iter("step"):
            params = step_el.findall("parameterizedString")
            action = ""
            expected = ""
            if len(params) >= 1:
                raw_action = params[0].text or ""
                action = re.sub(r"<[^>]+>", " ", raw_action).strip()
            if len(params) >= 2:
                raw_expected = params[1].text or ""
                expected = re.sub(r"<[^>]+>", " ", raw_expected).strip()
            if action or expected:
                steps.append({"action": action, "expected": expected})
        return steps

    async def fetch_test_case_details(self, case_ids: list[str]) -> list[dict[str, Any]]:
        """Fetch work-item details (title + parsed steps) for a list of Test Case IDs.

        Returns a list of dicts: {id, title, steps: [{action, expected}]}
        """
        if not case_ids:
            return []

        fields = [
            "System.Id",
            "System.Title",
            "Microsoft.VSTS.TCM.Steps",
        ]
        results: list[dict[str, Any]] = []

        try:
            async with httpx.AsyncClient() as client:
                auth = ("", self.pat)
                for i in range(0, len(case_ids), 200):
                    chunk = case_ids[i : i + 200]
                    response = await client.get(
                        f"{self.base_url}/wit/workitems",
                        auth=auth,
                        params={
                            "ids": ",".join(chunk),
                            "fields": ",".join(fields),
                            "api-version": "7.1",
                        },
                        timeout=60,
                    )
                    if response.status_code != 200:
                        logger.error(f"fetch_test_case_details failed: {response.text}")
                        continue
                    for item in response.json().get("value", []):
                        item_fields = item.get("fields", {})
                        steps_xml = item_fields.get("Microsoft.VSTS.TCM.Steps") or ""
                        results.append(
                            {
                                "id": str(item.get("id", "")),
                                "title": item_fields.get("System.Title", ""),
                                "steps": self._parse_steps_xml(steps_xml),
                            }
                        )
        except Exception as exc:
            logger.error(f"Error in fetch_test_case_details: {exc}")

        return results


__all__ = ["AzureDevOpsClient"]
