"""Workflows UI"""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from apps.app.database import get_session_factory
from apps.app.config import get_settings
from packages.common import WorkflowType

router = APIRouter()


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
        workflow_type = WorkflowType(workflow_key)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Unknown workflow: {workflow_key}")

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
