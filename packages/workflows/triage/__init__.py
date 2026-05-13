"""Bug triage and classification workflow"""

from typing import Any
from datetime import datetime

from packages.common import get_logger

logger = get_logger(__name__)


async def triage_bug_tickets(
    jira_client, project: str, query: str
) -> dict[str, Any]:
    """Triage and classify bug tickets with automation gap detection"""
    logger.info(f"Triaging bug tickets in project: {project} with query: {query}")

    try:
        # Fetch bugs using JQL
        bugs = await jira_client.fetch_issues(query)
        
        triaged_bugs = []
        severity_distribution = {
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 0
        }
        
        for bug in bugs:
            fields = bug.get("fields", {})
            priority = fields.get("priority", {}).get("name", "Medium").lower()
            
            # Map to severity levels
            if priority in ["critical", "blocker"]:
                severity_level = "critical"
            elif priority in ["high"]:
                severity_level = "high"
            elif priority in ["medium", "normal"]:
                severity_level = "medium"
            else:
                severity_level = "low"
            
            severity_distribution[severity_level] += 1
            
            # Classify automation gap
            description = fields.get("description", "")
            is_automation_gap = _detect_automation_gap(description, fields)
            
            triaged_bug = {
                "key": bug.get("key"),
                "summary": fields.get("summary", ""),
                "severity": severity_level,
                "status": fields.get("status", {}).get("name", ""),
                "assignee": fields.get("assignee", {}).get("displayName", "Unassigned"),
                "is_automation_gap": is_automation_gap,
                "gap_confidence": 0.8 if is_automation_gap else 0.0,
                "recommendation": _get_automation_recommendation(is_automation_gap, severity_level),
                "created": fields.get("created", ""),
            }
            
            triaged_bugs.append(triaged_bug)
        
        return {
            "project": project,
            "bugs_processed": len(bugs),
            "bugs_triaged": len(triaged_bugs),
            "severity_distribution": severity_distribution,
            "automation_gaps_found": sum(1 for b in triaged_bugs if b["is_automation_gap"]),
            "bugs": triaged_bugs,
            "status": "success" if bugs else "no_results",
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.error(f"Error triaging bugs: {str(e)}")
        return {
            "project": project,
            "bugs_processed": 0,
            "bugs_triaged": 0,
            "bugs": [],
            "error": str(e),
            "status": "failed",
            "timestamp": datetime.utcnow().isoformat(),
        }


def _detect_automation_gap(description: str, fields: dict[str, Any]) -> bool:
    """Detect if bug represents a potential automation gap"""
    gap_indicators = [
        "manual",
        "could not automate",
        "untested",
        "edge case",
        "integration",
        "data-dependent",
        "timing sensitive",
        "environment specific",
        "not covered by automation",
        "difficult to automate"
    ]
    
    combined_text = f"{description} {fields.get('summary', '')}".lower()
    
    # Check for gap indicators
    for indicator in gap_indicators:
        if indicator in combined_text:
            return True
    
    # Check if in a test-related component
    component = fields.get("components", [])
    if any("test" in str(c).lower() for c in component):
        return True
    
    # Check labels
    labels = fields.get("labels", [])
    if any("bug" in str(l).lower() for l in labels):
        return True
    
    return False


def _get_automation_recommendation(is_gap: bool, severity: str) -> str:
    """Get automation recommendation based on gap and severity"""
    if not is_gap:
        return "Monitor for patterns"
    
    if severity == "critical":
        return "HIGH PRIORITY: Add automated regression test"
    elif severity == "high":
        return "Add integration test for this scenario"
    elif severity == "medium":
        return "Consider adding UI automation test"
    else:
        return "Document as edge case, consider future automation"


async def classify_automation_gap(
    bug: dict[str, Any], test_cases: list[str]
) -> dict[str, Any]:
    """Classify if bug represents automation gap with detailed analysis"""
    logger.info(f"Classifying automation gap for bug: {bug.get('key', 'unknown')}")

    try:
        bug_summary = bug.get("summary", "").lower()
        bug_description = bug.get("description", "").lower()
        combined_text = f"{bug_summary} {bug_description}"
        
        # Check coverage in existing tests
        covered_by_tests = []
        for test in test_cases:
            if any(keyword in test.lower() for keyword in bug_summary.split()):
                covered_by_tests.append(test)
        
        is_gap = len(covered_by_tests) == 0
        
        # Calculate confidence score
        gap_indicators = sum(1 for indicator in [
            "untested",
            "not covered",
            "edge case",
            "integration",
            "manual test"
        ] if indicator in combined_text)
        
        confidence = min(0.95, 0.5 + (gap_indicators * 0.15))
        
        return {
            "bug_key": bug.get("key"),
            "is_automation_gap": is_gap,
            "confidence": confidence,
            "covered_by_tests": covered_by_tests,
            "gap_type": _classify_gap_type(combined_text) if is_gap else "no_gap",
            "recommendation": _get_gap_recommendation(is_gap, confidence),
            "severity": bug.get("priority", "medium"),
            "analysis_timestamp": datetime.utcnow().isoformat(),
            "status": "success",
        }
    except Exception as e:
        logger.error(f"Error classifying gap: {str(e)}")
        return {
            "is_automation_gap": False,
            "confidence": 0.0,
            "recommendation": "Error during classification",
            "error": str(e),
            "status": "failed",
        }


def _classify_gap_type(text: str) -> str:
    """Classify the type of automation gap"""
    if "ui" in text or "ui automation" in text:
        return "UI_AUTOMATION"
    elif "integration" in text or "api" in text:
        return "INTEGRATION_TEST"
    elif "performance" in text or "load" in text:
        return "PERFORMANCE_TEST"
    elif "security" in text or "authentication" in text:
        return "SECURITY_TEST"
    elif "data" in text or "database" in text:
        return "DATA_VALIDATION"
    else:
        return "FUNCTIONAL_TEST"


def _get_gap_recommendation(is_gap: bool, confidence: float) -> str:
    """Get recommendation based on gap classification"""
    if not is_gap:
        return "Gap already covered by existing tests"
    
    if confidence >= 0.8:
        return "URGENT: Add automated test case"
    elif confidence >= 0.6:
        return "HIGH: Recommend adding test automation"
    else:
        return "MEDIUM: Review for automation potential"


__all__ = [
    "triage_bug_tickets",
    "classify_automation_gap",
]
