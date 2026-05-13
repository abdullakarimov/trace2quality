"""Integrations UI"""

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

        integration_rows += f"""
        <tr>
            <td>{integration_type.value}</td>
            <td><span style="background: {status_color}; color: white; padding: 4px 8px; border-radius: 3px; font-size: 12px;">{status.upper()}</span></td>
            <td>
                <a href="/ui/integrations/{integration_type.value}">Configure</a> |
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
