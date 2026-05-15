"""Workflows UI."""

from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from apps.app.database import WorkflowRunModel
from apps.app.database import get_session_factory
from apps.app.config import get_settings
from apps.app.workflows import enqueue_workflow
from packages.common import UpdateCoverageRunRequest, TriageBugTicketsRunRequest
from packages.common import WorkflowType

router = APIRouter()

HIDDEN_WEBAPP_WORKFLOW_KEYS = {
    "fetch_catalog",
    "generate_api_tests",
    "generate_ui_tests",
    "associate_automation",
    "generate_report",
}


def get_db(request: Request) -> Session:
    """Get database session."""
    settings = get_settings()
    SessionLocal = get_session_factory(settings.database_url)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _bool_from_form(value: str | None) -> bool:
    return str(value or "").lower() in {"1", "true", "on", "yes"}


_FRIENDLY_VALIDATION_MESSAGES: dict[str, str] = {
    "us_code is required when mode=single": "Please enter a User Story code (e.g. US-3.3.1) when running in Single mode.",
}


def _friendly_coverage_validation_error(exc: Exception) -> str:
    raw = str(exc)
    for key, message in _FRIENDLY_VALIDATION_MESSAGES.items():
        if key in raw:
            return message
    return raw


def _render_update_coverage_page(
    *,
    form_values: dict[str, str] | None = None,
    validation_error: str | None = None,
    run_id: str | None = None,
) -> str:
    settings = get_settings()
    confluence_base_url = str(settings.confluence_base_url or "").rstrip("/")
    confluence_space = str(settings.confluence_space or "")

    values = {
        "mode": "single",
        "us_code": "",
        "apply": "",
        "force": "",
        "batch_delay_seconds": "3",
        "max_items": "",
        "fail_fast": "",
        "include_debug_artifacts": "on",
        "use_cached_azure_snapshot": "",
    }
    if form_values:
        values.update(form_values)

    mode = values.get("mode", "single")
    error_block = (
        f'<div class="error">{validation_error}</div>'
        if validation_error
        else ""
    )

    run_panel = ""
    if run_id:
        run_panel = f"""
        <div class="result-card">
            <h3>Run Monitor</h3>
            <p>Run ID: <code>{run_id}</code></p>
            <div id="dryRunBadge" class="badge">Pending...</div>
            <div id="runProgress" class="progress-line">Preparing monitor...</div>
            <div id="currentStep" class="step-line">Current step: waiting...</div>
            <div class="counters">
                <div>Total: <strong id="countTotal">0</strong></div>
                <div>Succeeded: <strong id="countSucceeded">0</strong></div>
                <div>Failed: <strong id="countFailed">0</strong></div>
                <div>Skipped: <strong id="countSkipped">0</strong></div>
            </div>
            <h4>Status</h4>
            <pre id="runStatus">Loading...</pre>
            <h4>Terminal-Like Stream</h4>
            <div class="logs-toolbar">
                <span id="logMeta">Logs: 0</span>
                <label><input type="checkbox" id="autoScrollLogs" checked /> Auto-scroll</label>
            </div>
            <pre id="liveLogs">Loading logs...</pre>
            <h4>Per-US Status</h4>
            <table>
                <thead>
                    <tr><th>US Code</th><th>Status</th><th>TC Page</th><th>Message</th></tr>
                </thead>
                <tbody id="resultsTableBody"><tr><td colspan="4">Waiting for results...</td></tr></tbody>
            </table>
            <h4>Artifacts</h4>
            <ul id="artifactLinks"><li>Waiting for artifacts...</li></ul>
        </div>
        <script>
            const runId = "{run_id}";
            const confluenceBaseUrl = "{confluence_base_url}";
            const confluenceSpace = "{confluence_space}";
            let done = false;
            const monitorStartedAt = Date.now();
            let lastLogTimestamp = null;
            const POLL_INTERVAL_MS = 1000;
            const ARTIFACT_POLL_EVERY_TICKS = 5;
            let tickCount = 0;

            function renderTcPageCell(row) {{
                const raw = String(row.tc_page_id || "").trim();
                if (!raw) return "";

                // If backend ever provides full URL, use it directly.
                if (/^https?:\/\//i.test(raw)) {{
                    return `<a href="${{raw}}" target="_blank" rel="noopener noreferrer">${{raw}}</a>`;
                }}

                // Confluence cloud page URL from page id and configured space.
                const href = `${{confluenceBaseUrl}}/spaces/${{encodeURIComponent(confluenceSpace)}}/pages/${{encodeURIComponent(raw)}}`;
                return `<a href="${{href}}" target="_blank" rel="noopener noreferrer">${{raw}}</a>`;
            }}

            function fmtElapsed(ms) {{
                const sec = Math.floor(ms / 1000);
                const min = Math.floor(sec / 60);
                const rem = sec % 60;
                return `${{min}}m ${{rem}}s`;
            }}

            async function refreshRun() {{
                const runResp = await fetch(`/api/runs/${{runId}}`);
                if (!runResp.ok) {{
                    const msg = `Failed to load run status (HTTP ${{runResp.status}})`;
                    document.getElementById("runStatus").textContent = msg;
                    document.getElementById("runProgress").textContent = msg;
                    return;
                }}
                const run = await runResp.json();
                document.getElementById("runStatus").textContent = JSON.stringify(run, null, 2);

                const elapsed = fmtElapsed(Date.now() - monitorStartedAt);
                const statusUpper = String(run.status || "unknown").toUpperCase();
                document.getElementById("runProgress").textContent = `Status: ${{statusUpper}} | Elapsed: ${{elapsed}}`;

                const dryRunBadge = document.getElementById("dryRunBadge");
                if (run.dry_run) {{
                    dryRunBadge.textContent = "DRY-RUN (preview only)";
                    dryRunBadge.className = "badge dry";
                }} else {{
                    dryRunBadge.textContent = "APPLY MODE (writes enabled)";
                    dryRunBadge.className = "badge apply";
                }}

                const logsResp = await fetch(`/api/runs/${{runId}}/logs`);
                if (logsResp.ok) {{
                    const logsData = await logsResp.json();
                    const logs = logsData.logs || [];
                    const stripLogPrefix = (msg) => msg.replace(/^\[[\dT:.+\-Z]+\]\s*\[cid=[^\]]+\]\s*/, "");
                    const lines = logs.map((l) => `${{l.timestamp}} [${{l.level}}] ${{stripLogPrefix(l.message)}}`);
                    const logsEl = document.getElementById("liveLogs");
                    logsEl.textContent = lines.join("\\n") || "No logs yet";

                    if (logs.length > 0) {{
                        lastLogTimestamp = logs[logs.length - 1].timestamp;
                    }}
                    const logMeta = `Logs: ${{logs.length}} | Last update: ${{lastLogTimestamp || "n/a"}}`;
                    document.getElementById("logMeta").textContent = logMeta;

                    const currentStepEl = document.getElementById("currentStep");
                    if (logs.length > 0) {{
                        const last = logs[logs.length - 1];
                        currentStepEl.textContent = `Current step: [${{last.level}}] ${{stripLogPrefix(last.message)}}`;
                    }} else {{
                        currentStepEl.textContent = "Current step: waiting for first log line...";
                    }}

                    if (document.getElementById("autoScrollLogs").checked) {{
                        logsEl.scrollTop = logsEl.scrollHeight;
                    }}

                    if (run.status === "running" || run.status === "queued") {{
                        const waitHint = logs.length === 0
                            ? "Waiting for worker logs..."
                            : "Workflow is running. Integration calls may take time; logs update as each step completes.";
                        document.getElementById("runProgress").textContent =
                            `Status: ${{statusUpper}} | Elapsed: ${{elapsed}} | ${{waitHint}}`;
                    }}
                }}

                // Artifacts are heavier and change less frequently than status/logs.
                // Poll them every N ticks during run, and once on terminal state.
                const shouldPollArtifacts =
                    (tickCount % ARTIFACT_POLL_EVERY_TICKS === 0) ||
                    ["succeeded", "failed", "canceled"].includes(run.status);

                if (shouldPollArtifacts) {{
                    const artifactResp = await fetch(`/api/artifacts/run/${{runId}}`);
                    if (artifactResp.ok) {{
                        const artifacts = await artifactResp.json();
                        const linksEl = document.getElementById("artifactLinks");
                        linksEl.innerHTML = "";
                        for (const item of artifacts) {{
                            const li = document.createElement("li");
                            const a = document.createElement("a");
                            a.href = item.download_url;
                            a.textContent = item.filename;
                            li.appendChild(a);
                            linksEl.appendChild(li);
                        }}

                        const summaryArtifact = artifacts.find((a) => a.filename === "run_summary.json");
                        if (summaryArtifact) {{
                            const summaryResp = await fetch(summaryArtifact.download_url);
                            if (summaryResp.ok) {{
                                const summary = await summaryResp.json();
                                document.getElementById("countTotal").textContent = summary.total ?? 0;
                                document.getElementById("countSucceeded").textContent = summary.succeeded ?? 0;
                                document.getElementById("countFailed").textContent = summary.failed ?? 0;
                                document.getElementById("countSkipped").textContent = summary.skipped ?? 0;
                            }}
                        }}

                        const perItemArtifact = artifacts.find((a) => a.filename === "per_item_results.json");
                        if (perItemArtifact) {{
                            const resultResp = await fetch(perItemArtifact.download_url);
                            if (resultResp.ok) {{
                                const rows = await resultResp.json();
                                const body = document.getElementById("resultsTableBody");
                                body.innerHTML = "";
                                for (const row of rows) {{
                                    const tr = document.createElement("tr");
                                    tr.innerHTML = `<td>${{row.us_code || ""}}</td><td>${{row.action || ""}}</td><td>${{renderTcPageCell(row)}}</td><td>${{row.message || ""}}</td>`;
                                    body.appendChild(tr);
                                }}
                            }}
                        }}
                    }}
                }}

                if (["succeeded", "failed", "canceled"].includes(run.status)) {{
                    done = true;
                }}
            }}

            async function tick() {{
                tickCount += 1;
                try {{ await refreshRun(); }} catch (e) {{}}
                if (!done) setTimeout(tick, POLL_INTERVAL_MS);
            }}
            tick();
        </script>
        """

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Run update_coverage - Trace2Quality</title>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f5f5f5; }}
            nav {{ background: #0066cc; color: white; padding: 15px 30px; }}
            nav h1 {{ margin: 0; font-size: 24px; }}
            nav ul {{ list-style: none; display: flex; gap: 20px; margin-top: 10px; }}
            nav a {{ color: white; text-decoration: none; }}
            .container {{ max-width: 1100px; margin: 0 auto; padding: 20px; }}
            h2 {{ color: #333; margin: 20px 0 10px 0; }}
            form, .result-card {{ background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); margin-bottom: 16px; }}
            .form-row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
            .form-group {{ margin-bottom: 14px; }}
            label {{ display: block; font-weight: bold; margin-bottom: 6px; color: #333; }}
            input, select {{ width: 100%; padding: 8px; border: 1px solid #ddd; border-radius: 4px; }}
            .checkbox {{ display: flex; gap: 8px; align-items: center; margin-bottom: 8px; }}
            .checkbox input {{ width: auto; }}
            button {{ background: #0066cc; color: white; padding: 10px 20px; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; }}
            button:hover {{ background: #0052a3; }}
            .error {{ background: #ffe7e7; color: #8b0000; border: 1px solid #f5baba; padding: 10px; margin-bottom: 12px; border-radius: 6px; }}
            .badge {{ display: inline-block; padding: 4px 8px; border-radius: 12px; font-weight: 600; margin: 8px 0; }}
            .badge.dry {{ background: #fff3cd; color: #664d03; }}
            .badge.apply {{ background: #d1e7dd; color: #0f5132; }}
            .progress-line {{ margin: 6px 0 12px 0; font-size: 14px; color: #333; }}
            .step-line {{ margin: 0 0 10px 0; font-size: 13px; color: #555; }}
            .logs-toolbar {{ display: flex; justify-content: space-between; align-items: center; margin: 6px 0; font-size: 13px; color: #444; }}
            .logs-toolbar label {{ font-weight: normal; margin: 0; }}
            table {{ width: 100%; border-collapse: collapse; background: white; }}
            th, td {{ padding: 8px; border-bottom: 1px solid #eee; text-align: left; }}
            .counters {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin: 10px 0; }}
            pre {{ background: #f7f7f7; border-radius: 4px; padding: 10px; overflow: auto; max-height: 240px; }}
            .hidden {{ display: none; }}
        </style>
    </head>
    <body>
        <nav>
            <h1>🚀 Trace2Quality</h1>
            <ul>
                <li><a href="/ui">Dashboard</a></li>
                <li><a href="/ui/workflows">Workflows</a></li>
                <li><a href="/ui/runs">Runs</a></li>
            </ul>
        </nav>

        <div class="container">
            <h2>Update Coverage Pages</h2>
            {error_block}
            <form method="post" action="/ui/workflows/update_coverage/run" id="updateCoverageForm">
                <div class="form-group">
                    <label for="mode">Mode</label>
                    <select id="mode" name="mode">
                        <option value="single" {"selected" if mode == "single" else ""}>Single User Story</option>
                        <option value="all_mapped" {"selected" if mode == "all_mapped" else ""}>Batch mapped (all mapped)</option>
                        <option value="all_missing" {"selected" if mode == "all_missing" else ""}>Batch missing (all missing)</option>
                    </select>
                </div>

                <div class="form-group" id="usCodeGroup">
                    <label for="us_code">US Code</label>
                    <input id="us_code" name="us_code" value="{values.get('us_code', '')}" placeholder="US-2.1.1" pattern="^US-[0-9]+(\.[0-9]+)*$" />
                </div>

                <div class="form-row">
                    <div class="form-group">
                        <label for="batch_delay_seconds">Batch Delay Seconds</label>
                        <input id="batch_delay_seconds" type="number" min="0" max="30" name="batch_delay_seconds" value="{values.get('batch_delay_seconds', '3')}" />
                    </div>
                    <div class="form-group">
                        <label for="max_items">Max Items (optional)</label>
                        <input id="max_items" type="number" min="1" name="max_items" value="{values.get('max_items', '')}" />
                    </div>
                </div>

                <div class="checkbox"><input type="checkbox" id="apply" name="apply" {"checked" if _bool_from_form(values.get('apply')) else ""} /><label for="apply">Apply (write to Confluence)</label></div>
                <div class="checkbox"><input type="checkbox" id="force" name="force" {"checked" if _bool_from_form(values.get('force')) else ""} /><label for="force">Force rewrite existing non-stub pages</label></div>
                <div class="checkbox"><input type="checkbox" id="fail_fast" name="fail_fast" {"checked" if _bool_from_form(values.get('fail_fast')) else ""} /><label for="fail_fast">Fail fast in batch mode</label></div>
                <div class="checkbox"><input type="checkbox" id="include_debug_artifacts" name="include_debug_artifacts" {"checked" if _bool_from_form(values.get('include_debug_artifacts')) else ""} /><label for="include_debug_artifacts">Include debug artifacts</label></div>
                <div class="checkbox"><input type="checkbox" id="use_cached_azure_snapshot" name="use_cached_azure_snapshot" {"checked" if _bool_from_form(values.get('use_cached_azure_snapshot')) else ""} /><label for="use_cached_azure_snapshot">Use cached Azure snapshot</label></div>

                <button type="submit">Run Workflow</button>
            </form>

            {run_panel}
        </div>
        <script>
            const modeEl = document.getElementById("mode");
            const usGroupEl = document.getElementById("usCodeGroup");
            const applyEl = document.getElementById("apply");
            const forceEl = document.getElementById("force");

            function syncMode() {{
                const mode = modeEl.value;
                if (mode === "single") {{
                    usGroupEl.classList.remove("hidden");
                }} else {{
                    usGroupEl.classList.add("hidden");
                }}
            }}
            syncMode();
            modeEl.addEventListener("change", syncMode);

            document.getElementById("updateCoverageForm").addEventListener("submit", (e) => {{
                if (applyEl.checked && forceEl.checked) {{
                    const ok = window.confirm("You are about to APPLY with FORCE enabled. Existing non-stub content can be overwritten. Continue?");
                    if (!ok) e.preventDefault();
                }}
            }});
        </script>
    </body>
    </html>
    """


def _render_triage_bugs_page(
    *,
    form_values: dict[str, str] | None = None,
    validation_error: str | None = None,
    run_id: str | None = None,
) -> str:
    default_jql = 'issuetype in ("BE BUG", "Mobile bug", Bug, "FE bug") AND status = Backlog'
    values = {
        "jql": default_jql,
        "max_results": "50",
        "apply": "",
        "add_comment": "",
        "severity_field_id": "customfield_10865",
        "impact_field_id": "customfield_10004",
        "target_status": "Triage",
        "batch_delay_seconds": "10",
    }
    if form_values:
        values.update(form_values)

    error_block = (
        f'<div class="error">Validation error: {validation_error}</div>'
        if validation_error
        else ""
    )

    run_panel = ""
    if run_id:
        run_panel = f"""
        <div class="result-card">
            <h3>Run Monitor</h3>
            <p>Run ID: <code>{run_id}</code></p>
            <div id="dryRunBadge" class="badge">Pending...</div>
            <div id="runProgress" class="progress-line">Preparing monitor...</div>
            <div id="currentStep" class="step-line">Current step: waiting...</div>
            <div class="counters">
                <div>Fetched: <strong id="countFetched">0</strong></div>
                <div>Triaged: <strong id="countTriaged">0</strong></div>
                <div>Not Real Bug: <strong id="countNotReal">0</strong></div>
                <div>Errors: <strong id="countErrors">0</strong></div>
            </div>
            <h4>Status</h4>
            <pre id="runStatus">Loading...</pre>
            <h4>Terminal-Like Stream</h4>
            <div class="logs-toolbar">
                <span id="logMeta">Logs: 0</span>
                <label><input type="checkbox" id="autoScrollLogs" checked /> Auto-scroll</label>
            </div>
            <pre id="liveLogs">Loading logs...</pre>
            <h4>Per-Issue Results</h4>
            <div id="bulkApplyBar" style="display:none; margin-bottom:8px;">
                <button id="btnApplyAll" class="btn-apply-all" onclick="applyAll()">✅ Apply All Real Bugs to Jira</button>
                <label style="margin-left:12px; font-size:13px;"><input type="checkbox" id="addCommentApply" /> Add Jira triage comments</label>
                <span id="bulkApplyStatus" style="margin-left:12px; font-size:13px;"></span>
            </div>
            <table>
                <thead>
                    <tr><th>Key</th><th>Summary</th><th>Real Bug</th><th>Severity</th><th>Impact</th><th>Priority</th><th>Outcome</th><th>Reasoning</th><th id="applyColHeader"></th></tr>
                </thead>
                <tbody id="resultsTableBody"><tr><td colspan="9">Waiting for results...</td></tr></tbody>
            </table>
            <h4>Artifacts</h4>
            <ul id="artifactLinks"><li>Waiting for artifacts...</li></ul>
        </div>
        <script>
            const runId = "{run_id}";
            let done = false;
            let isDryRun = true;
            let runFinished = false;
            let lastRows = [];
            const monitorStartedAt = Date.now();
            let lastLogTimestamp = null;
            const POLL_INTERVAL_MS = 1000;
            const ARTIFACT_POLL_EVERY_TICKS = 5;
            let tickCount = 0;

            function outcomeClass(outcome) {{
                if (outcome === 'triaged') return 'outcome-ok';
                if (outcome === 'dry_run') return 'outcome-dry';
                if (outcome === 'error' || outcome === 'partial_update') return 'outcome-err';
                return 'outcome-skip';
            }}

            function fmtElapsed(ms) {{
                const sec = Math.floor(ms / 1000);
                const min = Math.floor(sec / 60);
                const rem = sec % 60;
                return `${{min}}m ${{rem}}s`;
            }}

            async function refreshRun() {{
                const runResp = await fetch(`/api/runs/${{runId}}`);
                if (!runResp.ok) {{
                    const msg = `Failed to load run status (HTTP ${{runResp.status}})`;
                    document.getElementById("runStatus").textContent = msg;
                    document.getElementById("runProgress").textContent = msg;
                    return;
                }}
                const run = await runResp.json();
                document.getElementById("runStatus").textContent = JSON.stringify(run, null, 2);

                const elapsed = fmtElapsed(Date.now() - monitorStartedAt);
                const statusUpper = String(run.status || "unknown").toUpperCase();
                document.getElementById("runProgress").textContent = `Status: ${{statusUpper}} | Elapsed: ${{elapsed}}`;

                const dryRunBadge = document.getElementById("dryRunBadge");
                if (run.dry_run) {{
                    isDryRun = true;
                    dryRunBadge.textContent = "DRY-RUN (preview only \u2014 no Jira changes)";
                    dryRunBadge.className = "badge dry";
                }} else {{
                    isDryRun = false;
                    dryRunBadge.textContent = "APPLY MODE (writes enabled — Jira will be updated)";
                    dryRunBadge.className = "badge apply";
                }}

                const logsResp = await fetch(`/api/runs/${{runId}}/logs`);
                if (logsResp.ok) {{
                    const logsData = await logsResp.json();
                    const logs = logsData.logs || [];
                    const stripLogPrefix = (msg) => msg.replace(/^\[[\dT:.+\-Z]+\]\s*\[cid=[^\]]+\]\s*/, "");
                    const lines = logs.map((l) => `${{l.timestamp}} [${{l.level}}] ${{stripLogPrefix(l.message)}}`);
                    const logsEl = document.getElementById("liveLogs");
                    logsEl.textContent = lines.join("\\n") || "No logs yet";

                    if (logs.length > 0) {{
                        lastLogTimestamp = logs[logs.length - 1].timestamp;
                    }}
                    document.getElementById("logMeta").textContent =
                        `Logs: ${{logs.length}} | Last update: ${{lastLogTimestamp || "n/a"}}`;

                    const currentStepEl = document.getElementById("currentStep");
                    if (logs.length > 0) {{
                        const last = logs[logs.length - 1];
                        currentStepEl.textContent = `Current step: [${{last.level}}] ${{stripLogPrefix(last.message)}}`;
                    }} else {{
                        currentStepEl.textContent = "Current step: waiting for first log line...";
                    }}

                    if (document.getElementById("autoScrollLogs").checked) {{
                        logsEl.scrollTop = logsEl.scrollHeight;
                    }}

                    if (run.status === "running" || run.status === "queued") {{
                        const waitHint = logs.length === 0
                            ? "Waiting for worker logs..."
                            : "Workflow is running. Gemini calls may take time; logs update as each issue is processed.";
                        document.getElementById("runProgress").textContent =
                            `Status: ${{statusUpper}} | Elapsed: ${{elapsed}} | ${{waitHint}}`;
                    }}
                }}

                const isTerminal = ["succeeded", "failed", "canceled"].includes(run.status);
                if (isTerminal) {{
                    runFinished = true;
                }}

                const shouldPollArtifacts =
                    (tickCount % ARTIFACT_POLL_EVERY_TICKS === 0) ||
                    isTerminal;

                if (shouldPollArtifacts) {{
                    const artifactResp = await fetch(`/api/artifacts/run/${{runId}}`);
                    if (artifactResp.ok) {{
                        const artifacts = await artifactResp.json();
                        const linksEl = document.getElementById("artifactLinks");
                        linksEl.innerHTML = "";
                        for (const item of artifacts) {{
                            const li = document.createElement("li");
                            const a = document.createElement("a");
                            a.href = item.download_url;
                            a.textContent = item.filename;
                            li.appendChild(a);
                            linksEl.appendChild(li);
                        }}

                        const summaryArtifact = artifacts.find((a) => a.filename === "triage_summary.json");
                        if (summaryArtifact) {{
                            const summaryResp = await fetch(summaryArtifact.download_url);
                            if (summaryResp.ok) {{
                                const summary = await summaryResp.json();
                                document.getElementById("countFetched").textContent = summary.bugs_fetched ?? 0;
                                document.getElementById("countTriaged").textContent = summary.bugs_triaged ?? 0;
                                document.getElementById("countNotReal").textContent = summary.skipped_not_real_bug ?? 0;
                                document.getElementById("countErrors").textContent = summary.errors ?? 0;
                            }}
                        }}

                        const perIssueArtifact = artifacts.find((a) => a.filename === "per_issue_results.json");
                        if (perIssueArtifact) {{
                            const resultResp = await fetch(perIssueArtifact.download_url);
                            if (resultResp.ok) {{
                                const rows = await resultResp.json();
                                lastRows = rows;
                                const body = document.getElementById("resultsTableBody");
                                body.innerHTML = "";
                                const showApplyCol = isDryRun && runFinished;
                                document.getElementById("applyColHeader").textContent = showApplyCol ? "Apply" : "";
                                for (const row of rows) {{
                                    const tr = document.createElement("tr");
                                    tr.id = `row-${{row.key}}`;
                                    tr.className = outcomeClass(row.outcome);
                                    const isReal = row.is_real_bug === null ? "-" : row.is_real_bug ? "✅ Yes" : "❌ No";
                                    const sev = row.severity || "-";
                                    const imp = row.impact || "-";
                                    const pri = row.priority || "-";
                                    const applyCell = (showApplyCol && row.is_real_bug)
                                        ? `<td><button class="btn-apply-row" onclick="applyOne('${{row.key}}', this)">Apply</button></td>`
                                        : `<td></td>`;
                                    tr.innerHTML = `
                                        <td><a href="/ui/runs" target="_blank">${{row.key || ""}}</a></td>
                                        <td>${{row.summary || ""}}</td>
                                        <td>${{isReal}}</td>
                                        <td>${{sev}}</td>
                                        <td>${{imp}}</td>
                                        <td>${{pri}}</td>
                                        <td><span class="outcome-badge ${{row.outcome || ""}}">${{row.outcome || ""}}</span></td>
                                        <td>${{row.reasoning || row.reason || ""}}</td>
                                        ${{applyCell}}
                                    `;
                                    body.appendChild(tr);
                                }}
                                if (showApplyCol && rows.some(r => r.is_real_bug)) {{
                                    document.getElementById("bulkApplyBar").style.display = "";
                                }}
                            }}
                        }}
                    }}
                }}

                if (isTerminal) {{
                    done = true;
                }}
            }}

            async function _callApply(issueKeys) {{
                const statusEl = document.getElementById("bulkApplyStatus");
                const addComment = !!document.getElementById("addCommentApply")?.checked;
                const resp = await fetch("/api/workflows/triage-bugs/apply-issues", {{
                    method: "POST",
                    headers: {{ "Content-Type": "application/json" }},
                    body: JSON.stringify({{ run_id: runId, issue_keys: issueKeys, add_comment: addComment }}),
                }});
                if (!resp.ok) {{
                    const err = await resp.text();
                    statusEl.textContent = `Error: ${{err}}`;
                    return null;
                }}
                return await resp.json();
            }}

            async function applyOne(issueKey, btn) {{
                const addComment = !!document.getElementById("addCommentApply")?.checked;
                const commentSuffix = addComment ? " and post a triage comment" : "";
                if (!confirm(`Apply triage to ${{issueKey}} in Jira${{commentSuffix}}?`)) return;
                btn.disabled = true;
                btn.textContent = "...";
                const result = await _callApply([issueKey]);
                if (!result) {{ btn.textContent = "Error"; return; }}
                if (result.applied && result.applied.includes(issueKey)) {{
                    btn.textContent = "\u2705 Applied";
                    btn.style.background = "#198754";
                }} else if (result.errors && result.errors.length) {{
                    btn.textContent = "\u274c Failed";
                    btn.title = result.errors[0]?.error || "";
                    btn.style.background = "#dc3545";
                }}
            }}

            async function applyAll() {{
                const realBugKeys = lastRows.filter(r => r.is_real_bug).map(r => r.key);
                if (!realBugKeys.length) return;
                const addComment = !!document.getElementById("addCommentApply")?.checked;
                const commentSuffix = addComment ? " and add triage comments" : "";
                if (!confirm(`Apply triage to ${{realBugKeys.length}} real bug(s) in Jira? This will update severity, impact, priority and transition status${{commentSuffix}}.`)) return;
                const statusEl = document.getElementById("bulkApplyStatus");
                const allBtn = document.getElementById("btnApplyAll");
                allBtn.disabled = true;
                statusEl.textContent = "Applying...";
                const result = await _callApply(null);
                if (!result) {{ statusEl.textContent = "Request failed."; allBtn.disabled = false; return; }}
                statusEl.textContent = `\u2705 Applied ${{result.applied_count}} | \u274c Errors: ${{result.error_count}}`;
                document.querySelectorAll(".btn-apply-row").forEach(b => {{
                    const key = b.closest("tr")?.id?.replace("row-", "");
                    if (result.applied && result.applied.includes(key)) {{
                        b.textContent = "\u2705 Applied"; b.disabled = true; b.style.background = "#198754";
                    }} else if (result.errors && result.errors.some(e => e.key === key)) {{
                        b.textContent = "\u274c Failed"; b.disabled = true; b.style.background = "#dc3545";
                    }}
                }});
            }}

            async function tick() {{
                tickCount += 1;
                try {{ await refreshRun(); }} catch (e) {{}}
                if (!done) setTimeout(tick, POLL_INTERVAL_MS);
            }}
            tick();
        </script>
        """

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Run Triage Bugs - Trace2Quality</title>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f5f5f5; }}
            nav {{ background: #0066cc; color: white; padding: 15px 30px; }}
            nav h1 {{ margin: 0; font-size: 24px; }}
            nav ul {{ list-style: none; display: flex; gap: 20px; margin-top: 10px; }}
            nav a {{ color: white; text-decoration: none; }}
            .container {{ max-width: 1100px; margin: 0 auto; padding: 20px; }}
            h2 {{ color: #333; margin: 20px 0 10px 0; }}
            form, .result-card {{ background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); margin-bottom: 16px; }}
            .form-row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
            .form-group {{ margin-bottom: 14px; }}
            label {{ display: block; font-weight: bold; margin-bottom: 6px; color: #333; }}
            input, select, textarea {{ width: 100%; padding: 8px; border: 1px solid #ddd; border-radius: 4px; font-family: inherit; }}
            textarea {{ font-family: monospace; font-size: 13px; resize: vertical; }}
            .checkbox {{ display: flex; gap: 8px; align-items: center; margin-bottom: 8px; }}
            .checkbox input {{ width: auto; }}
            .checkbox label {{ font-weight: normal; margin: 0; }}
            button {{ background: #0066cc; color: white; padding: 10px 20px; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; }}
            button:hover {{ background: #0052a3; }}
            .error {{ background: #ffe7e7; color: #8b0000; border: 1px solid #f5baba; padding: 10px; margin-bottom: 12px; border-radius: 6px; }}
            .badge {{ display: inline-block; padding: 4px 8px; border-radius: 12px; font-weight: 600; margin: 8px 0; }}
            .badge.dry {{ background: #fff3cd; color: #664d03; }}
            .badge.apply {{ background: #d1e7dd; color: #0f5132; }}
            .progress-line {{ margin: 6px 0 12px 0; font-size: 14px; color: #333; }}
            .step-line {{ margin: 0 0 10px 0; font-size: 13px; color: #555; }}
            .logs-toolbar {{ display: flex; justify-content: space-between; align-items: center; margin: 6px 0; font-size: 13px; color: #444; }}
            .logs-toolbar label {{ font-weight: normal; margin: 0; }}
            table {{ width: 100%; border-collapse: collapse; }}
            th, td {{ padding: 8px; border-bottom: 1px solid #eee; text-align: left; font-size: 13px; }}
            th {{ background: #f9f9f9; font-weight: bold; }}
            .counters {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin: 10px 0; }}
            .counters div {{ background: #f5f5f5; border-radius: 6px; padding: 10px; text-align: center; font-size: 13px; }}
            pre {{ background: #1e1e1e; color: #d4d4d4; border-radius: 4px; padding: 10px; overflow: auto; max-height: 260px; font-size: 12px; }}
            .outcome-badge {{ display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 12px; font-weight: 600; }}
            .triaged td, tr.outcome-ok td {{ background: #f0fff4; }}
            tr.outcome-dry td {{ background: #fffbea; }}
            tr.outcome-err td {{ background: #fff5f5; }}
            tr.outcome-skip td {{ background: #fafafa; }}
            .outcome-badge.triaged {{ background: #d1e7dd; color: #0f5132; }}
            .outcome-badge.dry_run {{ background: #fff3cd; color: #664d03; }}
            .outcome-badge.error, .outcome-badge.partial_update {{ background: #f8d7da; color: #842029; }}
            .outcome-badge.skipped, .outcome-badge.not_real_bug {{ background: #e2e3e5; color: #41464b; }}
            h4 {{ margin: 16px 0 6px 0; color: #333; }}
            .hint {{ font-size: 12px; color: #666; margin-top: 4px; }}
            .btn-apply-row {{ background: #0066cc; color: white; border: none; border-radius: 4px; padding: 3px 10px; font-size: 12px; cursor: pointer; white-space: nowrap; }}
            .btn-apply-row:hover {{ background: #0052a3; }}
            .btn-apply-row:disabled {{ opacity: 0.7; cursor: default; }}
            .btn-apply-all {{ background: #198754; color: white; border: none; border-radius: 4px; padding: 8px 16px; font-size: 13px; cursor: pointer; font-weight: 600; }}
            .btn-apply-all:hover {{ background: #157347; }}
            .btn-apply-all:disabled {{ opacity: 0.7; cursor: default; }}
        </style>
    </head>
    <body>
        <nav>
            <h1>🚀 Trace2Quality</h1>
            <ul>
                <li><a href="/ui">Dashboard</a></li>
                <li><a href="/ui/workflows">Workflows</a></li>
                <li><a href="/ui/runs">Runs</a></li>
            </ul>
        </nav>

        <div class="container">
            <h2>Triage Bug Tickets</h2>
            <p style="margin-bottom: 16px; color: #555;">Fetches bug issues from Jira, looks up their User Story spec in Confluence, and uses Gemini to classify severity and impact. In dry-run mode no changes are made to Jira.</p>
            {error_block}
            <form method="post" action="/ui/workflows/triage_bugs/run" id="triageBugsForm">
                <div class="form-group">
                    <label for="jql">JQL Query</label>
                    <textarea id="jql" name="jql" rows="3">{values.get('jql', '')}</textarea>
                    <p class="hint">Jira Query Language filter — only issues matching this query will be triaged.</p>
                </div>

                <div class="form-row">
                    <div class="form-group">
                        <label for="max_results">Max Results</label>
                        <input id="max_results" type="number" min="1" max="500" name="max_results" value="{values.get('max_results', '50')}" />
                    </div>
                    <div class="form-group">
                        <label for="batch_delay_seconds">Delay Between Gemini Calls (seconds)</label>
                        <input id="batch_delay_seconds" type="number" min="0" max="60" name="batch_delay_seconds" value="{values.get('batch_delay_seconds', '10')}" />
                    </div>
                </div>

                <div class="form-row">
                    <div class="form-group">
                        <label for="severity_field_id">Jira Severity Field ID</label>
                        <input id="severity_field_id" name="severity_field_id" value="{values.get('severity_field_id', 'customfield_10865')}" />
                    </div>
                    <div class="form-group">
                        <label for="impact_field_id">Jira Impact Field ID</label>
                        <input id="impact_field_id" name="impact_field_id" value="{values.get('impact_field_id', 'customfield_10004')}" />
                    </div>
                </div>

                <div class="form-group">
                    <label for="target_status">Target Jira Status (after triage)</label>
                    <input id="target_status" name="target_status" value="{values.get('target_status', 'Triage')}" />
                </div>

                <div class="checkbox">
                    <input type="checkbox" id="apply" name="apply" {"checked" if _bool_from_form(values.get('apply')) else ""} />
                    <label for="apply">Apply (update Jira fields and transition status)</label>
                </div>

                <div class="checkbox">
                    <input type="checkbox" id="add_comment" name="add_comment" {"checked" if _bool_from_form(values.get('add_comment')) else ""} />
                    <label for="add_comment">Add Jira triage comment (optional, off by default)</label>
                </div>

                <button type="submit">Run Triage</button>
            </form>

            {run_panel}
        </div>
        <script>
            document.getElementById("triageBugsForm").addEventListener("submit", (e) => {{
                const applyEl = document.getElementById("apply");
                if (applyEl.checked) {{
                    const ok = window.confirm("You are about to APPLY triage changes. Severity, impact, and status will be written to Jira. Continue?");
                    if (!ok) e.preventDefault();
                }}
            }});
        </script>
    </body>
    </html>
    """


@router.get("", response_class=HTMLResponse)
async def workflows_page(request: Request) -> str:
    """Workflows page"""
    workflow_rows = ""

    for workflow in WorkflowType:
        if workflow.value in HIDDEN_WEBAPP_WORKFLOW_KEYS:
            continue
        workflow_rows += f"""
        <tr>
            <td>{workflow.value}</td>
            <td>{workflow.value.replace('_', ' ').title()}</td>
            <td><a href="/ui/workflows/{workflow.value}/run">Run Workflow</a></td>
        </tr>
        """

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Workflows - Trace2Quality</title>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f5f5f5; }}
            nav {{ background: #0066cc; color: white; padding: 15px 30px; }}
            nav h1 {{ margin: 0; font-size: 24px; }}
            nav ul {{ list-style: none; display: flex; gap: 20px; margin-top: 10px; }}
            nav a {{ color: white; text-decoration: none; }}
            .container {{ max-width: 1000px; margin: 0 auto; padding: 20px; }}
            h2 {{ color: #333; margin: 20px 0 10px 0; }}
            table {{ width: 100%; border-collapse: collapse; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
            th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #eee; }}
            th {{ background: #f9f9f9; font-weight: bold; }}
            a {{ color: #0066cc; text-decoration: none; }}
        </style>
    </head>
    <body>
        <nav>
            <h1>🚀 Trace2Quality</h1>
            <ul>
                <li><a href="/ui">Dashboard</a></li>
                <li><a href="/ui/workflows">Workflows</a></li>
                <li><a href="/ui/runs">Runs</a></li>
            </ul>
        </nav>

        <div class="container">
            <h2>Available Workflows</h2>
            <p>Select a workflow to run</p>

            <table>
                <thead>
                    <tr>
                        <th>Key</th>
                        <th>Name</th>
                        <th>Action</th>
                    </tr>
                </thead>
                <tbody>
                    {workflow_rows}
                </tbody>
            </table>
        </div>
    </body>
    </html>
    """


@router.get("/{workflow_key}/run", response_class=HTMLResponse)
async def run_workflow_page(request: Request, workflow_key: str) -> str:
    """Workflow run form"""
    # Validate workflow exists
    try:
        WorkflowType(workflow_key)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Unknown workflow: {workflow_key}")

    if workflow_key in HIDDEN_WEBAPP_WORKFLOW_KEYS:
        raise HTTPException(status_code=404, detail=f"Unknown workflow: {workflow_key}")

    if workflow_key == "update_coverage":
        run_id = request.query_params.get("run_id")
        return _render_update_coverage_page(run_id=run_id)

    if workflow_key == "triage_bugs":
        run_id = request.query_params.get("run_id")
        return _render_triage_bugs_page(run_id=run_id)

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Run {workflow_key} - Trace2Quality</title>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f5f5f5; }}
            nav {{ background: #0066cc; color: white; padding: 15px 30px; }}
            nav h1 {{ margin: 0; font-size: 24px; }}
            nav ul {{ list-style: none; display: flex; gap: 20px; margin-top: 10px; }}
            nav a {{ color: white; text-decoration: none; }}
            .container {{ max-width: 1000px; margin: 0 auto; padding: 20px; }}
            h2 {{ color: #333; margin: 20px 0 10px 0; }}
            form {{ background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
            .form-group {{ margin-bottom: 15px; }}
            label {{ display: block; font-weight: bold; margin-bottom: 5px; color: #333; }}
            input, textarea {{ width: 100%; padding: 8px; border: 1px solid #ddd; border-radius: 4px; font-family: monospace; }}
            button {{ background: #0066cc; color: white; padding: 10px 20px; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; }}
            button:hover {{ background: #0052a3; }}
            .back-link {{ margin-top: 20px; }}
            .back-link a {{ color: #0066cc; text-decoration: none; }}
        </style>
    </head>
    <body>
        <nav>
            <h1>🚀 Trace2Quality</h1>
            <ul>
                <li><a href="/ui">Dashboard</a></li>
                <li><a href="/ui/workflows">Workflows</a></li>
                <li><a href="/ui/runs">Runs</a></li>
            </ul>
        </nav>

        <div class="container">
            <h2>Run Workflow: {workflow_key}</h2>
            
            <form method="post" action="/api/workflows/{workflow_key}/runs">
                <div class="form-group">
                    <label for="parameters">Parameters (JSON):</label>
                    <textarea id="parameters" name="parameters" rows="10" placeholder="{{}}">{{}}</textarea>
                </div>
                
                <div class="form-group">
                    <input type="checkbox" id="dry_run" name="dry_run" value="true">
                    <label for="dry_run" style="display: inline; font-weight: normal;">Dry run (no changes)</label>
                </div>
                
                <button type="submit">Run Workflow</button>
            </form>

            <div class="back-link">
                <a href="/ui/workflows">← Back to Workflows</a>
            </div>
        </div>
    </body>
    </html>
    """


@router.post("/triage_bugs/run", response_class=HTMLResponse)
async def run_triage_bugs_submit(request: Request, db: Session = Depends(get_db)):
    """Form submit endpoint for triage_bugs workflow UI."""
    form = await request.form()
    form_values = {k: str(v) for k, v in form.items()}

    payload = {
        "jql": str(form.get("jql") or "").strip() or 'issuetype in ("BE BUG", "Mobile bug", Bug, "FE bug") AND status = Backlog',
        "max_results": int(str(form.get("max_results") or "50").strip() or "50"),
        "apply": _bool_from_form(form.get("apply")),
        "add_comment": _bool_from_form(form.get("add_comment")),
        "severity_field_id": str(form.get("severity_field_id") or "customfield_10865").strip(),
        "impact_field_id": str(form.get("impact_field_id") or "customfield_10004").strip(),
        "target_status": str(form.get("target_status") or "Triage").strip(),
        "batch_delay_seconds": int(str(form.get("batch_delay_seconds") or "10").strip() or "10"),
    }

    try:
        validated = TriageBugTicketsRunRequest(**payload)
    except (ValidationError, ValueError) as exc:
        return _render_triage_bugs_page(
            form_values=form_values,
            validation_error=str(exc),
        )

    run_id = str(uuid4())
    run = WorkflowRunModel(
        id=run_id,
        workflow_key="triage_bugs",
        parameters=validated.model_dump(),
        dry_run="0" if validated.apply else "1",
        status="queued",
        created_at=datetime.utcnow(),
    )
    db.add(run)
    db.commit()

    enqueue_workflow(run_id, "triage_bugs")
    return RedirectResponse(url=f"/ui/workflows/triage_bugs/run?run_id={run_id}", status_code=303)


@router.post("/update_coverage/run", response_class=HTMLResponse)
async def run_update_coverage_submit(request: Request, db: Session = Depends(get_db)):
    """Form submit endpoint for update_coverage workflow UI."""
    form = await request.form()
    form_values = {k: str(v) for k, v in form.items()}

    max_items_raw = str(form.get("max_items") or "").strip()

    payload = {
        "mode": str(form.get("mode") or "single").strip(),
        "us_code": str(form.get("us_code") or "").strip() or None,
        "apply": _bool_from_form(form.get("apply")),
        "force": _bool_from_form(form.get("force")),
        "batch_delay_seconds": int(str(form.get("batch_delay_seconds") or "3").strip() or "3"),
        "max_items": int(max_items_raw) if max_items_raw else None,
        "fail_fast": _bool_from_form(form.get("fail_fast")),
        "include_debug_artifacts": _bool_from_form(form.get("include_debug_artifacts")),
        "use_cached_azure_snapshot": _bool_from_form(form.get("use_cached_azure_snapshot")),
    }

    try:
        validated = UpdateCoverageRunRequest(**payload)
    except (ValidationError, ValueError) as exc:
        friendly = _friendly_coverage_validation_error(exc)
        return _render_update_coverage_page(
            form_values=form_values,
            validation_error=friendly,
        )

    run_id = str(uuid4())
    run = WorkflowRunModel(
        id=run_id,
        workflow_key="update_coverage",
        parameters=validated.model_dump(),
        dry_run="0" if validated.apply else "1",
        status="queued",
        created_at=datetime.utcnow(),
    )
    db.add(run)
    db.commit()

    enqueue_workflow(run_id, "update_coverage")
    return RedirectResponse(url=f"/ui/workflows/update_coverage/run?run_id={run_id}", status_code=303)
