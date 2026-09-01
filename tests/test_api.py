"""Contract tests for the fixture-backed FastAPI skeleton."""

import asyncio
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from backend.main import create_app
from backend.services import MockDataStore


@pytest.fixture
def app() -> FastAPI:
    return create_app(MockDataStore())


def request(
    app: FastAPI,
    method: str,
    path: str,
    *,
    json: Any = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.request(
                method,
                path,
                json=json,
                headers=headers,
            )

    return asyncio.run(send())


def test_health_reports_mock_mode(app: FastAPI) -> None:
    response = request(app, "GET", "/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "data_mode": "mock"}


@pytest.mark.parametrize(
    "path,expected_count",
    [
        ("/assessments", 3),
        ("/tasks", 16),
        ("/calendar-blocks", 8),
        ("/schedule", 16),
        ("/planning-events", 5),
    ],
)
def test_read_endpoints_return_validated_fixture_lists(
    app: FastAPI,
    path: str,
    expected_count: int,
) -> None:
    response = request(app, "GET", path)

    assert response.status_code == 200
    assert len(response.json()) == expected_count


def test_plan_returns_explicit_fixture_backed_scheduling_result(
    app: FastAPI,
) -> None:
    response = request(app, "POST", "/plan")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["scheduled_tasks"]) == 16
    assert payload["unscheduled_tasks"] == []


def test_planning_event_can_be_posted_and_duplicate_ids_are_rejected(
    app: FastAPI,
) -> None:
    event = {
        "id": "event-api-demo-missed",
        "event_type": "task_missed",
        "timestamp": "2026-09-04T12:10:00+08:00",
        "reference_id": "task-presentation-slides",
    }

    created = request(app, "POST", "/planning-events", json=event)
    duplicate = request(app, "POST", "/planning-events", json=event)

    assert created.status_code == 201
    assert created.json() == event
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "duplicate_event_id"
    assert len(request(app, "GET", "/planning-events").json()) == 6


def test_planning_event_input_uses_canonical_schema_validation(
    app: FastAPI,
) -> None:
    response = request(
        app,
        "POST",
        "/planning-events",
        json={
            "id": "event-naive-time",
            "event_type": "task_completed",
            "timestamp": "2026-09-04T12:10:00",
            "reference_id": "task-presentation-slides",
        },
    )

    assert response.status_code == 422


def test_unknown_event_reference_is_rejected(app: FastAPI) -> None:
    response = request(
        app,
        "POST",
        "/planning-events",
        json={
            "id": "event-unknown-task",
            "event_type": "task_missed",
            "timestamp": "2026-09-04T12:10:00+08:00",
            "reference_id": "task-does-not-exist",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "unknown_reference"


def test_replan_contract_is_explicitly_unimplemented(app: FastAPI) -> None:
    response = request(
        app,
        "POST",
        "/replan",
        json={
            "id": "event-replan-demo",
            "event_type": "task_missed",
            "timestamp": "2026-09-04T12:10:00+08:00",
            "reference_id": "task-presentation-slides",
        },
    )

    assert response.status_code == 501
    assert response.json()["detail"]["code"] == "replanning_not_implemented"
    assert response.json()["detail"]["event_id"] == "event-replan-demo"


def test_default_frontend_origins_receive_cors_headers(app: FastAPI) -> None:
    response = request(
        app,
        "OPTIONS",
        "/assessments",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
