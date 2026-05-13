"""Data Explorer UI"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
import os

from apps.app.database import get_session_factory, DatasetSnapshotModel
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
async def data_explorer_page(request: Request, db: Session = Depends(get_db)) -> str:
    """Data explorer page"""
    settings = get_settings()

    # Get cached datasets
    datasets = db.query(DatasetSnapshotModel).order_by(
        DatasetSnapshotModel.updated_at.desc()
    ).all()

    dataset_rows = ""
    for dataset in datasets:
        size_kb = int(dataset.size_bytes) // 1024 if dataset.size_bytes else 0
        dataset_rows += f"""
        <tr>
            <td>{dataset.dataset_name}</td>
            <td>{size_kb} KB</td>
            <td>{dataset.updated_at.strftime('%Y-%m-%d %H:%M:%S')}</td>
            <td><a href="/data/download/{dataset.id}">Download</a></td>
        </tr>
        """

    # Get files from artifact storage
    artifact_files = []
    if os.path.exists(settings.artifact_storage_path):
        for filename in os.listdir(settings.artifact_storage_path):
            filepath = os.path.join(settings.artifact_storage_path, filename)
            if os.path.isfile(filepath):
                size = os.path.getsize(filepath)
                size_kb = size // 1024
                artifact_files.append((filename, size_kb))

    artifact_rows = ""
    for filename, size_kb in artifact_files:
        artifact_rows += f"""
        <tr>
            <td>{filename}</td>
            <td>{size_kb} KB</td>
            <td><a href="/data/artifacts/{filename}">View</a></td>
        </tr>
        """

    logger.info("Rendered data explorer page")

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Data Explorer - Trace2Quality</title>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f5f5f5; }}
            nav {{ background: #0066cc; color: white; padding: 15px 30px; }}
            nav h1 {{ margin: 0; font-size: 24px; }}
            nav ul {{ list-style: none; display: flex; gap: 20px; margin-top: 10px; }}
            nav a {{ color: white; text-decoration: none; }}
            .container {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}
            h2 {{ color: #333; margin: 20px 0 10px 0; }}
            table {{ width: 100%; border-collapse: collapse; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 4px rgba(0,0,0,0.1); margin-bottom: 20px; }}
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
            <h2>Data Explorer</h2>
            <p>Browse cached datasets and generated artifacts</p>

            <h3>Cached Datasets</h3>
            <table>
                <thead>
                    <tr>
                        <th>Dataset</th>
                        <th>Size</th>
                        <th>Updated</th>
                        <th>Action</th>
                    </tr>
                </thead>
                <tbody>
                    {dataset_rows if dataset_rows else '<tr><td colspan="4" style="text-align: center; color: #999; padding: 40px;">No datasets yet</td></tr>'}
                </tbody>
            </table>

            <h3>Output Artifacts</h3>
            <table>
                <thead>
                    <tr>
                        <th>Filename</th>
                        <th>Size</th>
                        <th>Action</th>
                    </tr>
                </thead>
                <tbody>
                    {artifact_rows if artifact_rows else '<tr><td colspan="3" style="text-align: center; color: #999; padding: 40px;">No artifacts yet</td></tr>'}
                </tbody>
            </table>
        </div>
    </body>
    </html>
    """
