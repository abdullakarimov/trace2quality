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

    async def get_page(self, page_id: str) -> Optional[dict[str, Any]]:
        """Fetch full page payload including storage body and metadata."""
        try:
            async with httpx.AsyncClient() as client:
                auth = (self.email, self.api_token)
                response = await client.get(
                    f"{self.base_url}/rest/api/content/{page_id}",
                    auth=auth,
                    params={"expand": "body.storage,version,space,ancestors"},
                    timeout=30,
                )
                if response.status_code == 200:
                    return response.json()
                return None
        except Exception as e:
            logger.error(f"Error getting page {page_id}: {str(e)}")
            return None

    async def search_pages(self, cql: str, limit: int = 100) -> list[dict[str, Any]]:
        """Search Confluence pages with CQL and pagination."""
        collected: list[dict[str, Any]] = []
        start = 0
        page_size = min(max(limit, 1), 100)

        try:
            async with httpx.AsyncClient() as client:
                auth = (self.email, self.api_token)
                while len(collected) < limit:
                    response = await client.get(
                        f"{self.base_url}/rest/api/content/search",
                        auth=auth,
                        params={
                            "cql": cql,
                            "limit": page_size,
                            "start": start,
                            "expand": "space",
                        },
                        timeout=30,
                    )
                    if response.status_code != 200:
                        break
                    data = response.json()
                    batch = data.get("results", [])
                    if not batch:
                        break
                    for item in batch:
                        collected.append(
                            {
                                "id": str(item.get("id", "")),
                                "title": item.get("title", ""),
                                "space": item.get("space", {}).get("key", ""),
                                "url": item.get("_links", {}).get("self", ""),
                            }
                        )
                        if len(collected) >= limit:
                            break
                    if len(batch) < page_size:
                        break
                    start += page_size
        except Exception as e:
            logger.error(f"Error searching pages via CQL: {str(e)}")

        return collected

    async def search_pages_by_space(self, limit: int = 250, timeout: int = 15) -> list[dict[str, Any]]:
        """Fetch pages from space using direct /content endpoint (bypasses CQL search limitations).
        
        This method is more reliable than CQL search for discovering all pages in a space,
        as it doesn't have the same pagination/filtering limitations.
        Includes timeout to prevent hanging on slow Confluence instances.
        """
        collected: list[dict[str, Any]] = []
        start = 0
        page_size = min(max(limit, 1), 100)  # Reduced page size for faster responses
        max_batches = min(5, max(1, (limit + page_size - 1) // page_size))  # Limit batches to prevent long waits
        batch_count = 0

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                auth = (self.email, self.api_token)
                while len(collected) < limit and batch_count < max_batches:
                    batch_count += 1
                    try:
                        response = await client.get(
                            f"{self.base_url}/rest/api/content",
                            auth=auth,
                            params={
                                "spaceKey": self.space,
                                "type": "page",
                                "limit": page_size,
                                "start": start,
                                "expand": "space",
                            },
                        )
                        if response.status_code != 200:
                            logger.warning(f"Confluence API returned {response.status_code}, stopping pagination")
                            break
                        data = response.json()
                        batch = data.get("results", [])
                        if not batch:
                            break
                        for item in batch:
                            collected.append(
                                {
                                    "id": str(item.get("id", "")),
                                    "title": item.get("title", ""),
                                    "space": item.get("space", {}).get("key", ""),
                                    "url": item.get("_links", {}).get("self", ""),
                                }
                            )
                            if len(collected) >= limit:
                                break
                        if len(batch) < page_size:
                            break  # Reached end of results
                        start += page_size
                    except httpx.TimeoutException:
                        logger.warning(f"Confluence API timeout during batch {batch_count}, stopping pagination")
                        break
        except Exception as e:
            logger.error(f"Error fetching pages by space: {str(e)}")

        return collected

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

    async def create_page(self, title: str, content: str, parent_id: Optional[str] = None) -> dict[str, Any]:
        """Create a new page in Confluence, optionally as a child of parent_id."""
        try:
            async with httpx.AsyncClient() as client:
                auth = (self.email, self.api_token)
                body: dict[str, Any] = {
                    "type": "page",
                    "title": title,
                    "space": {"key": self.space},
                    "body": {"storage": {"value": content, "representation": "storage"}},
                }
                if parent_id:
                    body["ancestors"] = [{"id": parent_id}]
                response = await client.post(
                    f"{self.base_url}/rest/api/content",
                    auth=auth,
                    json=body,
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

    async def find_page_by_title(self, title: str) -> Optional[dict[str, Any]]:
        """Find a page by exact title in the configured space."""
        try:
            async with httpx.AsyncClient() as client:
                auth = (self.email, self.api_token)
                cql = f'space="{self.space}" and title="{title.replace("\"", "\\\"")}"'
                response = await client.get(
                    f"{self.base_url}/rest/api/content/search",
                    auth=auth,
                    params={"cql": cql, "limit": 1},
                    timeout=30,
                )
                if response.status_code != 200:
                    return None
                results = response.json().get("results", [])
                if not results:
                    return None
                found = results[0]
                return {
                    "id": str(found.get("id")),
                    "title": found.get("title", ""),
                    "url": found.get("_links", {}).get("self", ""),
                }
        except Exception as e:
            logger.error(f"Error finding page by title {title}: {str(e)}")
            return None


__all__ = ["ConfluenceClient"]
