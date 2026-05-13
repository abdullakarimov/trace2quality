"""Webhook API endpoints for workflow triggering"""

from typing import Optional
from fastapi import APIRouter, HTTPException
from datetime import datetime
import json

from packages.workflows.scheduler import create_webhook_event, WebhookEvent
from packages.common import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

# In-memory storage for demo (replace with database in production)
_webhook_events: dict[str, WebhookEvent] = {}
_webhook_subscriptions: dict[str, list[str]] = {}  # event_type -> [workflow_keys]


@router.post("/subscribe")
async def subscribe_to_event(event_type: str, workflow_key: str):
    """Subscribe a workflow to an event type"""
    try:
        if event_type not in _webhook_subscriptions:
            _webhook_subscriptions[event_type] = []
        
        if workflow_key not in _webhook_subscriptions[event_type]:
            _webhook_subscriptions[event_type].append(workflow_key)
        
        logger.info(f"Subscribed {workflow_key} to {event_type}")
        return {
            "event_type": event_type,
            "workflow_key": workflow_key,
            "subscribed_at": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Error subscribing to event: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/trigger")
async def trigger_workflow_via_webhook(
    event_type: str,
    workflow_key: str,
    trigger_data: dict
):
    """Trigger a workflow via webhook"""
    try:
        event = create_webhook_event(
            event_type=event_type,
            workflow_key=workflow_key,
            trigger_data=trigger_data
        )
        
        _webhook_events[event.event_id] = event
        
        logger.info(f"Created webhook event: {event.event_id}")
        return {
            "event_id": event.event_id,
            "event_type": event_type,
            "workflow_key": workflow_key,
            "status": "received",
            "created_at": event.created_at
        }
    except Exception as e:
        logger.error(f"Error triggering workflow: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/github")
async def github_webhook(payload: dict):
    """GitHub webhook endpoint for events like push, pull request"""
    try:
        event_type = payload.get("action", "unknown")
        
        # Map GitHub events to workflow triggers
        workflow_key = None
        trigger_data = {}
        
        if payload.get("action") == "opened" and "pull_request" in payload:
            # New pull request
            workflow_key = "analyze_coverage"
            trigger_data = {
                "pr_number": payload["pull_request"].get("number"),
                "pr_title": payload["pull_request"].get("title"),
                "branch": payload["pull_request"].get("head", {}).get("ref")
            }
        elif payload.get("ref", "").endswith("/main"):
            # Push to main branch
            workflow_key = "run_tests"
            trigger_data = {
                "commit": payload.get("after", "")[:8],
                "branch": payload.get("ref", "").split("/")[-1],
                "commits": len(payload.get("commits", []))
            }
        
        if workflow_key:
            event = create_webhook_event(
                event_type=event_type,
                workflow_key=workflow_key,
                trigger_data=trigger_data
            )
            _webhook_events[event.event_id] = event
            logger.info(f"GitHub event triggered workflow {workflow_key}")
            return {"event_id": event.event_id, "status": "accepted"}
        else:
            logger.debug(f"GitHub event {event_type} ignored (no workflow mapping)")
            return {"status": "ignored"}
    except Exception as e:
        logger.error(f"Error processing GitHub webhook: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/jira")
async def jira_webhook(payload: dict):
    """Jira webhook endpoint for issue events"""
    try:
        event_type = payload.get("webhookEvent", "unknown")
        issue = payload.get("issue", {})
        
        # Map Jira events to workflow triggers
        workflow_key = None
        trigger_data = {}
        
        if "issue_created" in event_type:
            issue_type = issue.get("fields", {}).get("issuetype", {}).get("name", "").lower()
            if "bug" in issue_type:
                workflow_key = "triage_bugs"
                trigger_data = {
                    "issue_key": issue.get("key"),
                    "issue_type": issue_type,
                    "summary": issue.get("fields", {}).get("summary"),
                }
        elif "issue_updated" in event_type:
            status = issue.get("fields", {}).get("status", {}).get("name", "").lower()
            if "resolved" in status or "closed" in status:
                workflow_key = "generate_report"
                trigger_data = {
                    "issue_key": issue.get("key"),
                    "new_status": status
                }
        
        if workflow_key:
            event = create_webhook_event(
                event_type=event_type,
                workflow_key=workflow_key,
                trigger_data=trigger_data
            )
            _webhook_events[event.event_id] = event
            logger.info(f"Jira event triggered workflow {workflow_key}")
            return {"event_id": event.event_id, "status": "accepted"}
        else:
            logger.debug(f"Jira event {event_type} ignored")
            return {"status": "ignored"}
    except Exception as e:
        logger.error(f"Error processing Jira webhook: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/confluence")
async def confluence_webhook(payload: dict):
    """Confluence webhook endpoint for page updates"""
    try:
        event_type = payload.get("webhookEvent", "unknown")
        
        workflow_key = None
        trigger_data = {}
        
        if "page_published" in event_type or "page_updated" in event_type:
            page = payload.get("page", {})
            workflow_key = "fetch_confluence"
            trigger_data = {
                "page_id": page.get("id"),
                "page_title": page.get("title"),
                "space": page.get("space", {}).get("key")
            }
        
        if workflow_key:
            event = create_webhook_event(
                event_type=event_type,
                workflow_key=workflow_key,
                trigger_data=trigger_data
            )
            _webhook_events[event.event_id] = event
            logger.info(f"Confluence event triggered workflow {workflow_key}")
            return {"event_id": event.event_id, "status": "accepted"}
        else:
            logger.debug(f"Confluence event {event_type} ignored")
            return {"status": "ignored"}
    except Exception as e:
        logger.error(f"Error processing Confluence webhook: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/events")
async def list_webhook_events(limit: int = 100):
    """List recent webhook events"""
    events = sorted(
        _webhook_events.values(),
        key=lambda e: e.created_at,
        reverse=True
    )[:limit]
    
    return {
        "events": [e.to_dict() for e in events],
        "total": len(_webhook_events),
        "recent_count": len(events)
    }


@router.get("/events/{event_id}")
async def get_webhook_event(event_id: str):
    """Get webhook event details"""
    event = _webhook_events.get(event_id)
    if not event:
        raise HTTPException(status_code=404, detail=f"Event not found: {event_id}")
    
    return event.to_dict()


@router.get("/subscriptions")
async def list_subscriptions():
    """List all webhook subscriptions"""
    return {
        "subscriptions": [
            {
                "event_type": event_type,
                "workflows": workflows,
                "count": len(workflows)
            }
            for event_type, workflows in _webhook_subscriptions.items()
        ],
        "total_subscriptions": sum(len(w) for w in _webhook_subscriptions.values())
    }


__all__ = ["router"]
