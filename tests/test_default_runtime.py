"""End-to-end tests for C's provider-backed default application runtime."""

import asyncio
from collections.abc import Sequence
from datetime import datetime
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from backend.main import create_app
from backend.scheduler import SchedulingResult
from backend.schemas import (
    Assessment,
    AssessmentType,
    CalendarBlock,
    PlanningEvent,
    ScheduledTask,
    Task,
)
from backend.services import MockDataStore, PlanningPipeline


def fixed_clock() -> datetime:
    return datetime.fromisoformat("2026-09-04T01:00:00+08:00")


def request(
    app: FastAPI,
    method: str,
    path: str,
    *,
    json: Any = None,
) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.request(method, path, json=json)

    return asyncio.run(send())


def test_default_plan_runs_provider_to_agent_to_real_scheduler() -> None:
    app = create_app(clock=fixed_clock)

    assert len(request(app, "GET", "/assessments").json()) == 3
    assert request(app, "GET", "/tasks").json() == []
    assert request(app, "GET", "/schedule").json() == []

    response = request(app, "POST", "/plan")

    assert response.status_code == 200
    result = response.json()
    tasks = request(app, "GET", "/tasks").json()
    schedule = request(app, "GET", "/schedule").json()
    assert len(tasks) == 15
    assert len(schedule) == 15
    assert schedule == result["scheduled_tasks"]
    assert result["unscheduled_tasks"] == []
    assert {item["task_id"] for item in schedule} == {
        task["id"] for task in tasks
    }
    assert all(task["name"] != task["id"] for task in tasks)
    assert all(task["status"] == "scheduled" for task in tasks)


def test_default_plan_is_reproducible_and_avoids_hard_blocks() -> None:
    app = create_app(clock=fixed_clock)

    first = request(app, "POST", "/plan").json()
    second = request(app, "POST", "/plan").json()
    hard_blocks = [
        block
        for block in request(app, "GET", "/calendar-blocks").json()
        if block["flexibility"] == "hard"
    ]

    assert second == first
    for placement in second["scheduled_tasks"]:
        placement_start = datetime.fromisoformat(placement["start_time"])
        placement_end = datetime.fromisoformat(placement["end_time"])
        for block in hard_blocks:
            block_start = datetime.fromisoformat(block["start_time"])
            block_end = datetime.fromisoformat(block["end_time"])
            assert (
                placement_end <= block_start
                or placement_start >= block_end
            )


def test_september_5_demo_plan_has_repeatable_times() -> None:
    app = create_app(
        clock=lambda: datetime.fromisoformat("2026-09-05T08:00:00+08:00")
    )

    response = request(app, "POST", "/plan")

    assert response.status_code == 200
    result = response.json()
    assert result["unscheduled_tasks"] == []
    assert [
        (item["start_time"], item["end_time"])
        for item in result["scheduled_tasks"]
    ] == [
        ("2026-09-05T08:00:00+08:00", "2026-09-05T08:30:00+08:00"),
        ("2026-09-05T08:30:00+08:00", "2026-09-05T10:30:00+08:00"),
        ("2026-09-05T10:30:00+08:00", "2026-09-05T11:00:00+08:00"),
        ("2026-09-05T12:00:00+08:00", "2026-09-05T15:00:00+08:00"),
        ("2026-09-05T15:00:00+08:00", "2026-09-05T16:00:00+08:00"),
        ("2026-09-05T16:00:00+08:00", "2026-09-05T16:30:00+08:00"),
        ("2026-09-05T16:30:00+08:00", "2026-09-05T17:30:00+08:00"),
        ("2026-09-05T17:30:00+08:00", "2026-09-05T19:00:00+08:00"),
        ("2026-09-05T19:00:00+08:00", "2026-09-05T20:00:00+08:00"),
        ("2026-09-05T20:00:00+08:00", "2026-09-05T20:15:00+08:00"),
        ("2026-09-05T20:15:00+08:00", "2026-09-05T20:45:00+08:00"),
        ("2026-09-06T08:00:00+08:00", "2026-09-06T10:00:00+08:00"),
        ("2026-09-06T10:00:00+08:00", "2026-09-06T11:00:00+08:00"),
        ("2026-09-06T11:00:00+08:00", "2026-09-06T12:00:00+08:00"),
        ("2026-09-06T12:00:00+08:00", "2026-09-06T12:30:00+08:00"),
    ]


def test_live_runtime_uses_current_time_instead_of_mock_or_previous_plan(monkeypatch) -> None:
    now = datetime.fromisoformat("2026-09-04T01:00:00+08:00")
    monkeypatch.setattr("backend.main.current_study_time", lambda: now)
    app = create_app()

    first = request(app, "POST", "/plan")
    assert first.status_code == 200
    schedule = first.json()["scheduled_tasks"]
    assert min(datetime.fromisoformat(item["start_time"]) for item in schedule) == (
        datetime.fromisoformat("2026-09-04T08:00:00+08:00")
    )
    assert all(datetime.fromisoformat(item["start_time"]) >= now for item in schedule)

    # The same app stays open overnight. Old placements must not pin its clock.
    now = datetime.fromisoformat("2026-09-05T12:10:30+08:00")
    second = request(app, "POST", "/plan")
    assert second.status_code == 200
    schedule = second.json()["scheduled_tasks"]
    assert min(datetime.fromisoformat(item["start_time"]) for item in schedule) == (
        datetime.fromisoformat("2026-09-05T12:11:00+08:00")
    )
    assert all(datetime.fromisoformat(item["start_time"]) >= now for item in schedule)
    assert second.json()["unscheduled_tasks"] == []


@pytest.mark.parametrize("timestamp,expected_start", [
    ("2026-09-04T01:00:00+08:00", "2026-09-04T08:00:00+08:00"),
    ("2026-09-04T22:00:00+08:00", "2026-09-05T08:00:00+08:00"),
])
def test_live_plan_respects_daily_study_window(timestamp: str, expected_start: str) -> None:
    app = create_app(clock=lambda: datetime.fromisoformat(timestamp))
    response = request(app, "POST", "/plan")
    assert response.status_code == 200
    schedule = response.json()["scheduled_tasks"]
    assert min(item["start_time"] for item in schedule) == expected_start


def test_live_plan_reports_expired_deadlines_instead_of_scheduling_in_the_past() -> None:
    app = create_app(clock=lambda: datetime.fromisoformat("2026-09-20T09:00:00+08:00"))
    response = request(app, "POST", "/plan")
    assert response.status_code == 200
    result = response.json()
    assert result["scheduled_tasks"] == []
    tasks = request(app, "GET", "/tasks").json()
    assert {item["task_id"] for item in result["unscheduled_tasks"]} == {task["id"] for task in tasks}
    assert all(item["reason"] in {"deadline_constraint", "dependency_conflict"}
               for item in result["unscheduled_tasks"])


def test_default_replan_commits_event_and_keeps_state_consistent() -> None:
    app = create_app(clock=fixed_clock)
    request(app, "POST", "/plan")
    tasks = request(app, "GET", "/tasks").json()
    # Task names are presentation copy, not stable identifiers. Choose an
    # actual dependency-bearing, non-leaf task from the generated graph.
    referenced_task = next(
        task for task in tasks if task["dependencies"]
        and any(task["id"] in child["dependencies"] for child in tasks)
    )
    event = {
        "id": "event-default-runtime-missed-slides",
        "event_type": "task_missed",
        "timestamp": "2026-09-04T12:10:00+08:00",
        "reference_id": referenced_task["id"],
    }

    response = request(app, "POST", "/replan", json=event)

    assert response.status_code == 200
    assert request(app, "GET", "/schedule").json() == response.json()[
        "scheduled_tasks"
    ]
    assert request(app, "GET", "/planning-events").json() == [event]


class FailingAgent:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def classify_assessment(self, assessment: Assessment) -> AssessmentType:
        raise self.error

    def decompose_assessment(self, assessment: Assessment) -> list[Task]:
        return []

    def find_affected_task_ids(
        self,
        event: PlanningEvent,
        tasks: Sequence[Task],
    ) -> set[str]:
        return set()


class EmptyScheduler:
    def schedule_tasks(
        self,
        assessments: Sequence[Assessment],
        tasks: Sequence[Task],
        calendar_blocks: Sequence[CalendarBlock],
        existing_schedule: Sequence[ScheduledTask] = (),
    ) -> SchedulingResult:
        return SchedulingResult()

    def reschedule_tasks(
        self,
        assessments: Sequence[Assessment],
        tasks: Sequence[Task],
        calendar_blocks: Sequence[CalendarBlock],
        existing_schedule: Sequence[ScheduledTask],
        affected_task_ids: set[str],
        *,
        replanning_start: datetime | None = None,
        preserve_valid_affected: bool = False,
    ) -> SchedulingResult:
        return SchedulingResult()


def test_invalid_pipeline_input_returns_422_without_mutating_state() -> None:
    store = MockDataStore()
    original_tasks = store.list_tasks()
    app = create_app(
        store,
        PlanningPipeline(FailingAgent(ValueError("invalid agent input")), EmptyScheduler()),
    )

    response = request(app, "POST", "/plan")

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_planning_input"
    assert store.list_tasks() == original_tasks


def test_unexpected_pipeline_failure_returns_500_without_mutating_state() -> None:
    store = MockDataStore()
    original_schedule = store.list_scheduled_tasks()
    app = create_app(
        store,
        PlanningPipeline(FailingAgent(RuntimeError("provider unavailable")), EmptyScheduler()),
    )

    response = request(app, "POST", "/plan")

    assert response.status_code == 500
    assert response.json()["detail"] == {
        "code": "planning_failed",
        "message": "The planning pipeline could not complete.",
    }
    assert store.list_scheduled_tasks() == original_schedule
