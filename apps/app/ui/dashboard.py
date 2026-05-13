"""Dashboard UI"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from apps.app.database import get_session_factory, WorkflowRunModel, IntegrationConfigModel
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

    # Get integration statuses
    integrations = db.query(IntegrationConfigModel).all()
    integration_health = {}
    for integration in integrations:
        integration_health[integration.type.value] = {
            "status": integration.status,
            "configured": integration.status != "unconfigured",
        }

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

    integrations_html = ""
    for integration_type, health in integration_health.items():
        status_color = "green" if health["status"] == "healthy" else "red" if health["status"] == "unhealthy" else "gray"
        integrations_html += f"""
        <div style="padding: 10px; border-bottom: 1px solid #eee; display: flex; justify-content: space-between; align-items: center;">
            <div>
                <strong>{integration_type.replace('_', ' ').title()}</strong>
                <br/>
                <small style="color: #666;">
                    {('Configured' if health['configured'] else 'Not Configured')}
                </small>
            </div>
            <span style="background: {status_color}; color: white; padding: 4px 8px; border-radius: 3px; font-size: 12px; font-weight: bold;">
                {health['status'].upper()}
            </span>
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
            .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
            .card {{ background: white; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
            .card-header {{ background: #f9f9f9; padding: 15px; border-bottom: 1px solid #eee; font-weight: bold; }}
            .card-content {{ padding: 0; }}
            a {{ color: #0066cc; text-decoration: none; }}
            a:hover {{ text-decoration: underline; }}
            .button {{ display: inline-block; background: #0066cc; color: white; padding: 10px 20px; border-radius: 4px; text-decoration: none; margin-top: 10px; }}
            .button:hover {{ background: #0052a3; }}
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
                <li><a href="/docs">API Docs</a></li>
            </ul>
        </nav>

        <div class="container">
            <h2>Dashboard</h2>
            <p>Welcome to Trace2Quality - Enterprise QA Automation and Traceability</p>

            <div class="grid">
                <div class="card">
                    <div class="card-header">Integration Health</div>
                    <div class="card-content">
                        {integrations_html}
                        <div style="padding: 10px;">
                            <a class="button" href="/ui/integrations">Configure Integrations</a>
                        </div>
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

            <h2>Quick Actions</h2>
            <ul>
                <li><a href="/ui/workflows?action=fetch-catalog">📚 Fetch Catalog</a></li>
                <li><a href="/ui/workflows?action=generate-api-tests">🧪 Generate API Tests</a></li>
                <li><a href="/ui/workflows?action=generate-ui-tests">🖥️ Generate UI Tests</a></li>
                <li><a href="/ui/workflows?action=update-coverage">📊 Update Coverage</a></li>
            </ul>
        </div>
    </body>
    </html>
    """
