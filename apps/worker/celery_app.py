"""Celery worker setup."""

from celery import Celery

from apps.app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "trace2quality",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=30 * 60,  # 30 minutes
    task_soft_time_limit=25 * 60,  # 25 minutes
    worker_prefetch_multiplier=4,
    worker_max_tasks_per_child=1000,
)


@celery_app.task(bind=True)
def run_workflow(self, run_id: str, workflow_key: str):
    """Task to execute a workflow."""
    from apps.app.workflows import run_workflow as execute_workflow

    execute_workflow(run_id, workflow_key)
