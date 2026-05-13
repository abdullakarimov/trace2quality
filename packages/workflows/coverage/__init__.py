"""Coverage tracking and update workflow."""

import asyncio
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from bs4 import BeautifulSoup

from packages.common import get_logger

logger = get_logger(__name__)

# Restrict coverage Azure suite discovery to specific plans only.
_ALLOWED_AZURE_PLAN_IDS = {"438", "2015"}

STUB_CONTENT_THRESHOLD = 260


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _classify_error(exc: Exception) -> str:
    message = str(exc).lower()
    if "validation" in message or "required" in message:
        return "validation_error"
    if "401" in message or "403" in message or "unauthorized" in message:
        return "integration_auth_error"
    if "timeout" in message or "connection" in message or "network" in message:
        return "integration_network_error"
    if "not found" in message:
        return "not_found_error"
    if "gemini" in message or "generate" in message:
        return "generation_error"
    if "publish" in message or "confluence" in message:
        return "publish_error"
    return "unexpected_error"


def _clean_story_text(text: str) -> str:
    lines = []
    for line in (text or "").splitlines():
        lowered = line.strip().lower()
        if not lowered:
            continue
        if "revision history" in lowered:
            continue
        if lowered.startswith("updated by") or lowered.startswith("last modified"):
            continue
        lines.append(line.strip())
    return "\n".join(lines)


def _text_from_html(storage_html: str) -> str:
    soup = BeautifulSoup(storage_html or "", "html.parser")
    return soup.get_text("\n", strip=True)


def _extract_acceptance_criteria(storage_html: str) -> list[str]:
    soup = BeautifulSoup(storage_html or "", "html.parser")
    ac: list[str] = []

    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = row.find_all(["th", "td"])
            if len(cells) < 2:
                continue
            key = cells[0].get_text(" ", strip=True).lower()
            if "acceptance" in key and "criteria" in key:
                value = cells[1].get_text(" ", strip=True)
                if value:
                    ac.append(value)

    if ac:
        return ac

    for bullet in soup.find_all(["li", "p"]):
        text = bullet.get_text(" ", strip=True)
        if text.lower().startswith("ac") or "acceptance criteria" in text.lower():
            ac.append(text)

    return ac


def _extract_code_from_title(title: str) -> Optional[str]:
    if not title:
        return None
    match = re.match(r"^\s*(US-[0-9]+(?:\.[0-9]+)*)\b", title)
    return match.group(1) if match else None


def _extract_mapped_page(entry: Any) -> Optional[dict[str, Any]]:
    if isinstance(entry, dict):
        for id_key in ["tc_page_id", "page_id", "id", "target_page_id"]:
            if entry.get(id_key):
                return {
                    "tc_page_id": str(entry.get(id_key)),
                    "tc_title": (
                        entry.get("tc_title")
                        or entry.get("new_title")
                        or entry.get("title")
                        or ""
                    ),
                }
        if entry.get("tc_title") or entry.get("new_title") or entry.get("title"):
            return {
                "tc_page_id": None,
                "tc_title": (
                    entry.get("tc_title")
                    or entry.get("new_title")
                    or entry.get("title")
                    or ""
                ),
            }
    if isinstance(entry, str):
        if entry.isdigit():
            return {"tc_page_id": entry, "tc_title": ""}
        return {"tc_page_id": None, "tc_title": entry}
    return None


def _inject_tc_tag(title: str) -> str:
    if "| TC |" in title:
        return title
    if "|" in title:
        return re.sub(r"\s*\|\s*", " | TC | ", title, count=1)
    return title


def _build_tc_title(us_code: str, us_title: str) -> str:
    tagged = _inject_tc_tag(us_title)
    if tagged != us_title:
        return tagged
    tail = re.sub(rf"^\s*{re.escape(us_code)}\s*", "", us_title).strip(" |-:")
    return f"{us_code} | TC | {tail}" if tail else f"{us_code} | TC"


def _flatten_us_catalog(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict) and isinstance(raw.get("epics"), list):
        out: list[dict[str, Any]] = []
        for epic in raw.get("epics", []):
            for us in epic.get("user_stories", []):
                out.append(
                    {
                        "id": str(us.get("id") or ""),
                        "title": us.get("title", ""),
                        "story_code": _extract_code_from_title(us.get("title", "") or ""),
                        "epic_id": str(epic.get("id") or ""),
                        "epic_title": epic.get("title", ""),
                    }
                )
        return out
    return []


def _flatten_api_doc_catalog(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict) and isinstance(raw.get("pages"), list):
        return raw.get("pages", [])
    return []


def _build_mapping_indexes(rename_mapping: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    by_us_code: dict[str, Any] = {}
    by_us_id: dict[str, Any] = {}

    if isinstance(rename_mapping, dict):
        for key, value in rename_mapping.items():
            by_us_code[str(key)] = value
        return by_us_code, by_us_id

    if isinstance(rename_mapping, list):
        for entry in rename_mapping:
            if not isinstance(entry, dict):
                continue
            matched_id = entry.get("matched_catalog_id")
            if matched_id:
                by_us_id[str(matched_id)] = entry
            title = str(entry.get("new_title") or entry.get("old_title") or "")
            code = _extract_code_from_title(title)
            if code:
                by_us_code[code] = entry
    return by_us_code, by_us_id


def _suite_ids_for_us(ui_suite_mapping: Any, us_code: str, us_id: Optional[str]) -> list[str]:
    ids: list[str] = []
    if isinstance(ui_suite_mapping, dict):
        raw = ui_suite_mapping.get(us_code)
        if isinstance(raw, list):
            return [str(x) for x in raw]
        if raw:
            return [str(raw)]

    if isinstance(ui_suite_mapping, list):
        for item in ui_suite_mapping:
            if not isinstance(item, dict):
                continue
            if us_id and str(item.get("us_id") or "") == str(us_id):
                if item.get("suite_id"):
                    ids.append(str(item.get("suite_id")))
            elif item.get("us_code") and str(item.get("us_code")) == us_code:
                if item.get("suite_id"):
                    ids.append(str(item.get("suite_id")))
    return list(dict.fromkeys(ids))


async def _fetch_provider_us_pages(confluence_client, log_fn=None) -> list[dict[str, Any]]:
    if log_fn:
        log_fn("INFO", "Searching Confluence for US pages using direct space listing")
    
    # Use direct space listing instead of CQL search (more reliable for finding all pages)
    # Limit to 250 pages with 15-second timeout to prevent hanging on slow Confluence instances
    pages = await confluence_client.search_pages_by_space(limit=250, timeout=15)
    out: list[dict[str, Any]] = []
    page_count = 0
    for page in pages:
        code = _extract_code_from_title(str(page.get("title") or ""))
        if code:
            page_id = str(page.get("id") or "")
            page_title = page.get("title", "")
            # Log at INFO level periodically instead of for every page to reduce DB writes
            page_count += 1
            if page_count % 10 == 0 and log_fn:
                log_fn("DEBUG", f"Processing US page {page_count}: code={code}")
            out.append(
                {
                    "id": page_id,
                    "title": page_title,
                    "story_code": code,
                    "url": page.get("url", ""),
                }
            )
    if log_fn:
        log_fn("INFO", f"Confluence US pages loaded: total={len(out)} pages (scanned {len(pages)} total pages)")
    return out


async def _fetch_provider_api_docs(confluence_client, log_fn=None) -> list[dict[str, Any]]:
    cql = f'space="{confluence_client.space}" and type=page and title ~ "API"'
    if log_fn:
        log_fn("INFO", f"Searching Confluence for API doc pages: CQL={cql}")
    pages = await confluence_client.search_pages(cql, limit=500)
    out = []
    for p in pages:
        if p.get("title"):
            page_id = p.get("id")
            page_title = p.get("title", "")
            if log_fn:
                log_fn("DEBUG", f"Found API doc page: id={page_id} title={page_title}")
            out.append({"id": page_id, "title": page_title})
    if log_fn:
        log_fn("INFO", f"Confluence API doc pages loaded: total={len(out)} pages")
    return out


def _ensure_related_links_section(body_html: str, related_links_html: str) -> str:
    marker = '<h2 id="related-links">Related Links</h2>'
    if marker in body_html:
        head = body_html.split(marker)[0]
        return f"{head}{related_links_html}"
    return f"{body_html}\n{related_links_html}"


def _sanitize_storage_html(raw_html: str) -> str:
    soup = BeautifulSoup(raw_html or "", "html.parser")
    for tag in soup.find_all(["script", "style", "iframe", "object", "embed"]):
        tag.decompose()
    for tag in soup.find_all(True):
        attrs = dict(tag.attrs)
        for attr_name in attrs:
            if attr_name.lower().startswith("on"):
                del tag.attrs[attr_name]
    return str(soup)


def _minimal_storage_html(us_code: str, tc_title: str, message: str) -> str:
    safe_message = message.replace("<", "&lt;").replace(">", "&gt;")
    return (
        f"<h1>{tc_title}</h1>"
        f"<p><strong>User Story:</strong> {us_code}</p>"
        f"<p>{safe_message}</p>"
        f"<p>Generated at {_utc_now_iso()}</p>"
    )


def _default_preview_html(payload: dict[str, Any]) -> str:
    ac_rows = "".join(f"<li>{item}</li>" for item in payload.get("acceptance_criteria", []))
    api_tests = payload.get("api_tests", [])
    ui_tests = payload.get("ui_tests", [])
    api_rows = "".join(f"<li>{t}</li>" for t in api_tests) or "<li>No API tests found</li>"
    ui_rows = "".join(f"<li>{t}</li>" for t in ui_tests) or "<li>No UI tests found</li>"
    return (
        f"<h1>{payload.get('tc_title', 'Coverage Page')}</h1>"
        f"<p><strong>User Story:</strong> {payload.get('us_code')}</p>"
        f"<h2>Acceptance Criteria</h2><ul>{ac_rows or '<li>None extracted</li>'}</ul>"
        f"<h2>API Test Cases</h2><ul>{api_rows}</ul>"
        f"<h2>UI Test Cases</h2><ul>{ui_rows}</ul>"
        f"<h2>API Documentation Match</h2><p>{payload.get('api_doc_title') or 'No strong match found'}</p>"
    )


def _load_json(path: Path) -> Any:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _resolve_story_entry(us_pages: list[dict[str, Any]], us_code: str) -> Optional[dict[str, Any]]:
    for entry in us_pages:
        story_code = str(entry.get("story_code") or entry.get("us_code") or "").strip()
        title_code = _extract_code_from_title(str(entry.get("title") or ""))
        if story_code == us_code or title_code == us_code:
            return entry
    return None


def _build_related_links_html(
    us_record: dict[str, Any],
    jira_links: list[dict[str, str]],
    api_suite_ids: list[str],
    ui_suite_ids: list[str],
    azure_org_url: str,
    azure_project: str,
) -> str:
    us_link = us_record.get("url") or ""
    parts = ['<h2 id="related-links">Related Links</h2>', "<ul>"]
    if us_link:
        parts.append(f'<li><a href="{us_link}">User Story Source</a></li>')

    for issue in jira_links:
        parts.append(f'<li><a href="{issue.get("url", "")}">{issue.get("key", "Jira Task")}</a></li>')

    for suite_id in api_suite_ids:
        suite_url = f"{azure_org_url}/{azure_project}/_testPlans/execute?planId=&suiteId={suite_id}"
        parts.append(f'<li><a href="{suite_url}">Azure API Suite {suite_id}</a></li>')

    for suite_id in ui_suite_ids:
        suite_url = f"{azure_org_url}/{azure_project}/_testPlans/execute?planId=&suiteId={suite_id}"
        parts.append(f'<li><a href="{suite_url}">Azure UI Suite {suite_id}</a></li>')

    parts.append("</ul>")
    return "".join(parts)


async def _safe_match_api_doc(gemini_client, us_text: str, api_docs: list[dict[str, Any]]) -> dict[str, Any]:
    candidates = [str(item.get("title") or "") for item in api_docs if item.get("title")]
    if not candidates:
        return {"api_doc_title": None, "api_doc_id": None}

    try:
        result = await gemini_client.choose_best_match(us_text, candidates)
        title = result.get("title")
    except Exception:
        title = candidates[0]

    matched = next((d for d in api_docs if d.get("title") == title), {})
    return {
        "api_doc_title": title,
        "api_doc_id": matched.get("id") or matched.get("page_id"),
    }


async def _collect_azure_tests(
    azure_client,
    us_code: str,
    mapped_suite_ids: list[str],
    use_cached_azure_snapshot: bool,
    cache_file: Path,
    pre_fetched_snapshot: Optional[dict[str, Any]] = None,
    log_fn=None,
) -> dict[str, Any]:
    """Collect Azure test cases for a US code.
    
    If pre_fetched_snapshot is provided (from batch pre-fetch), use it directly.
    Otherwise, fetch on-demand (single mode behavior).
    """
    snapshot: dict[str, Any] = {}

    # Use pre-fetched snapshot if available (batch mode optimization)
    if pre_fetched_snapshot is not None:
        snapshot = pre_fetched_snapshot
        if log_fn:
            log_fn("DEBUG", f"Using pre-fetched Azure snapshot for {us_code}")
    elif use_cached_azure_snapshot and cache_file.exists():
        snapshot = _load_json(cache_file) or {}
        if log_fn:
            log_fn("DEBUG", f"Loaded Azure snapshot from cache for {us_code}")
    else:
        if log_fn:
            log_fn("INFO", f"Fetching Azure Test Plans for {us_code}...")
        plans = await azure_client.fetch_test_plans()
        plans = [p for p in plans if str(p.get("id") or "") in _ALLOWED_AZURE_PLAN_IDS]
        if log_fn:
            log_fn(
                "DEBUG",
                f"Found {len(plans)} Azure Test Plans after allowlist filter: {sorted(_ALLOWED_AZURE_PLAN_IDS)}",
            )
        for plan in plans:
            plan_id = str(plan.get("id") or "")
            if not plan_id:
                continue
            plan_name = str(plan.get("name") or plan_id)
            if log_fn:
                log_fn("DEBUG", f"Fetching suites for plan {plan_id} ({plan_name})")
            suites = await azure_client.fetch_suites(plan_id)
            if log_fn:
                log_fn("DEBUG", f"Plan {plan_id} has {len(suites)} suites")
            snapshot[plan_id] = suites
        if use_cached_azure_snapshot:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
            if log_fn:
                log_fn("DEBUG", f"Cached Azure snapshot to {cache_file}")

    matched_api_suites: list[dict[str, str]] = []
    matched_ui_suites: list[dict[str, str]] = []
    api_tests: list[str] = []
    ui_tests: list[str] = []

    if log_fn:
        log_fn("INFO", f"Searching Azure suites for {us_code} (mapped_ids={mapped_suite_ids})")
    
    for plan_id, suites in snapshot.items():
        for suite in suites:
            suite_id = str(suite.get("id") or "")
            suite_name = str(suite.get("name") or "")
            if not suite_id:
                continue
            if mapped_suite_ids and suite_id not in mapped_suite_ids:
                continue
            if not mapped_suite_ids and us_code not in suite_name:
                continue

            if log_fn:
                log_fn("DEBUG", f"Fetching test cases from suite {suite_id} ({suite_name}) in plan {plan_id}")
            suite_tests = await azure_client.fetch_test_cases_for_suite(str(plan_id), suite_id)
            titles = [
                str((item.get("workItem") or {}).get("name") or item.get("name") or "")
                for item in suite_tests
            ]
            titles = [t for t in titles if t]

            if log_fn:
                log_fn("DEBUG", f"Suite {suite_id} ({suite_name}): {len(titles)} test cases")
                for i, tc in enumerate(titles[:3], 1):
                    log_fn("DEBUG", f"  Test case {i}: {tc}")
                if len(titles) > 3:
                    log_fn("DEBUG", f"  ... and {len(titles) - 3} more test cases")

            if "api" in suite_name.lower():
                matched_api_suites.append({"id": suite_id, "name": suite_name})
                api_tests.extend(titles)
            else:
                matched_ui_suites.append({"id": suite_id, "name": suite_name})
                ui_tests.extend(titles)

    return {
        "api_tests": api_tests,
        "ui_tests": ui_tests,
        "api_suite_ids": [item["id"] for item in matched_api_suites],
        "ui_suite_ids": [item["id"] for item in matched_ui_suites],
    }


async def _publish_with_fallback(
    confluence_client,
    tc_page_id: Optional[str],
    tc_title: str,
    us_page_id: Optional[str],
    generated_html: str,
    regenerate_once: Callable[[], Any],
) -> dict[str, Any]:
    if tc_page_id and us_page_id and str(tc_page_id) == str(us_page_id):
        raise RuntimeError("Safety abort: tc_page_id equals source US page id")

    if tc_page_id:
        result = await confluence_client.update_page_content(tc_page_id, generated_html)
    else:
        result = await confluence_client.create_page(tc_title, generated_html)

    if result.get("success"):
        return result

    error = str(result.get("error", ""))
    if "already exists" in error.lower() and not tc_page_id:
        existing = await confluence_client.find_page_by_title(tc_title)
        if existing and existing.get("id"):
            return await confluence_client.update_page_content(existing["id"], generated_html)

    if "unsupported" in error.lower() or "extension" in error.lower():
        regenerated = await regenerate_once()
        retry = await (
            confluence_client.update_page_content(tc_page_id, regenerated)
            if tc_page_id
            else confluence_client.create_page(tc_title, regenerated)
        )
        if retry.get("success"):
            return retry

    sanitized = _sanitize_storage_html(generated_html)
    retry_sanitized = await (
        confluence_client.update_page_content(tc_page_id, sanitized)
        if tc_page_id
        else confluence_client.create_page(tc_title, sanitized)
    )
    if retry_sanitized.get("success"):
        return retry_sanitized

    minimal = _minimal_storage_html("unknown", tc_title, "Fallback content due to publish errors")
    return await (
        confluence_client.update_page_content(tc_page_id, minimal)
        if tc_page_id
        else confluence_client.create_page(tc_title, minimal)
    )


async def run_update_coverage_pages_workflow(
    *,
    confluence_client,
    azure_client,
    jira_client,
    gemini_client,
    mode: str,
    us_code: Optional[str],
    apply: bool,
    force: bool,
    batch_delay_seconds: int,
    max_items: Optional[int],
    fail_fast: bool,
    include_debug_artifacts: bool,
    use_cached_azure_snapshot: bool,
    correlation_id: str,
    log_fn: Optional[Callable[[str, str], None]] = None,
) -> dict[str, Any]:
    """Generate/update coverage pages with script-equivalent operational controls."""

    def log(level: str, message: str):
        stamped = f"[{_utc_now_iso()}] [cid={correlation_id}] {message}"
        if log_fn:
            log_fn(level, stamped)
        getattr(logger, level.lower(), logger.info)(stamped)

    root = _project_root()
    data_dir = root / "data"
    catalog_dir = data_dir / "catalog"
    confluence_dir = data_dir / "confluence"
    cache_file = data_dir / "cache" / "azure_full_snapshot.json"

    log("INFO", "Loading provider-first workflow inputs")

    local_us_seed = _flatten_us_catalog(_load_json(catalog_dir / "epic_us_pages.json") or [])
    local_api_seed = _flatten_api_doc_catalog(_load_json(catalog_dir / "api_doc_pages.json") or [])
    rename_mapping = _load_json(confluence_dir / "rename_mapping.json") or {}
    ui_suite_mapping = _load_json(confluence_dir / "ui_suite_us_mapping.json") or {}
    jira_catalog = _load_json(catalog_dir / "jira_qa_tasks.json") or []

    by_us_code_mapping, by_us_id_mapping = _build_mapping_indexes(rename_mapping)

    provider_us_pages = await _fetch_provider_us_pages(confluence_client, log_fn=log)
    provider_api_docs = await _fetch_provider_api_docs(confluence_client, log_fn=log)
    log(
        "INFO",
        f"Confluence catalogs loaded: us_pages={len(provider_us_pages)} api_docs={len(provider_api_docs)}",
    )

    epic_us_pages = provider_us_pages or local_us_seed
    api_doc_pages = provider_api_docs or local_api_seed

    mapped_us_codes: set[str] = set(by_us_code_mapping.keys())
    all_us_codes = [
        str(item.get("story_code") or item.get("us_code") or "").strip()
        for item in epic_us_pages
        if (item.get("story_code") or item.get("us_code"))
    ]
    all_us_codes = [code for code in all_us_codes if code]
    if not all_us_codes:
        all_us_codes = [
            _extract_code_from_title(str(item.get("title") or "")) or ""
            for item in epic_us_pages
        ]
        all_us_codes = [code for code in all_us_codes if code]

    all_us_codes = list(dict.fromkeys(all_us_codes))

    if not all_us_codes:
        raise RuntimeError(
            "No user stories found from Confluence provider, and no local fallback catalog is available"
        )

    if mode == "single":
        target_us_codes = [us_code] if us_code else []
    elif mode == "all_mapped":
        target_us_codes = []
        for code in all_us_codes:
            if code in mapped_us_codes:
                target_us_codes.append(code)
                continue
            us_entry = _resolve_story_entry(epic_us_pages, code)
            if not us_entry:
                continue
            tc_title = _build_tc_title(code, str(us_entry.get("title") or code))
            existing = await confluence_client.find_page_by_title(tc_title)
            if existing and existing.get("id") != str(us_entry.get("id") or ""):
                target_us_codes.append(code)
    else:
        target_us_codes = []
        for code in all_us_codes:
            us_entry = _resolve_story_entry(epic_us_pages, code)
            if not us_entry:
                continue
            tc_title = _build_tc_title(code, str(us_entry.get("title") or code))
            existing = await confluence_client.find_page_by_title(tc_title)
            if code in mapped_us_codes:
                continue
            if existing and existing.get("id") != str(us_entry.get("id") or ""):
                continue
            target_us_codes.append(code)

    if max_items:
        target_us_codes = target_us_codes[:max_items]

    log("INFO", f"Resolved {len(target_us_codes)} user stories for mode={mode}")

    per_item_results: list[dict[str, Any]] = []
    generated_previews: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    # ─────────────────────────────────────────────────────────────────────────────
    # PRE-FETCH AZURE DATA UPFRONT FOR BATCH MODES (Optimize batch performance)
    # ─────────────────────────────────────────────────────────────────────────────
    # Per legacy script behavior: for batch modes, pre-load full Azure snapshot once,
    # then reuse for all USes. Single mode fetches per-US subsets on demand.
    azure_snapshot: dict[str, Any] = {}
    if mode != "single":
        log("INFO", "PRE-FETCHING: Loading full Azure Test Plan snapshot for batch mode")
        if use_cached_azure_snapshot and cache_file.exists():
            azure_snapshot = _load_json(cache_file) or {}
            log("INFO", f"PRE-FETCHING: Loaded Azure snapshot from cache: {len(azure_snapshot)} plans")
            for plan_id, suites in azure_snapshot.items():
                suite_count = len(suites) if isinstance(suites, list) else 0
                log("DEBUG", f"  Plan {plan_id}: {suite_count} suites")
        else:
            try:
                log("INFO", "PRE-FETCHING: Fetching Azure Test Plans...")
                plans = await azure_client.fetch_test_plans()
                plans = [p for p in plans if str(p.get("id") or "") in _ALLOWED_AZURE_PLAN_IDS]
                log(
                    "INFO",
                    f"PRE-FETCHING: Found {len(plans)} plans after allowlist filter: {sorted(_ALLOWED_AZURE_PLAN_IDS)}",
                )
                for plan in plans:
                    plan_id = str(plan.get("id") or "")
                    if not plan_id:
                        continue
                    plan_name = str(plan.get("name") or plan_id)
                    log("INFO", f"PRE-FETCHING: Fetching suites for plan {plan_id} ({plan_name})")
                    suites = await azure_client.fetch_suites(plan_id)
                    log("INFO", f"PRE-FETCHING: Plan {plan_id} has {len(suites)} suites")
                    for i, suite in enumerate(suites[:5], 1):
                        suite_id = str(suite.get("id") or "")
                        suite_name = str(suite.get("name") or "")
                        log("DEBUG", f"  Suite {i}: id={suite_id} name={suite_name}")
                    if len(suites) > 5:
                        log("DEBUG", f"  ... and {len(suites) - 5} more suites")
                    azure_snapshot[plan_id] = suites
                log("INFO", f"PRE-FETCHING: Azure snapshot ready: {len(azure_snapshot)} plans")
                if use_cached_azure_snapshot:
                    cache_file.parent.mkdir(parents=True, exist_ok=True)
                    cache_file.write_text(json.dumps(azure_snapshot, indent=2), encoding="utf-8")
                    log("INFO", f"PRE-FETCHING: Cached snapshot to {cache_file}")
            except Exception as e:
                log("WARNING", f"PRE-FETCHING: Failed to pre-fetch Azure snapshot: {e}")
    else:
        log("INFO", "SINGLE MODE: Azure data will be fetched per-US on demand")

    for index, item_us_code in enumerate(target_us_codes):
        log("INFO", f"Processing {item_us_code} ({index + 1}/{len(target_us_codes)})")
        
        # ─────────────────────────────────────────────────────────────────────────────
        # DATA FLOW ORDER (per legacy script):
        # 1. Resolve US entry from catalog
        # 2. FETCH US page from Confluence (get story text & acceptance criteria)
        # 3. Match API doc via Gemini (using story text)
        # 4. COLLECT test cases from Azure (before LLM generation)
        # 5. Resolve Jira links
        # 6. GENERATE coverage page via Gemini (using all collected data)
        # 7. Publish to Confluence with fallback sanitization
        # ─────────────────────────────────────────────────────────────────────────────
        
        try:
            us_record = _resolve_story_entry(epic_us_pages, item_us_code)
            if not us_record:
                raise RuntimeError(f"User story not found: {item_us_code}")
            log("INFO", f"Resolved user story record for {item_us_code}")

            us_page_id = str(us_record.get("id") or us_record.get("page_id") or "") or None
            provider_page = await confluence_client.get_page(us_page_id) if us_page_id else None
            storage_html = (
                (provider_page or {}).get("body", {}).get("storage", {}).get("value", "")
                or str(us_record.get("storage_html") or "")
            )

            us_text = _clean_story_text(
                str(us_record.get("content") or us_record.get("body") or _text_from_html(storage_html))
            )
            ac_list = _extract_acceptance_criteria(storage_html)
            log("INFO", f"[STEP 2] Fetched US page from Confluence: {item_us_code}: chars={len(us_text)} ac_items={len(ac_list)}")

            mapped_raw = by_us_code_mapping.get(item_us_code)
            if not mapped_raw and us_page_id:
                mapped_raw = by_us_id_mapping.get(us_page_id)
            mapped_entry = _extract_mapped_page(mapped_raw)
            tc_page_id = mapped_entry.get("tc_page_id") if mapped_entry else None
            tc_title = (
                (mapped_entry.get("tc_title") if mapped_entry else None)
                or _build_tc_title(item_us_code, str(us_record.get("title") or item_us_code))
            )

            if not tc_page_id:
                found = await confluence_client.find_page_by_title(tc_title)
                tc_page_id = found.get("id") if found else None
            log("INFO", f"TC target for {item_us_code}: title='{tc_title}' page_id={tc_page_id or 'new'}")

            existing_content = ""
            rewrite_allowed = True
            if tc_page_id:
                existing_content = await confluence_client.fetch_page_content(tc_page_id)
                existing_text = _text_from_html(existing_content)
                is_stub = len(existing_text.strip()) < STUB_CONTENT_THRESHOLD
                rewrite_allowed = is_stub or force
                if not rewrite_allowed:
                    log("INFO", f"Skipping {item_us_code}: existing page has non-stub content and force=false")
                    per_item_results.append(
                        {
                            "us_code": item_us_code,
                            "mode": mode,
                            "action": "skipped",
                            "tc_page_id": tc_page_id,
                            "tc_title": tc_title,
                            "api_doc_title": None,
                            "api_tc_count": 0,
                            "ui_tc_count": 0,
                            "api_suite_ids": [],
                            "ui_suite_ids": [],
                            "message": "Skipped: existing non-stub page and force=false",
                        }
                    )
                    continue

            api_doc_match = await _safe_match_api_doc(gemini_client, us_text, api_doc_pages)
            log("INFO", f"[STEP 3] API doc match (via Gemini) for {item_us_code}: {api_doc_match.get('api_doc_title') or 'none'}")
            suite_ids = _suite_ids_for_us(ui_suite_mapping, item_us_code, us_page_id)
            log("INFO", f"Suite seed mapping for {item_us_code}: {len(suite_ids)} ids")

            # ─────────────────────────────────────────────────────────────────────────────
            # DATA FLOW: Confluence → Azure → LLM
            # Collect Azure test data (pre-fetched in batch mode, on-demand in single mode)
            # ─────────────────────────────────────────────────────────────────────────────
            azure_data = await _collect_azure_tests(
                azure_client=azure_client,
                us_code=item_us_code,
                mapped_suite_ids=suite_ids,
                use_cached_azure_snapshot=use_cached_azure_snapshot,
                cache_file=cache_file,
                pre_fetched_snapshot=azure_snapshot if azure_snapshot else None,
                log_fn=log,
            )
            log(
                "INFO",
                f"[STEP 4] Azure test data collected for {item_us_code}: api_tests={len(azure_data.get('api_tests', []))} ui_tests={len(azure_data.get('ui_tests', []))} "
                f"(from {'pre-fetched snapshot' if mode != 'single' else 'on-demand fetch'})",
            )

            jira_links: list[dict[str, str]] = []
            issues = await jira_client.fetch_issues(f'text ~ "{item_us_code}" AND labels = QA')
            for issue in issues[:5]:
                key = issue.get("key", "Jira Task")
                jira_links.append(
                    {
                        "key": key,
                        "url": f"{jira_client.base_url}/browse/{key}",
                    }
                )
            log("INFO", f"[STEP 5] Jira links resolved for {item_us_code}: {len(jira_links)}")

            if not jira_links and jira_catalog:
                for task in jira_catalog:
                    title = str(task.get("title") or task.get("summary") or "")
                    if item_us_code in title:
                        jira_links.append(
                            {
                                "key": str(task.get("key") or "Jira Task"),
                                "url": str(task.get("url") or ""),
                            }
                        )

            generation_payload = {
                "us_code": item_us_code,
                "us_title": us_record.get("title", ""),
                "tc_title": tc_title,
                "user_story_text": us_text,
                "acceptance_criteria": ac_list,
                "api_doc_title": api_doc_match.get("api_doc_title"),
                "api_tests": azure_data.get("api_tests", []),
                "ui_tests": azure_data.get("ui_tests", []),
                "jira_links": jira_links,
            }

            generated_html = ""
            gemini_ok = False
            for attempt in range(1, 6):
                try:
                    log("INFO", f"[STEP 6] Gemini generation attempt {attempt}/5 for {item_us_code} (using Confluence US + Azure tests + Jira links)")
                    t0 = time.perf_counter()
                    generated_html = await gemini_client.generate_confluence_coverage_page(generation_payload)
                    elapsed_s = round(time.perf_counter() - t0, 2)
                    log("INFO", f"Gemini generation succeeded for {item_us_code} in {elapsed_s}s")
                    gemini_ok = True
                    break
                except Exception as e:
                    err = str(e)
                    retryable = any(token in err for token in ["429", "500", "502", "503", "504", "UNAVAILABLE"])
                    log("WARNING", f"Gemini generation failed on attempt {attempt}/5 for {item_us_code}: {err}")
                    if retryable and attempt < 5:
                        wait_s = attempt * 10
                        log("INFO", f"Retrying Gemini generation for {item_us_code} in {wait_s}s")
                        await asyncio.sleep(wait_s)
                        continue
                    break

            if not gemini_ok:
                log("WARNING", f"Gemini generation fallback used for {item_us_code}")
                generated_html = _default_preview_html(generation_payload)

            related_links_html = _build_related_links_html(
                us_record,
                jira_links,
                azure_data.get("api_suite_ids", []),
                azure_data.get("ui_suite_ids", []),
                getattr(azure_client, "org_url", ""),
                getattr(azure_client, "project", ""),
            )
            generated_html = _ensure_related_links_section(generated_html, related_links_html)

            if include_debug_artifacts:
                generated_previews.append(
                    {
                        "us_code": item_us_code,
                        "tc_title": tc_title,
                        "tc_page_id": tc_page_id,
                        "api_doc_title": api_doc_match.get("api_doc_title"),
                        "api_doc_id": api_doc_match.get("api_doc_id"),
                        "acceptance_criteria": ac_list,
                        "html": generated_html,
                    }
                )

            action = "preview"
            message = "Dry-run preview generated"
            final_page_id = tc_page_id

            if apply:
                log("INFO", f"[STEP 7] Publishing Confluence content for {item_us_code}")
                publish_result = await _publish_with_fallback(
                    confluence_client=confluence_client,
                    tc_page_id=tc_page_id,
                    tc_title=tc_title,
                    us_page_id=us_page_id,
                    generated_html=generated_html,
                    regenerate_once=lambda: gemini_client.generate_confluence_coverage_page(
                        {**generation_payload, "strict_storage": True}
                    ),
                )
                if not publish_result.get("success"):
                    raise RuntimeError(
                        f"Confluence publish failed: {publish_result.get('error', 'unknown error')}"
                    )
                final_page_id = str(publish_result.get("page_id") or tc_page_id or "")
                action = "updated" if tc_page_id else "created"
                message = "Coverage page published"
                log("INFO", f"Publish successful for {item_us_code}: action={action} page_id={final_page_id}")
            else:
                log("INFO", f"Dry-run preview completed for {item_us_code}")

            per_item_results.append(
                {
                    "us_code": item_us_code,
                    "mode": mode,
                    "action": action,
                    "tc_page_id": final_page_id,
                    "tc_title": tc_title,
                    "api_doc_title": api_doc_match.get("api_doc_title"),
                    "api_tc_count": len(azure_data.get("api_tests", [])),
                    "ui_tc_count": len(azure_data.get("ui_tests", [])),
                    "api_suite_ids": azure_data.get("api_suite_ids", []),
                    "ui_suite_ids": azure_data.get("ui_suite_ids", []),
                    "message": message,
                }
            )
        except Exception as exc:
            category = _classify_error(exc)
            error_message = str(exc)
            errors.append(
                {
                    "us_code": item_us_code,
                    "category": category,
                    "message": error_message,
                }
            )
            per_item_results.append(
                {
                    "us_code": item_us_code,
                    "mode": mode,
                    "action": "failed",
                    "tc_page_id": None,
                    "tc_title": f"{item_us_code} - Test Coverage",
                    "api_doc_title": None,
                    "api_tc_count": 0,
                    "ui_tc_count": 0,
                    "api_suite_ids": [],
                    "ui_suite_ids": [],
                    "message": f"{category}: {error_message}",
                }
            )
            log("ERROR", f"Failed processing {item_us_code}: {category} - {error_message}")
            if fail_fast:
                break
        finally:
            if index < len(target_us_codes) - 1 and batch_delay_seconds > 0:
                log("INFO", f"Batch delay: sleeping {batch_delay_seconds}s before next item")
                await asyncio.sleep(batch_delay_seconds)

    total = len(per_item_results)
    succeeded = sum(1 for item in per_item_results if item["action"] in {"updated", "created", "preview"})
    failed = sum(1 for item in per_item_results if item["action"] == "failed")
    skipped = sum(1 for item in per_item_results if item["action"] == "skipped")

    log(
        "INFO",
        f"Run summary: total={total} succeeded={succeeded} failed={failed} skipped={skipped}",
    )

    return {
        "status": "success" if failed == 0 else "partial_failure",
        "mode": mode,
        "summary": {
            "total": total,
            "succeeded": succeeded,
            "failed": failed,
            "skipped": skipped,
        },
        "per_item_results": per_item_results,
        "generated_pages_preview": generated_previews,
        "errors": errors,
    }


async def update_coverage_pages(
    confluence_client, project: str, test_results: dict[str, Any]
) -> dict[str, Any]:
    """Legacy helper for generic coverage page updates."""
    logger.info(f"Updating coverage pages for project: {project}")

    try:
        coverage_pct = test_results.get("coverage_percentage", 0.0)
        passed_tests = test_results.get("passed_tests", 0)
        total_tests = test_results.get("total_tests", 0)

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

        result = await confluence_client.create_page(
            title=f"Coverage Report - {project}", content=html_content
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
    "run_update_coverage_pages_workflow",
    "calculate_coverage_metrics",
]
