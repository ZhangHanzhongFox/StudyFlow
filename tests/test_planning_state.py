"""Atomic state and cross-reference validation tests."""

from datetime import datetime, timezone

import pytest

from backend.schemas import PlanningEvent, PlanningEventType, TaskStatus
from backend.services import (
    DuplicatePlanningEventError,
    MockDataStore,
    PlanningStateValidationError,
)


def test_state_returns_defensive_model_copies() -> None:
    state = MockDataStore()
    returned = state.list_assessments()
    returned[0].title = "Changed outside state"

    assert state.list_assessments()[0].title != "Changed outside state"


def test_invalid_plan_replacement_is_atomic() -> None:
    state = MockDataStore()
    original_tasks = state.list_tasks()
    original_schedule = state.list_scheduled_tasks()
    invalid_task = original_tasks[0].model_copy(
        update={"assessment_id": "assessment-missing"}
    )

    with pytest.raises(PlanningStateValidationError, match="unknown assessment"):
        state.replace_plan(
            state.list_assessments(),
            [invalid_task, *original_tasks[1:]],
            original_schedule,
        )

    assert state.list_tasks() == original_tasks
    assert state.list_scheduled_tasks() == original_schedule


def test_schedule_cannot_reference_unknown_task() -> None:
    state = MockDataStore()
    invalid = state.list_scheduled_tasks()[0].model_copy(
        update={"task_id": "task-missing"}
    )

    with pytest.raises(PlanningStateValidationError, match="unknown task"):
        state.replace_schedule([invalid, *state.list_scheduled_tasks()[1:]])


def test_event_validation_does_not_mutate_state() -> None:
    state = MockDataStore()
    event = state.list_planning_events()[-1].model_copy(
        update={"id": "event-preflight-only"}
    )
    before = state.list_planning_events()

    state.validate_planning_event(event)

    assert state.list_planning_events() == before


def test_duplicate_event_is_rejected_before_mutation() -> None:
    state = MockDataStore()
    event = state.list_planning_events()[0]

    with pytest.raises(DuplicatePlanningEventError, match="already exists"):
        state.add_planning_event(event)


def test_task_progress_event_updates_task_status() -> None:
    state = MockDataStore()
    task = state.list_tasks()[0]
    event = PlanningEvent(
        id="event-state-completed",
        event_type=PlanningEventType.TASK_COMPLETED,
        timestamp=datetime(2026, 9, 2, 12, tzinfo=timezone.utc),
        reference_id=task.id,
    )

    state.add_planning_event(event)

    updated = next(item for item in state.list_tasks() if item.id == task.id)
    assert updated.status is TaskStatus.COMPLETED


def test_replan_schedule_and_event_commit_is_atomic() -> None:
    state = MockDataStore()
    original_schedule = state.list_scheduled_tasks()
    original_events = state.list_planning_events()
    invalid_placement = original_schedule[0].model_copy(
        update={"task_id": "task-missing"}
    )
    event = original_events[-1].model_copy(update={"id": "event-atomic"})

    with pytest.raises(PlanningStateValidationError, match="unknown task"):
        state.replace_schedule_and_add_event(
            [invalid_placement, *original_schedule[1:]],
            event,
        )

    assert state.list_scheduled_tasks() == original_schedule
    assert state.list_planning_events() == original_events
