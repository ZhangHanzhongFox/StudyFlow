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


def test_explicit_demo_start_takes_precedence_over_live_clock() -> None:
    scheduler = StudyScheduler(
        planning_start=PLANNING_START,
        clock=lambda: datetime(2026, 9, 20, 9, tzinfo=SGT),
    )
    result = scheduler.schedule_tasks([make_assessment()], [make_task("task-1")], [])
    assert result.scheduled_tasks[0].start_time == PLANNING_START


def test_clock_must_be_timezone_aware() -> None:
    scheduler = StudyScheduler(clock=lambda: datetime(2026, 9, 2, 9))
    with pytest.raises(ValueError, match="timezone"):
        scheduler.schedule_tasks([make_assessment()], [make_task("task-1")], [])


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


def test_reschedule_keeps_hard_dependent_when_prerequisite_can_move_before_it() -> None:
    event_time = datetime(2026, 9, 3, 10, tzinfo=SGT)
    tasks = [
        make_task(
            "prep",
            duration_minutes=120,
            priority=1,
            status=TaskStatus.MISSED,
        ),
        make_task("unrelated", priority=10, status=TaskStatus.SCHEDULED),
        make_task(
            "fixed-demo",
            dependencies=["prep"],
            status=TaskStatus.SCHEDULED,
        ),
    ]
    old_prep = ScheduledTask(
        id="old-prep",
        task_id="prep",
        start_time=datetime(2026, 9, 3, 8, tzinfo=SGT),
        end_time=datetime(2026, 9, 3, 9, tzinfo=SGT),
        flexibility=Flexibility.FLEXIBLE,
    )
    old_unrelated = ScheduledTask(
        id="old-unrelated",
        task_id="unrelated",
        start_time=datetime(2026, 9, 3, 9, tzinfo=SGT),
        end_time=datetime(2026, 9, 3, 10, tzinfo=SGT),
        flexibility=Flexibility.FLEXIBLE,
    )
    fixed_demo = ScheduledTask(
        id="fixed-demo-placement",
        task_id="fixed-demo",
        start_time=datetime(2026, 9, 3, 12, tzinfo=SGT),
        end_time=datetime(2026, 9, 3, 13, tzinfo=SGT),
        flexibility=Flexibility.HARD,
    )

    result = make_scheduler().reschedule_tasks(
        [make_assessment()],
        tasks,
        [],
        [old_prep, old_unrelated, fixed_demo],
        {"prep", "unrelated"},
        replanning_start=event_time,
    )

    by_task_id = {item.task_id: item for item in result.scheduled_tasks}
    assert by_task_id["prep"].start_time == event_time
    assert by_task_id["prep"].end_time <= fixed_demo.start_time
    assert by_task_id["fixed-demo"] == fixed_demo
    assert by_task_id["unrelated"].start_time >= fixed_demo.end_time


def test_reschedule_rejects_dependency_violation_against_hard_dependent() -> None:
    tasks = [
        make_task("prep", status=TaskStatus.MISSED),
        make_task(
            "fixed-demo",
            dependencies=["prep"],
            status=TaskStatus.SCHEDULED,
        ),
    ]
    schedule = [
        ScheduledTask(
            id="old-prep",
            task_id="prep",
            start_time=datetime(2026, 9, 3, 8, tzinfo=SGT),
            end_time=datetime(2026, 9, 3, 9, tzinfo=SGT),
            flexibility=Flexibility.FLEXIBLE,
        ),
        ScheduledTask(
            id="fixed-demo-placement",
            task_id="fixed-demo",
            start_time=datetime(2026, 9, 3, 12, tzinfo=SGT),
            end_time=datetime(2026, 9, 3, 13, tzinfo=SGT),
            flexibility=Flexibility.HARD,
        ),
    ]

    with pytest.raises(ValueError, match="without prerequisite"):
        make_scheduler().reschedule_tasks(
            [make_assessment()],
            tasks,
            [],
            schedule,
            {"prep"},
            replanning_start=datetime(2026, 9, 3, 11, 30, tzinfo=SGT),
        )


def test_reschedule_propagates_deep_dependencies_across_days() -> None:
    assessment = make_assessment(
        deadline=datetime(2026, 9, 4, 12, tzinfo=SGT)
    )
    tasks = [
        make_task("slides", status=TaskStatus.MISSED),
        make_task(
            "script",
            dependencies=["slides"],
            status=TaskStatus.SCHEDULED,
        ),
        make_task(
            "rehearsal",
            dependencies=["script"],
            status=TaskStatus.SCHEDULED,
        ),
    ]
    existing_schedule = [
        ScheduledTask(
            id=f"old-{task_id}",
            task_id=task_id,
            start_time=datetime(2026, 9, 3, hour, tzinfo=SGT),
            end_time=datetime(2026, 9, 3, hour + 1, tzinfo=SGT),
            flexibility=Flexibility.FLEXIBLE,
        )
        for task_id, hour in (("slides", 18), ("script", 19), ("rehearsal", 20))
    ]
    next_morning_class = CalendarBlock(
        id="morning-class",
        title="Morning class",
        start_time=datetime(2026, 9, 4, 8, tzinfo=SGT),
        end_time=datetime(2026, 9, 4, 9, tzinfo=SGT),
        flexibility=Flexibility.HARD,
    )
    event_time = datetime(2026, 9, 3, 21, 30, tzinfo=SGT)

    result = make_scheduler().reschedule_tasks(
        [assessment],
        tasks,
        [next_morning_class],
        existing_schedule,
        {"slides"},
        replanning_start=event_time,
    )

    by_task_id = {item.task_id: item for item in result.scheduled_tasks}
    assert result.unscheduled_tasks == []
    assert by_task_id["slides"].start_time == datetime(2026, 9, 4, 9, tzinfo=SGT)
    assert by_task_id["script"].start_time == by_task_id["slides"].end_time
    assert by_task_id["rehearsal"].start_time == by_task_id["script"].end_time
    assert by_task_id["rehearsal"].end_time == assessment.deadline
    assert all(item.start_time >= event_time for item in result.scheduled_tasks)


def test_calendar_replan_moves_only_conflicts_and_required_dependents() -> None:
    tasks = [
        make_task("slides", status=TaskStatus.SCHEDULED),
        make_task(
            "script",
            dependencies=["slides"],
            status=TaskStatus.SCHEDULED,
        ),
        make_task("independent", status=TaskStatus.SCHEDULED),
    ]
    existing_schedule = [
        ScheduledTask(
            id=f"old-{task_id}",
            task_id=task_id,
            start_time=datetime(2026, 9, 3, hour, tzinfo=SGT),
            end_time=datetime(2026, 9, 3, hour + 1, tzinfo=SGT),
            flexibility=Flexibility.FLEXIBLE,
        )
        for task_id, hour in (("slides", 9), ("script", 10), ("independent", 15))
    ]
    new_class = CalendarBlock(
        id="new-class",
        title="New class",
        start_time=datetime(2026, 9, 3, 9, tzinfo=SGT),
        end_time=datetime(2026, 9, 3, 10, tzinfo=SGT),
        flexibility=Flexibility.HARD,
    )

    result = make_scheduler().reschedule_tasks(
        [make_assessment()],
        tasks,
        [new_class],
        existing_schedule,
        {task.id for task in tasks},
        replanning_start=datetime(2026, 9, 3, 9, tzinfo=SGT),
        preserve_valid_affected=True,
    )

    by_task_id = {item.task_id: item for item in result.scheduled_tasks}
    assert by_task_id["slides"].start_time == new_class.end_time
    assert by_task_id["script"].start_time == by_task_id["slides"].end_time
    assert by_task_id["independent"] == existing_schedule[2]


def test_consecutive_calendar_replans_use_the_latest_schedule() -> None:
    tasks = [
        make_task("slides", status=TaskStatus.SCHEDULED),
        make_task(
            "script",
            dependencies=["slides"],
            status=TaskStatus.SCHEDULED,
        ),
        make_task("independent", status=TaskStatus.SCHEDULED),
    ]
    initial_schedule = [
        ScheduledTask(
            id=f"old-{task_id}",
            task_id=task_id,
            start_time=datetime(2026, 9, 3, hour, tzinfo=SGT),
            end_time=datetime(2026, 9, 3, hour + 1, tzinfo=SGT),
            flexibility=Flexibility.FLEXIBLE,
        )
        for task_id, hour in (("slides", 9), ("script", 10), ("independent", 15))
    ]
    first_class = CalendarBlock(
        id="class-1",
        title="First class",
        start_time=datetime(2026, 9, 3, 9, tzinfo=SGT),
        end_time=datetime(2026, 9, 3, 10, tzinfo=SGT),
        flexibility=Flexibility.HARD,
    )
    scheduler = make_scheduler()
    first = scheduler.reschedule_tasks(
        [make_assessment()],
        tasks,
        [first_class],
        initial_schedule,
        {task.id for task in tasks},
        replanning_start=datetime(2026, 9, 3, 9, tzinfo=SGT),
        preserve_valid_affected=True,
    )
    second_class = CalendarBlock(
        id="class-2",
        title="Second class",
        start_time=datetime(2026, 9, 3, 10, tzinfo=SGT),
        end_time=datetime(2026, 9, 3, 11, tzinfo=SGT),
        flexibility=Flexibility.HARD,
    )

    second = scheduler.reschedule_tasks(
        [make_assessment()],
        tasks,
        [first_class, second_class],
        first.scheduled_tasks,
        {task.id for task in tasks},
        replanning_start=datetime(2026, 9, 3, 9, 30, tzinfo=SGT),
        preserve_valid_affected=True,
    )

    by_task_id = {item.task_id: item for item in second.scheduled_tasks}
    assert by_task_id["slides"].start_time == second_class.end_time
    assert by_task_id["script"].start_time == by_task_id["slides"].end_time
    assert by_task_id["independent"] == initial_schedule[2]


def test_replan_reports_deadline_and_dependency_failures_when_no_slot_remains() -> None:
    assessment = make_assessment(
        deadline=datetime(2026, 9, 3, 12, tzinfo=SGT)
    )
    tasks = [
        make_task("slides", status=TaskStatus.MISSED),
        make_task("script", dependencies=["slides"], status=TaskStatus.SCHEDULED),
    ]
    existing_schedule = [
        ScheduledTask(
            id=f"old-{task_id}",
            task_id=task_id,
            start_time=datetime(2026, 9, 3, hour, tzinfo=SGT),
            end_time=datetime(2026, 9, 3, hour + 1, tzinfo=SGT),
            flexibility=Flexibility.FLEXIBLE,
        )
        for task_id, hour in (("slides", 8), ("script", 9))
    ]
    blocking_class = CalendarBlock(
        id="blocking-class",
        title="Blocking class",
        start_time=datetime(2026, 9, 3, 10, tzinfo=SGT),
        end_time=assessment.deadline,
        flexibility=Flexibility.HARD,
    )

    result = make_scheduler().reschedule_tasks(
        [assessment],
        tasks,
        [blocking_class],
        existing_schedule,
        {"slides"},
        replanning_start=blocking_class.start_time,
    )

    assert result.scheduled_tasks == []
    assert [item.reason for item in result.unscheduled_tasks] == [
        SchedulingFailureReason.DEADLINE_CONSTRAINT,
        SchedulingFailureReason.DEPENDENCY_CONFLICT,
    ]
