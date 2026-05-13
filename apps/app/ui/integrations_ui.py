"""Integrations UI"""

from html import escape

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from apps.app.database import get_session_factory, IntegrationConfigModel
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


@router.get("", response_class=HTMLResponse)
async def integrations_page(request: Request, db: Session = Depends(get_db)) -> str:
    """Integration settings page"""
    integration_rows = ""

    from packages.common import IntegrationType

    for integration_type in IntegrationType:
        config = (
            db.query(IntegrationConfigModel)
            .filter(IntegrationConfigModel.type == integration_type)
            .first()
        )

        status = config.status if config else "unconfigured"
        status_color = {
            "healthy": "green",
            "unhealthy": "red",
            "unconfigured": "gray",
        }.get(status, "gray")

        extra_actions = ""
        if integration_type.value == "azure_devops":
            extra_actions = (
                '<a href="/ui/integrations/azure_devops/orphan-test-cases">'
                "Orphan Test Cases</a> | "
            )

        integration_rows += f"""
        <tr>
            <td>{integration_type.value}</td>
            <td><span style="background: {status_color}; color: white; padding: 4px 8px; border-radius: 3px; font-size: 12px;">{status.upper()}</span></td>
            <td>
                {extra_actions}<a href="/ui/integrations/{integration_type.value}">Configure</a> |
                <button onclick="testConnection('{integration_type.value}')">Test</button>
            </td>
        </tr>
        """

    logger.info("Rendered integrations page")

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Integrations - Trace2Quality</title>
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
            button {{ background: #0066cc; color: white; border: none; padding: 6px 12px; border-radius: 4px; cursor: pointer; }}
            button:hover {{ background: #0052a3; }}
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
            <h2>Integration Settings</h2>
            <p>Configure connections to external services</p>

            <table>
                <thead>
                    <tr>
                        <th>Provider</th>
                        <th>Status</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    {integration_rows}
                </tbody>
            </table>
        </div>

        <script>
        async function testConnection(type) {{
            const response = await fetch(`/api/integrations/${{type}}/test`, {{ method: 'POST' }});
            const data = await response.json();
            if (data.success) {{
                alert('Connection successful! ✓');
            }} else {{
                alert('Connection failed: ' + data.error);
            }}
            location.reload();
        }}
        </script>
    </body>
    </html>
    """


@router.get("/azure_devops/orphan-test-cases", response_class=HTMLResponse)
async def azure_devops_orphan_test_cases_page(request: Request) -> str:
    """Azure DevOps orphan Test Cases management page."""
    settings = get_settings()
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
                <li><a href="/ui/integrations">Integrations</a></li>
                <li><a href="/ui/data">Data Explorer</a></li>
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
                <a href="/ui/integrations">← Back to Integrations</a>
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
