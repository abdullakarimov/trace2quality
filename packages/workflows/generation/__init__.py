"""Test generation workflow using Gemini"""

from typing import Any
from datetime import datetime

from packages.common import get_logger

logger = get_logger(__name__)


async def generate_api_test_cases(
    gemini_client, spec: str, project: str, suite: str
) -> dict[str, Any]:
    """Generate API test cases from OpenAPI/specification"""
    logger.info(f"Generating API test cases for project: {project}, suite: {suite}")

    try:
        test_cases = await gemini_client.generate_test_cases(spec, test_type="api")
        
        if not test_cases:
            logger.warning("No test cases generated from Gemini")
            return {
                "project": project,
                "suite": suite,
                "test_type": "api",
                "tests_generated": 0,
                "status": "no_tests",
                "timestamp": datetime.utcnow().isoformat(),
            }
        
        logger.info(f"Generated {len(test_cases)} API test cases")
        return {
            "project": project,
            "suite": suite,
            "test_type": "api",
            "tests_generated": len(test_cases),
            "test_cases": test_cases,
            "status": "success",
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.error(f"Error generating API test cases: {str(e)}")
        return {
            "project": project,
            "suite": suite,
            "test_type": "api",
            "tests_generated": 0,
            "error": str(e),
            "status": "failed",
            "timestamp": datetime.utcnow().isoformat(),
        }


async def generate_ui_test_cases(
    gemini_client, user_story: str, project: str, suite: str
) -> dict[str, Any]:
    """Generate UI test cases from user stories"""
    logger.info(f"Generating UI test cases for project: {project}, suite: {suite}")

    try:
        test_case = await gemini_client.generate_test_case(user_story, test_type="ui")
        
        if not test_case:
            logger.warning("No test case generated from Gemini")
            return {
                "project": project,
                "suite": suite,
                "test_type": "ui",
                "tests_generated": 0,
                "status": "no_tests",
                "timestamp": datetime.utcnow().isoformat(),
            }
        
        logger.info(f"Generated UI test case: {test_case.get('id', 'unknown')}")
        return {
            "project": project,
            "suite": suite,
            "test_type": "ui",
            "tests_generated": 1,
            "test_case": test_case,
            "status": "success",
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.error(f"Error generating UI test cases: {str(e)}")
        return {
            "project": project,
            "suite": suite,
            "test_type": "ui",
            "tests_generated": 0,
            "error": str(e),
            "status": "failed",
            "timestamp": datetime.utcnow().isoformat(),
        }


async def analyze_coverage(
    gemini_client, requirements: list[str], tests: list[str]
) -> dict[str, Any]:
    """Analyze test coverage vs requirements"""
    logger.info(f"Analyzing coverage for {len(requirements)} requirements and {len(tests)} tests")

    try:
        analysis = await gemini_client.analyze_coverage(requirements, tests)
        
        if not analysis:
            logger.warning("No coverage analysis returned from Gemini")
            return {
                "requirements_count": len(requirements),
                "tests_count": len(tests),
                "coverage_percentage": 0.0,
                "gaps": [],
                "status": "no_analysis",
                "timestamp": datetime.utcnow().isoformat(),
            }
        
        coverage_pct = analysis.get("coverage_percentage", 0.0)
        logger.info(f"Coverage analysis complete: {coverage_pct}% covered")
        
        return {
            "requirements_count": analysis.get("total_requirements", len(requirements)),
            "covered_count": analysis.get("covered_count", 0),
            "tests_count": len(tests),
            "coverage_percentage": coverage_pct,
            "gaps": analysis.get("gaps", []),
            "recommendations": analysis.get("recommendations", []),
            "status": "success",
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.error(f"Error analyzing coverage: {str(e)}")
        return {
            "requirements_count": len(requirements),
            "tests_count": len(tests),
            "coverage_percentage": 0.0,
            "gaps": [],
            "error": str(e),
            "status": "failed",
            "timestamp": datetime.utcnow().isoformat(),
        }


__all__ = [
    "generate_api_test_cases",
    "generate_ui_test_cases",
    "analyze_coverage",
]
