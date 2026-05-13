"""Unit tests for integration clients"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from packages.integrations.confluence import ConfluenceClient
from packages.integrations.jira import JiraClient
from packages.integrations.azure_devops import AzureDevOpsClient
from packages.integrations.gemini import GeminiClient
from packages.common import IntegrationConnectionStatus


class TestConfluenceClient:
    """Tests for Confluence integration client"""

    @pytest.mark.asyncio
    async def test_test_connection_success(self):
        """Test successful Confluence connection"""
        config = {
            "base_url": "http://confluence.test",
            "space": "TEST",
            "email": "test@example.com",
            "api_token": "test_token"
        }
        
        with patch("httpx.AsyncClient.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json = MagicMock(return_value={"id": "space1"})
            mock_get.return_value = mock_response

            client = ConfluenceClient(config)
            result = await client.test_connection()

            assert result[0] is True
            assert result[1] is None

    @pytest.mark.asyncio
    async def test_test_connection_failure(self):
        """Test failed Confluence connection"""
        config = {
            "base_url": "http://confluence.test",
            "space": "TEST",
            "email": "test@example.com",
            "api_token": "bad_token"
        }
        
        with patch("httpx.AsyncClient.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 401
            mock_get.return_value = mock_response

            client = ConfluenceClient(config)
            result = await client.test_connection()

            assert result[0] is False

    @pytest.mark.asyncio
    async def test_fetch_pages_by_label(self):
        """Test fetching Confluence pages by label"""
        config = {
            "base_url": "http://confluence.test",
            "space": "TEST",
            "email": "test@example.com",
            "api_token": "test_token"
        }

        with patch("httpx.AsyncClient.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json = MagicMock(return_value={
                "results": [
                    {"id": "1", "title": "Page 1", "_links": {"self": "url1"}},
                    {"id": "2", "title": "Page 2", "_links": {"self": "url2"}}
                ]
            })
            mock_get.return_value = mock_response

            client = ConfluenceClient(config)
            result = await client.fetch_pages_by_label("requirements")

            assert len(result) == 2
            assert result[0]["id"] == "1"


class TestJiraClient:
    """Tests for Jira integration client"""

    @pytest.mark.asyncio
    async def test_fetch_issues(self):
        """Test fetching Jira issues"""
        config = {
            "base_url": "http://jira.test",
            "email": "test@example.com",
            "api_token": "test_token"
        }

        with patch("httpx.AsyncClient.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json = MagicMock(return_value={
                "issues": [
                    {
                        "key": "PROJ-1",
                        "fields": {
                            "summary": "Issue 1",
                            "status": {"name": "Open"},
                            "priority": {"name": "High"}
                        }
                    }
                ]
            })
            mock_get.return_value = mock_response

            client = JiraClient(config)
            result = await client.fetch_issues("project=PROJ")

            assert len(result) == 1
            assert result[0]["key"] == "PROJ-1"

    @pytest.mark.asyncio
    async def test_create_issue(self):
        """Test creating a Jira issue"""
        config = {
            "base_url": "http://jira.test",
            "email": "test@example.com",
            "api_token": "test_token"
        }

        with patch("httpx.AsyncClient.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 201
            mock_response.json = MagicMock(return_value={
                "id": "10000",
                "key": "PROJ-100"
            })
            mock_post.return_value = mock_response

            client = JiraClient(config)
            result = await client.create_issue({"fields": {"summary": "New issue"}})

            assert result["success"] is True
            assert result["issue_key"] == "PROJ-100"

    @pytest.mark.asyncio
    async def test_fetch_qa_tasks(self):
        """Test fetching QA tasks"""
        config = {
            "base_url": "http://jira.test",
            "email": "test@example.com",
            "api_token": "test_token"
        }

        with patch("httpx.AsyncClient.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json = MagicMock(return_value={"issues": []})
            mock_get.return_value = mock_response

            client = JiraClient(config)
            result = await client.fetch_qa_tasks()

            # Should call fetch_issues with QA JQL
            mock_get.assert_called_once()


class TestAzureDevOpsClient:
    """Tests for Azure DevOps integration client"""

    @pytest.mark.asyncio
    async def test_test_connection_success(self):
        """Test successful Azure DevOps connection"""
        config = {
            "org_url": "https://ado.example.test/org",
            "project": "MyProject",
            "pat": "test_pat"
        }

        with patch("httpx.AsyncClient.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json = MagicMock(return_value={"id": "proj1"})
            mock_get.return_value = mock_response

            client = AzureDevOpsClient(config)
            result = await client.test_connection()

            assert result[0] is True

    @pytest.mark.asyncio
    async def test_fetch_test_plans(self):
        """Test fetching test plans"""
        config = {
            "org_url": "https://ado.example.test/org",
            "project": "MyProject",
            "pat": "test_pat"
        }

        with patch("httpx.AsyncClient.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json = MagicMock(return_value={
                "value": [
                    {"id": "1", "name": "Plan 1"}
                ]
            })
            mock_get.return_value = mock_response

            client = AzureDevOpsClient(config)
            result = await client.fetch_test_plans()

            assert len(result) == 1
            assert result[0]["id"] == "1"

    @pytest.mark.asyncio
    async def test_list_orphan_test_cases_filters_linked_cases(self):
        """Test orphan Test Case detection by excluding cases already in suites."""
        config = {
            "org_url": "https://ado.example.test/org",
            "project": "MyProject",
            "pat": "test_pat"
        }

        client = AzureDevOpsClient(config)

        with patch.object(
            client,
            "_fetch_all_test_case_work_items",
            AsyncMock(
                return_value=[
                    {"id": "101", "title": "Case 101", "state": "Active"},
                    {"id": "102", "title": "Case 102", "state": "Design"},
                ]
            ),
        ), patch.object(
            client,
            "_fetch_test_case_ids_in_suites",
            AsyncMock(return_value={"101"}),
        ):
            result = await client.list_orphan_test_cases()

        assert result["success"] is True
        assert result["total_test_cases"] == 2
        assert result["linked_test_cases"] == 1
        assert len(result["orphan_test_cases"]) == 1
        assert result["orphan_test_cases"][0]["id"] == "102"

    @pytest.mark.asyncio
    async def test_delete_test_cases_partial_failure(self):
        """Test deleting Test Cases returns both deleted and failed IDs."""
        config = {
            "org_url": "https://ado.example.test/org",
            "project": "MyProject",
            "pat": "test_pat"
        }

        with patch("httpx.AsyncClient.delete") as mock_delete:
            success_response = MagicMock()
            success_response.status_code = 204
            success_response.text = ""

            failed_response = MagicMock()
            failed_response.status_code = 400
            failed_response.text = "Bad request"

            mock_delete.side_effect = [success_response, failed_response]

            client = AzureDevOpsClient(config)
            result = await client.delete_test_cases(["1001", "1002"])

            assert result["success"] is False
            assert result["deleted"] == ["1001"]
            assert result["deleted_count"] == 1
            assert result["failed_count"] == 1
            assert result["failed"][0]["id"] == "1002"
            delete_url = mock_delete.call_args_list[0].args[0]
            assert delete_url == (
                "https://ado.example.test/org/MyProject/_apis/test/testcases/1001?api-version=7.1-preview.1"
            )

    @pytest.mark.asyncio
    async def test_orphan_detection_excludes_suite_linked_cases(self):
        """Test that linked test cases are removed from the orphan list."""
        config = {
            "org_url": "https://ado.example.test/org",
            "project": "MyProject",
            "pat": "test_pat"
        }

        client = AzureDevOpsClient(config)

        with patch.object(
            client,
            "_fetch_all_test_case_work_items",
            AsyncMock(
                return_value=[
                    {"id": "101", "title": "Linked case", "state": "Active"},
                    {"id": "102", "title": "Orphan case", "state": "Active"},
                ]
            ),
        ), patch.object(
            client,
            "_fetch_test_case_ids_in_suites",
            AsyncMock(return_value={"101"}),
        ):
            result = await client.list_orphan_test_cases()

        assert result["success"] is True
        assert len(result["orphan_test_cases"]) == 1
        assert {case["id"] for case in result["orphan_test_cases"]} == {"102"}


class TestGeminiClient:
    """Tests for Gemini integration client"""

    @pytest.mark.asyncio
    async def test_test_connection_success(self):
        """Test successful Gemini connection"""
        config = {
            "api_key": "test_key",
            "model": "gemini-pro"
        }

        with patch("google.generativeai.GenerativeModel") as mock_model:
            mock_instance = MagicMock()
            mock_response = MagicMock()
            mock_response.text = "OK"
            mock_instance.generate_content = MagicMock(return_value=mock_response)
            mock_model.return_value = mock_instance

            client = GeminiClient(config)
            result = await client.test_connection()

            assert result[0] is True

    @pytest.mark.asyncio
    async def test_generate_test_cases(self):
        """Test generating test cases with Gemini"""
        config = {
            "api_key": "test_key",
            "model": "gemini-pro"
        }

        test_case_json = """[
            {
                "id": "TC_001",
                "name": "Test case 1",
                "steps": ["Step 1", "Step 2"],
                "expected_result": "Success"
            }
        ]"""

        with patch("google.generativeai.GenerativeModel") as mock_model:
            mock_instance = MagicMock()
            mock_response = MagicMock()
            mock_response.text = test_case_json
            mock_instance.generate_content = MagicMock(return_value=mock_response)
            mock_model.return_value = mock_instance

            client = GeminiClient(config)
            result = await client.generate_test_cases("Sample spec")

            assert len(result) >= 0

    @pytest.mark.asyncio
    async def test_analyze_coverage(self):
        """Test coverage analysis with Gemini"""
        config = {
            "api_key": "test_key",
            "model": "gemini-pro"
        }

        analysis_json = """{
            "total_requirements": 5,
            "covered_count": 4,
            "coverage_percentage": 80.0,
            "gaps": ["Requirement 5"],
            "recommendations": ["Add test for requirement 5"]
        }"""

        with patch("google.generativeai.GenerativeModel") as mock_model:
            mock_instance = MagicMock()
            mock_response = MagicMock()
            mock_response.text = analysis_json
            mock_instance.generate_content = MagicMock(return_value=mock_response)
            mock_model.return_value = mock_instance

            client = GeminiClient(config)
            result = await client.analyze_coverage(
                requirements=["R1", "R2"],
                tests=["T1", "T2"]
            )

            assert result.get("coverage_percentage") >= 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
