"""Reporting and run association workflows"""

from typing import Any
from datetime import datetime
from collections import defaultdict

from packages.common import get_logger

logger = get_logger(__name__)


async def associate_automation_from_run(
    azure_client, run_id: str, confluence_client
) -> dict[str, Any]:
    """Associate test automation results to requirements and update traceability"""
    logger.info(f"Associating automation from run: {run_id}")

    try:
        # Fetch test plans to get test cases
        test_plans = await azure_client.fetch_test_plans()
        
        test_to_requirement_map = {}
        requirement_coverage = defaultdict(list)
        
        for plan in test_plans:
            plan_id = plan.get("id")
            test_suites = await azure_client.fetch_test_cases(plan_id)
            
            for suite in test_suites:
                suite_id = suite.get("id")
                # In a real scenario, we'd fetch actual test cases
                # For now, we map suite to requirements
                
                # Extract requirement IDs from suite name or description
                suite_name = suite.get("name", "").lower()
                for i, part in enumerate(suite_name.split()):
                    if part.startswith("req"):
                        req_id = f"REQ_{i}"
                        requirement_coverage[req_id].append(suite_id)
        
        # Generate traceability matrix
        traceability_matrix = {
            req_id: {
                "covered_by": tests,
                "coverage_percentage": 100.0 if tests else 0.0
            }
            for req_id, tests in requirement_coverage.items()
        }
        
        # Update Confluence with traceability report
        traceability_html = _generate_traceability_html(traceability_matrix)
        
        result = await confluence_client.create_page(
            title=f"Test Traceability Matrix - {run_id}",
            content=traceability_html
        )
        
        if result.get("success"):
            logger.info(f"Traceability matrix created: {result.get('page_id')}")
            return {
                "run_id": run_id,
                "tests_processed": sum(len(v) for v in requirement_coverage.values()),
                "requirements_updated": len(requirement_coverage),
                "traceability_matrix": traceability_matrix,
                "confluence_page_id": result.get("page_id"),
                "status": "success",
                "timestamp": datetime.utcnow().isoformat(),
            }
        else:
            return {
                "run_id": run_id,
                "tests_processed": 0,
                "requirements_updated": 0,
                "error": result.get("error"),
                "status": "failed",
                "timestamp": datetime.utcnow().isoformat(),
            }
    except Exception as e:
        logger.error(f"Error associating automation: {str(e)}")
        return {
            "run_id": run_id,
            "tests_processed": 0,
            "requirements_updated": 0,
            "error": str(e),
            "status": "failed",
            "timestamp": datetime.utcnow().isoformat(),
        }


async def generate_coverage_report(
    project: str, requirements: dict[str, Any], tests: dict[str, Any]
) -> dict[str, Any]:
    """Generate comprehensive coverage report with metrics and recommendations"""
    logger.info(f"Generating coverage report for project: {project}")

    try:
        total_requirements = len(requirements) if isinstance(requirements, dict) else len(requirements) if isinstance(requirements, list) else 0
        total_tests = len(tests) if isinstance(tests, dict) else len(tests) if isinstance(tests, list) else 0
        
        # Calculate coverage by matching requirements to tests
        covered_requirements = 0
        uncovered_requirements = []
        
        req_list = requirements if isinstance(requirements, (list, dict)) else [requirements]
        test_list = tests if isinstance(tests, (list, dict)) else [tests]
        
        for req in req_list:
            req_text = str(req).lower()
            covered = any(req_text in str(t).lower() for t in test_list)
            if covered:
                covered_requirements += 1
            else:
                uncovered_requirements.append(str(req)[:100])
        
        coverage_percentage = (covered_requirements / total_requirements * 100) if total_requirements > 0 else 0.0
        
        # Generate report HTML
        report_html = f"""
<h2>Coverage Report - {project}</h2>
<p>Generated: {datetime.utcnow().isoformat()}</p>

<h3>Executive Summary</h3>
<table>
  <tr><td><strong>Total Requirements</strong></td><td>{total_requirements}</td></tr>
  <tr><td><strong>Total Tests</strong></td><td>{total_tests}</td></tr>
  <tr><td><strong>Covered Requirements</strong></td><td>{covered_requirements}</td></tr>
  <tr><td><strong>Coverage Percentage</strong></td><td>{coverage_percentage:.1f}%</td></tr>
</table>

<h3>Coverage Quality</h3>
<p>Test-to-Requirement Ratio: {(total_tests / total_requirements):.2f}:1</p>
<p>Average Tests per Requirement: {(total_tests / total_requirements) if total_requirements > 0 else 0:.2f}</p>

<h3>Uncovered Requirements</h3>
<ul>
"""
        for req in uncovered_requirements[:10]:
            report_html += f"<li>{req}</li>\n"
        
        if len(uncovered_requirements) > 10:
            report_html += f"<li>... and {len(uncovered_requirements) - 10} more</li>\n"
        
        report_html += """</ul>

<h3>Recommendations</h3>
<ul>
"""
        
        if coverage_percentage < 50:
            report_html += "<li>CRITICAL: Coverage is below 50%. Prioritize test creation.</li>\n"
        if coverage_percentage < 80:
            report_html += "<li>HIGH: Aim for 80%+ coverage. Focus on remaining gaps.</li>\n"
        if total_tests < total_requirements:
            report_html += "<li>Add more test cases for better coverage.</li>\n"
        
        report_html += "</ul>"
        
        return {
            "project": project,
            "report_html": report_html,
            "coverage_percentage": coverage_percentage,
            "total_requirements": total_requirements,
            "covered_requirements": covered_requirements,
            "total_tests": total_tests,
            "uncovered_count": len(uncovered_requirements),
            "status": "success",
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.error(f"Error generating coverage report: {str(e)}")
        return {
            "project": project,
            "coverage_percentage": 0.0,
            "error": str(e),
            "status": "failed",
            "timestamp": datetime.utcnow().isoformat(),
        }


async def generate_test_summary(
    run_id: str, test_results: list[dict[str, Any]]
) -> dict[str, Any]:
    """Generate comprehensive test execution summary with detailed metrics"""
    logger.info(f"Generating test summary for run: {run_id}")

    try:
        total_tests = len(test_results)
        passed = sum(1 for t in test_results if t.get("status") == "passed")
        failed = sum(1 for t in test_results if t.get("status") == "failed")
        skipped = sum(1 for t in test_results if t.get("status") == "skipped")
        
        # Calculate pass rate
        pass_rate = (passed / total_tests * 100) if total_tests > 0 else 0.0
        
        # Group by test type
        by_type = defaultdict(lambda: {"total": 0, "passed": 0, "failed": 0})
        for test in test_results:
            test_type = test.get("type", "unknown")
            by_type[test_type]["total"] += 1
            if test.get("status") == "passed":
                by_type[test_type]["passed"] += 1
            elif test.get("status") == "failed":
                by_type[test_type]["failed"] += 1
        
        # Collect failures
        failures = [
            {
                "test_id": t.get("id"),
                "test_name": t.get("name"),
                "error": t.get("error", "No error message"),
                "type": t.get("type", "unknown")
            }
            for t in test_results if t.get("status") == "failed"
        ]
        
        # Generate summary HTML
        summary_html = f"""
<h2>Test Execution Summary - {run_id}</h2>
<p>Generated: {datetime.utcnow().isoformat()}</p>

<h3>Results</h3>
<table>
  <tr><td><strong>Total Tests</strong></td><td>{total_tests}</td></tr>
  <tr><td><strong>Passed</strong></td><td style="color:green">{passed}</td></tr>
  <tr><td><strong>Failed</strong></td><td style="color:red">{failed}</td></tr>
  <tr><td><strong>Skipped</strong></td><td style="color:orange">{skipped}</td></tr>
  <tr><td><strong>Pass Rate</strong></td><td>{pass_rate:.1f}%</td></tr>
</table>

<h3>Results by Type</h3>
<table>
  <tr><th>Test Type</th><th>Total</th><th>Passed</th><th>Failed</th><th>Pass %</th></tr>
"""
        
        for test_type, stats in by_type.items():
            type_pass_rate = (stats["passed"] / stats["total"] * 100) if stats["total"] > 0 else 0.0
            summary_html += f"""  <tr>
    <td>{test_type}</td>
    <td>{stats['total']}</td>
    <td style="color:green">{stats['passed']}</td>
    <td style="color:red">{stats['failed']}</td>
    <td>{type_pass_rate:.1f}%</td>
  </tr>
"""
        
        summary_html += "</table>"
        
        if failures:
            summary_html += """
<h3>Failures</h3>
<ul>
"""
            for failure in failures[:20]:
                summary_html += f"<li><strong>{failure['test_name']}</strong> ({failure['type']}): {failure['error'][:100]}</li>\n"
            
            if len(failures) > 20:
                summary_html += f"<li>... and {len(failures) - 20} more failures</li>\n"
            
            summary_html += "</ul>"
        
        return {
            "run_id": run_id,
            "total_tests": total_tests,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "pass_rate": pass_rate,
            "by_type": dict(by_type),
            "failures": failures,
            "summary_html": summary_html,
            "status": "success" if failed == 0 else "partial_failures" if failed < total_tests else "all_failed",
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.error(f"Error generating test summary: {str(e)}")
        return {
            "run_id": run_id,
            "total_tests": len(test_results),
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "error": str(e),
            "status": "failed",
            "timestamp": datetime.utcnow().isoformat(),
        }


def _generate_traceability_html(matrix: dict[str, Any]) -> str:
    """Generate HTML for traceability matrix"""
    html = """
<h2>Test Traceability Matrix</h2>
<table>
  <tr>
    <th>Requirement</th>
    <th>Test Cases</th>
    <th>Coverage</th>
  </tr>
"""
    
    for req_id, coverage in matrix.items():
        tests = coverage.get("covered_by", [])
        test_count = len(tests)
        coverage_pct = coverage.get("coverage_percentage", 0.0)
        
        html += f"""  <tr>
    <td><strong>{req_id}</strong></td>
    <td>{test_count} test(s)</td>
    <td>{coverage_pct:.0f}%</td>
  </tr>
"""
    
    html += """</table>
"""
    
    return html


__all__ = [
    "associate_automation_from_run",
    "generate_coverage_report",
    "generate_test_summary",
]
