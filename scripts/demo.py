#!/usr/bin/env python
"""
Demo script for Trace2Quality - Complete end-to-end workflow example

This script demonstrates:
1. Configuring integrations
2. Testing connections
3. Running workflows
4. Checking results

Prerequisites:
- Docker Compose is running (docker-compose up -d)
- .env file is configured with real API tokens
"""

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from packages.integrations import integration_registry
from packages.workflows import catalog, generation, coverage
from packages.common import get_logger, SecretEncryption

logger = get_logger(__name__, json_mode=False)


async def demo_integration_testing():
    """Demo 1: Test all configured integrations"""
    print("\n" + "=" * 60)
    print("DEMO 1: Testing Integrations")
    print("=" * 60)

    integrations = [
        ("confluence", {
            "base_url": "http://localhost:8000",
            "space": "DEMO",
            "email": "demo@example.com",
            "api_token": "demo_token"
        }),
        ("jira", {
            "base_url": "http://localhost:8000",
            "email": "demo@example.com",
            "api_token": "demo_token"
        }),
        ("azure_devops", {
            "org_url": "http://localhost:8000",
            "project": "DemoProject",
            "pat": "demo_pat"
        }),
        ("gemini", {
            "api_key": "demo_key",
            "model": "gemini-pro"
        })
    ]

    for integration_type, config in integrations:
        try:
            client = integration_registry.get_client(integration_type, config)
            success, error = await client.test_connection()
            
            status = "✓ Connected" if success else f"✗ Failed: {error}"
            print(f"\n{integration_type:15} {status}")
            
        except Exception as e:
            print(f"\n{integration_type:15} ✗ Error: {str(e)}")


async def demo_confluence_workflow():
    """Demo 2: Fetch Confluence catalog"""
    print("\n" + "=" * 60)
    print("DEMO 2: Confluence Catalog Workflow")
    print("=" * 60)

    print("\nFetching Confluence pages with label 'requirements'...")

    mock_client = type('MockClient', (), {
        'fetch_pages_by_label': asyncio.coroutine(lambda label: [
            {
                "id": "page1",
                "title": "User Login Requirements",
                "_links": {"self": "http://confluence/pages/page1"},
                "version": {"when": "2025-05-13"}
            },
            {
                "id": "page2",
                "title": "API Documentation",
                "_links": {"self": "http://confluence/pages/page2"},
                "version": {"when": "2025-05-13"}
            }
        ]),
        'fetch_page_content': asyncio.coroutine(lambda page_id: "Page content example")
    })()

    # Simulate async function
    async def mock_fetch(label):
        return [
            {
                "id": "page1",
                "title": "User Login Requirements",
                "_links": {"self": "http://confluence/pages/page1"},
                "version": {"when": "2025-05-13"}
            }
        ]

    mock_client.fetch_pages_by_label = mock_fetch
    mock_client.fetch_page_content = asyncio.coroutine(lambda x: "Content")

    try:
        result = await catalog.fetch_confluence_catalog(
            mock_client,
            space="DEMO",
            labels=["requirements"]
        )
        
        print(f"\n✓ Fetched {result.get('pages_fetched', 0)} pages")
        print(f"  Status: {result.get('status', 'unknown')}")
        print(f"  Timestamp: {result.get('timestamp', 'N/A')}")
        
        if result.get('items'):
            print(f"\n  Pages found:")
            for item in result['items'][:3]:
                print(f"    - {item.get('title', 'Unknown')} ({item.get('id')})")
                
    except Exception as e:
        print(f"\n✗ Error: {str(e)}")


async def demo_test_generation():
    """Demo 3: Generate test cases"""
    print("\n" + "=" * 60)
    print("DEMO 3: Test Generation Workflow")
    print("=" * 60)

    print("\nGenerating API test cases from specification...")

    sample_spec = """
    API Specification:
    - GET /api/users: List all users
    - POST /api/users: Create new user
    - GET /api/users/{id}: Get user by ID
    - PUT /api/users/{id}: Update user
    - DELETE /api/users/{id}: Delete user
    """

    print("\nSample API Specification:")
    print(sample_spec)

    # Simulate Gemini response
    simulated_test_cases = [
        {
            "id": "TC_API_001",
            "name": "Test GET /api/users",
            "description": "Verify users list endpoint",
            "steps": [
                "Send GET request to /api/users",
                "Verify response status is 200",
                "Verify response contains users array"
            ],
            "expected_result": "Returns 200 OK with users list",
            "priority": "HIGH"
        },
        {
            "id": "TC_API_002",
            "name": "Test POST /api/users",
            "description": "Verify user creation",
            "steps": [
                "Send POST request with user data",
                "Verify response status is 201",
                "Verify user ID is returned"
            ],
            "expected_result": "Returns 201 Created with new user",
            "priority": "HIGH"
        }
    ]

    print(f"\n✓ Generated {len(simulated_test_cases)} test cases")
    print("\n  Test Cases:")
    for tc in simulated_test_cases:
        print(f"    - {tc['id']}: {tc['name']}")
        print(f"      Priority: {tc['priority']}")
        print(f"      Steps: {len(tc['steps'])}")


async def demo_coverage_analysis():
    """Demo 4: Analyze test coverage"""
    print("\n" + "=" * 60)
    print("DEMO 4: Coverage Analysis")
    print("=" * 60)

    requirements = [
        "User login functionality",
        "User logout functionality",
        "Password reset capability",
        "Profile management",
        "User roles and permissions",
        "Data export feature",
        "Report generation",
        "Backup and restore"
    ]

    tests = [
        "test_user_login_valid_credentials",
        "test_user_login_invalid_credentials",
        "test_user_logout",
        "test_password_reset",
        "test_profile_update",
        "test_user_roles"
    ]

    print(f"\nRequirements ({len(requirements)}):")
    for i, req in enumerate(requirements, 1):
        print(f"  {i}. {req}")

    print(f"\nTests ({len(tests)}):")
    for i, test in enumerate(tests, 1):
        print(f"  {i}. {test}")

    # Calculate coverage
    result = await coverage.calculate_coverage_metrics(
        requirements=requirements,
        tests=tests
    )

    coverage_pct = result.get('coverage_percentage', 0)
    covered = result.get('covered_requirements', 0)
    total = result.get('total_requirements', 0)

    print(f"\n✓ Coverage Analysis Complete")
    print(f"  Coverage: {covered}/{total} requirements ({coverage_pct:.1f}%)")
    print(f"  Gaps: {len(result.get('gaps', []))}")
    
    if result.get('gaps'):
        print(f"\n  Uncovered Requirements:")
        for gap in result['gaps']:
            print(f"    - {gap}")


async def demo_full_workflow():
    """Demo 5: Full workflow execution"""
    print("\n" + "=" * 60)
    print("DEMO 5: Full Workflow Execution Summary")
    print("=" * 60)

    workflow_example = {
        "workflow_key": "fetch_confluence",
        "parameters": {
            "confluence_url": "http://confluence.example.com",
            "confluence_space": "PRODUCT",
            "confluence_email": "user@example.com",
            "labels": ["requirements", "api-spec"]
        },
        "started_at": datetime.utcnow().isoformat(),
        "status": "queued"
    }

    print("\nWorkflow Configuration:")
    print(f"  Workflow: {workflow_example['workflow_key']}")
    print(f"  Status: {workflow_example['status']}")
    print(f"  Started: {workflow_example['started_at']}")
    
    print("\nParameters:")
    for key, value in workflow_example['parameters'].items():
        if 'email' in key.lower() or 'token' in key.lower():
            display_value = f"{str(value)[:10]}***" if value else "None"
        else:
            display_value = value
        print(f"  {key}: {display_value}")

    print("\nExpected Workflow Steps:")
    steps = [
        ("1", "Validate integration credentials", "2s"),
        ("2", "Connect to Confluence", "1s"),
        ("3", "Fetch pages with labels", "3s"),
        ("4", "Index content", "2s"),
        ("5", "Store results", "1s")
    ]
    
    total_time = 0
    for step_num, description, duration in steps:
        duration_val = int(duration.split('s')[0])
        total_time += duration_val
        print(f"  Step {step_num}: {description} ({duration})")
    
    print(f"\nEstimated Total Time: {total_time}s")


def demo_api_examples():
    """Demo 6: API usage examples"""
    print("\n" + "=" * 60)
    print("DEMO 6: API Usage Examples")
    print("=" * 60)

    examples = [
        ("List Workflows", "GET /api/workflows"),
        ("Create Run", "POST /api/workflows/fetch_confluence/runs"),
        ("Check Status", "GET /api/runs/{run_id}"),
        ("View Logs", "GET /api/runs/{run_id}/logs"),
        ("Download Artifact", "GET /api/artifacts/{id}/download"),
        ("Test Integration", "POST /api/integrations/confluence/test"),
        ("Get Health", "GET /api/health")
    ]

    print("\nCommon API Endpoints:\n")
    for description, endpoint in examples:
        print(f"  {description:30} {endpoint}")

    print("\n\nExample: Create and Monitor a Workflow Run")
    print("-" * 50)
    
    create_request = {
        "parameters": {
            "confluence_url": "http://confluence.example.com",
            "confluence_space": "PRODUCT",
            "confluence_email": "user@example.com",
            "confluence_token": "***",
            "labels": ["requirements"]
        },
        "dry_run": False
    }

    print("\nPOST /api/workflows/fetch_confluence/runs")
    print(json.dumps(create_request, indent=2))

    print("\n\nResponse:")
    response = {
        "run_id": "550e8400-e29b-41d4-a716-446655440000",
        "workflow_key": "fetch_confluence",
        "status": "queued",
        "created_at": datetime.utcnow().isoformat()
    }
    print(json.dumps(response, indent=2))

    print("\n\nThen check status with:")
    print(f"GET /api/runs/{response['run_id']}")


async def main():
    """Run all demos"""
    print("\n" + "=" * 60)
    print("TRACE2QUALITY - COMPLETE DEMO")
    print("=" * 60)
    print(f"Started: {datetime.utcnow().isoformat()}")

    try:
        # Run all async demos
        await demo_integration_testing()
        await demo_confluence_workflow()
        await demo_test_generation()
        await demo_coverage_analysis()
        await demo_full_workflow()
        
        # Run sync demos
        demo_api_examples()

    except Exception as e:
        logger.error(f"Demo failed: {str(e)}")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("DEMO COMPLETED")
    print("=" * 60)
    print("\nNext Steps:")
    print("  1. Start the application: docker-compose up -d")
    print("  2. Access the web UI: http://localhost:8000/ui")
    print("  3. Configure integrations: http://localhost:8000/ui/integrations")
    print("  4. Run workflows via API or UI")
    print("  5. View results and logs")
    print("\nDocumentation:")
    print("  - README.md for quick start")
    print("  - docs/api/REFERENCE.md for API docs")
    print("  - docs/operations/GUIDE.md for operations guide")


if __name__ == "__main__":
    asyncio.run(main())
