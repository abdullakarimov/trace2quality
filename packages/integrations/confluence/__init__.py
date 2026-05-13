"""Confluence integration client"""

from typing import Any, Optional

import httpx

from packages.common import IntegrationConnectionStatus, IntegrationType, get_logger
from packages.integrations import IntegrationClient

logger = get_logger(__name__)


class ConfluenceClient(IntegrationClient):
    """Confluence Cloud API client"""

    provider_type = IntegrationType.CONFLUENCE

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self.base_url = config.get("base_url", "https://yourdomain.atlassian.net/wiki")
        self.space = config.get("space", "YOURSPACE")
        self.email = config.get("email", "")
        self.api_token = config.get("api_token", "")

    async def test_connection(self) -> tuple[bool, Optional[str]]:
        """Test connection to Confluence"""
        if not self.api_token or not self.email:
            return False, "API token or email not configured"

        try:
            async with httpx.AsyncClient() as client:
                auth = (self.email, self.api_token)
                response = await client.get(
                    f"{self.base_url}/rest/api/space/{self.space}",
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

    async def fetch_pages_by_label(self, label: str) -> list[dict[str, Any]]:
        """Fetch pages with a specific label from Confluence"""
        try:
            async with httpx.AsyncClient() as client:
                auth = (self.email, self.api_token)
                response = await client.get(
                    f"{self.base_url}/rest/api/content/search?cql=label={label}",
                    auth=auth,
                    timeout=30,
                )
                if response.status_code == 200:
                    data = response.json()
                    return data.get("results", [])
                else:
                    logger.error(f"Failed to fetch pages: {response.text}")
                    return []
        except Exception as e:
            logger.error(f"Error fetching pages by label {label}: {str(e)}")
            return []

    async def fetch_page_content(self, page_id: str) -> str:
        """Fetch page content from Confluence"""
        try:
            async with httpx.AsyncClient() as client:
                auth = (self.email, self.api_token)
                response = await client.get(
                    f"{self.base_url}/rest/api/content/{page_id}?expand=body.storage",
                    auth=auth,
                    timeout=30,
                )
                if response.status_code == 200:
                    data = response.json()
                    return data.get("body", {}).get("storage", {}).get("value", "")
                else:
                    logger.error(f"Failed to fetch page {page_id}: {response.text}")
                    return ""
        except Exception as e:
            logger.error(f"Error fetching page content {page_id}: {str(e)}")
            return ""

    async def update_page_content(self, page_id: str, content: str) -> dict[str, Any]:
        """Update page content in Confluence"""
        try:
            async with httpx.AsyncClient() as client:
                auth = (self.email, self.api_token)
                
                # First, get current version
                get_response = await client.get(
                    f"{self.base_url}/rest/api/content/{page_id}",
                    auth=auth,
                    timeout=30,
                )
                if get_response.status_code != 200:
                    return {"success": False, "error": "Could not fetch page"}
                
                current_version = get_response.json().get("version", {}).get("number", 0)
                
                # Then update
                update_response = await client.put(
                    f"{self.base_url}/rest/api/content/{page_id}",
                    auth=auth,
                    json={
                        "version": {"number": current_version + 1},
                        "title": get_response.json().get("title", ""),
                        "type": "page",
                        "body": {"storage": {"value": content, "representation": "storage"}},
                    },
                    timeout=30,
                )
                
                if update_response.status_code in (200, 201):
                    return {"success": True, "page_id": page_id}
                else:
                    return {"success": False, "error": update_response.text}
        except Exception as e:
            logger.error(f"Error updating page {page_id}: {str(e)}")
            return {"success": False, "error": str(e)}

    async def create_page(self, title: str, content: str) -> dict[str, Any]:
        """Create a new page in Confluence"""
        try:
            async with httpx.AsyncClient() as client:
                auth = (self.email, self.api_token)
                response = await client.post(
                    f"{self.base_url}/rest/api/content",
                    auth=auth,
                    json={
                        "type": "page",
                        "title": title,
                        "space": {"key": self.space},
                        "body": {"storage": {"value": content, "representation": "storage"}},
                    },
                    timeout=30,
                )
                
                if response.status_code in (200, 201):
                    data = response.json()
                    return {"success": True, "page_id": data.get("id"), "url": data.get("_links", {}).get("self", "")}
                else:
                    return {"success": False, "error": response.text}
        except Exception as e:
            logger.error(f"Error creating page {title}: {str(e)}")
            return {"success": False, "error": str(e)}


__all__ = ["ConfluenceClient"]
