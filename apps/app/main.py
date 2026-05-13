"""FastAPI application entrypoint"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from apps.app.config import get_settings
from apps.app.database import create_all_tables, get_session_factory
from packages.common import generate_correlation_id, get_logger
from packages.common import IntegrationType
from packages.integrations import integration_registry
from packages.integrations.azure_devops import AzureDevOpsClient
from packages.integrations.confluence import ConfluenceClient
from packages.integrations.gemini import GeminiClient
from packages.integrations.jira import JiraClient

logger = get_logger(__name__)

# Register integration clients
integration_registry.register(IntegrationType.AZURE_DEVOPS, AzureDevOpsClient)
integration_registry.register(IntegrationType.CONFLUENCE, ConfluenceClient)
integration_registry.register(IntegrationType.JIRA, JiraClient)
integration_registry.register(IntegrationType.GEMINI, GeminiClient)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown"""
    logger.info("Starting Trace2Quality application")

    settings = get_settings()

    # Create data directories
    os.makedirs(settings.artifact_storage_path, exist_ok=True)
    os.makedirs(settings.cache_storage_path, exist_ok=True)

    # Initialize database
    create_all_tables(settings.database_url)
    logger.info("Database initialized")

    yield

    logger.info("Shutting down Trace2Quality application")


def create_app() -> FastAPI:
    """Create and configure FastAPI application"""
    settings = get_settings()

    app = FastAPI(
        title="Trace2Quality API",
        description="Enterprise QA Automation Platform",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.is_development else ["https://yourdomain.com"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Request correlation ID middleware
    @app.middleware("http")
    async def add_correlation_id(request: Request, call_next):
        correlation_id = request.headers.get("x-correlation-id", generate_correlation_id())
        request.state.correlation_id = correlation_id
        response = await call_next(request)
        response.headers["x-correlation-id"] = correlation_id
        return response

    # Root route
    @app.get("/", response_class=HTMLResponse)
    async def root():
        return """
        <html>
            <head>
                <title>Trace2Quality</title>
                <style>
                    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; 
                           margin: 40px; color: #333; }
                    h1 { color: #0066cc; }
                    a { color: #0066cc; text-decoration: none; }
                    a:hover { text-decoration: underline; }
                    code { background: #f5f5f5; padding: 2px 6px; border-radius: 3px; }
                </style>
            </head>
            <body>
                <h1>🚀 Trace2Quality</h1>
                <p>Enterprise QA Automation and Traceability Platform</p>
                <h2>Quick Links</h2>
                <ul>
                    <li><a href="/docs">📚 API Documentation (Swagger)</a></li>
                    <li><a href="/redoc">📖 ReDoc</a></li>
                    <li><a href="/ui">💻 Dashboard</a></li>
                </ul>
                <h2>Status</h2>
                <p><code>Phase 1</code> - Foundation (in development)</p>
            </body>
        </html>
        """

    # Health check endpoint
    @app.get("/health")
    async def health_check():
        return {"status": "ok", "version": "0.1.0"}

    # Import and include API routers
    from apps.app.api import integrations, workflows, runs, artifacts, health, schedules, webhooks, compositions

    app.include_router(integrations.router, prefix="/api/integrations", tags=["integrations"])
    app.include_router(workflows.router, prefix="/api/workflows", tags=["workflows"])
    app.include_router(runs.router, prefix="/api/runs", tags=["runs"])
    app.include_router(artifacts.router, prefix="/api/artifacts", tags=["artifacts"])
    app.include_router(health.router, prefix="/api", tags=["health"])
    app.include_router(schedules.router, tags=["schedules"])
    app.include_router(webhooks.router, tags=["webhooks"])
    app.include_router(compositions.router, tags=["compositions"])

    # Import and include UI routers
    from apps.app.ui import dashboard, integrations_ui, workflows_ui, runs_ui, data_explorer

    app.include_router(dashboard.router, tags=["ui-dashboard"])
    app.include_router(integrations_ui.router, prefix="/ui/integrations", tags=["ui"])
    app.include_router(workflows_ui.router, prefix="/ui/workflows", tags=["ui"])
    app.include_router(runs_ui.router, prefix="/ui/runs", tags=["ui"])
    app.include_router(data_explorer.router, prefix="/ui/data", tags=["ui"])

    # Global error handler
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        correlation_id = getattr(request.state, "correlation_id", "unknown")
        logger.error(f"Unhandled exception: {str(exc)}", correlation_id=correlation_id)
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal server error",
                "correlation_id": correlation_id,
            },
        )

    logger.info("FastAPI application created successfully")
    return app


# Create application instance
app = create_app()

if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=settings.app_port,
        reload=settings.is_development,
        workers=1 if settings.is_development else settings.app_workers,
    )
