"""Bug triage workflow: validate Jira bug tickets against user story specs via Gemini."""

import asyncio
import re
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from bs4 import BeautifulSoup

from packages.common import get_logger

logger = get_logger(__name__)

# Default JQL that selects untriaged bugs (can be overridden via parameters)
DEFAULT_BUG_JQL = 'issuetype in ("BE BUG", "Mobile bug", Bug, "FE bug") AND status = Backlog'

# Default JIRA custom field IDs (discoverable via /rest/api/3/issue/createmeta)
DEFAULT_SEVERITY_FIELD_ID = "customfield_10865"
DEFAULT_IMPACT_FIELD_ID = "customfield_10004"

# Status to transition confirmed bugs into
DEFAULT_TARGET_STATUS = "Triage"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_us_number(issue_title: str) -> Optional[str]:
    """Extract a user-story number like '11.1.2' from an issue title.

    Matches 'US-X.Y.Z', 'US: X.Y.Z', or 'US X.Y.Z' but not 'AUS-X.Y.Z'.
    Returns the dotted number string (e.g. '11.1.2'), not the full 'US-' token.
    """
    match = re.search(r"(?:^|[^\w])US[:\s-]*([\d]+(?:\.[\d]+)*)", issue_title)
    return match.group(1) if match else None


def _text_from_html(storage_html: str) -> str:
    """Convert Confluence storage-format HTML to plain text."""
    soup = BeautifulSoup(storage_html or "", "html.parser")
    return soup.get_text("\n", strip=True)


async def _find_us_confluence_page(
    confluence_client,
    us_number: str,
    log_fn: Optional[Callable] = None,
) -> Optional[str]:
    """Search Confluence for a page whose title contains 'US-{us_number}' exactly.

    Returns the page ID if found, else None.

    Strategy (most to least precise):
    1. Quoted-phrase CQL: title ~ '"US-{us_number}"' — avoids Lucene tokenisation splitting
       dots/hyphens, so '11.1.2' is matched as a single phrase.
    2. Broad CQL on the major part (e.g. 'US-11') with Python-side regex filtering —
       handles cases where the Confluence analyser still can't match the dotted phrase.
    """
    pattern = re.compile(rf"\bUS-{re.escape(us_number)}\b", re.IGNORECASE)
    space_filter = (
        f' AND space = "{confluence_client.space}"' if getattr(confluence_client, "space", None) else ""
    )

    async def _search_and_collect(cql: str) -> list[dict]:
        """Run CQL and return all pages whose title matches the pattern."""
        if log_fn:
            log_fn("DEBUG", f"Searching Confluence for US-{us_number}: CQL={cql}")
        try:
            pages = await confluence_client.search_pages(cql, limit=50)
        except Exception as exc:
            if log_fn:
                log_fn("WARNING", f"Confluence search failed ({cql!r}): {exc}")
            return []
        return [p for p in pages if pattern.search(str(p.get("title") or ""))]

    def _best_match(pages: list[dict]) -> Optional[str]:
        """From multiple matching pages prefer the main spec (not API sub-pages)."""
        if not pages:
            return None
        # Prefer pages that don't have ' API' immediately after the US number
        api_pat = re.compile(rf"US-{re.escape(us_number)}\s+API", re.IGNORECASE)
        preferred = [p for p in pages if not api_pat.search(str(p.get("title") or ""))]
        candidates = preferred if preferred else pages
        # Among candidates pick shortest title — most likely the canonical spec page
        best = min(candidates, key=lambda p: len(str(p.get("title") or "")))
        page_id = str(best.get("id") or "")
        if log_fn:
            log_fn("DEBUG", f"Selected Confluence page id={page_id} title={best.get('title')!r} (from {len(pages)} match(es))")
        return page_id or None

    # Strategy 1: quoted-phrase CQL (exact phrase, immune to tokenisation)
    quoted_us = f"US-{us_number}".replace('"', '\\"')
    cql1 = f'type=page AND title ~ "\\"{quoted_us}\\""' + space_filter
    matches = await _search_and_collect(cql1)
    result = _best_match(matches)
    if result:
        return result

    # Strategy 2: broad search on the major segment + Python-side exact filter
    major = us_number.split(".")[0]
    cql2 = f'type=page AND title ~ "US-{major}"' + space_filter
    matches = await _search_and_collect(cql2)
    result = _best_match(matches)
    if result:
        return result

    if log_fn:
        log_fn("WARNING", f"No Confluence page found for US-{us_number}")
    return None


def _extract_description_text(issue: dict[str, Any]) -> str:
    """Extract plain-text description from a Jira issue (ADF or plain string)."""
    description = (issue.get("fields") or {}).get("description") or ""
    if isinstance(description, dict):
        # Atlassian Document Format — walk the content tree
        parts: list[str] = []

        def _walk(node: Any) -> None:
            if isinstance(node, dict):
                if node.get("type") == "text":
                    parts.append(str(node.get("text") or ""))
                for child in node.get("content") or []:
                    _walk(child)
            elif isinstance(node, list):
                for item in node:
                    _walk(item)

        _walk(description)
        return " ".join(parts).strip()
    return str(description).strip()


async def run_triage_bugs_workflow(
    jira_client,
    confluence_client,
    gemini_client,
    *,
    jql: str = DEFAULT_BUG_JQL,
    max_results: int = 50,
    apply: bool = False,
    severity_field_id: str = DEFAULT_SEVERITY_FIELD_ID,
    impact_field_id: str = DEFAULT_IMPACT_FIELD_ID,
    target_status: str = DEFAULT_TARGET_STATUS,
    batch_delay_seconds: int = 10,
    correlation_id: Optional[str] = None,
    log_fn: Optional[Callable[[str, str], None]] = None,
) -> dict[str, Any]:
    """Triage Jira bug tickets using Confluence user-story specs and Gemini LLM assessment.

    For each bug matched by `jql`:
      1. Extract the US number from the issue summary.
      2. Fetch the corresponding user-story page from Confluence.
      3. Send the spec + bug details to Gemini for severity/impact classification.
      4. If `apply=True` and the LLM confirms it is a real bug:
         - Update the Jira issue with severity and impact custom fields.
         - Transition the issue to `target_status`.
         - Add a triage comment summarising the assessment.

    Returns a structured summary dict suitable for artifact persistence.
    """

    def _log(level: str, msg: str) -> None:
        logger.info(msg) if level == "INFO" else logger.warning(msg) if level == "WARNING" else logger.debug(msg)
        if log_fn:
            log_fn(level, msg)

    _log("INFO", f"Triage workflow started: jql={jql!r}, max_results={max_results}, apply={apply}")

    # ── 1. Fetch bug issues from Jira ──────────────────────────────────────────
    try:
        issues = await jira_client.fetch_bugs(jql, max_results=max_results)
    except Exception as exc:
        _log("ERROR", f"Failed to fetch bugs from Jira: {exc}")
        return {
            "status": "failed",
            "error": str(exc),
            "bugs_fetched": 0,
            "bugs_triaged": 0,
            "per_issue_results": [],
            "timestamp": _utc_now_iso(),
        }

    _log("INFO", f"Fetched {len(issues)} bug issues from Jira")

    per_issue_results: list[dict[str, Any]] = []
    triaged_count = 0
    skipped_no_us = 0
    skipped_no_confluence = 0
    skipped_not_real = 0
    error_count = 0

    # ── 2. Process each issue ──────────────────────────────────────────────────
    for idx, issue in enumerate(issues, 1):
        issue_key = str(issue.get("key") or "")
        fields = issue.get("fields") or {}
        summary = str(fields.get("summary") or "")
        status_name = str((fields.get("status") or {}).get("name") or "")

        _log("INFO", f"[{idx}/{len(issues)}] Processing {issue_key}: {summary[:70]}")

        result: dict[str, Any] = {
            "key": issue_key,
            "summary": summary,
            "status_before": status_name,
            "outcome": "skipped",
            "reason": "",
            "severity": None,
            "impact": None,
            "priority": None,
            "is_real_bug": None,
            "reasoning": "",
            "updated": False,
        }

        # 2a. Extract US number
        us_number = _extract_us_number(summary)
        if not us_number:
            _log("WARNING", f"  No US number found in title, skipping")
            result["reason"] = "no_us_number_in_title"
            per_issue_results.append(result)
            skipped_no_us += 1
            continue

        # 2b. Find Confluence page for this US
        page_id = await _find_us_confluence_page(confluence_client, us_number, log_fn=_log)
        if not page_id:
            _log("WARNING", f"  Confluence page not found for US-{us_number}, skipping")
            result["reason"] = f"confluence_page_not_found_for_US-{us_number}"
            per_issue_results.append(result)
            skipped_no_confluence += 1
            continue

        # 2c. Fetch page content
        try:
            raw_html = await confluence_client.fetch_page_content(page_id)
            us_text = _text_from_html(raw_html)
        except Exception as exc:
            _log("WARNING", f"  Failed to fetch Confluence page {page_id}: {exc}")
            result["reason"] = f"confluence_fetch_error: {exc}"
            result["outcome"] = "error"
            per_issue_results.append(result)
            error_count += 1
            continue

        if not us_text.strip():
            _log("WARNING", f"  Confluence page {page_id} returned empty content, skipping")
            result["reason"] = "confluence_page_empty"
            per_issue_results.append(result)
            skipped_no_confluence += 1
            continue

        # 2d. Rate-limit delay before Gemini call (skip for the first issue)
        if idx > 1 and batch_delay_seconds > 0:
            _log("DEBUG", f"  Waiting {batch_delay_seconds}s before Gemini call")
            await asyncio.sleep(batch_delay_seconds)

        # 2e. Gemini assessment
        bug_description = _extract_description_text(issue)
        _log("INFO", f"  Assessing bug with Gemini (US-{us_number}, page_id={page_id})")
        try:
            assessment = await gemini_client.assess_bug(
                us_content=us_text,
                bug_title=summary,
                bug_description=bug_description,
            )
        except Exception as exc:
            _log("WARNING", f"  Gemini assessment failed: {exc}")
            result["reason"] = f"gemini_error: {exc}"
            result["outcome"] = "error"
            per_issue_results.append(result)
            error_count += 1
            continue

        result["is_real_bug"] = assessment.get("is_real_bug")
        result["severity"] = assessment.get("severity")
        result["impact"] = assessment.get("impact")
        result["priority"] = assessment.get("priority")
        result["reasoning"] = assessment.get("reasoning", "")

        if not assessment.get("is_real_bug"):
            _log("INFO", f"  Not a real bug — no Jira changes. Reason: {assessment.get('reasoning')}")
            result["outcome"] = "not_real_bug"
            result["reason"] = assessment.get("reasoning", "")
            per_issue_results.append(result)
            skipped_not_real += 1
            continue

        severity = str(assessment.get("severity") or "Major")
        impact = str(assessment.get("impact") or "Moderate / Limited")
        priority = str(assessment.get("priority") or "Medium")
        _log("INFO", f"  Real bug confirmed — severity={severity}, impact={impact}, priority={priority}")
        _log("INFO", f"  Reasoning: {assessment.get('reasoning')}")

        # 2f. Apply updates (or dry-run)
        if not apply:
            _log("INFO", f"  [DRY-RUN] Would update {issue_key}: severity={severity}, impact={impact}, priority={priority}, status={target_status}")
            result["outcome"] = "dry_run"
            result["updated"] = False
            per_issue_results.append(result)
            triaged_count += 1
            continue

        update_ok = False
        try:
            update_resp = await jira_client.update_issue(
                issue_key,
                {
                    "fields": {
                        severity_field_id: {"value": severity},
                        impact_field_id: {"value": impact},
                        "priority": {"name": priority},
                    }
                },
            )
            update_ok = bool(update_resp.get("success"))
            if not update_ok:
                _log("WARNING", f"  Field update failed: {update_resp.get('error')}")
        except Exception as exc:
            _log("WARNING", f"  Field update raised: {exc}")

        transition_ok = False
        try:
            transition_ok = await jira_client.transition_issue(issue_key, target_status)
            if not transition_ok:
                _log("WARNING", f"  Transition to '{target_status}' failed or not available")
        except Exception as exc:
            _log("WARNING", f"  Transition raised: {exc}")

        comment_text = (
            f"Triaged by automated system:\n"
            f"- Severity: {severity}\n"
            f"- Impact: {impact}\n"
            f"- Priority: {priority}\n"
            f"- Reason: {assessment.get('reasoning', '')}"
        )
        try:
            await jira_client.add_comment(issue_key, comment_text)
        except Exception as exc:
            _log("WARNING", f"  Comment failed: {exc}")

        result["updated"] = update_ok or transition_ok
        result["outcome"] = "triaged" if result["updated"] else "partial_update"
        per_issue_results.append(result)
        triaged_count += 1

    # ── 3. Build summary ───────────────────────────────────────────────────────
    summary_data = {
        "bugs_fetched": len(issues),
        "bugs_triaged": triaged_count,
        "skipped_no_us_number": skipped_no_us,
        "skipped_no_confluence_page": skipped_no_confluence,
        "skipped_not_real_bug": skipped_not_real,
        "errors": error_count,
        "apply": apply,
        "jql": jql,
        "target_status": target_status,
    }

    _log(
        "INFO",
        f"Triage complete: triaged={triaged_count}/{len(issues)}, "
        f"not_real={skipped_not_real}, no_us={skipped_no_us}, "
        f"no_confluence={skipped_no_confluence}, errors={error_count}",
    )

    return {
        "status": "succeeded",
        "summary": summary_data,
        "per_issue_results": per_issue_results,
        "timestamp": _utc_now_iso(),
        "correlation_id": correlation_id,
    }

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
