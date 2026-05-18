"""Test generation workflow using Gemini"""

import difflib
import json
import math
import re
import textwrap
from datetime import datetime
from typing import Any, Callable, Optional

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
    "run_generate_from_confluence_workflow",
]


# ──────────────────────────────────────────────────────────────────────────────
# generate_from_confluence — ported from legacy/test_generators/generate/api.py
# ──────────────────────────────────────────────────────────────────────────────

# Gemini prompt for API test case generation (Russian output, structured JSON)
_API_TC_PROMPT = textwrap.dedent("""\
    Выступай как Lead QA Engineer с глубоким пониманием API-тестирования.

    Тебе даны:
        1. Описание User Story.
        2. API-спецификация, относящаяся к этой User Story.

    Твоя задача
    ------------
    Сгенерировать МИНИМУМ {min_test_cases} API тест-кейсов (можно больше),
    покрывающих ВСЕ указанные ниже категории.

    Критическое требование к покрытию Acceptance Criteria
    ------------------------------------------------------
    Внимательно прочитай раздел «Acceptance Criteria» (или «Критерии приёмки»)
    в описании User Story. Для КАЖДОГО пункта Acceptance Criteria ДОЛЖЕН
    существовать как минимум один тест-кейс, явно проверяющий этот критерий.
    Если пункт AC описывает несколько условий — раздели их на отдельные
    тест-кейсы. Не пропускай ни одного пункта AC.

    Критическое требование к покрытию сценариев (E2E)
    --------------------------------------------------
    Если в User Story есть разделы вида «Основной сценарий»,
    «Альтернативный сценарий», «Исключение/Exception»,
    «Заменяемый шаг», шаги с суффиксами (например, 9a/9в/9ps/9pc),
    то ОБЯЗАТЕЛЬНО сгенерируй тест-кейсы на их основе.
    Минимальные правила:
    - Основной сценарий: как минимум 1 полноценный E2E тест-кейс
        по ключевому happy path.
    - Каждый альтернативный сценарий: как минимум 1 отдельный тест-кейс,
        явно проверяющий ответвление и возврат в основной поток
        (если это указано в спецификации).
    - Для сценариев с ретраями/повторными попытками: отдельные проверки
        "успешно после N попыток" и "ошибка после исчерпания попыток"
        (когда это применимо по тексту требования).
    - Для сценариев с логированием/аудитом: отдельная проверка факта записи
        ошибки/события в лог или аудит.

    Важно: AC-покрытие и сценарное покрытие дополняют друг друга.
    Не заменяй сценарные тесты AC-тестами и наоборот.

    Обязательные категории покрытия
    --------------------------------
    1. Позитивные сценарии — корректный вызов каждого описанного endpoint
       с валидными данными; проверка обязательных полей и структуры ответа.
    2. Валидация полей запроса — невалидные типы, пустые/null значения,
       отсутствующие обязательные поля, превышение максимальной длины,
       граничные значения (boundary values).
    3. Негативные / error-сценарии — невалидный ввод, некорректный формат
       данных, несуществующий ресурс (404), конфликт состояния (409).
    4. Авторизация — запросы без токена, с истёкшим токеном,
       с недостаточными правами, попытка доступа к чужим ресурсам.
    5. Граничные и edge-case сценарии — пустой/огромный payload,
       максимальное количество элементов, специальные символы Unicode,
       параллельные запросы со взаимно конфликтующими данными.
    6. Бизнес-логика — проверки, вытекающие из требований User Story:
       условия, при которых операция допустима/недопустима,
       последовательные зависимости шагов.
    7. Идемпотентность — повторный вызов того же запроса (PUT/DELETE)
       возвращает тот же результат; повторный POST не создаёт дубликат.
    8. Ответ и структура данных — наличие обязательных полей, корректные
       типы, формат дат, пагинация, сортировка (где применимо).

    Требования к шагам (steps)
    ----------------------------
    Каждый шаг (step) должен быть конкретным и воспроизводимым:
    - «action» должен содержать: HTTP метод, endpoint (или его ключевую
      часть), описание тела (body)/параметров запроса.
    - «expected» должен содержать: ожидаемый HTTP-статус код, ключевые
      поля ответа и их значения/типы, побочные эффекты (если есть).

    Критически важно
    ----------------
    Верни тест-кейсы НА РУССКОМ ЯЗЫКЕ.
    Все значения полей "title", "action" и "expected" должны быть
    написаны по-русски.
    Не используй английские названия тест-кейсов, если только это
    не часть API path, HTTP method, field name, error code, status code
    или другого технического идентификатора.

    Формат ответа
    -------------
    Верни ТОЛЬКО валидный JSON-массив — без markdown-блоков, без
    пояснений, без комментариев.
    Каждый элемент массива должен быть объектом ровно с такими ключами:

        "title"    : краткое и понятное название тест-кейса (string)
        "priority" : одно из значений "High", "Medium", "Low" (string)
        "steps"    : список объектов шагов, где каждый объект содержит:
            "action"   — какое действие или HTTP-запрос выполнить (string)
            "expected" — какой ожидается HTTP-статус, ответ или
                         поведение (string)

    Требования к именованию title
    -----------------------------
    Для сценарных тест-кейсов (Основной/Альтернативный/Exception)
    явно укажи в title тип сценария и номер/идентификатор шага,
    если он есть в спецификации.
    Примеры фрагментов title:
    - «Основной сценарий: ... (шаги 1-15)»
    - «Альтернативный сценарий #1: ... (шаги 3a-6a)»
    - «Альтернативный сценарий #2: ... (шаги 12в-16в)»
    Не добавляй никаких внешних префиксов к title вручную
    (они добавляются отдельно системой).

    ── User Story ───────────────────────────────────────────────────────────
    {us_content}

    ── API Documentation ────────────────────────────────────────────────────
    {api_content}
""")

_CATALOG_PICK_PROMPT = textwrap.dedent("""\
    You are a QA automation assistant.

    Given the User Story title below and a list of API documentation page titles,
    identify which single page title is the most relevant API documentation for
    that User Story.

    Rules:
    - Reply with ONLY the exact page title string — nothing else, no quotes, no explanation.
    - If none of the pages is relevant, reply with exactly: NONE

    User Story title: {us_title}

    API documentation page titles:
    {catalog_titles}
""")

# Patterns for sizing heuristics (mirrors legacy api.py)
_AC_PATTERN = re.compile(r"[АA][СC][-\s]*(\d+)", re.IGNORECASE)
_SCENARIO_MAIN_PATTERN = re.compile(r"основн\w*\s+сценар\w*", re.IGNORECASE)
_SCENARIO_ALT_PATTERN = re.compile(r"альтернативн\w*\s+сценар\w*", re.IGNORECASE)
_SCENARIO_EXCEPTION_PATTERN = re.compile(r"исключени\w*|exception", re.IGNORECASE)
_API_METHOD_PATTERN = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE)\b", re.IGNORECASE)

# Default sizing constants
_TC_CHARS_PER_CASE = 800
_TC_MIN_FLOOR = 5
_TC_MIN_CAP = 40


def _estimate_min_test_cases(
    us_content: str,
    api_content: str,
    chars_per_case: int = _TC_CHARS_PER_CASE,
    min_floor: int = _TC_MIN_FLOOR,
    min_cap: int = _TC_MIN_CAP,
) -> int:
    """Estimate the minimum number of test cases to request from Gemini."""
    us_chars = len(us_content)
    ac_count = len({m.group(1) for m in _AC_PATTERN.finditer(us_content)})
    has_main = 1 if _SCENARIO_MAIN_PATTERN.search(us_content) else 0
    alt_count = len(_SCENARIO_ALT_PATTERN.findall(us_content))
    exception_count = len(_SCENARIO_EXCEPTION_PATTERN.findall(us_content))
    method_count = len({m.group(1).upper() for m in _API_METHOD_PATTERN.finditer(api_content)})

    ac_based = ac_count * 2 if ac_count else min_floor
    size_based = math.ceil(us_chars / max(1, chars_per_case))
    scenario_based = has_main * 2 + alt_count * 3 + exception_count * 2
    endpoint_based = method_count * 2

    raw = max(ac_based, size_based, scenario_based, endpoint_based, min_floor)
    return min(max(min_floor, raw), min_cap)


def _build_tc_prefix(epic_title: str, us_title: str) -> str:
    """Build a deterministic test-case prefix like 'API - US2.1.1 - '."""
    us_match = re.search(r"\b(?:AUS|US)-([\d.]+)\b", us_title, flags=re.IGNORECASE)
    us_num = us_match.group(1) if us_match else "0"
    return f"API - US{us_num} - "


def _normalize_title(value: str) -> str:
    lowered = value.strip().lower()
    lowered = re.sub(r"[`'\"""'']", "", lowered)
    return re.sub(r"\s+", " ", lowered)


def _tokenize(value: str) -> set[str]:
    return {t for t in re.findall(r"[A-Za-zА-Яа-яЁё0-9]+", value.lower()) if len(t) >= 4}


def _resolve_catalog_page_by_title(catalog: list[dict], picked_title: str) -> Optional[dict]:
    """Tolerant catalog lookup: exact → containment → fuzzy."""
    if not picked_title:
        return None
    clean = _normalize_title(picked_title)
    for page in catalog:
        if _normalize_title(page.get("title", "")) == clean:
            return page
    for page in catalog:
        page_key = _normalize_title(page.get("title", ""))
        if clean in page_key or page_key in clean:
            return page
    best_page, best_ratio = None, 0.0
    for page in catalog:
        ratio = difflib.SequenceMatcher(None, clean, _normalize_title(page.get("title", ""))).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_page = page
    return best_page if best_ratio >= 0.78 else None


def _resolve_catalog_page_by_topic(catalog: list[dict], us_title: str) -> Optional[dict]:
    """Topic-token fallback: pick most semantically related page."""
    topic = re.sub(r"^\s*[A-Za-z]+\s*-?\s*\d+(?:\.\d+)*\s*\|?\s*", "", us_title).strip()
    topic_tokens = _tokenize(topic)
    if not topic_tokens:
        return None
    best_page, best_score = None, -1.0
    for page in catalog:
        title_tokens = _tokenize(page.get("title", ""))
        overlap = len(topic_tokens & title_tokens)
        if not overlap:
            continue
        ratio = difflib.SequenceMatcher(None, topic.lower(), page.get("title", "").lower()).ratio()
        score = overlap * 3 + ratio
        if score > best_score:
            best_score = score
            best_page = page
    return best_page


async def _find_api_doc_for_us(
    confluence_client,
    us_page: dict,
    api_keyword: str,
    catalog: list[dict],
    gemini_client,
    log_fn: Callable,
) -> Optional[dict]:
    """Locate the API-doc page for a User Story: child pages → Gemini catalog → topic fallback."""
    us_id = us_page["id"]
    us_title = us_page["title"]
    kw = api_keyword.lower()

    # 1. Child pages
    children = await confluence_client.get_child_pages(us_id)
    for child in children:
        if kw in child.get("title", "").lower():
            log_fn("INFO", f"  [API-doc] Found child page: {child['title']}")
            return child

    # 2. Gemini catalog pick
    if catalog and gemini_client:
        catalog_titles = "\n".join(f"- {p['title']}" for p in catalog)
        prompt = _CATALOG_PICK_PROMPT.format(us_title=us_title, catalog_titles=catalog_titles)
        try:
            raw = await gemini_client._generate_with_retry(prompt)
            if raw:
                picked = raw.strip()
                if picked and picked.upper() != "NONE":
                    page = _resolve_catalog_page_by_title(catalog, picked)
                    if page:
                        log_fn("INFO", f"  [API-doc] Gemini picked: {page['title']}")
                        return page
        except Exception as exc:
            log_fn("WARNING", f"  [API-doc] Gemini catalog pick failed: {exc}")

    # 3. Topic-token fallback
    if catalog:
        page = _resolve_catalog_page_by_topic(catalog, us_title)
        if page:
            log_fn("INFO", f"  [API-doc] Fallback topic match: {page['title']}")
            return page

    log_fn("WARNING", f"  [API-doc] Not found for US: '{us_title}'")
    return None


async def _generate_tc_via_gemini(
    gemini_client,
    us_content: str,
    api_content: str,
    min_test_cases: int,
    existing_titles: list[str],
    log_fn: Callable,
) -> list[dict]:
    """Call Gemini with the legacy prompt and return parsed test cases."""
    prompt = _API_TC_PROMPT.format(
        us_content=us_content[:8_000],
        api_content=api_content[:8_000],
        min_test_cases=min_test_cases,
    )
    if existing_titles:
        titles_block = "\n".join(f"- {t}" for t in existing_titles)
        prompt += (
            "\n── Уже существующие тест-кейсы (НЕ дублировать) ─────────────────────────\n"
            "Следующие тест-кейсы уже есть в наборе. "
            "НЕ создавай тест-кейсы, семантически совпадающие с ними "
            "(даже если формулировка отличается).\n"
            f"{titles_block}\n"
        )
    try:
        raw = await gemini_client._generate_with_retry(prompt, max_attempts=5)
    except Exception as exc:
        log_fn("ERROR", f"  [Gemini] API error: {exc}")
        return []

    if not raw:
        log_fn("ERROR", "  [Gemini] Empty response; skipping US.")
        return []

    try:
        cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.MULTILINE)
        cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.MULTILINE)
        test_cases = json.loads(cleaned)
        if not isinstance(test_cases, list):
            raise ValueError("Response is not a JSON array.")
        log_fn("INFO", f"  [Gemini] Parsed {len(test_cases)} test case(s).")
        return test_cases
    except (json.JSONDecodeError, ValueError) as exc:
        log_fn("ERROR", f"  [Gemini] Failed to parse response: {exc}")
        return []


async def run_generate_from_confluence_workflow(
    confluence_client,
    gemini_client,
    azure_client,
    epic_page_id: str,
    test_plan_id: str,
    api_docs_folder_id: str = "",
    api_keyword: str = "API",
    single_us_id: Optional[str] = None,
    resume_from: Optional[str] = None,
    force: bool = False,
    dry_run: bool = False,
    gemini_delay_seconds: int = 10,
    log_fn: Optional[Callable] = None,
) -> dict[str, Any]:
    """
    Generate API test cases from Confluence US pages into Azure DevOps.

    Mirrors the legacy generate/api.py `run()` function using the modern
    async integration clients.

    Parameters
    ----------
    confluence_client : ConfluenceClient
    gemini_client     : GeminiClient
    azure_client      : AzureDevOpsClient
    epic_page_id      : Confluence page ID of the Epic (parent of US pages)
    test_plan_id      : Azure DevOps test plan ID
    api_docs_folder_id: Confluence folder page ID that contains API-doc pages;
                        if empty, only child-page and Gemini-catalog discovery is used
    api_keyword       : Keyword that identifies API-doc child pages (default "API")
    single_us_id      : If set, process only this Confluence page ID
    resume_from       : Title substring — skip US pages until this is matched
    force             : Remove existing test cases from the suite before generating
    dry_run           : Log actions without writing to Azure DevOps
    gemini_delay_seconds : Seconds to sleep between Gemini calls (rate limiting)
    log_fn            : Optional callable(level, message) for structured logging
    """
    if log_fn is None:
        log_fn = lambda level, msg: logger.info(msg)  # noqa: E731

    log_fn("INFO", f"generate_from_confluence starting — epic_page_id={epic_page_id}, plan={test_plan_id}")
    if dry_run:
        log_fn("INFO", "*** DRY RUN — no changes will be written to Azure DevOps ***")

    # ── Load API-docs catalog ────────────────────────────────────────────────
    api_docs_catalog: list[dict] = []
    if api_docs_folder_id:
        log_fn("INFO", f"Fetching API-doc catalog from folder {api_docs_folder_id} …")
        try:
            api_docs_catalog = await confluence_client.get_all_child_pages_recursive(api_docs_folder_id)
            log_fn("INFO", f"Loaded {len(api_docs_catalog)} API-doc pages.")
        except Exception as exc:
            log_fn("WARNING", f"Could not load API-doc catalog: {exc}")

    # ── Resolve epic groups ──────────────────────────────────────────────────
    if single_us_id:
        page_info = await confluence_client.get_page(single_us_id)
        us_title = (page_info or {}).get("title", single_us_id)
        us_pages = [{"id": single_us_id, "title": us_title}]
        # Try to find the epic ancestor title from the page ancestors
        epic_title = f"Epic-{epic_page_id}"
        ancestors = (page_info or {}).get("ancestors", [])
        if ancestors:
            epic_title = ancestors[0].get("title", epic_title)
        epic_groups = [{"title": epic_title, "user_stories": us_pages}]
        log_fn("INFO", f"Single-US mode: {us_title}")
    else:
        epic_info = await confluence_client.get_page(epic_page_id)
        epic_title = (epic_info or {}).get("title", f"Epic-{epic_page_id}")
        us_pages = await confluence_client.get_child_pages(epic_page_id)
        log_fn("INFO", f"Found {len(us_pages)} US page(s) under epic '{epic_title}'.")
        epic_groups = [{"title": epic_title, "user_stories": us_pages}]

    # ── Resolve ADO root suite ───────────────────────────────────────────────
    root_suite_id: Optional[str] = None
    if not dry_run:
        try:
            root_suite_id = await azure_client.get_root_suite_id(test_plan_id)
        except Exception as exc:
            log_fn("ERROR", f"Could not fetch root suite: {exc}")
            return {
                "status": "failed",
                "error": str(exc),
                "tests_created": 0,
                "us_processed": 0,
                "timestamp": datetime.utcnow().isoformat(),
            }

    per_us_results: list[dict] = []
    total_created = 0
    _resume_reached = resume_from is None
    import asyncio as _asyncio

    for epic_group in epic_groups:
        epic_title = epic_group["title"]
        us_list = epic_group["user_stories"]

        epic_suite_id: Optional[str] = None
        if not dry_run:
            try:
                epic_suite_id = await azure_client.get_or_create_suite(
                    test_plan_id, epic_title, root_suite_id
                )
            except Exception as exc:
                log_fn("ERROR", f"Could not create/find epic suite '{epic_title}': {exc}")
                continue
        else:
            log_fn("INFO", f"  [DRY-RUN] Would create/find epic suite: '{epic_title}'")

        for idx, us_page in enumerate(us_list):
            us_title = us_page["title"]
            us_id = us_page["id"]

            # Resume logic
            if not _resume_reached:
                if resume_from and resume_from in us_title:
                    _resume_reached = True
                    log_fn("INFO", f"  [RESUME] Resuming from '{us_title}'")
                else:
                    log_fn("INFO", f"  [SKIP] {us_title} (before resume point)")
                    continue

            log_fn("INFO", f"Processing US: {us_title} (page_id={us_id})")

            # Resolve ADO US suite
            us_suite_id: Optional[str] = None
            existing_titles: list[str] = []
            if not dry_run:
                try:
                    us_suite_id = await azure_client.get_or_create_suite(
                        test_plan_id, us_title, epic_suite_id
                    )
                    existing_tcs = await azure_client.fetch_test_cases_for_suite(
                        test_plan_id, us_suite_id
                    )
                    existing_titles = [
                        tc.get("workItem", {}).get("name", "")
                        for tc in existing_tcs
                        if tc.get("workItem", {}).get("name")
                    ]
                    if existing_titles:
                        log_fn("INFO", f"  Suite has {len(existing_titles)} existing TC(s); passing to Gemini for dedup.")
                    if existing_titles and force:
                        tc_ids = [
                            str(tc["workItem"]["id"])
                            for tc in existing_tcs
                            if tc.get("workItem", {}).get("id")
                        ]
                        log_fn("INFO", f"  [Force] Removing {len(tc_ids)} existing TC(s).")
                        await azure_client.delete_test_cases(tc_ids)
                        existing_titles = []
                except Exception as exc:
                    log_fn("WARNING", f"  Could not resolve US suite '{us_title}': {exc}")
            else:
                log_fn("INFO", f"  [DRY-RUN] Would create/find suite: '{us_title}'")

            # Find API-doc page
            api_doc = await _find_api_doc_for_us(
                confluence_client, us_page, api_keyword,
                api_docs_catalog, gemini_client, log_fn,
            )
            if api_doc is None:
                log_fn("WARNING", f"  Skipping — no API doc found for '{us_title}'.")
                per_us_results.append({"us_title": us_title, "status": "skipped_no_api_doc", "tests_created": 0})
                continue

            # Fetch page contents
            try:
                us_content = await confluence_client.fetch_page_content(us_id)
                api_content = await confluence_client.fetch_page_content(api_doc["id"])
                log_fn("INFO", f"  Content: US={len(us_content)} chars | API-doc={len(api_content)} chars")
            except Exception as exc:
                log_fn("ERROR", f"  Could not fetch page content: {exc}")
                per_us_results.append({"us_title": us_title, "status": "failed_content_fetch", "tests_created": 0})
                continue

            # Compute minimum test case count
            min_tc = _estimate_min_test_cases(us_content, api_content)
            log_fn("INFO", f"  Estimated minimum test cases: {min_tc}")

            # Rate limiting before Gemini call (skip before very first call)
            if idx > 0 and gemini_delay_seconds > 0:
                log_fn("INFO", f"  [Rate-limit] Sleeping {gemini_delay_seconds}s …")
                await _asyncio.sleep(gemini_delay_seconds)

            # Generate test cases via Gemini
            test_cases = await _generate_tc_via_gemini(
                gemini_client, us_content, api_content, min_tc, existing_titles, log_fn,
            )
            if not test_cases:
                log_fn("WARNING", f"  Skipping — Gemini returned no test cases for '{us_title}'.")
                per_us_results.append({"us_title": us_title, "status": "skipped_no_tests", "tests_created": 0})
                continue

            # Apply title prefix
            prefix = _build_tc_prefix(epic_title, us_title)
            for tc in test_cases:
                tc["title"] = prefix + tc.get("title", "Untitled")

            if dry_run:
                log_fn("INFO", f"  [DRY-RUN] Would create {len(test_cases)} TC(s) in suite '{us_title}':")
                for tc in test_cases:
                    log_fn("INFO", f"    • {tc.get('title')}  [{tc.get('priority', '?')}]")
                per_us_results.append({"us_title": us_title, "status": "dry_run", "tests_created": len(test_cases)})
                total_created += len(test_cases)
                continue

            # Create test cases in Azure DevOps
            created_count = 0
            for tc in test_cases:
                try:
                    result = await azure_client.create_test_case_in_suite(
                        test_plan_id=test_plan_id,
                        suite_id=us_suite_id,
                        title=tc.get("title", "Untitled Test Case"),
                        priority=tc.get("priority", "Medium"),
                        steps=tc.get("steps", []),
                    )
                    if result.get("success"):
                        created_count += 1
                    else:
                        log_fn("WARNING", f"  Failed to create TC '{tc.get('title')}': {result.get('error')}")
                except Exception as exc:
                    log_fn("ERROR", f"  Error creating TC '{tc.get('title')}': {exc}")

            log_fn("INFO", f"  Created {created_count}/{len(test_cases)} TC(s) for '{us_title}'.")
            per_us_results.append({"us_title": us_title, "status": "success", "tests_created": created_count})
            total_created += created_count

    summary = {
        "status": "success",
        "dry_run": dry_run,
        "epic_page_id": epic_page_id,
        "test_plan_id": test_plan_id,
        "us_processed": len(per_us_results),
        "tests_created": total_created,
        "per_us_results": per_us_results,
        "timestamp": datetime.utcnow().isoformat(),
    }
    log_fn("INFO", f"generate_from_confluence complete — {total_created} TC(s) {'would be ' if dry_run else ''}created across {len(per_us_results)} US(s).")
    return summary
