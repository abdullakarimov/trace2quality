"""Google Gemini integration client using the google-genai SDK"""

import json
from typing import Any, Optional

from google import genai

from packages.common import IntegrationConnectionStatus, IntegrationType, get_logger
from packages.integrations import IntegrationClient

logger = get_logger(__name__)


class GeminiClient(IntegrationClient):
    """Google Gemini API client for test case generation"""

    provider_type = IntegrationType.GEMINI

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self.api_key = config.get("api_key", "")
        self.model = config.get("model", "gemini-2.0-flash")
        self._client: Optional[genai.Client] = (
            genai.Client(api_key=self.api_key) if self.api_key else None
        )

    async def _generate(self, prompt: str) -> Optional[str]:
        """Generate content using the google-genai SDK asynchronously."""
        if not self._client:
            return None
        response = await self._client.aio.models.generate_content(
            model=self.model,
            contents=prompt,
        )
        return response.text

    async def test_connection(self) -> tuple[bool, Optional[str]]:
        """Test connection to Gemini."""
        if not self.api_key:
            return False, "API key not configured"
        try:
            text = await self._generate("Say 'OK' if you can read this.")
            if text:
                return True, None
            return False, "Empty response from Gemini"
        except Exception as e:
            return False, str(e)

    async def get_health_status(self) -> IntegrationConnectionStatus:
        """Get current health status."""
        if not self.api_key:
            return IntegrationConnectionStatus.UNCONFIGURED
        success, _ = await self.test_connection()
        return (
            IntegrationConnectionStatus.HEALTHY
            if success
            else IntegrationConnectionStatus.UNHEALTHY
        )

    def _parse_json(self, text: str) -> Any:
        """Extract and parse JSON that may be wrapped in markdown code fences."""
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        return json.loads(text.strip())

    async def generate_test_cases(
        self, spec: str, test_type: str = "api"
    ) -> list[dict[str, Any]]:
        """Generate multiple test cases from a specification"""
        if not self.api_key:
            logger.error("Gemini API key not configured")
            return []

        prompt = f"""Generate {test_type.upper()} test cases for the following specification:

{spec}

Return a JSON array of test case objects with these fields:
- id: unique identifier (e.g., TC_001)
- name: test case name
- description: what is being tested
- preconditions: setup required
- steps: list of action steps
- expected_result: expected outcome
- priority: HIGH, MEDIUM, or LOW
- tags: array of relevant tags

Return ONLY valid JSON array, no markdown or code blocks."""

        try:
            text = await self._generate(prompt)
            if text:
                try:
                    result = self._parse_json(text)
                    return result if isinstance(result, list) else [result]
                except json.JSONDecodeError:
                    logger.error(f"Failed to parse Gemini response as JSON: {text}")
            return []
        except Exception as e:
            logger.error(f"Error generating test cases: {str(e)}")
            return []

    async def generate_test_case(
        self, user_story: str, test_type: str = "ui"
    ) -> dict[str, Any]:
        """Generate a single test case from a user story"""
        if not self.api_key:
            logger.error("Gemini API key not configured")
            return {}

        prompt = f"""Create a single {test_type.upper()} test case for this user story:

{user_story}

Return a JSON object with:
- id: unique identifier
- name: test case name
- description: detailed description
- preconditions: list of prerequisites
- steps: ordered list of test steps with expected results for each
- expected_result: final expected outcome
- priority: HIGH, MEDIUM, or LOW
- tags: array of tags

Return ONLY valid JSON, no markdown."""

        try:
            text = await self._generate(prompt)
            if text:
                try:
                    return self._parse_json(text)
                except json.JSONDecodeError:
                    logger.error(f"Failed to parse Gemini response: {text}")
            return {}
        except Exception as e:
            logger.error(f"Error generating test case: {str(e)}")
            return {}

    async def analyze_coverage(
        self, requirements: list[str], tests: list[str]
    ) -> dict[str, Any]:
        """Analyze test coverage vs requirements"""
        if not self.api_key:
            logger.error("Gemini API key not configured")
            return {}

        prompt = f"""Analyze test coverage for these requirements:

REQUIREMENTS:
{chr(10).join(f"- {r}" for r in requirements)}

TESTS:
{chr(10).join(f"- {t}" for t in tests)}

Provide a JSON analysis with:
- total_requirements: number of requirements
- covered_count: how many are covered
- coverage_percentage: percent covered
- gaps: list of uncovered requirements
- recommendations: list of suggested improvements

Return ONLY valid JSON."""

        try:
            text = await self._generate(prompt)
            if text:
                try:
                    return self._parse_json(text)
                except json.JSONDecodeError:
                    logger.error(f"Failed to parse coverage analysis: {text}")
            return {}
        except Exception as e:
            logger.error(f"Error analyzing coverage: {str(e)}")
            return {}


__all__ = ["GeminiClient"]
