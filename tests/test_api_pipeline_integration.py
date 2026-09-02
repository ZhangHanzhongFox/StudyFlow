"""HTTP integration tests for injectable planning and replanning."""

import asyncio
from collections.abc import Sequence
from typing import Any

import httpx
from fastapi import FastAPI

from backend.agents import StudyFlowAgent
from backend.main import create_app
from backend.scheduler import SchedulingResult, StudyScheduler
from backend.schemas import (
    Assessment,
    AssessmentType,
    CalendarBlock,
    PlanningEvent,
    ScheduledTask,
    Task,
)
from backend.services import MockDataStore, PlanningPipeline, PlanningState


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


class CanonicalFixtureAgent:
    def __init__(self, tasks: Sequence[Task]) -> None:
        self.tasks = list(tasks)

    def classify_assessment(self, assessment: Assessment) -> AssessmentType:
        return assessment.type

    def decompose_assessment(self, assessment: Assessment) -> list[Task]:
        return [task for task in self.tasks if task.assessment_id == assessment.id]

    def find_affected_task_ids(
        self,
        event: PlanningEvent,
        tasks: Sequence[Task],
    ) -> set[str]:
        return {event.reference_id}


class FixtureScheduler:
    def __init__(self, scheduled_tasks: Sequence[ScheduledTask]) -> None:
        self.scheduled_tasks = list(scheduled_tasks)

    def schedule_tasks(
        self,
        assessments: Sequence[Assessment],
        tasks: Sequence[Task],
        calendar_blocks: Sequence[CalendarBlock],
        existing_schedule: Sequence[ScheduledTask] = (),
    ) -> SchedulingResult:
        return SchedulingResult(scheduled_tasks=self.scheduled_tasks)

    def reschedule_tasks(
        self,
        assessments: Sequence[Assessment],
        tasks: Sequence[Task],
        calendar_blocks: Sequence[CalendarBlock],
        existing_schedule: Sequence[ScheduledTask],
        affected_task_ids: set[str],
    ) -> SchedulingResult:
        return SchedulingResult(scheduled_tasks=self.scheduled_tasks)


def configured_app() -> tuple[FastAPI, MockDataStore]:
    store = MockDataStore()
    pipeline = PlanningPipeline(
        CanonicalFixtureAgent(store.list_tasks()),
        FixtureScheduler(store.list_scheduled_tasks()),
    )
    return create_app(store, pipeline), store


def test_injected_plan_updates_current_state() -> None:
    app, store = configured_app()

    response = request(app, "POST", "/plan")

    assert response.status_code == 200
    assert response.json()["scheduled_tasks"] == [
        item.model_dump(mode="json") for item in store.list_scheduled_tasks()
    ]
    assert len(request(app, "GET", "/tasks").json()) == 15


def test_real_agent_and_scheduler_generate_a_deadline_safe_plan() -> None:
    fixtures = MockDataStore.from_provider_fixtures()
    store = PlanningState(
        assessments=fixtures.list_assessments(),
        calendar_blocks=fixtures.list_calendar_blocks(),
    )
    pipeline = PlanningPipeline(
        StudyFlowAgent(),
        StudyScheduler(),
    )
    app = create_app(store, pipeline)

    response = request(app, "POST", "/plan")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["scheduled_tasks"]) == 15
    assert payload["unscheduled_tasks"] == []

    assessments = {
        item["id"]: item for item in request(app, "GET", "/assessments").json()
    }
    tasks = {item["id"]: item for item in request(app, "GET", "/tasks").json()}
    schedule = request(app, "GET", "/schedule").json()
    hard_blocks = [
        item
        for item in request(app, "GET", "/calendar-blocks").json()
        if item["flexibility"] == "hard"
    ]

    for placement in schedule:
        task = tasks[placement["task_id"]]
        assessment = assessments[task["assessment_id"]]
        assert placement["end_time"] <= assessment["deadline"]
        assert all(
            placement["end_time"] <= block["start_time"]
            or placement["start_time"] >= block["end_time"]
            for block in hard_blocks
        )


def test_injected_replan_persists_event_and_schedule() -> None:
    app, store = configured_app()
    event = {
        "id": "event-api-replan-missed",
        "event_type": "task_missed",
        "timestamp": "2026-09-04T12:10:00+08:00",
        "reference_id": "task-presentation-slides",
    }

    response = request(app, "POST", "/replan", json=event)

    assert response.status_code == 200
    assert len(store.list_planning_events()) == 6
    assert store.list_planning_events()[-1].id == event["id"]
    assert request(app, "GET", "/schedule").json() == response.json()[
        "scheduled_tasks"
    ]


def test_invalid_scheduler_references_use_stable_api_error_shape() -> None:
    store = MockDataStore()
    invalid_placement = store.list_scheduled_tasks()[0].model_copy(
        update={"task_id": "task-does-not-exist"}
    )
    pipeline = PlanningPipeline(
        CanonicalFixtureAgent(store.list_tasks()),
        FixtureScheduler([invalid_placement]),
    )
    app = create_app(store, pipeline)

    response = request(app, "POST", "/plan")

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "invalid_planning_state"
    assert "unknown task" in response.json()["detail"]["message"]


def test_invalid_replan_does_not_partially_store_event_or_schedule() -> None:
    store = MockDataStore()
    original_schedule = store.list_scheduled_tasks()
    invalid_placement = original_schedule[0].model_copy(
        update={"task_id": "task-does-not-exist"}
    )
    pipeline = PlanningPipeline(
        CanonicalFixtureAgent(store.list_tasks()),
        FixtureScheduler([invalid_placement]),
    )
    app = create_app(store, pipeline)
    event = {
        "id": "event-invalid-replan",
        "event_type": "task_missed",
        "timestamp": "2026-09-04T12:10:00+08:00",
        "reference_id": "task-presentation-slides",
    }

    response = request(app, "POST", "/replan", json=event)

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "invalid_planning_state"
    assert store.list_scheduled_tasks() == original_schedule
    assert all(item.id != event["id"] for item in store.list_planning_events())
