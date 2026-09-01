"""Focused tests for StudyFlow's canonical shared data contracts."""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from backend.schemas import (
    Assessment,
    AssessmentType,
    CalendarBlock,
    Flexibility,
    PlanningEvent,
    PlanningEventType,
    ScheduledTask,
    Task,
    TaskStatus,
    validate_task_graph,
)

NOW = datetime(2026, 9, 1, 9, 0, tzinfo=timezone(timedelta(hours=8)))


def assessment_data(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "id": "assessment-1",
        "course_code": "CS1010",
        "title": "Project presentation",
        "description": "Present the implemented system.",
        "type": "presentation",
        "unlock_at": NOW,
        "deadline": NOW + timedelta(days=7),
        "weightage": 20.0,
        "is_group": True,
        "group_size": 4,
    }
    data.update(overrides)
    return data


def task_data(task_id: str, **overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "id": task_id,
        "assessment_id": "assessment-1",
        "name": f"Complete {task_id}",
        "duration_minutes": 60,
        "dependencies": [],
        "priority": 1,
        "status": "pending",
    }
    data.update(overrides)
    return data


def test_assessment_accepts_canonical_values_and_serializes_iso_datetimes() -> None:
    assessment = Assessment.model_validate(assessment_data())

    assert assessment.type is AssessmentType.PRESENTATION
    assert '"deadline":"2026-09-08T09:00:00+08:00"' in assessment.model_dump_json()


def test_assessment_accepts_quiz_type() -> None:
    assessment = Assessment.model_validate(
        assessment_data(
            type="quiz",
            is_group=False,
            group_size=None,
        )
    )

    assert assessment.type is AssessmentType.QUIZ


@pytest.mark.parametrize(
    "overrides",
    [
        {"deadline": datetime(2026, 9, 8, 9, 0)},
        {"deadline": NOW},
        {"weightage": -1},
        {"is_group": True, "group_size": 1},
        {"is_group": False, "group_size": 4},
    ],
)
def test_assessment_rejects_invalid_contract_values(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        Assessment.model_validate(assessment_data(**overrides))


def test_assessment_rejects_fields_excluded_from_the_contract() -> None:
    with pytest.raises(ValidationError):
        Assessment.model_validate(assessment_data(source="canvas"))


@pytest.mark.parametrize(
    "overrides",
    [
        {"duration_minutes": 0},
        {"dependencies": ["task-1"]},
        {"dependencies": ["task-0", "task-0"]},
    ],
)
def test_task_rejects_invalid_local_values(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Task.model_validate(task_data("task-1", **overrides))


def test_task_graph_accepts_valid_dependencies() -> None:
    research = Task.model_validate(task_data("research"))
    slides = Task.model_validate(
        task_data("slides", dependencies=["research"], status="scheduled")
    )

    assert validate_task_graph([research, slides]) == [research, slides]
    assert slides.status is TaskStatus.SCHEDULED


@pytest.mark.parametrize("case", ["unknown", "cross_assessment", "cycle", "duplicate"])
def test_task_graph_rejects_invalid_references_and_cycles(case: str) -> None:
    if case == "unknown":
        tasks = [Task.model_validate(task_data("task-1", dependencies=["missing"]))]
    elif case == "cross_assessment":
        tasks = [
            Task.model_validate(task_data("task-1", dependencies=["task-2"])),
            Task.model_validate(task_data("task-2", assessment_id="assessment-2")),
        ]
    elif case == "cycle":
        tasks = [
            Task.model_validate(task_data("task-1", dependencies=["task-2"])),
            Task.model_validate(task_data("task-2", dependencies=["task-1"])),
        ]
    else:
        tasks = [
            Task.model_validate(task_data("task-1")),
            Task.model_validate(task_data("task-1")),
        ]

    with pytest.raises(ValueError):
        validate_task_graph(tasks)


def test_calendar_block_and_scheduled_task_share_flexibility_semantics() -> None:
    block = CalendarBlock(
        id="calendar-1",
        title="Lecture",
        start_time=NOW,
        end_time=NOW + timedelta(hours=1),
        flexibility="hard",
    )
    scheduled = ScheduledTask(
        id="scheduled-1",
        task_id="task-1",
        start_time=NOW + timedelta(hours=1),
        end_time=NOW + timedelta(hours=2),
        flexibility="flexible",
    )

    assert block.flexibility is Flexibility.HARD
    assert scheduled.flexibility is Flexibility.FLEXIBLE


@pytest.mark.parametrize(
    "model,data",
    [
        (
            CalendarBlock,
            {
                "id": "calendar-1",
                "title": "Invalid block",
                "start_time": NOW,
                "end_time": NOW,
                "flexibility": "hard",
            },
        ),
        (
            ScheduledTask,
            {
                "id": "scheduled-1",
                "task_id": "task-1",
                "start_time": datetime(2026, 9, 1, 9, 0),
                "end_time": datetime(2026, 9, 1, 10, 0),
                "flexibility": "soft",
            },
        ),
    ],
)
def test_time_ranges_reject_invalid_or_naive_datetimes(
    model: type[CalendarBlock] | type[ScheduledTask],
    data: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(data)


def test_scheduled_task_rejects_legacy_lock_fields() -> None:
    with pytest.raises(ValidationError):
        ScheduledTask(
            id="scheduled-1",
            task_id="task-1",
            start_time=NOW,
            end_time=NOW + timedelta(hours=1),
            flexibility="hard",
            locked=True,
        )


def test_planning_event_validates_type_timestamp_and_reference() -> None:
    event = PlanningEvent(
        id="event-1",
        event_type="task_missed",
        timestamp=NOW,
        reference_id="task-1",
    )

    assert event.event_type is PlanningEventType.TASK_MISSED

    with pytest.raises(ValidationError):
        PlanningEvent(
            id="event-2",
            event_type="unknown_event",
            timestamp=NOW,
            reference_id="task-1",
        )

    with pytest.raises(ValidationError):
        PlanningEvent(
            id="event-3",
            event_type="calendar_changed",
            timestamp=datetime(2026, 9, 1, 9, 0),
            reference_id="calendar-1",
        )
