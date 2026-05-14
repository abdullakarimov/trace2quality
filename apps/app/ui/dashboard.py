"""Dashboard UI"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from apps.app.database import get_session_factory, WorkflowRunModel
from apps.app.config import get_settings
from packages.common import get_logger

logger = get_logger(__name__)

router = APIRouter()


def get_db(request: Request) -> Session:
    """Get database session"""
    settings = get_settings()
    SessionLocal = get_session_factory(settings.database_url)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@router.get("/ui", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)) -> str:
    """Dashboard homepage"""
    correlation_id = getattr(request.state, "correlation_id", None)

    # Get recent runs
    recent_runs = (
        db.query(WorkflowRunModel)
        .order_by(WorkflowRunModel.created_at.desc())
        .limit(5)
        .all()
    )

    runs_html = ""
    for run in recent_runs:
        status_color = {
            "queued": "blue",
            "running": "orange",
            "succeeded": "green",
            "failed": "red",
            "canceled": "gray",
        }.get(run.status.value, "gray")

        runs_html += f"""
        <div style="padding: 10px; border-bottom: 1px solid #eee;">
            <strong>{run.workflow_key}</strong>
            <span style="background: {status_color}; color: white; padding: 2px 6px; border-radius: 3px; font-size: 12px;">
                {run.status.value.upper()}
            </span>
            <small>{run.created_at.strftime('%Y-%m-%d %H:%M:%S')}</small>
            <br/>
            <a href="/ui/runs/{run.id}">View Details →</a>
        </div>
        """

    logger.info("Rendered dashboard", correlation_id=correlation_id)

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Trace2Quality - Dashboard</title>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f5f5f5; }}
            nav {{ background: #0066cc; color: white; padding: 15px 30px; }}
            nav h1 {{ margin: 0; font-size: 24px; }}
            nav ul {{ list-style: none; display: flex; gap: 20px; margin-top: 10px; }}
            nav a {{ color: white; text-decoration: none; }}
            nav a:hover {{ text-decoration: underline; }}
            .container {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}
            h2 {{ color: #333; margin: 20px 0 10px 0; }}
            .card {{ background: white; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
            .card-header {{ background: #f9f9f9; padding: 15px; border-bottom: 1px solid #eee; font-weight: bold; }}
            .card-content {{ padding: 0; }}
            a {{ color: #0066cc; text-decoration: none; }}
            a:hover {{ text-decoration: underline; }}
            .actions-block {{
                background: linear-gradient(135deg, #0052a3 0%, #0b6bc8 55%, #3789da 100%);
                border-radius: 14px;
                padding: 22px;
                margin: 16px 0 24px 0;
                box-shadow: 0 8px 20px rgba(0, 82, 163, 0.22);
                color: white;
            }}
            .actions-title {{ font-size: 22px; font-weight: 700; margin-bottom: 8px; }}
            .actions-subtitle {{ color: #e9f3ff; margin-bottom: 16px; }}
            .action-buttons {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }}
            .action-btn {{
                display: block;
                background: rgba(255, 255, 255, 0.15);
                border: 1px solid rgba(255, 255, 255, 0.3);
                color: white;
                text-decoration: none;
                border-radius: 10px;
                padding: 16px;
                min-height: 96px;
                transition: transform 0.15s ease, background 0.15s ease;
            }}
            .action-btn:hover {{
                background: rgba(255, 255, 255, 0.24);
                text-decoration: none;
                transform: translateY(-1px);
            }}
            .action-btn .label {{ display: block; font-size: 18px; font-weight: 700; margin-bottom: 4px; }}
            .action-btn .hint {{ display: block; font-size: 13px; color: #e9f3ff; }}
            @media (max-width: 900px) {{
                .action-buttons {{ grid-template-columns: 1fr; }}
            }}
        </style>
    </head>
    <body>
        <nav>
            <h1>🚀 Trace2Quality</h1>
            <ul>
                <li><a href="/ui">Dashboard</a></li>
                <li><a href="/ui/workflows">Workflows</a></li>
                <li><a href="/ui/runs">Runs</a></li>
                <li><a href="/docs">API Docs</a></li>
            </ul>
        </nav>

        <div class="container">
            <h2>Dashboard</h2>
            <p>Welcome to Trace2Quality - Enterprise QA Automation and Traceability</p>

            <div class="actions-block">
                <div class="actions-title">Primary Workflows</div>
                <div class="actions-subtitle">Start the most important workflows directly from home.</div>
                <div class="action-buttons">
                    <a class="action-btn" href="/ui/workflows/update_coverage/run">
                        <span class="label">Update Coverage</span>
                        <span class="hint">Refresh requirement coverage pages.</span>
                    </a>
                    <a class="action-btn" href="/ui/workflows/triage_bugs/run">
                        <span class="label">Triage Bugs</span>
                        <span class="hint">Analyze defects and identify automation gaps.</span>
                    </a>
                    <a class="action-btn" href="/ui/csv-fixer">
                        <span class="label">CSV Fixer</span>
                        <span class="hint">Fix broken ADO Test Plan CSV files for import.</span>
                    </a>
                </div>
            </div>

            <div class="card">
                <div class="card-header">Recent Runs</div>
                <div class="card-content">
                    {runs_html if runs_html else '<div style="padding: 20px; text-align: center; color: #999;">No runs yet</div>'}
                    <div style="padding: 10px;">
                        <a href="/ui/runs">View All Runs →</a>
                    </div>
                </div>
            </div>
        </div>
    </body>
    </html>
    """


@router.get("/ui/orphan-test-cases", response_class=HTMLResponse)
async def orphan_test_cases_page(request: Request) -> str:
    """Azure DevOps orphan Test Cases management page."""
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Azure DevOps Orphan Test Cases - Trace2Quality</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f5f5f5; }
            nav { background: #0066cc; color: white; padding: 15px 30px; }
            nav h1 { margin: 0; font-size: 24px; }
            nav ul { list-style: none; display: flex; gap: 20px; margin-top: 10px; }
            nav a { color: white; text-decoration: none; }
            .container { max-width: 1100px; margin: 0 auto; padding: 20px; }
            h2 { color: #333; margin: 20px 0 10px 0; }
            .panel { background: white; border-radius: 8px; padding: 16px; margin: 16px 0; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
            .toolbar { display: flex; gap: 10px; margin: 16px 0; }
            button { background: #0066cc; color: white; border: none; padding: 8px 14px; border-radius: 4px; cursor: pointer; }
            button:hover { background: #0052a3; }
            button.danger { background: #c62828; }
            button.danger:hover { background: #a61f1f; }
            button.secondary { background: #5c6bc0; }
            button.secondary:hover { background: #3949ab; }
            button:disabled { background: #b3b3b3; cursor: not-allowed; }
            .reassign-form { display: flex; align-items: center; gap: 8px; }
            .reassign-form input[type=email] { padding: 7px 10px; border: 1px solid #ccc; border-radius: 4px; font-size: 14px; width: 260px; }
            .reassign-form input[type=email]:disabled { background: #f5f5f5; }
            table { width: 100%; border-collapse: collapse; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
            th, td { padding: 10px; text-align: left; border-bottom: 1px solid #eee; }
            th { background: #f9f9f9; font-weight: bold; }
            .summary { background: white; border-radius: 8px; padding: 12px; margin: 12px 0; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
            .muted { color: #666; }
            .empty { background: white; border-radius: 8px; padding: 20px; color: #333; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
            .back-link { margin-top: 18px; }
            .back-link a { color: #0066cc; text-decoration: none; }
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
            <h2>Azure DevOps Orphan Test Cases</h2>
            <p class="muted">Test Case work items that are not assigned to any test suite.</p>

            <div class="toolbar">
                <button onclick="loadOrphans()">Refresh</button>
                <button id="deleteBtn" class="danger" onclick="deleteSelected()" disabled>Delete Selected</button>
            </div>
            <div class="reassign-form">
                <input type="email" id="assigneeEmail" placeholder="Assignee email" disabled />
                <button id="reassignBtn" class="secondary" onclick="reassignSelected()" disabled>Re-assign Selected</button>
            </div>

            <div id="summary" class="summary" style="display:none;"></div>
            <div id="content"></div>

            <div class="back-link">
                <a href="/ui">← Back to Dashboard</a>
            </div>
        </div>

        <script>
        let currentItems = [];

        function escapeHtml(value) {
            const div = document.createElement('div');
            div.textContent = value || '';
            return div.innerHTML;
        }

        function updateActionButtons() {
            const selected = document.querySelectorAll('input[name="caseSelect"]:checked');
            const hasSelection = selected.length > 0;
            document.getElementById('deleteBtn').disabled = !hasSelection;
            document.getElementById('reassignBtn').disabled = !hasSelection;
            document.getElementById('assigneeEmail').disabled = !hasSelection;
        }

        function renderTable(items) {
            const content = document.getElementById('content');
            if (!items.length) {
                content.innerHTML = '<div class="empty">No orphan Test Cases found.</div>';
                return;
            }

            const rows = items.map((item) => `
                <tr>
                    <td><input type="checkbox" name="caseSelect" value="${escapeHtml(item.id)}" onchange="updateActionButtons()"></td>
                    <td>${escapeHtml(item.id)}</td>
                    <td>${escapeHtml(item.title)}</td>
                    <td>${escapeHtml(item.state)}</td>
                    <td>${escapeHtml(item.area_path)}</td>
                    <td>${escapeHtml(item.iteration_path)}</td>
                </tr>
            `).join('');

            content.innerHTML = `
                <table>
                    <thead>
                        <tr>
                            <th><input type="checkbox" id="selectAll"></th>
                            <th>ID</th>
                            <th>Title</th>
                            <th>State</th>
                            <th>Area</th>
                            <th>Iteration</th>
                        </tr>
                    </thead>
                    <tbody>${rows}</tbody>
                </table>
            `;

            document.getElementById('selectAll').addEventListener('change', (e) => {
                const checked = e.target.checked;
                document.querySelectorAll('input[name="caseSelect"]').forEach((cb) => {
                    cb.checked = checked;
                });
                updateActionButtons();
            });
        }

        async function loadOrphans() {
            const content = document.getElementById('content');
            const summary = document.getElementById('summary');
            content.innerHTML = '<div class="empty">Loading...</div>';
            document.getElementById('deleteBtn').disabled = true;
            document.getElementById('reassignBtn').disabled = true;
            document.getElementById('assigneeEmail').disabled = true;

            try {
                const response = await fetch('/api/integrations/azure_devops/orphan-test-cases');
                const data = await response.json();

                if (!response.ok || !data.success) {
                    throw new Error(data.detail || data.error || 'Failed to load orphan test cases');
                }

                currentItems = data.items || [];
                summary.style.display = 'block';
                summary.innerHTML = `
                    <strong>Summary:</strong>
                    Source: ${escapeHtml(data.source || 'unknown')} |
                    Total Test Cases: ${data.summary.total_test_cases} |
                    In Suites: ${data.summary.linked_test_cases} |
                    Orphans: ${data.summary.orphan_test_cases}
                `;

                renderTable(currentItems);
            } catch (err) {
                content.innerHTML = `<div class="empty">Error: ${escapeHtml(err.message)}</div>`;
            }
        }

        async function deleteSelected() {
            const selected = Array.from(document.querySelectorAll('input[name="caseSelect"]:checked'))
                .map((cb) => cb.value);

            if (!selected.length) {
                return;
            }

            const confirmed = confirm(`Delete ${selected.length} selected Test Case(s)? This cannot be undone.`);
            if (!confirmed) {
                return;
            }

            try {
                const response = await fetch('/api/integrations/azure_devops/orphan-test-cases', {
                    method: 'DELETE',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        case_ids: selected,
                    }),
                });
                const data = await response.json();

                if (!response.ok) {
                    throw new Error(data.detail || data.error || 'Failed to delete test cases');
                }

                const deletedCount = data.deleted_count || 0;
                const failedCount = data.failed_count || 0;
                alert(`Deleted: ${deletedCount}, Failed: ${failedCount}`);
                await loadOrphans();
            } catch (err) {
                alert('Delete failed: ' + err.message);
            }
        }

        async function reassignSelected() {
            const selected = Array.from(document.querySelectorAll('input[name="caseSelect"]:checked'))
                .map((cb) => cb.value);
            const assigneeEmail = document.getElementById('assigneeEmail').value.trim();

            if (!selected.length) return;

            if (!assigneeEmail) {
                alert('Please enter an assignee email address.');
                document.getElementById('assigneeEmail').focus();
                return;
            }

            const confirmed = confirm(`Re-assign ${selected.length} Test Case(s) to "${escapeHtml(assigneeEmail)}"?`);
            if (!confirmed) return;

            try {
                const response = await fetch('/api/integrations/azure_devops/orphan-test-cases/reassign', {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ case_ids: selected, assigned_to: assigneeEmail }),
                });
                const data = await response.json();

                if (!response.ok) {
                    throw new Error(data.detail || data.error || 'Failed to re-assign test cases');
                }

                const updatedCount = data.updated_count || 0;
                const failedCount = data.failed_count || 0;
                alert(`Re-assigned: ${updatedCount}, Failed: ${failedCount}`);
                await loadOrphans();
            } catch (err) {
                alert('Re-assign failed: ' + err.message);
            }
        }

        loadOrphans();
        </script>
    </body>
    </html>
    """

    return html
