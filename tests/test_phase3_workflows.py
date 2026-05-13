"""Tests for reporting and scheduling workflows"""

import pytest
from datetime import datetime, timedelta

from packages.workflows.reporting import (
    associate_automation_from_run,
    generate_coverage_report,
    generate_test_summary,
)
from packages.workflows.scheduler import (
    ScheduleFrequency,
    WorkflowSchedule,
    WebhookEvent,
    create_schedule,
    create_webhook_event,
    filter_schedules_due_now,
)
from packages.workflows.composition import (
    WorkflowCompositionType,
    WorkflowComposition,
    ComposedWorkflowExecution,
    create_sequential_composition,
    create_full_qa_cycle_composition,
)


class TestReportingWorkflows:
    """Test reporting workflows"""

    @pytest.mark.asyncio
    async def test_generate_coverage_report_success(self):
        """Test coverage report generation"""
        requirements = ["REQ-001", "REQ-002", "REQ-003"]
        tests = ["test_req_001", "test_req_002"]

        result = await generate_coverage_report(
            project="TestProject",
            requirements=requirements,
            tests=tests
        )

        assert result["status"] == "success"
        assert result["total_requirements"] == 3
        assert result["total_tests"] == 2
        assert result["coverage_percentage"] >= 0
        assert "report_html" in result

    @pytest.mark.asyncio
    async def test_generate_coverage_report_full_coverage(self):
        """Test with full coverage"""
        requirements = ["REQ-001", "REQ-002"]
        tests = ["test_req_001", "test_req_002"]

        result = await generate_coverage_report(
            project="TestProject",
            requirements=requirements,
            tests=tests
        )

        assert result["covered_requirements"] == 2
        assert result["coverage_percentage"] == 100.0

    @pytest.mark.asyncio
    async def test_generate_test_summary_success(self):
        """Test test summary generation"""
        test_results = [
            {"id": "test1", "name": "Test 1", "status": "passed", "type": "api"},
            {"id": "test2", "name": "Test 2", "status": "passed", "type": "ui"},
            {"id": "test3", "name": "Test 3", "status": "failed", "type": "integration"},
            {"id": "test4", "name": "Test 4", "status": "skipped", "type": "performance"},
        ]

        result = await generate_test_summary(
            run_id="run_12345",
            test_results=test_results
        )

        assert result["status"] == "partial_failures"
        assert result["total_tests"] == 4
        assert result["passed"] == 2
        assert result["failed"] == 1
        assert result["skipped"] == 1
        assert result["pass_rate"] == 50.0

    @pytest.mark.asyncio
    async def test_generate_test_summary_all_passed(self):
        """Test with all tests passing"""
        test_results = [
            {"id": f"test{i}", "name": f"Test {i}", "status": "passed", "type": "api"}
            for i in range(5)
        ]

        result = await generate_test_summary(
            run_id="run_12345",
            test_results=test_results
        )

        assert result["status"] == "success"
        assert result["pass_rate"] == 100.0
        assert result["failed"] == 0

    @pytest.mark.asyncio
    async def test_generate_test_summary_by_type(self):
        """Test summary grouped by test type"""
        test_results = [
            {"id": "test1", "status": "passed", "type": "api"},
            {"id": "test2", "status": "passed", "type": "api"},
            {"id": "test3", "status": "failed", "type": "ui"},
            {"id": "test4", "status": "passed", "type": "ui"},
        ]

        result = await generate_test_summary(
            run_id="run_12345",
            test_results=test_results
        )

        assert "by_type" in result
        assert result["by_type"]["api"]["total"] == 2
        assert result["by_type"]["api"]["passed"] == 2
        assert result["by_type"]["ui"]["total"] == 2
        assert result["by_type"]["ui"]["passed"] == 1


class TestScheduling:
    """Test workflow scheduling"""

    def test_create_schedule_hourly(self):
        """Test creating hourly schedule"""
        schedule = create_schedule(
            workflow_key="fetch_confluence",
            frequency="hourly",
            parameters={"space": "TEST"}
        )

        assert schedule.workflow_key == "fetch_confluence"
        assert schedule.frequency == ScheduleFrequency.HOURLY
        assert schedule.active is True
        assert schedule.run_count == 0

    def test_create_schedule_daily(self):
        """Test creating daily schedule"""
        schedule = create_schedule(
            workflow_key="generate_tests",
            frequency="daily",
            parameters={"project": "TestProject"}
        )

        assert schedule.frequency == ScheduleFrequency.DAILY
        assert schedule.next_run is not None

    def test_schedule_is_due(self):
        """Test schedule due checking"""
        # Create schedule in the past
        past_time = (datetime.utcnow() - timedelta(hours=2)).isoformat()
        
        schedule = WorkflowSchedule(
            schedule_id="test_schedule",
            workflow_key="test_workflow",
            frequency=ScheduleFrequency.HOURLY,
            parameters={},
            start_time=past_time,
            active=True
        )

        assert schedule.is_due() is True

    def test_schedule_not_due(self):
        """Test schedule not due"""
        # Create schedule in the future
        future_time = (datetime.utcnow() + timedelta(hours=2)).isoformat()
        
        schedule = WorkflowSchedule(
            schedule_id="test_schedule",
            workflow_key="test_workflow",
            frequency=ScheduleFrequency.DAILY,
            parameters={},
            start_time=future_time,
            active=False
        )

        assert schedule.is_due() is False

    def test_schedule_execute_tracking(self):
        """Test tracking schedule executions"""
        schedule = create_schedule(
            workflow_key="test_workflow",
            frequency="daily",
            parameters={}
        )

        assert schedule.run_count == 0
        assert schedule.failure_count == 0

        schedule.mark_executed(success=True)
        assert schedule.run_count == 1
        assert schedule.failure_count == 0

        schedule.mark_executed(success=False)
        assert schedule.run_count == 2
        assert schedule.failure_count == 1

    def test_filter_schedules_due(self):
        """Test filtering schedules due now"""
        past_time = (datetime.utcnow() - timedelta(hours=1)).isoformat()
        future_time = (datetime.utcnow() + timedelta(hours=1)).isoformat()

        schedules = [
            WorkflowSchedule(
                schedule_id="due1",
                workflow_key="wf1",
                frequency=ScheduleFrequency.HOURLY,
                parameters={},
                start_time=past_time,
                active=True
            ),
            WorkflowSchedule(
                schedule_id="not_due",
                workflow_key="wf2",
                frequency=ScheduleFrequency.DAILY,
                parameters={},
                start_time=future_time,
                active=True
            ),
        ]

        due = filter_schedules_due_now(schedules)
        assert len(due) == 1
        assert due[0].schedule_id == "due1"


class TestWebhooks:
    """Test webhook events"""

    def test_create_webhook_event(self):
        """Test creating webhook event"""
        event = create_webhook_event(
            event_type="issue_created",
            workflow_key="triage_bugs",
            trigger_data={"issue_key": "BUG-123"}
        )

        assert event.event_type == "issue_created"
        assert event.workflow_key == "triage_bugs"
        assert event.trigger_data["issue_key"] == "BUG-123"
        assert event.processed is False

    def test_webhook_event_to_dict(self):
        """Test webhook event serialization"""
        event = create_webhook_event(
            event_type="push",
            workflow_key="run_tests",
            trigger_data={"branch": "main"}
        )

        event_dict = event.to_dict()
        assert "event_id" in event_dict
        assert event_dict["event_type"] == "push"
        assert event_dict["workflow_key"] == "run_tests"


class TestComposition:
    """Test workflow composition"""

    def test_create_sequential_composition(self):
        """Test creating sequential composition"""
        workflows = [
            {"workflow_key": "fetch_confluence", "parameters": {}},
            {"workflow_key": "generate_tests", "parameters": {}},
        ]

        composition = create_sequential_composition(
            name="Test Sequence",
            workflow_configs=workflows
        )

        assert composition.name == "Test Sequence"
        assert composition.composition_type == WorkflowCompositionType.SEQUENTIAL
        assert len(composition.workflows) == 2

    def test_create_qa_cycle_composition(self):
        """Test creating QA cycle template"""
        composition = create_full_qa_cycle_composition(project="TestProject")

        assert "Full QA Cycle" in composition.name
        assert composition.composition_type == WorkflowCompositionType.SEQUENTIAL
        assert len(composition.workflows) == 4

    def test_composed_execution_tracking(self):
        """Test execution tracking"""
        execution = ComposedWorkflowExecution(
            execution_id="exec_123",
            composition_id="comp_456",
            composition_type=WorkflowCompositionType.SEQUENTIAL
        )

        assert execution.status == "running"
        assert execution.get_duration() == 0.0

        execution.add_result(
            workflow_key="fetch_confluence",
            run_id="run_001",
            status="succeeded",
            output={"items": 5}
        )

        assert len(execution.workflow_results) == 1

        execution.mark_complete("succeeded")
        assert execution.status == "succeeded"
        assert execution.completed_at is not None

    def test_composition_validation(self):
        """Test composition validation"""
        # Valid composition
        valid_comp = WorkflowComposition(
            composition_id="test",
            name="Test",
            composition_type=WorkflowCompositionType.SEQUENTIAL,
            workflows=[{"workflow_key": "test_workflow", "parameters": {}}]
        )
        valid, error = valid_comp.validate()
        assert valid is True

        # Invalid - no workflows
        invalid_comp = WorkflowComposition(
            composition_id="test",
            name="Test",
            composition_type=WorkflowCompositionType.SEQUENTIAL,
            workflows=[]
        )
        valid, error = invalid_comp.validate()
        assert valid is False
        assert error is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
