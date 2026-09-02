"""Contract tests for C's adapter around B's concrete scheduler."""

from datetime import datetime, timedelta, timezone

from backend.scheduler import SchedulingFailureReason, StudyScheduler
from backend.schemas import Assessment, AssessmentType, Task, TaskStatus
from backend.services import StudySchedulerAdapter


def assessment(deadline: datetime) -> Assessment:
    return Assessment(
        id="assessment-adapter",
        course_code="CS0000",
        title="Adapter test",
        description="",
        type=AssessmentType.CODING_ASSIGNMENT,
        unlock_at=None,
        deadline=deadline,
        weightage=None,
        is_group=False,
        group_size=None,
    )


def task(
    task_id: str,
    *,
    dependencies: list[str] | None = None,
) -> Task:
    return Task(
        id=task_id,
        assessment_id="assessment-adapter",
        name=task_id,
        duration_minutes=60,
        dependencies=dependencies or [],
        priority=3,
        status=TaskStatus.PENDING,
    )


def test_adapter_maps_deadline_and_dependency_failures() -> None:
    start = datetime(2026, 9, 2, 8, tzinfo=timezone.utc)
    first = task("first")
    second = task("second", dependencies=["first"])
    adapter = StudySchedulerAdapter(StudyScheduler(), start)

    result = adapter.schedule_tasks(
        [assessment(start + timedelta(minutes=30))],
        [first, second],
        [],
    )

    assert result.scheduled_tasks == []
    assert [failure.reason for failure in result.unscheduled_tasks] == [
        SchedulingFailureReason.DEADLINE_CONSTRAINT,
        SchedulingFailureReason.DEPENDENCY_CONFLICT,
    ]


def test_adapter_maps_concrete_scheduler_validation_to_invalid_input() -> None:
    start = datetime(2026, 9, 2, 8, tzinfo=timezone.utc)
    oversized = task("oversized").model_copy(
        update={"duration_minutes": 61}
    )
    adapter = StudySchedulerAdapter(
        StudyScheduler(daily_start_hour=8, daily_end_hour=9),
        start,
    )

    result = adapter.schedule_tasks(
        [assessment(start + timedelta(days=1))],
        [oversized],
        [],
    )

    assert result.scheduled_tasks == []
    assert result.unscheduled_tasks[0].reason is SchedulingFailureReason.INVALID_INPUT
