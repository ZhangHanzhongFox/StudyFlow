"""Dependency-aware greedy scheduling for StudyFlow tasks."""

from __future__ import annotations

import heapq
from datetime import date, datetime, time, timedelta, timezone
from typing import TypeAlias

from backend.schemas import (
    CalendarBlock,
    Flexibility,
    ScheduledTask,
    Task,
    TaskStatus,
    require_timezone_aware,
    validate_task_graph,
)


BusyInterval: TypeAlias = tuple[datetime, datetime]


class StudyScheduler:
    """Schedule tasks with topological ordering and greedy slot allocation.

    All scheduling is performed in UTC. Only hard calendar blocks consume
    availability; soft and flexible blocks may be displaced by study work.
    """

    def __init__(self, daily_start_hour: int = 8, daily_end_hour: int = 22):
        if not 0 <= daily_start_hour <= 23:
            raise ValueError("daily_start_hour must be between 0 and 23")
        if not 1 <= daily_end_hour <= 24:
            raise ValueError("daily_end_hour must be between 1 and 24")
        if daily_start_hour >= daily_end_hour:
            raise ValueError("daily_start_hour must be earlier than daily_end_hour")

        self.daily_start_hour = daily_start_hour
        self.daily_end_hour = daily_end_hour

    def schedule(
        self,
        tasks: list[Task],
        calendar_blocks: list[CalendarBlock],
        planning_start: datetime,
    ) -> list[ScheduledTask]:
        """Return deterministic placements for every task.

        Tasks are selected from the currently dependency-ready set by priority
        (highest first), then placed in the first continuous UTC study slot
        after both ``planning_start`` and all prerequisite placements.
        """

        require_timezone_aware(planning_start, "planning_start")
        planning_start_utc = planning_start.astimezone(timezone.utc)
        ordered_tasks = self._topological_sort(tasks)
        busy_intervals = self._hard_busy_intervals(calendar_blocks)
        scheduled: list[ScheduledTask] = []
        task_end_times: dict[str, datetime] = {}

        daily_capacity_minutes = (
            self.daily_end_hour - self.daily_start_hour
        ) * 60

        for task in ordered_tasks:
            if task.duration_minutes > daily_capacity_minutes:
                raise ValueError(
                    f"task {task.id} requires {task.duration_minutes} continuous "
                    f"minutes, exceeding the {daily_capacity_minutes}-minute "
                    "daily study window"
                )

            dependency_ready_time = max(
                (task_end_times[dependency_id] for dependency_id in task.dependencies),
                default=planning_start_utc,
            )
            earliest_start = max(planning_start_utc, dependency_ready_time)
            start_time = self._find_first_slot(
                earliest_start,
                task.duration_minutes,
                busy_intervals,
            )
            end_time = start_time + timedelta(minutes=task.duration_minutes)

            placement = ScheduledTask(
                id=f"scheduled-{task.id}",
                task_id=task.id,
                start_time=start_time,
                end_time=end_time,
                flexibility=Flexibility.FLEXIBLE,
            )
            scheduled.append(placement)
            task_end_times[task.id] = end_time
            busy_intervals = self._merge_intervals(
                [*busy_intervals, (start_time, end_time)]
            )

        return scheduled

    @staticmethod
    def _topological_sort(tasks: list[Task]) -> list[Task]:
        """Kahn-sort tasks, prioritizing ready tasks by descending priority."""

        task_list = validate_task_graph(tasks)
        tasks_by_id = {task.id: task for task in task_list}
        input_order = {task.id: index for index, task in enumerate(task_list)}
        indegree = {task.id: len(task.dependencies) for task in task_list}
        dependents: dict[str, list[str]] = {task.id: [] for task in task_list}

        for task in task_list:
            for dependency_id in task.dependencies:
                dependents[dependency_id].append(task.id)

        ready: list[tuple[int, int, str]] = []
        for task in task_list:
            if indegree[task.id] == 0:
                heapq.heappush(
                    ready,
                    (-task.priority, input_order[task.id], task.id),
                )

        ordered: list[Task] = []
        while ready:
            _, _, task_id = heapq.heappop(ready)
            ordered.append(tasks_by_id[task_id])

            for dependent_id in dependents[task_id]:
                indegree[dependent_id] -= 1
                if indegree[dependent_id] == 0:
                    dependent = tasks_by_id[dependent_id]
                    heapq.heappush(
                        ready,
                        (
                            -dependent.priority,
                            input_order[dependent_id],
                            dependent_id,
                        ),
                    )

        # ``validate_task_graph`` already checks this, but retain the boundary
        # guard so this method stays safe if validation changes in the future.
        if len(ordered) != len(task_list):
            raise ValueError("task dependency graph must be acyclic")

        return ordered

    @classmethod
    def _hard_busy_intervals(
        cls,
        calendar_blocks: list[CalendarBlock],
    ) -> list[BusyInterval]:
        hard_intervals = [
            (
                block.start_time.astimezone(timezone.utc),
                block.end_time.astimezone(timezone.utc),
            )
            for block in calendar_blocks
            if block.flexibility == Flexibility.HARD
        ]
        return cls._merge_intervals(hard_intervals)

    @staticmethod
    def _merge_intervals(intervals: list[BusyInterval]) -> list[BusyInterval]:
        """Merge overlapping or touching intervals in chronological order."""

        if not intervals:
            return []

        ordered = sorted(intervals, key=lambda interval: interval[0])
        merged: list[BusyInterval] = [ordered[0]]

        for start_time, end_time in ordered[1:]:
            previous_start, previous_end = merged[-1]
            if start_time <= previous_end:
                merged[-1] = (previous_start, max(previous_end, end_time))
            else:
                merged.append((start_time, end_time))

        return merged

    def _find_first_slot(
        self,
        earliest_start: datetime,
        duration_minutes: int,
        busy_intervals: list[BusyInterval],
    ) -> datetime:
        duration = timedelta(minutes=duration_minutes)
        candidate = earliest_start.astimezone(timezone.utc)
        candidate_day = candidate.date()

        while True:
            window_start, window_end = self._daily_window(candidate_day)
            cursor = max(candidate, window_start)

            if cursor + duration <= window_end:
                for busy_start, busy_end in busy_intervals:
                    if busy_end <= cursor:
                        continue
                    if busy_start >= window_end:
                        break
                    if cursor + duration <= busy_start:
                        return cursor

                    cursor = max(cursor, busy_end)
                    if cursor + duration > window_end:
                        break
                else:
                    return cursor

                if cursor + duration <= window_end:
                    return cursor

            candidate_day += timedelta(days=1)
            candidate, _ = self._daily_window(candidate_day)

    def _daily_window(self, day: date) -> BusyInterval:
        start_time = datetime.combine(
            day,
            time(hour=self.daily_start_hour),
            tzinfo=timezone.utc,
        )
        if self.daily_end_hour == 24:
            end_time = datetime.combine(
                day + timedelta(days=1),
                time.min,
                tzinfo=timezone.utc,
            )
        else:
            end_time = datetime.combine(
                day,
                time(hour=self.daily_end_hour),
                tzinfo=timezone.utc,
            )
        return start_time, end_time


def test_scheduler_happy_path() -> None:
    """Exercise a presentation workflow around hard and soft commitments."""

    tasks = [
        Task(
            id="presentation-research",
            assessment_id="presentation-1",
            name="Research",
            duration_minutes=60,
            dependencies=[],
            priority=3,
            status=TaskStatus.PENDING,
        ),
        Task(
            id="presentation-slides",
            assessment_id="presentation-1",
            name="Slides",
            duration_minutes=90,
            dependencies=["presentation-research"],
            priority=5,
            status=TaskStatus.PENDING,
        ),
        Task(
            id="presentation-rehearsal",
            assessment_id="presentation-1",
            name="Rehearsal",
            duration_minutes=30,
            dependencies=["presentation-slides"],
            priority=4,
            status=TaskStatus.PENDING,
        ),
    ]
    lecture = CalendarBlock(
        id="cs1010-lecture",
        title="CS1010 Lecture",
        start_time=datetime(2026, 9, 2, 10, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc),
        flexibility=Flexibility.HARD,
    )
    gym = CalendarBlock(
        id="gym",
        title="Gym",
        start_time=datetime(2026, 9, 2, 16, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 9, 2, 17, 0, tzinfo=timezone.utc),
        flexibility=Flexibility.SOFT,
    )

    scheduled = StudyScheduler().schedule(
        tasks,
        [lecture, gym],
        datetime(2026, 9, 2, 8, 0, tzinfo=timezone.utc),
    )

    assert len(scheduled) == 3
    assert all(
        placement.end_time <= lecture.start_time
        or placement.start_time >= lecture.end_time
        for placement in scheduled
    )

    by_task_id = {placement.task_id: placement for placement in scheduled}
    assert (
        by_task_id["presentation-slides"].start_time
        >= by_task_id["presentation-research"].end_time
    )
    assert (
        by_task_id["presentation-rehearsal"].start_time
        >= by_task_id["presentation-slides"].end_time
    )

    task_names = {task.id: task.name for task in tasks}
    print("\nStudyFlow scheduled timeline (UTC)")
    for placement in sorted(scheduled, key=lambda item: item.start_time):
        print(
            f"  {placement.start_time:%Y-%m-%d %H:%M}–"
            f"{placement.end_time:%H:%M}  {task_names[placement.task_id]}"
        )
