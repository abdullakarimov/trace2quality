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
from packages.common import UpdateCoverageRunRequest
from packages.common import WorkflowType

router = APIRouter()


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


def _render_update_coverage_page(
    *,
    form_values: dict[str, str] | None = None,
    validation_error: str | None = None,
    run_id: str | None = None,
) -> str:
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
            let done = false;
            const monitorStartedAt = Date.now();
            let lastLogTimestamp = null;

            function fmtElapsed(ms) {{
                const sec = Math.floor(ms / 1000);
                const min = Math.floor(sec / 60);
                const rem = sec % 60;
                return `${{min}}m ${{rem}}s`;
            }}

            async function refreshRun() {{
                const runResp = await fetch(`/api/runs/${{runId}}`);
                if (!runResp.ok) return;
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
                    const lines = logs.map((l) => `${{l.timestamp}} [${{l.level}}] ${{l.message}}`);
                    const logsEl = document.getElementById("liveLogs");
                    logsEl.textContent = lines.join("\n") || "No logs yet";

                    if (logs.length > 0) {{
                        lastLogTimestamp = logs[logs.length - 1].timestamp;
                    }}
                    const logMeta = `Logs: ${{logs.length}} | Last update: ${{lastLogTimestamp || "n/a"}}`;
                    document.getElementById("logMeta").textContent = logMeta;

                    const currentStepEl = document.getElementById("currentStep");
                    if (logs.length > 0) {{
                        const last = logs[logs.length - 1];
                        currentStepEl.textContent = `Current step: [${{last.level}}] ${{last.message}}`;
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
                                tr.innerHTML = `<td>${{row.us_code || ""}}</td><td>${{row.action || ""}}</td><td>${{row.tc_page_id || ""}}</td><td>${{row.message || ""}}</td>`;
                                body.appendChild(tr);
                            }}
                        }}
                    }}
                }}

                if (["succeeded", "failed", "canceled"].includes(run.status)) {{
                    done = true;
                }}
            }}

            async function tick() {{
                try {{ await refreshRun(); }} catch (e) {{}}
                if (!done) setTimeout(tick, 1000);
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
                <li><a href="/ui/integrations">Integrations</a></li>
                <li><a href="/ui/data">Data Explorer</a></li>
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


@router.get("", response_class=HTMLResponse)
async def workflows_page(request: Request) -> str:
    """Workflows page"""
    workflow_rows = ""

    for workflow in WorkflowType:
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
                <li><a href="/ui/integrations">Integrations</a></li>
                <li><a href="/ui/data">Data Explorer</a></li>
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

    if workflow_key == "update_coverage":
        run_id = request.query_params.get("run_id")
        return _render_update_coverage_page(run_id=run_id)

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
                <li><a href="/ui/integrations">Integrations</a></li>
                <li><a href="/ui/data">Data Explorer</a></li>
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
        return _render_update_coverage_page(
            form_values=form_values,
            validation_error=str(exc),
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
