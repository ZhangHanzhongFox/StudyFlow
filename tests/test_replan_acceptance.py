"""Shared A/B/C/D examples and regression gates for observation transactions."""

import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI

from backend.agents import StudyFlowAgent
from backend.main import create_app
from backend.scheduler import (
    Scheduler,
    SchedulingFailureReason,
    SchedulingResult,
    StudyScheduler,
    UnscheduledTask,
)
from backend.schemas import Assessment, CalendarBlock, Flexibility, ScheduledTask, Task
from backend.services import MockDataStore, PlanningPipeline, PlanningState
from tests.test_default_runtime import request


FIXTURE = json.loads((Path(__file__).parents[1] / "data/scenarios/replan_acceptance.json").read_text())


def setup(scheduler: Scheduler | None = None) -> tuple[FastAPI, PlanningState]:
    initial = FIXTURE["initial_state"]
    state = PlanningState(
        assessments=[Assessment.model_validate(item) for item in initial["assessments"]],
        tasks=[Task.model_validate(item) for item in initial["tasks"]],
        calendar_blocks=[CalendarBlock.model_validate(item) for item in initial["calendar_blocks"]],
        scheduled_tasks=[ScheduledTask.model_validate(item) for item in initial["scheduled_tasks"]],
    )
    pipeline = PlanningPipeline(StudyFlowAgent(), scheduler or StudyScheduler())
    return create_app(state, pipeline), state


def snapshot(app: FastAPI) -> dict[str, Any]:
    return {path: request(app, "GET", path).json() for path in (
        "/tasks", "/schedule", "/calendar-blocks", "/planning-events",
    )}


@pytest.mark.parametrize("scenario_name", ["missed", "calendar_changed"])
def test_shared_acceptance_scenarios(scenario_name: str) -> None:
    app, _ = setup()
    scenario = FIXTURE["scenarios"][scenario_name]
    before = snapshot(app)
    response = request(app, "POST", scenario["endpoint"], json=scenario["request"])
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["unscheduled_tasks"] == []
    after = snapshot(app)
    assert after["/schedule"] == result["scheduled_tasks"]
    placements = {item["task_id"]: item for item in after["/schedule"]}
    for task_id, start_time in scenario["expected_start_times"].items():
        assert placements[task_id]["start_time"] == start_time
    for item in before["/schedule"]:
        if item["task_id"] in scenario["preserved_task_ids"]:
            assert placements[item["task_id"]] == item
    tasks = {item["id"]: item for item in after["/tasks"]}
    for item in placements.values():
        for dependency in tasks[item["task_id"]]["dependencies"]:
            assert datetime.fromisoformat(placements[dependency]["end_time"]) <= datetime.fromisoformat(item["start_time"])
        for block in after["/calendar-blocks"]:
            assert (datetime.fromisoformat(item["end_time"]) <= datetime.fromisoformat(block["start_time"])
                    or datetime.fromisoformat(item["start_time"]) >= datetime.fromisoformat(block["end_time"]))
    assert tasks["task-research"]["status"] == "completed"
    assert len(after["/planning-events"]) == 1
    if scenario_name == "calendar_changed":
        assert after["/calendar-blocks"] == [scenario["request"]["calendar_block"]]


def test_staged_new_assessment_schedules_new_tasks_and_preserves_existing_plan() -> None:
    initial = deepcopy(FIXTURE["initial_state"])
    initial["assessments"].append({
        **initial["assessments"][0],
        "id": "assessment-new",
        "title": "New presentation",
        "type": "presentation",
        "deadline": "2026-09-03T14:00:00+08:00",
    })
    initial["tasks"].extend([
        {
            "id": "task-new-outline",
            "assessment_id": "assessment-new",
            "name": "Create outline",
            "duration_minutes": 60,
            "dependencies": [],
            "priority": 4,
            "status": "pending",
        },
        {
            "id": "task-new-slides",
            "assessment_id": "assessment-new",
            "name": "Create slides",
            "duration_minutes": 60,
            "dependencies": ["task-new-outline"],
            "priority": 4,
            "status": "pending",
        },
    ])
    state = PlanningState(
        assessments=[Assessment.model_validate(item) for item in initial["assessments"]],
        tasks=[Task.model_validate(item) for item in initial["tasks"]],
        calendar_blocks=[],
        scheduled_tasks=[
            ScheduledTask.model_validate(item)
            for item in initial["scheduled_tasks"]
        ],
    )
    app = create_app(
        state,
        PlanningPipeline(StudyFlowAgent(), StudyScheduler()),
    )
    before = snapshot(app)
    event = {
        "id": "event-acceptance-new-assessment",
        "event_type": "new_assessment",
        "timestamp": "2026-09-03T11:00:00+08:00",
        "reference_id": "assessment-new",
    }

    response = request(app, "POST", "/replan", json=event)

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["unscheduled_tasks"] == []
    after_by_task = {
        item["task_id"]: item for item in result["scheduled_tasks"]
    }
    assert after_by_task["task-new-outline"]["start_time"] == (
        "2026-09-03T11:00:00+08:00"
    )
    assert after_by_task["task-new-slides"]["start_time"] == (
        "2026-09-03T12:00:00+08:00"
    )
    for old in before["/schedule"]:
        assert after_by_task[old["task_id"]] == old


def test_mock_demo_slides_missed_moves_full_chain_and_preserves_other_work() -> None:
    fixtures = MockDataStore()
    state = PlanningState(
        assessments=fixtures.list_assessments(),
        tasks=fixtures.list_tasks(),
        calendar_blocks=fixtures.list_calendar_blocks(),
        scheduled_tasks=fixtures.list_scheduled_tasks(),
        planning_events=[],
    )
    app = create_app(
        state,
        PlanningPipeline(StudyFlowAgent(), StudyScheduler()),
    )
    before = snapshot(app)
    event = {
        "id": "event-sept5-b-missed",
        "event_type": "task_missed",
        "timestamp": "2026-09-04T12:05:00+08:00",
        "reference_id": "task-presentation-slides",
    }

    response = request(app, "POST", "/replan", json=event)

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["unscheduled_tasks"] == []
    old_by_task = {item["task_id"]: item for item in before["/schedule"]}
    new_by_task = {
        item["task_id"]: item for item in result["scheduled_tasks"]
    }
    expected_moved_starts = {
        "task-presentation-slides": "2026-09-04T12:05:00+08:00",
        "task-presentation-script": "2026-09-04T13:05:00+08:00",
        "task-presentation-rehearsal": "2026-09-04T16:00:00+08:00",
    }
    assert {
        task_id: new_by_task[task_id]["start_time"]
        for task_id in expected_moved_starts
    } == expected_moved_starts
    for task_id in old_by_task.keys() - expected_moved_starts.keys():
        assert new_by_task[task_id] == old_by_task[task_id]
    stored_tasks = {
        item["id"]: item for item in request(app, "GET", "/tasks").json()
    }
    assert stored_tasks["task-presentation-requirements"]["status"] == "completed"
    assert stored_tasks["task-presentation-slides"]["status"] == "scheduled"


def test_completed_status_is_applied_before_agent_and_scheduler() -> None:
    class InspectScheduler(StudyScheduler):
        def reschedule_tasks(
            self, assessments: list[Assessment], tasks: list[Task],
            blocks: list[CalendarBlock], schedule: list[ScheduledTask],
            affected: set[str], **kwargs: Any,
        ) -> SchedulingResult:
            task = next(item for item in tasks if item.id == "task-slides")
            assert task.status.value == "completed"
            assert "task-slides" not in affected
            assert kwargs["replanning_start"].isoformat() == "2026-09-03T10:30:00+08:00"
            return super().reschedule_tasks(assessments, tasks, blocks, schedule, affected, **kwargs)

    app, _ = setup(InspectScheduler())
    event = {**FIXTURE["scenarios"]["missed"]["request"], "event_type": "task_completed"}
    before = snapshot(app)
    response = request(app, "POST", "/replan", json=event)
    assert response.status_code == 200, response.text
    after = snapshot(app)
    assert next(t for t in after["/tasks"] if t["id"] == "task-slides")["status"] == "completed"
    assert next(s for s in after["/schedule"] if s["task_id"] == "task-slides") == next(s for s in before["/schedule"] if s["task_id"] == "task-slides")
    event.update(id="event-cannot-undo-completion", event_type="task_missed")
    assert request(app, "POST", "/replan", json=event).status_code == 422
    assert snapshot(app) == after


def test_equivalent_utc_event_keeps_local_study_hours() -> None:
    event = deepcopy(FIXTURE["scenarios"]["missed"]["request"])
    app, _ = setup()
    local = request(app, "POST", "/replan", json=event).json()
    app, _ = setup()
    event["timestamp"] = "2026-09-03T02:30:00Z"
    utc = request(app, "POST", "/replan", json=event).json()
    assert utc == local


@pytest.mark.parametrize("scenario_name", ["missed", "calendar_changed"])
def test_duplicate_event_does_not_apply_twice(scenario_name: str) -> None:
    app, _ = setup()
    scenario = FIXTURE["scenarios"][scenario_name]
    assert request(app, "POST", scenario["endpoint"], json=scenario["request"]).status_code == 200
    after = snapshot(app)
    response = request(app, "POST", scenario["endpoint"], json=scenario["request"])
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "duplicate_event_id"
    assert snapshot(app) == after


@pytest.mark.parametrize("event_type", ["task_missed", "task_completed", "calendar_changed"])
def test_runtime_failure_rolls_back_every_collection(event_type: str) -> None:
    class FailingScheduler(StudyScheduler):
        def reschedule_tasks(self, *args: Any, **kwargs: Any) -> SchedulingResult:
            raise RuntimeError("test failure after staging")

    app, _ = setup(FailingScheduler())
    if event_type == "calendar_changed":
        scenario = deepcopy(FIXTURE["scenarios"]["calendar_changed"])
    else:
        scenario = deepcopy(FIXTURE["scenarios"]["missed"])
        scenario["request"]["event_type"] = event_type
    before = snapshot(app)
    response = request(app, "POST", scenario["endpoint"], json=scenario["request"])
    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "replanning_failed"
    assert snapshot(app) == before


@pytest.mark.parametrize("invalid_result", ["omitted", "duplicate", "completed_failure"])
def test_invalid_scheduler_result_rolls_back_every_collection(
    invalid_result: str,
) -> None:
    class InvalidScheduler(StudyScheduler):
        def reschedule_tasks(
            self, assessments: list[Assessment], tasks: list[Task],
            blocks: list[CalendarBlock], schedule: list[ScheduledTask],
            affected: set[str], **kwargs: Any,
        ) -> SchedulingResult:
            if invalid_result == "omitted":
                return SchedulingResult(scheduled_tasks=schedule[:-1])
            if invalid_result == "duplicate":
                duplicate = schedule[0].model_copy(update={"id": "schedule-duplicate"})
                return SchedulingResult(scheduled_tasks=[*schedule, duplicate])
            return SchedulingResult(
                scheduled_tasks=schedule,
                unscheduled_tasks=[UnscheduledTask(
                    task_id="task-research",
                    reason=SchedulingFailureReason.INVALID_INPUT,
                    message="completed work cannot be unscheduled",
                )],
            )

    app, _ = setup(InvalidScheduler())
    before = snapshot(app)
    response = request(
        app,
        "POST",
        "/replan",
        json=FIXTURE["scenarios"]["missed"]["request"],
    )
    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "invalid_planning_state"
    assert snapshot(app) == before


def test_no_remaining_slot_commits_calendar_and_explicit_failures() -> None:
    app, _ = setup()
    change = deepcopy(FIXTURE["scenarios"]["calendar_changed"]["request"])
    change["calendar_block"]["end_time"] = "2026-09-03T18:00:00+08:00"
    response = request(app, "POST", "/calendar-changes", json=change)
    assert response.status_code == 200
    result = response.json()
    assert [item["task_id"] for item in result["scheduled_tasks"]] == ["task-research"]
    assert {item["task_id"]: item["reason"] for item in result["unscheduled_tasks"]} == {
        "task-slides": "deadline_constraint", "task-script": "dependency_conflict",
        "task-independent": "deadline_constraint",
    }
    after = snapshot(app)
    assert after["/calendar-blocks"] == [change["calendar_block"]]
    assert after["/planning-events"] == [change["event"]]
    assert all(item["status"] == "pending" for item in after["/tasks"] if item["id"] != "task-research")


def test_later_replan_keeps_reporting_previously_unscheduled_unrelated_work() -> None:
    app, _ = setup()
    change = deepcopy(FIXTURE["scenarios"]["calendar_changed"]["request"])
    change["calendar_block"]["end_time"] = "2026-09-03T18:00:00+08:00"
    first = request(app, "POST", "/calendar-changes", json=change)
    assert first.status_code == 200

    event = {
        "id": "event-after-partial-result",
        "event_type": "task_missed",
        "timestamp": "2026-09-03T10:30:00+08:00",
        "reference_id": "task-independent",
    }
    second = request(app, "POST", "/replan", json=event)

    assert second.status_code == 200, second.text
    result = second.json()
    assert [item["task_id"] for item in result["scheduled_tasks"]] == [
        "task-research",
    ]
    assert {item["task_id"]: item["reason"] for item in result["unscheduled_tasks"]} == {
        "task-slides": "deadline_constraint",
        "task-script": "dependency_conflict",
        "task-independent": "deadline_constraint",
    }


def test_calendar_update_replaces_one_block_and_preserves_unrelated_work() -> None:
    app, _ = setup()
    change = deepcopy(FIXTURE["scenarios"]["calendar_changed"]["request"])
    assert request(app, "POST", "/calendar-changes", json=change).status_code == 200
    change["event"]["id"] = "event-move-lecture"
    change["calendar_block"].update(start_time="2026-09-03T10:00:00+08:00", end_time="2026-09-03T11:00:00+08:00")
    response = request(app, "POST", "/calendar-changes", json=change)
    assert response.status_code == 200
    assert request(app, "GET", "/calendar-blocks").json() == [change["calendar_block"]]
    independent = next(item for item in response.json()["scheduled_tasks"] if item["task_id"] == "task-independent")
    assert independent["start_time"] == "2026-09-03T15:00:00+08:00"


@pytest.mark.parametrize("field,value", [
    ("reference_id", "wrong-id"), ("event_type", "task_missed"),
    ("timestamp", "2026-09-03T09:00:00"),
])
def test_calendar_request_validation_is_atomic(field: str, value: str) -> None:
    app, _ = setup()
    change = deepcopy(FIXTURE["scenarios"]["calendar_changed"]["request"])
    change["event"][field] = value
    before = snapshot(app)
    assert request(app, "POST", "/calendar-changes", json=change).status_code == 422
    assert snapshot(app) == before


def test_hard_calendar_cannot_overwrite_completed_history() -> None:
    app, _ = setup()
    change = deepcopy(FIXTURE["scenarios"]["calendar_changed"]["request"])
    change["calendar_block"]["start_time"] = "2026-09-03T08:30:00+08:00"
    before = snapshot(app)
    response = request(app, "POST", "/calendar-changes", json=change)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_replanning_input"
    assert snapshot(app) == before


def test_soft_calendar_change_does_not_move_valid_schedule() -> None:
    app, _ = setup()
    change = deepcopy(FIXTURE["scenarios"]["calendar_changed"]["request"])
    change["calendar_block"]["flexibility"] = "soft"
    before = snapshot(app)
    response = request(app, "POST", "/calendar-changes", json=change)
    assert response.status_code == 200
    assert response.json()["scheduled_tasks"] == before["/schedule"]


def test_unknown_task_is_rejected_without_changes() -> None:
    app, _ = setup()
    event = {**FIXTURE["scenarios"]["missed"]["request"], "reference_id": "unknown"}
    before = snapshot(app)
    response = request(app, "POST", "/replan", json=event)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "unknown_reference"
    assert snapshot(app) == before


def test_missed_hard_task_is_rejected_instead_of_preserving_missed_slot() -> None:
    app, state = setup()
    schedule = state.list_scheduled_tasks()
    for item in schedule:
        if item.task_id == "task-slides":
            item.flexibility = Flexibility.HARD
    state.replace_schedule(schedule)
    before = snapshot(app)
    response = request(app, "POST", "/replan", json=FIXTURE["scenarios"]["missed"]["request"])
    assert response.status_code == 422
    assert snapshot(app) == before


def test_unscheduled_missed_task_keeps_missed_status() -> None:
    app, _ = setup()
    event = {**FIXTURE["scenarios"]["missed"]["request"], "timestamp": "2026-09-03T18:00:00+08:00"}
    response = request(app, "POST", "/replan", json=event)
    assert response.status_code == 200
    assert {item["task_id"] for item in response.json()["unscheduled_tasks"]} == {"task-slides", "task-script"}
    after = snapshot(app)
    tasks = {item["id"]: item for item in after["/tasks"]}
    assert tasks["task-slides"]["status"] == "missed"
    assert tasks["task-script"]["status"] == "pending"
    assert after["/planning-events"] == [event]
