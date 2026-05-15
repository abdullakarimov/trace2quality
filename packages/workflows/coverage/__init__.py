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

API_PLAN_ID = 2015
UI_PLAN_ID = 438

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

    _AC_ID_RE = re.compile(r"^A[CС]-?\d+$", re.IGNORECASE)

    for table in soup.find_all("table"):
        rows = table.find_all("tr")

        # Strategy 1: table whose first-column cells are AC-XX IDs.
        # Collect all data rows where the first cell matches the AC-ID pattern,
        # then build "AC-XX: <description>" entries from the second cell.
        ac_rows: list[str] = []
        for row in rows:
            cells = row.find_all(["th", "td"])
            if len(cells) < 2:
                continue
            key = cells[0].get_text(" ", strip=True).strip()
            if _AC_ID_RE.match(key):
                description = cells[1].get_text(" ", strip=True)
                if description:
                    ac_rows.append(f"{key}: {description}")
        if ac_rows:
            ac.extend(ac_rows)
            continue

        # Strategy 2: English "acceptance criteria" two-column table (legacy format).
        for row in rows:
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

    # Fallback: scan paragraphs/list-items that start with an AC identifier.
    for bullet in soup.find_all(["li", "p"]):
        text = bullet.get_text(" ", strip=True)
        if re.match(r"A[CС]-?\d+", text, re.IGNORECASE) or "acceptance criteria" in text.lower():
            ac.append(text)

    return ac


def _extract_code_from_title(title: str) -> Optional[str]:
    if not title:
        return None
    match = re.search(r"\b(US-[0-9]+(?:\.[0-9]+)*)\b", title, flags=re.IGNORECASE)
    return match.group(1) if match else None


def _extract_epic_token_from_title(title: str) -> str:
    """Extract a compact epic marker (e.g. E3, EA1) from a title like '[E3]: ...'."""
    if not title:
        return ""
    match = re.search(r"\[\s*([A-Z]+\d+(?:-\d+)?)\s*\]", title, flags=re.IGNORECASE)
    return match.group(1).upper() if match else ""


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


_API_DOC_TITLE_RE = re.compile(r"\bAPI(?:\s+v?\d+(?:\.\d+)*)?\s*$", re.IGNORECASE)

# Cache so we don't search Confluence repeatedly for the same epic folder within a run.
_epic_tc_parent_cache: dict[str, Optional[str]] = {}


def _is_archived_title(title: str) -> bool:
    """Return True when the title contains an archive marker like '[Архив]'."""
    return bool(re.search(r"\[\s*[АаAa]рхив\s*\]", title, flags=re.IGNORECASE))


def _is_api_doc_title(title: str) -> bool:
    """Return True when the title looks like an API-documentation page rather than a US spec.

    Pages such as "US-9.1.1 | Базовый счет API" match this because they end with
    the standalone word "API" (optionally followed by a version like "API v2").
    Pure user-story spec pages ("US-9.1.1 | Базовый счет") do not.
    """
    return bool(_API_DOC_TITLE_RE.search(title))


def _api_score(t: str) -> int:
    """Lower is better (more spec-like).  Used to prefer US-spec pages over API-doc pages."""
    if _is_api_doc_title(t):
        return 2
    desc = t.split("|", 1)[-1] if "|" in t else t
    if re.search(r"\bAPI\b", desc, re.IGNORECASE):
        return 1
    return 0


def _epic_number_from_us_code(us_code: str) -> Optional[str]:
    """Return the top-level epic number from a US code.

    "US-9.1.1" → "9",  "US-12.3" → "12",  "US-9" → "9".
    """
    m = re.match(r"US-(\d+)", us_code, flags=re.IGNORECASE)
    return m.group(1) if m else None


async def _find_epic_tc_parent_id(confluence_client, us_code: str, log_fn=None) -> Optional[str]:
    """Return the Confluence page ID of the epic-level TC folder for *us_code*.

    Looks for a page whose title starts with "E-{n} | TC" (e.g. "E-9 | TC | …").
    Results are cached per epic number for the lifetime of the current process.
    """
    epic_num = _epic_number_from_us_code(us_code)
    if not epic_num:
        return None

    cache_key = f"{getattr(confluence_client, 'space', '')}:E-{epic_num}"
    if cache_key in _epic_tc_parent_cache:
        return _epic_tc_parent_cache[cache_key]

    # CQL title search — no type filter so both pages AND folders are matched.
    # Confluence Cloud folders have type="folder" and are excluded when type=page is used.
    # Use contains (~) searches to avoid CQL issues with Cyrillic homoglyphs:
    #   Е (U+0415) vs E,  Т (U+0422) vs T,  С (U+0421) vs C.
    # Two OR branches cover Latin "TC" and Cyrillic "ТС".
    cql = (
        f'space="{confluence_client.space}" '
        f'AND (title ~ "{epic_num} | TC" OR title ~ "{epic_num} | ТС")'
    )
    pages = await confluence_client.search_pages(cql, limit=10)
    parent_id: Optional[str] = None
    # Match "E-9 | TC" or "Е-9 | ТС" — any mix of Latin/Cyrillic E, T, C.
    pattern = re.compile(
        rf"^[EЕ]-{re.escape(epic_num)}\s*\|\s*[TТ][CС]\b", flags=re.IGNORECASE
    )
    for page in pages:
        title = str(page.get("title") or "")
        if pattern.match(title):
            parent_id = str(page.get("id") or "") or None
            if log_fn:
                log_fn("INFO", f"Found epic TC parent for E-{epic_num}: id={parent_id} title='{title}'")
            break

    _epic_tc_parent_cache[cache_key] = parent_id
    if not parent_id and log_fn:
        log_fn("WARNING", f"No epic TC parent page found for E-{epic_num} (US code: {us_code})")
    return parent_id


async def _fetch_provider_us_pages(confluence_client, log_fn=None) -> list[dict[str, Any]]:
    if log_fn:
        log_fn("INFO", "Searching Confluence for US pages using CQL title search")

    # Use CQL to search only for pages whose title contains "US-" instead of listing
    # all pages in the space. This avoids the batch-count cap and finds every US page
    # regardless of where it appears in the space's default sort order.
    cql = f'space="{confluence_client.space}" AND type=page AND title ~ "US-"'
    pages = await confluence_client.search_pages(cql, limit=500)

    # Deduplicate by US code.  When both an API-doc page ("US-X | … API") and a plain
    # US-spec page ("US-X | …") share the same code, prefer the spec page so that
    # tc_title derivation doesn't inherit the "API" suffix.
    #
    # Preference order (highest wins):
    #   1. Not an API-doc title  (no trailing "API" word)
    #   2. Not containing "API" as a standalone word at all in the description part
    #   3. Shorter title (fewer characters — spec pages tend to be shorter)

    by_code: dict[str, dict[str, Any]] = {}
    for page in pages:
        title = str(page.get("title") or "")
        if _is_archived_title(title):
            continue
        code = _extract_code_from_title(title)
        if not code:
            continue
        entry = {
            "id": str(page.get("id") or ""),
            "title": title,
            "story_code": code,
            "url": page.get("url", ""),
        }
        existing = by_code.get(code)
        if existing is None:
            by_code[code] = entry
        else:
            # Prefer the more spec-like entry; on tie, prefer the shorter title
            if _api_score(entry["title"]) < _api_score(existing["title"]):
                by_code[code] = entry
            elif _api_score(entry["title"]) == _api_score(existing["title"]) and len(entry["title"]) < len(existing["title"]):
                by_code[code] = entry

    out = list(by_code.values())
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
    """Strip any existing section 4 from body_html and append the canonical links block."""
    marker = "<h2>4. Связанные ссылки</h2>"
    if marker in body_html:
        body_html = body_html.split(marker)[0].strip()
    return f"{body_html.strip()}\n{related_links_html}"


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
        "<h2>1. Покрытие критериев приёмки</h2>"
        "<table>"
        "<tr><th>Критерий приёмки</th><th>Покрывающие тест-кейсы</th><th>Статус</th></tr>"
        "</table>"
        "<h2>2. Пробелы в покрытии</h2>"
        f"<p>{safe_message}</p>"
        "<h2>3. Итоговая сводка</h2>"
        "<table>"
        "<tr><th>Метрика</th><th>Значение</th></tr>"
        "<tr><td>Всего критериев приёмки</td><td>0</td></tr>"
        "<tr><td>Покрыто полностью</td><td>0</td></tr>"
        "<tr><td>Покрыто частично</td><td>0</td></tr>"
        "<tr><td>Не покрыто</td><td>0</td></tr>"
        "<tr><td>API тест-кейсов</td><td>0</td></tr>"
        "<tr><td>UI тест-кейсов</td><td>0</td></tr>"
        "</table>"
        f"<p><strong>US:</strong> {us_code} | <strong>TC:</strong> {tc_title}</p>"
        f"<p>Сгенерировано: {_utc_now_iso()}</p>"
    )


def _default_preview_html(payload: dict[str, Any]) -> str:
    ac_rows = "".join(f"<li>{item}</li>" for item in payload.get("acceptance_criteria", []))
    api_tests = payload.get("api_tests", [])
    ui_tests = payload.get("ui_tests", [])
    api_rows = "".join(f"<li>{t}</li>" for t in api_tests) or "<li>Нет API тест-кейсов</li>"
    ui_rows = "".join(f"<li>{t}</li>" for t in ui_tests) or "<li>Нет UI тест-кейсов</li>"
    return (
        "<h2>1. Покрытие критериев приёмки</h2>"
        "<table>"
        "<tr><th>Критерий приёмки</th><th>Покрывающие тест-кейсы</th><th>Статус</th></tr>"
        f"<tr><td>{(ac_rows or '<li>Нет явного списка AC</li>').replace('<li>', '').replace('</li>', '<br/>')}</td><td></td><td>⚠️ Частично</td></tr>"
        "</table>"
        "<h2>2. Пробелы в покрытии</h2>"
        "<ul><li>Требуется ручная проверка соответствия AC и тест-кейсов.</li></ul>"
        "<h2>3. Итоговая сводка</h2>"
        "<table>"
        "<tr><th>Метрика</th><th>Значение</th></tr>"
        f"<tr><td>Всего критериев приёмки</td><td>{len(payload.get('acceptance_criteria') or [])}</td></tr>"
        "<tr><td>Покрыто полностью</td><td>0</td></tr>"
        "<tr><td>Покрыто частично</td><td>0</td></tr>"
        "<tr><td>Не покрыто</td><td>0</td></tr>"
        f"<tr><td>API тест-кейсов</td><td>{len(api_tests)}</td></tr>"
        f"<tr><td>UI тест-кейсов</td><td>{len(ui_tests)}</td></tr>"
        "</table>"
        f"<p><strong>API тест-кейсы (список):</strong></p><ul>{api_rows}</ul>"
        f"<p><strong>UI тест-кейсы (список):</strong></p><ul>{ui_rows}</ul>"
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


def _make_confluence_page_url(base_url: str, space_key: str, page_id: str) -> str:
    return f"{base_url.rstrip('/')}/spaces/{space_key}/pages/{page_id}"


def _normalize_us_code(us_code: str) -> str:
    return re.sub(r"[-\s]+", "", us_code.strip().lower())


def _is_supported_us_code(code: str) -> bool:
    """Only process product user stories (US-*), not admin stories like AUS-*."""
    return bool(re.match(r"^US-\d+(?:\.\d+)*$", str(code or "").strip(), flags=re.IGNORECASE))


def _extract_issue_summary(issue: dict[str, Any]) -> str:
    return str(issue.get("summary") or (issue.get("fields") or {}).get("summary") or "")


def _extract_issue_key(issue: dict[str, Any]) -> str:
    return str(issue.get("key") or "")


def _extract_issue_url(issue: dict[str, Any], jira_base_url: str) -> str:
    direct = str(issue.get("url") or "").strip()
    if direct:
        return direct
    key = _extract_issue_key(issue)
    return f"{jira_base_url.rstrip('/')}/browse/{key}" if key else ""


def _iter_jira_catalog_issues(jira_catalog: Any) -> list[dict[str, Any]]:
    if isinstance(jira_catalog, list):
        return jira_catalog
    if isinstance(jira_catalog, dict) and isinstance(jira_catalog.get("issues"), list):
        return jira_catalog.get("issues", [])
    return []


def _find_best_jira_issue_for_us(us_code: str, issues: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Jira Story matcher: exact US token + canonical summary preference."""
    if not issues:
        return None

    target = _normalize_us_code(us_code)

    # Prefer strict US-code equality extracted from summary (rejects US-3.3.1 for US-3.1).
    exact_by_extracted_code: list[dict[str, Any]] = []
    for issue in issues:
        summary = _extract_issue_summary(issue)
        extracted = _extract_code_from_title(summary)
        if extracted and _normalize_us_code(extracted) == target:
            exact_by_extracted_code.append(issue)

    if exact_by_extracted_code:
        issues = exact_by_extracted_code

    pattern = re.compile(rf"\b{re.escape(us_code)}\b", re.IGNORECASE)
    matched = [issue for issue in issues if pattern.search(_extract_issue_summary(issue))]
    if not matched:
        return None

    canonical_tail = re.compile(
        rf"\b{re.escape(us_code)}\b\s*\|\s*[^:]+$",
        re.IGNORECASE,
    )
    filtered: list[dict[str, Any]] = []
    for issue in matched:
        summary = _extract_issue_summary(issue)
        if not canonical_tail.search(summary):
            continue
        if re.search(r"\b(automate|document|create|coverage|test\s*cases?)\b", summary, re.IGNORECASE):
            continue
        filtered.append(issue)

    pool = filtered if filtered else matched
    pool.sort(key=lambda issue: len(_extract_issue_summary(issue)))
    return pool[0]


def _build_jira_title_hint(us_title: str) -> str:
    """Return a short title fragment that is likely to appear in Jira Story summaries."""
    title = str(us_title or "").strip()
    if not title:
        return ""

    # Remove a leading US code if present, then keep a compact human-readable fragment.
    title = re.sub(r"^\s*US[-\s]*\d+(?:\.\d+)*\s*[|:-]?\s*", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\s*\(.*?\)\s*", " ", title)
    title = re.sub(r"\s+", " ", title).strip(" |-:\t")
    words = [w for w in title.split(" ") if w]
    if not words:
        return ""
    return " ".join(words[: min(2, len(words))])


def _make_us_code_pattern(us_code: str) -> re.Pattern:
    """Return a regex that matches the exact US code in a suite name.

    Uses a negative lookahead for a trailing digit so 'US-9.1.1' does not
    match 'US-9.1.10'.
    """
    m = re.match(r"^US[-\s]*(\d+(?:\.\d+)*)$", us_code, flags=re.IGNORECASE)
    if not m:
        return re.compile(re.escape(us_code), re.IGNORECASE)
    numeric = re.escape(m.group(1))
    return re.compile(rf"\bUS[-\s]*{numeric}(?!\d|\.\d)\b", re.IGNORECASE)


def _build_related_links_html(
    us_record: dict[str, Any],
    jira_links: list[dict[str, str]],
    api_suite_ids: list[str],
    ui_suite_ids: list[str],
    azure_org_url: str,
    azure_project: str,
    confluence_base_url: str,
    confluence_space: str,
) -> str:
    import html as _html

    org_url = str(azure_org_url or "").rstrip("/")
    project = str(azure_project or "").strip("/")
    azure_test_plan_url = f"{org_url}/{project}/_testPlans/define" if org_url and project else ""

    us_page_id = str(us_record.get("id") or us_record.get("page_id") or "").strip()
    us_link = _make_confluence_page_url(confluence_base_url, confluence_space, us_page_id) if us_page_id else str(us_record.get("url") or "")
    us_code = str(us_record.get("story_code") or _extract_code_from_title(str(us_record.get("title") or "")) or "US")

    us_inline = _html.escape(us_code)
    if us_link:
        us_inline = (
            f'<a href="{_html.escape(us_link)}" data-card-appearance="inline">'
            f"{_html.escape(us_code)}</a>"
        )

    jira_line = "<li>Jira Story: не найдена</li>"
    if jira_links:
        issue = jira_links[0]
        issue_key = str(issue.get("key") or "")
        issue_url = str(issue.get("url") or "")
        if issue_url:
            jira_line = (
                "<li>Jira Story: "
                f'<a href="{_html.escape(issue_url)}" data-card-appearance="inline">{_html.escape(issue_key)}</a>'
                "</li>"
            )
        elif issue_key:
            jira_line = f"<li>Jira Story: {_html.escape(issue_key)}</li>"

    azure_lines: list[str] = []
    if azure_test_plan_url:
        for suite_id in api_suite_ids:
            azure_url = f"{azure_test_plan_url}?planId={API_PLAN_ID}&suiteId={suite_id}"
            azure_lines.append(
                f'<li>Azure Test Suite (API): <a href="{_html.escape(azure_url)}">plan {API_PLAN_ID}, suite {suite_id}</a></li>'
            )
        for suite_id in ui_suite_ids:
            azure_url = f"{azure_test_plan_url}?planId={UI_PLAN_ID}&suiteId={suite_id}"
            azure_lines.append(
                f'<li>Azure Test Suite (UI): <a href="{_html.escape(azure_url)}">plan {UI_PLAN_ID}, suite {suite_id}</a></li>'
            )

    azure_block = "".join(azure_lines)
    return (
        "<h2>4. Связанные ссылки</h2>"
        "<ul>"
        f"<li>User Story: {us_inline}</li>"
        f"{jira_line}"
        f"{azure_block}"
        "</ul>"
    )


async def _safe_match_api_doc(gemini_client, us_text: str, api_docs: list[dict[str, Any]]) -> dict[str, Any]:
    candidates = [str(item.get("title") or "") for item in api_docs if item.get("title")]
    if not candidates:
        return {"api_doc_title": None, "api_doc_id": None}

    try:
        result = await gemini_client.choose_best_match(us_text, candidates)
        title = result.get("title")
    except Exception:
        title = None

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
            if not mapped_suite_ids and not _make_us_code_pattern(us_code).search(suite_name):
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

            # Fetch full work-item details (steps) for each test case
            case_ids = [
                str((item.get("workItem") or {}).get("id") or item.get("id") or "")
                for item in suite_tests
            ]
            case_ids = [cid for cid in case_ids if cid]
            enriched: list[dict[str, Any]] = []
            if case_ids:
                if log_fn:
                    log_fn("DEBUG", f"Fetching steps for {len(case_ids)} test cases in suite {suite_id}")
                try:
                    enriched = await azure_client.fetch_test_case_details(case_ids)
                except Exception as exc:
                    if log_fn:
                        log_fn("WARNING", f"Could not fetch test case details for suite {suite_id}: {exc}")
                    # Fall back to title-only dicts
                    enriched = [{"id": cid, "title": t, "steps": []} for cid, t in zip(case_ids, titles)]

            if log_fn and enriched:
                total_steps = sum(len(tc.get("steps") or []) for tc in enriched)
                log_fn("DEBUG", f"Suite {suite_id}: fetched {total_steps} steps across {len(enriched)} test cases")

            # Classify by plan, not by suite name — plan 2015 = API, plan 438 = UI
            if str(plan_id) == str(API_PLAN_ID):
                matched_api_suites.append({"id": suite_id, "name": suite_name})
                api_tests.extend(enriched)
            else:
                matched_ui_suites.append({"id": suite_id, "name": suite_name})
                ui_tests.extend(enriched)

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
    parent_id: Optional[str] = None,
    related_links_html: str = "",
) -> dict[str, Any]:
    """Publish with escalating HTML sanitization fallbacks.

    *related_links_html* is the canonical section-4 block.  It is re-appended
    after every sanitization/minimal-fallback step so links are never lost.
    """
    if tc_page_id and us_page_id and str(tc_page_id) == str(us_page_id):
        raise RuntimeError("Safety abort: tc_page_id equals source US page id")

    def _with_links(html: str) -> str:
        """Ensure html ends with the related links block."""
        if not related_links_html:
            return html
        return _ensure_related_links_section(html, related_links_html)

    async def _send(html: str) -> dict[str, Any]:
        if tc_page_id:
            return await confluence_client.update_page_content(tc_page_id, html)
        return await confluence_client.create_page(tc_title, html, parent_id=parent_id)

    result = await _send(_with_links(generated_html))
    if result.get("success"):
        return result

    error = str(result.get("error", ""))
    if "already exists" in error.lower() and not tc_page_id:
        existing = await confluence_client.find_page_by_title(tc_title)
        if existing and existing.get("id"):
            return await confluence_client.update_page_content(existing["id"], _with_links(generated_html))
        # Page exists on Confluence but we still can't locate it — abort rather than
        # spinning through HTML-sanitization retries that will all fail the same way.
        return {"success": False, "error": f"Page with title already exists but could not be located for update: {tc_title!r}"}

    if "unsupported" in error.lower() or "extension" in error.lower():
        regenerated = await regenerate_once()
        retry = await _send(_with_links(regenerated))
        if retry.get("success"):
            return retry

    sanitized = _sanitize_storage_html(generated_html)
    retry_sanitized = await _send(_with_links(sanitized))
    if retry_sanitized.get("success"):
        return retry_sanitized

    minimal = _minimal_storage_html("unknown", tc_title, "Fallback content due to publish errors")
    return await _send(_with_links(minimal))


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
    preview_run_id: Optional[str] = None,
    log_fn: Optional[Callable[[str, str], None]] = None,
) -> dict[str, Any]:
    """Generate/update coverage pages with script-equivalent operational controls."""

    # Clear the per-run epic parent cache so stale entries from previous runs don't persist.
    _epic_tc_parent_cache.clear()

    def log(level: str, message: str):
        stamped = f"[{_utc_now_iso()}] [cid={correlation_id}] {message}"
        if log_fn:
            log_fn(level, stamped)
        getattr(logger, level.lower(), logger.info)(stamped)

    root = _project_root()

    # ─────────────────────────────────────────────────────────────────────────────
    # FAST-PATH: publish from a previous dry-run's saved preview (skip ADO/LLM)
    # ─────────────────────────────────────────────────────────────────────────────
    if preview_run_id and apply:
        preview_path = (
            root / "data" / "artifacts" / "results" / preview_run_id / "generated_pages_preview.json"
        )
        try:
            previews: list[dict[str, Any]] = json.loads(preview_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeError(f"Cannot load preview from run {preview_run_id!r}: {exc}") from exc

        log("INFO", f"Preview-apply fast-path: publishing {len(previews)} pages from run {preview_run_id}")
        per_item_results_fast: list[dict[str, Any]] = []
        errors_fast: list[dict[str, Any]] = []

        for item in previews:
            item_us_code = item.get("us_code", "unknown")
            tc_page_id = item.get("tc_page_id")
            tc_title = item.get("tc_title", item_us_code)
            html_snapshot = item.get("html", "")
            try:
                log("INFO", f"Publishing preview for {item_us_code} (tc_page_id={tc_page_id or 'new'})")
                epic_parent_id: Optional[str] = None
                if not tc_page_id:
                    epic_parent_id = await _find_epic_tc_parent_id(
                        confluence_client, item_us_code, log_fn=log
                    )

                async def _regen(h: str = html_snapshot) -> str:
                    return h

                publish_result = await _publish_with_fallback(
                    confluence_client=confluence_client,
                    tc_page_id=tc_page_id,
                    tc_title=tc_title,
                    us_page_id=None,
                    generated_html=html_snapshot,
                    regenerate_once=_regen,
                    parent_id=epic_parent_id,
                    related_links_html="",  # already embedded in stored html
                )
                if not publish_result.get("success"):
                    raise RuntimeError(
                        f"Confluence publish failed: {publish_result.get('error', 'unknown error')}"
                    )
                final_page_id = str(publish_result.get("page_id") or tc_page_id or "")
                action = "updated" if tc_page_id else "created"
                log("INFO", f"Published {item_us_code}: action={action} page_id={final_page_id}")
                per_item_results_fast.append(
                    {
                        "us_code": item_us_code,
                        "mode": "preview_apply",
                        "action": action,
                        "tc_page_id": final_page_id,
                        "tc_title": tc_title,
                        "api_doc_title": item.get("api_doc_title"),
                        "api_tc_count": 0,
                        "ui_tc_count": 0,
                        "api_suite_ids": [],
                        "ui_suite_ids": [],
                        "message": "Coverage page published from preview",
                    }
                )
            except Exception as exc:
                category = _classify_error(exc)
                error_message = str(exc)
                errors_fast.append(
                    {"us_code": item_us_code, "category": category, "message": error_message}
                )
                per_item_results_fast.append(
                    {
                        "us_code": item_us_code,
                        "mode": "preview_apply",
                        "action": "failed",
                        "tc_page_id": None,
                        "tc_title": tc_title,
                        "api_doc_title": None,
                        "api_tc_count": 0,
                        "ui_tc_count": 0,
                        "api_suite_ids": [],
                        "ui_suite_ids": [],
                        "message": f"{category}: {error_message}",
                    }
                )
                log("ERROR", f"Failed publishing preview for {item_us_code}: {error_message}")
                if fail_fast:
                    break

        total_f = len(per_item_results_fast)
        succeeded_f = sum(1 for r in per_item_results_fast if r["action"] in {"updated", "created"})
        failed_f = sum(1 for r in per_item_results_fast if r["action"] == "failed")
        log("INFO", f"Preview-apply complete: total={total_f} succeeded={succeeded_f} failed={failed_f}")
        return {
            "status": "success" if failed_f == 0 else "partial_failure",
            "mode": "preview_apply",
            "summary": {
                "total": total_f,
                "succeeded": succeeded_f,
                "failed": failed_f,
                "skipped": 0,
            },
            "per_item_results": per_item_results_fast,
            "generated_pages_preview": [],
            "errors": errors_fast,
        }
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
    all_us_codes = [code for code in all_us_codes if _is_supported_us_code(code)]

    if not all_us_codes:
        raise RuntimeError(
            "No user stories found from Confluence provider, and no local fallback catalog is available"
        )

    if mode == "single":
        target_us_codes = [us_code] if us_code and _is_supported_us_code(us_code) else []
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
    # For batch modes, pre-load full Azure snapshot once,
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
        # DATA FLOW ORDER:
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
                # The broad CQL fetch (limit=500) may have missed this page.
                # Try a targeted lookup by exact US code in the title.
                log("WARNING", f"US page not in prefetched list; trying direct CQL lookup for {item_us_code}")
                fallback_cql = (
                    f'space="{confluence_client.space}" AND type=page '
                    f'AND title = "{item_us_code}"'
                )
                fallback_pages = await confluence_client.search_pages(fallback_cql, limit=5)
                if not fallback_pages:
                    # Also try contains search in case the title has extra text
                    fallback_cql2 = (
                        f'space="{confluence_client.space}" AND type=page '
                        f'AND title ~ "{item_us_code} |"'
                    )
                    fallback_pages = await confluence_client.search_pages(fallback_cql2, limit=5)
                # Filter to pages whose extracted code exactly matches; among candidates
                # pick the most spec-like (lowest _api_score, then shortest title).
                best_fp: Optional[dict[str, Any]] = None
                for fp in fallback_pages:
                    fp_code = _extract_code_from_title(str(fp.get("title") or ""))
                    fp_title = str(fp.get("title") or "")
                    if fp_code != item_us_code or _is_archived_title(fp_title):
                        continue
                    candidate = {
                        "id": str(fp.get("id") or ""),
                        "title": fp_title,
                        "story_code": item_us_code,
                        "url": fp.get("url", ""),
                    }
                    if best_fp is None:
                        best_fp = candidate
                    else:
                        if _api_score(fp_title) < _api_score(best_fp["title"]):
                            best_fp = candidate
                        elif _api_score(fp_title) == _api_score(best_fp["title"]) and len(fp_title) < len(best_fp["title"]):
                            best_fp = candidate
                if best_fp:
                    us_record = best_fp
                    log("INFO", f"Found via direct lookup: id={us_record['id']} title={us_record['title']}")
                    # Cache it so subsequent lookups for the same code work
                    epic_us_pages.append(us_record)
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
                    if apply:
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
                    # Dry-run: still generate and preview; note that force=true would be required to apply
                    log("INFO", f"Dry-run: {item_us_code} has non-stub content; generating preview (force=true required to apply)")

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

            jira_queries = [
                (
                    'issuetype = Story '
                    f'AND summary ~ "{item_us_code}" '
                    'ORDER BY created DESC'
                ),
            ]

            aggregated_issues: list[dict[str, Any]] = []
            seen_jira_keys: set[str] = set()
            for query in jira_queries:
                fetched = await jira_client.fetch_issues(query)
                for issue in fetched:
                    key = _extract_issue_key(issue)
                    if key and key in seen_jira_keys:
                        continue
                    if key:
                        seen_jira_keys.add(key)
                    aggregated_issues.append(issue)
                if len(aggregated_issues) >= 100:
                    break

            best_live_issue = _find_best_jira_issue_for_us(item_us_code, aggregated_issues)

            if best_live_issue:
                jira_links.append(
                    {
                        "key": _extract_issue_key(best_live_issue) or "Jira Story",
                        "url": _extract_issue_url(best_live_issue, jira_client.base_url),
                    }
                )

            if not jira_links and jira_catalog:
                catalog_issues = _iter_jira_catalog_issues(jira_catalog)
                best_catalog_issue = _find_best_jira_issue_for_us(item_us_code, catalog_issues)
                if best_catalog_issue:
                    jira_links.append(
                        {
                            "key": _extract_issue_key(best_catalog_issue) or "Jira Story",
                            "url": _extract_issue_url(best_catalog_issue, jira_client.base_url),
                        }
                    )

            log("INFO", f"[STEP 5] Jira links resolved for {item_us_code}: {len(jira_links)}")

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
                getattr(confluence_client, "base_url", ""),
                getattr(confluence_client, "space", ""),
            )
            # Strip any section 4 Gemini may have generated; _publish_with_fallback
            # always re-appends the canonical links block (even on sanitized/minimal fallbacks).
            generated_html = _ensure_related_links_section(generated_html, "").strip()

            generated_previews.append(
                {
                    "us_code": item_us_code,
                    "tc_title": tc_title,
                    "tc_page_id": tc_page_id,
                    "api_doc_title": api_doc_match.get("api_doc_title"),
                    "api_doc_id": api_doc_match.get("api_doc_id"),
                    "acceptance_criteria": ac_list,
                    "html": generated_html + "\n" + related_links_html,
                }
            )

            action = "preview"
            message = "Dry-run preview generated"
            final_page_id = tc_page_id

            if apply:
                log("INFO", f"[STEP 7] Publishing Confluence content for {item_us_code}")
                # Resolve epic TC parent folder for new pages (skipped when updating existing)
                epic_parent_id: Optional[str] = None
                if not tc_page_id:
                    epic_parent_id = await _find_epic_tc_parent_id(confluence_client, item_us_code, log_fn=log)
                publish_result = await _publish_with_fallback(
                    confluence_client=confluence_client,
                    tc_page_id=tc_page_id,
                    tc_title=tc_title,
                    us_page_id=us_page_id,
                    generated_html=generated_html,
                    regenerate_once=lambda: gemini_client.generate_confluence_coverage_page(
                        {**generation_payload, "strict_storage": True}
                    ),
                    parent_id=epic_parent_id,
                    related_links_html=related_links_html,
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
