"""Focused tests for deadline-aware deterministic scheduling."""

from datetime import datetime, timedelta, timezone

import pytest

from backend.scheduler import SchedulingFailureReason, StudyScheduler
from backend.schemas import (
    Assessment,
    AssessmentType,
    CalendarBlock,
    Flexibility,
    ScheduledTask,
    Task,
    TaskStatus,
)


SGT = timezone(timedelta(hours=8))
PLANNING_START = datetime(2026, 9, 2, 8, tzinfo=SGT)


def make_assessment(
    assessment_id: str = "assessment-1",
    *,
    deadline: datetime = datetime(2026, 9, 3, 22, tzinfo=SGT),
    unlock_at: datetime | None = None,
) -> Assessment:
    return Assessment(
        id=assessment_id,
        course_code="CS1000",
        title=assessment_id,
        description="Assessment instructions",
        type=AssessmentType.EXAM,
        unlock_at=unlock_at,
        deadline=deadline,
        weightage=None,
        is_group=False,
        group_size=None,
    )


def make_task(
    task_id: str,
    *,
    assessment_id: str = "assessment-1",
    duration_minutes: int = 60,
    dependencies: list[str] | None = None,
    priority: int = 1,
    status: TaskStatus = TaskStatus.PENDING,
) -> Task:
    return Task(
        id=task_id,
        assessment_id=assessment_id,
        name=task_id,
        duration_minutes=duration_minutes,
        dependencies=dependencies or [],
        priority=priority,
        status=status,
    )


def make_scheduler() -> StudyScheduler:
    return StudyScheduler(planning_start=PLANNING_START)


def test_schedule_tasks_respects_dependencies_deadline_and_hard_blocks() -> None:
    tasks = [
        make_task("research", duration_minutes=60, priority=3),
        make_task(
            "slides",
            duration_minutes=90,
            dependencies=["research"],
            priority=5,
        ),
        make_task(
            "rehearsal",
            duration_minutes=30,
            dependencies=["slides"],
            priority=4,
        ),
    ]
    lecture = CalendarBlock(
        id="lecture",
        title="Lecture",
        start_time=datetime(2026, 9, 2, 9, tzinfo=SGT),
        end_time=datetime(2026, 9, 2, 12, tzinfo=SGT),
        flexibility=Flexibility.HARD,
    )
    assessment = make_assessment(
        deadline=datetime(2026, 9, 2, 16, tzinfo=SGT)
    )

    result = make_scheduler().schedule_tasks([assessment], tasks, [lecture])

    assert result.unscheduled_tasks == []
    assert [item.task_id for item in result.scheduled_tasks] == [
        "research",
        "slides",
        "rehearsal",
    ]
    by_task_id = {item.task_id: item for item in result.scheduled_tasks}
    assert by_task_id["research"].end_time <= lecture.start_time
    assert by_task_id["slides"].start_time >= lecture.end_time
    assert by_task_id["slides"].start_time >= by_task_id["research"].end_time
    assert (
        by_task_id["rehearsal"].start_time
        >= by_task_id["slides"].end_time
    )
    assert all(item.end_time <= assessment.deadline for item in result.scheduled_tasks)


def test_task_after_deadline_is_reported_and_dependents_are_not_scheduled() -> None:
    assessment = make_assessment(
        deadline=datetime(2026, 9, 2, 8, 30, tzinfo=SGT)
    )
    tasks = [
        make_task("research", duration_minutes=60),
        make_task("slides", dependencies=["research"]),
    ]

    result = make_scheduler().schedule_tasks([assessment], tasks, [])

    assert result.scheduled_tasks == []
    assert [item.reason for item in result.unscheduled_tasks] == [
        SchedulingFailureReason.DEADLINE_CONSTRAINT,
        SchedulingFailureReason.DEPENDENCY_CONFLICT,
    ]


def test_ready_tasks_are_ordered_by_descending_priority() -> None:
    result = make_scheduler().schedule_tasks(
        [make_assessment()],
        [make_task("low", priority=1), make_task("high", priority=10)],
        [],
    )

    assert [item.task_id for item in result.scheduled_tasks] == ["high", "low"]


def test_overlapping_hard_blocks_are_merged_before_slot_search() -> None:
    blocks = [
        CalendarBlock(
            id="block-1",
            title="Lecture",
            start_time=datetime(2026, 9, 2, 9, tzinfo=SGT),
            end_time=datetime(2026, 9, 2, 11, tzinfo=SGT),
            flexibility=Flexibility.HARD,
        ),
        CalendarBlock(
            id="block-2",
            title="Lab",
            start_time=datetime(2026, 9, 2, 10, tzinfo=SGT),
            end_time=datetime(2026, 9, 2, 12, tzinfo=SGT),
            flexibility=Flexibility.HARD,
        ),
    ]

    result = make_scheduler().schedule_tasks(
        [make_assessment()],
        [make_task("deep-work", duration_minutes=120)],
        blocks,
    )

    assert result.scheduled_tasks[0].start_time == datetime(
        2026, 9, 2, 12, tzinfo=SGT
    )


def test_task_larger_than_daily_window_is_explicitly_unscheduled() -> None:
    result = StudyScheduler(
        daily_start_hour=8,
        daily_end_hour=9,
        planning_start=PLANNING_START,
    ).schedule_tasks(
        [make_assessment()],
        [make_task("too-long", duration_minutes=61)],
        [],
    )

    assert result.scheduled_tasks == []
    assert result.unscheduled_tasks[0].reason is (
        SchedulingFailureReason.NO_AVAILABLE_SLOT
    )


def test_completed_task_placement_is_preserved_for_dependency_readiness() -> None:
    completed = make_task("research", status=TaskStatus.COMPLETED)
    dependent = make_task("slides", dependencies=["research"])
    existing = ScheduledTask(
        id="existing-research",
        task_id="research",
        start_time=PLANNING_START,
        end_time=PLANNING_START + timedelta(hours=1),
        flexibility=Flexibility.FLEXIBLE,
    )

    result = make_scheduler().schedule_tasks(
        [make_assessment()],
        [completed, dependent],
        [],
        [existing],
    )

    assert result.scheduled_tasks[0] == existing
    assert result.scheduled_tasks[1].task_id == "slides"
    assert result.scheduled_tasks[1].start_time >= existing.end_time


def test_unknown_assessment_reference_is_rejected_at_scheduler_boundary() -> None:
    with pytest.raises(ValueError, match="unknown assessment"):
        make_scheduler().schedule_tasks(
            [make_assessment()],
            [make_task("orphan", assessment_id="missing")],
            [],
        )


def test_reschedule_preserves_unaffected_placement() -> None:
    tasks = [make_task("research"), make_task("slides")]
    unaffected = ScheduledTask(
        id="existing-research",
        task_id="research",
        start_time=PLANNING_START,
        end_time=PLANNING_START + timedelta(hours=1),
        flexibility=Flexibility.FLEXIBLE,
    )
    affected = ScheduledTask(
        id="existing-slides",
        task_id="slides",
        start_time=PLANNING_START,
        end_time=PLANNING_START + timedelta(hours=1),
        flexibility=Flexibility.FLEXIBLE,
    )

    result = make_scheduler().reschedule_tasks(
        [make_assessment()],
        tasks,
        [],
        [unaffected, affected],
        {"slides"},
    )

    by_task_id = {item.task_id: item for item in result.scheduled_tasks}
    assert by_task_id["research"] == unaffected
    assert by_task_id["slides"].id == "scheduled-slides"
    assert by_task_id["slides"].start_time >= unaffected.end_time
