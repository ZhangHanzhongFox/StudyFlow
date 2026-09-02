"""Focused tests for dependency-aware greedy scheduling."""

from datetime import datetime, timezone

import pytest

from backend.scheduler import StudyScheduler
from backend.scheduler.core import test_scheduler_happy_path as run_happy_path
from backend.schemas import CalendarBlock, Flexibility, Task, TaskStatus


def make_task(
    task_id: str,
    *,
    duration_minutes: int = 60,
    dependencies: list[str] | None = None,
    priority: int = 1,
) -> Task:
    return Task(
        id=task_id,
        assessment_id="assessment-1",
        name=task_id,
        duration_minutes=duration_minutes,
        dependencies=dependencies or [],
        priority=priority,
        status=TaskStatus.PENDING,
    )


def test_happy_path() -> None:
    run_happy_path()


def test_ready_tasks_are_ordered_by_descending_priority() -> None:
    tasks = [
        make_task("low", priority=1),
        make_task("high", priority=10),
    ]

    scheduled = StudyScheduler().schedule(
        tasks,
        [],
        datetime(2026, 9, 2, 8, tzinfo=timezone.utc),
    )

    assert [placement.task_id for placement in scheduled] == ["high", "low"]


def test_overlapping_hard_blocks_are_merged_before_slot_search() -> None:
    blocks = [
        CalendarBlock(
            id="block-1",
            title="Lecture",
            start_time=datetime(2026, 9, 2, 9, tzinfo=timezone.utc),
            end_time=datetime(2026, 9, 2, 11, tzinfo=timezone.utc),
            flexibility=Flexibility.HARD,
        ),
        CalendarBlock(
            id="block-2",
            title="Lab",
            start_time=datetime(2026, 9, 2, 10, tzinfo=timezone.utc),
            end_time=datetime(2026, 9, 2, 12, tzinfo=timezone.utc),
            flexibility=Flexibility.HARD,
        ),
    ]

    scheduled = StudyScheduler().schedule(
        [make_task("deep-work", duration_minutes=120)],
        blocks,
        datetime(2026, 9, 2, 8, tzinfo=timezone.utc),
    )

    assert scheduled[0].start_time == datetime(
        2026, 9, 2, 12, tzinfo=timezone.utc
    )


def test_task_larger_than_daily_window_is_rejected() -> None:
    with pytest.raises(ValueError, match="exceeding"):
        StudyScheduler(daily_start_hour=8, daily_end_hour=9).schedule(
            [make_task("too-long", duration_minutes=61)],
            [],
            datetime(2026, 9, 2, 8, tzinfo=timezone.utc),
        )
