"""Coverage tracking and update workflow"""

from typing import Any
from datetime import datetime

from packages.common import get_logger

logger = get_logger(__name__)


async def update_coverage_pages(
    confluence_client, project: str, test_results: dict[str, Any]
) -> dict[str, Any]:
    """Update Confluence pages with coverage metrics"""
    logger.info(f"Updating coverage pages for project: {project}")

    try:
        coverage_pct = test_results.get("coverage_percentage", 0.0)
        passed_tests = test_results.get("passed_tests", 0)
        total_tests = test_results.get("total_tests", 0)
        
        # Generate HTML content for coverage page
        html_content = f"""
<h2>Coverage Report - {project}</h2>
<p>Generated: {datetime.utcnow().isoformat()}</p>

<h3>Summary</h3>
<table>
  <tr><td><strong>Coverage Percentage</strong></td><td>{coverage_pct:.1f}%</td></tr>
  <tr><td><strong>Tests Passed</strong></td><td>{passed_tests}/{total_tests}</td></tr>
</table>

<h3>Gaps</h3>
<ul>
"""
        gaps = test_results.get("gaps", [])
        if gaps:
            for gap in gaps:
                html_content += f"<li>{gap}</li>\n"
        else:
            html_content += "<li>No gaps identified</li>\n"
        
        html_content += """</ul>

<h3>Recommendations</h3>
<ul>
"""
        recommendations = test_results.get("recommendations", [])
        if recommendations:
            for rec in recommendations:
                html_content += f"<li>{rec}</li>\n"
        else:
            html_content += "<li>Coverage is sufficient</li>\n"
        
        html_content += "</ul>"
        
        # Try to find and update existing coverage page, or create new one
        # For now, we'll just create one
        result = await confluence_client.create_page(
            title=f"Coverage Report - {project}",
            content=html_content
        )
        
        if result.get("success"):
            logger.info(f"Coverage page created: {result.get('page_id')}")
            return {
                "project": project,
                "pages_updated": 1,
                "coverage_percentage": coverage_pct,
                "page_id": result.get("page_id"),
                "status": "success",
                "timestamp": datetime.utcnow().isoformat(),
            }
        else:
            logger.error(f"Failed to create coverage page: {result.get('error')}")
            return {
                "project": project,
                "pages_updated": 0,
                "coverage_percentage": coverage_pct,
                "error": result.get("error"),
                "status": "failed",
                "timestamp": datetime.utcnow().isoformat(),
            }
    except Exception as e:
        logger.error(f"Error updating coverage pages: {str(e)}")
        return {
            "project": project,
            "pages_updated": 0,
            "coverage_percentage": 0.0,
            "error": str(e),
            "status": "failed",
            "timestamp": datetime.utcnow().isoformat(),
        }


async def calculate_coverage_metrics(
    requirements: list[str], tests: list[str]
) -> dict[str, Any]:
    """Calculate coverage metrics"""
    logger.info(f"Calculating coverage metrics for {len(requirements)} requirements")

    try:
        # Simple coverage calculation: a requirement is covered if a test mentions it
        covered_count = 0
        gaps = []
        
        for req in requirements:
            req_lower = req.lower()
            covered = any(req_lower in test.lower() for test in tests)
            if covered:
                covered_count += 1
            else:
                gaps.append(req)
        
        coverage_pct = (covered_count / len(requirements) * 100) if requirements else 0.0
        
        logger.info(f"Coverage: {covered_count}/{len(requirements)} ({coverage_pct:.1f}%)")
        
        return {
            "total_requirements": len(requirements),
            "covered_requirements": covered_count,
            "coverage_percentage": coverage_pct,
            "gaps": gaps,
            "status": "success",
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.error(f"Error calculating coverage metrics: {str(e)}")
        return {
            "total_requirements": len(requirements),
            "covered_requirements": 0,
            "coverage_percentage": 0.0,
            "gaps": requirements,
            "error": str(e),
            "status": "failed",
            "timestamp": datetime.utcnow().isoformat(),
        }


__all__ = [
    "update_coverage_pages",
    "calculate_coverage_metrics",
]
