"""End-to-end tests for C's provider-backed default application runtime."""

import asyncio
from collections.abc import Sequence
from datetime import datetime
from typing import Any

import httpx
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
    app = create_app()

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
    app = create_app()

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


def test_default_replan_commits_event_and_keeps_state_consistent() -> None:
    app = create_app()
    request(app, "POST", "/plan")
    tasks = request(app, "GET", "/tasks").json()
    slides = next(task for task in tasks if "slides" in task["name"].lower())
    event = {
        "id": "event-default-runtime-missed-slides",
        "event_type": "task_missed",
        "timestamp": "2026-09-04T12:10:00+08:00",
        "reference_id": slides["id"],
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
