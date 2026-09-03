"""Deadline-aware deterministic scheduling for StudyFlow tasks."""

from __future__ import annotations

import heapq
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from typing import TypeAlias

from backend.schemas import (
    Assessment,
    CalendarBlock,
    Flexibility,
    ScheduledTask,
    Task,
    TaskStatus,
    require_timezone_aware,
    validate_task_graph,
)

from .contracts import (
    SchedulingFailureReason,
    SchedulingResult,
    UnscheduledTask,
)


BusyInterval: TypeAlias = tuple[datetime, datetime]


class StudyScheduler:
    """Place tasks around hard commitments before their assessment deadlines.

    Tasks are dependency ordered and priority breaks ties between currently
    ready tasks. Study sessions are continuous and constrained to a daily
    window interpreted in the planning start's timezone. Soft and flexible
    calendar blocks may be displaced; hard blocks are never overlapped.
    """

    def __init__(
        self,
        daily_start_hour: int = 8,
        daily_end_hour: int = 22,
        planning_start: datetime | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not 0 <= daily_start_hour <= 23:
            raise ValueError("daily_start_hour must be between 0 and 23")
        if not 1 <= daily_end_hour <= 24:
            raise ValueError("daily_end_hour must be between 1 and 24")
        if daily_start_hour >= daily_end_hour:
            raise ValueError("daily_start_hour must be earlier than daily_end_hour")
        if planning_start is not None:
            require_timezone_aware(planning_start, "planning_start")

        self.daily_start_hour = daily_start_hour
        self.daily_end_hour = daily_end_hour
        self.planning_start = planning_start
        self._clock = clock

    def schedule_tasks(
        self,
        assessments: Sequence[Assessment],
        tasks: Sequence[Task],
        calendar_blocks: Sequence[CalendarBlock],
        existing_schedule: Sequence[ScheduledTask] = (),
    ) -> SchedulingResult:
        """Schedule all incomplete tasks and explicitly report failures."""

        assessment_list = list(assessments)
        task_list = validate_task_graph(tasks)
        block_list = list(calendar_blocks)
        existing_list = list(existing_schedule)
        assessments_by_id = self._index_assessments(assessment_list)
        self._validate_task_assessments(task_list, assessments_by_id)

        tasks_by_id = {task.id: task for task in task_list}
        preserved = self._preserve_existing(
            existing_list,
            tasks_by_id,
            preserve_task_ids={
                task.id for task in task_list if task.status is TaskStatus.COMPLETED
            },
        )
        planning_start = self._resolve_planning_start(
            assessment_list,
            block_list,
            existing_list,
        )
        target_task_ids = {
            task.id for task in task_list if task.status is not TaskStatus.COMPLETED
        }
        return self._schedule_selected(
            task_list,
            assessments_by_id,
            block_list,
            planning_start,
            target_task_ids,
            preserved,
        )

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
        """Re-place affected work while preserving unaffected placements.

        New placements start no earlier than the observation. Calendar changes
        can preserve valid candidates. Completed work and hard placements are
        immutable; contradictory calendar changes are rejected.
        """

        assessment_list = list(assessments)
        task_list = validate_task_graph(tasks)
        block_list = list(calendar_blocks)
        existing_list = list(existing_schedule)
        assessments_by_id = self._index_assessments(assessment_list)
        self._validate_task_assessments(task_list, assessments_by_id)
        tasks_by_id = {task.id: task for task in task_list}

        unknown_affected = affected_task_ids - tasks_by_id.keys()
        if unknown_affected:
            unknown = ", ".join(sorted(unknown_affected))
            raise ValueError(f"affected tasks are unknown: {unknown}")

        default_start = self._resolve_planning_start(
            assessment_list, block_list, existing_list,
        )
        if replanning_start is not None:
            require_timezone_aware(replanning_start, "replanning_start")
        # Browsers often send UTC timestamps. Study hours still belong to the
        # schedule's timezone, not to the event's serialization offset.
        planning_start = (
            replanning_start.astimezone(default_start.tzinfo)
            if replanning_start is not None else default_start
        )
        immutable_ids = {
            task.id
            for task in task_list
            if task.status is TaskStatus.COMPLETED
        }
        immutable_ids.update(
            placement.task_id
            for placement in existing_list
            if placement.flexibility is Flexibility.HARD
        )
        placements_by_task = {item.task_id: item for item in existing_list}
        if len(placements_by_task) != len(existing_list):
            raise ValueError("multiple existing placements for a task")
        invalid_ids: set[str] = set()
        for placement in existing_list:
            task = tasks_by_id.get(placement.task_id)
            if task is None:
                raise ValueError(f"placement references unknown task: {placement.task_id}")
            if task.status is TaskStatus.MISSED and placement.flexibility is Flexibility.HARD:
                raise ValueError(f"Cannot automatically move missed hard task: {task.id}")
            assessment = assessments_by_id[task.assessment_id]
            conflicts = any(
                block.flexibility is Flexibility.HARD
                and placement.start_time < block.end_time
                and block.start_time < placement.end_time
                for block in block_list
            )
            invalid = (
                conflicts
                or placement.end_time > assessment.deadline
                or (assessment.unlock_at is not None
                    and placement.start_time < assessment.unlock_at)
                or placement.end_time - placement.start_time
                != timedelta(minutes=task.duration_minutes)
            )
            if invalid:
                if task.id in immutable_ids:
                    raise ValueError(
                        f"Calendar or assessment conflicts with immutable task: {task.id}"
                    )
                invalid_ids.add(task.id)

        target_task_ids = set(affected_task_ids) - immutable_ids
        if preserve_valid_affected:
            target_task_ids = {
                task_id for task_id in target_task_ids
                if task_id not in placements_by_task
                or task_id in invalid_ids
                or tasks_by_id[task_id].status is TaskStatus.MISSED
            }
        target_task_ids.update(invalid_ids)
        # A supplies semantic scope; B also repairs dependencies invalidated by
        # changed calendar constraints or by an injected agent's narrow scope.
        for task in self._topological_sort(task_list):
            placement = placements_by_task.get(task.id)
            invalid_dependency = any(
                dependency_id in target_task_ids
                or (tasks_by_id[dependency_id].status is not TaskStatus.COMPLETED
                    and dependency_id not in placements_by_task)
                or (placement is not None
                    and dependency_id in placements_by_task
                    and placements_by_task[dependency_id].end_time > placement.start_time)
                for dependency_id in task.dependencies
            )
            if invalid_dependency and task.status is not TaskStatus.COMPLETED:
                # A hard dependent may remain valid when its prerequisite can
                # be moved into an earlier slot. Keep that fixed placement as
                # a constraint and validate the resulting dependency order
                # after scheduling instead of rejecting the replan eagerly.
                if task.id not in immutable_ids:
                    target_task_ids.add(task.id)

        preserve_task_ids = tasks_by_id.keys() - target_task_ids
        preserved = self._preserve_existing(
            existing_list,
            tasks_by_id,
            preserve_task_ids,
        )
        for index, placement in enumerate(preserved):
            if any(
                placement.start_time < other.end_time
                and other.start_time < placement.end_time
                for other in preserved[:index]
            ):
                raise ValueError("preserved schedule contains overlapping tasks")
        dependency_deadlines = self._fixed_dependency_deadlines(
            task_list,
            existing_list,
            target_task_ids,
        )
        result = self._schedule_selected(
            task_list,
            assessments_by_id,
            block_list,
            planning_start,
            target_task_ids,
            preserved,
            dependency_deadlines,
        )
        self._validate_scheduled_dependencies(
            result.scheduled_tasks,
            tasks_by_id,
        )
        return result

    def schedule(
        self,
        tasks: list[Task],
        calendar_blocks: list[CalendarBlock],
        planning_start: datetime,
    ) -> list[ScheduledTask]:
        """Backward-compatible low-level scheduling without deadline inputs."""

        require_timezone_aware(planning_start, "planning_start")
        ordered_tasks = self._topological_sort(tasks)
        busy_intervals = self._hard_busy_intervals(
            calendar_blocks,
            planning_start.tzinfo or timezone.utc,
        )
        scheduled: list[ScheduledTask] = []
        task_end_times: dict[str, datetime] = {}

        for task in ordered_tasks:
            dependency_ready_time = max(
                (task_end_times[item] for item in task.dependencies),
                default=planning_start,
            )
            start_time = self._find_first_slot(
                max(planning_start, dependency_ready_time),
                task.duration_minutes,
                busy_intervals,
                latest_end=None,
            )
            if start_time is None:
                raise ValueError(f"no available slot for task {task.id}")
            end_time = start_time + timedelta(minutes=task.duration_minutes)
            placement = self._placement(task, start_time, end_time)
            scheduled.append(placement)
            task_end_times[task.id] = end_time
            busy_intervals = self._merge_intervals(
                [*busy_intervals, (start_time, end_time)]
            )

        return scheduled

    def _schedule_selected(
        self,
        tasks: list[Task],
        assessments_by_id: Mapping[str, Assessment],
        calendar_blocks: list[CalendarBlock],
        planning_start: datetime,
        target_task_ids: set[str],
        preserved: list[ScheduledTask],
        dependency_deadlines: Mapping[str, datetime] | None = None,
    ) -> SchedulingResult:
        planning_timezone = planning_start.tzinfo or timezone.utc
        busy_intervals = self._hard_busy_intervals(
            calendar_blocks,
            planning_timezone,
        )
        busy_intervals = self._merge_intervals(
            [
                *busy_intervals,
                *[
                    (
                        item.start_time.astimezone(planning_timezone),
                        item.end_time.astimezone(planning_timezone),
                    )
                    for item in preserved
                ],
            ]
        )
        scheduled = list(preserved)
        task_end_times = {
            item.task_id: item.end_time.astimezone(planning_timezone)
            for item in preserved
        }
        for task in tasks:
            if task.status is TaskStatus.COMPLETED:
                task_end_times.setdefault(task.id, planning_start)

        failures: list[UnscheduledTask] = []
        failed_task_ids: set[str] = set()
        daily_capacity_minutes = (
            self.daily_end_hour - self.daily_start_hour
        ) * 60

        ordering_deadlines = {
            task.id: min(
                assessments_by_id[task.assessment_id].deadline,
                dependency_deadlines.get(
                    task.id,
                    assessments_by_id[task.assessment_id].deadline,
                ),
            )
            for task in tasks
        } if dependency_deadlines else None

        for task in self._topological_sort(tasks, ordering_deadlines):
            if task.id not in target_task_ids:
                continue

            failed_dependencies = [
                dependency_id
                for dependency_id in task.dependencies
                if dependency_id in failed_task_ids
                or dependency_id not in task_end_times
            ]
            if failed_dependencies:
                failed_task_ids.add(task.id)
                failures.append(
                    UnscheduledTask(
                        task_id=task.id,
                        reason=SchedulingFailureReason.DEPENDENCY_CONFLICT,
                        message=(
                            "Prerequisite tasks could not be completed before "
                            "this task was scheduled: "
                            + ", ".join(failed_dependencies)
                        ),
                    )
                )
                continue

            assessment = assessments_by_id[task.assessment_id]
            deadline = assessment.deadline.astimezone(planning_timezone)
            if dependency_deadlines and task.id in dependency_deadlines:
                deadline = min(
                    deadline,
                    dependency_deadlines[task.id].astimezone(planning_timezone),
                )
            unlock_at = (
                assessment.unlock_at.astimezone(planning_timezone)
                if assessment.unlock_at is not None
                else planning_start
            )
            dependency_ready_time = max(
                (task_end_times[item] for item in task.dependencies),
                default=planning_start,
            )
            earliest_start = max(
                planning_start,
                unlock_at,
                dependency_ready_time,
            )

            if task.duration_minutes > daily_capacity_minutes:
                failed_task_ids.add(task.id)
                failures.append(
                    UnscheduledTask(
                        task_id=task.id,
                        reason=SchedulingFailureReason.NO_AVAILABLE_SLOT,
                        message=(
                            f"Task requires {task.duration_minutes} continuous "
                            f"minutes, exceeding the {daily_capacity_minutes}-minute "
                            "daily study window."
                        ),
                    )
                )
                continue

            start_time = self._find_first_slot(
                earliest_start,
                task.duration_minutes,
                busy_intervals,
                latest_end=deadline,
            )
            if start_time is None:
                failed_task_ids.add(task.id)
                failures.append(
                    UnscheduledTask(
                        task_id=task.id,
                        reason=SchedulingFailureReason.DEADLINE_CONSTRAINT,
                        message=(
                            "No dependency-valid continuous slot exists before "
                            f"the assessment deadline {assessment.deadline.isoformat()}."
                        ),
                    )
                )
                continue

            end_time = start_time + timedelta(minutes=task.duration_minutes)
            placement = self._placement(task, start_time, end_time)
            scheduled.append(placement)
            task_end_times[task.id] = end_time
            busy_intervals = self._merge_intervals(
                [*busy_intervals, (start_time, end_time)]
            )

        return SchedulingResult(
            scheduled_tasks=sorted(scheduled, key=lambda item: item.start_time),
            unscheduled_tasks=failures,
        )

    def _resolve_planning_start(
        self,
        assessments: list[Assessment],
        calendar_blocks: list[CalendarBlock],
        existing_schedule: list[ScheduledTask],
    ) -> datetime:
        if self.planning_start is not None:
            return self.planning_start
        if self._clock is not None:
            # Read at scheduling time, not server startup or the previous plan.
            now = self._clock()
            require_timezone_aware(now, "clock")
            # Keep minute-aligned slots without rounding into the past.
            if now.second or now.microsecond:
                now = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
            return now
        if existing_schedule:
            return min(item.start_time for item in existing_schedule)
        if calendar_blocks:
            first_block = min(calendar_blocks, key=lambda item: item.start_time)
            timezone_info = first_block.start_time.tzinfo or timezone.utc
            return datetime.combine(
                first_block.start_time.date(),
                time(hour=self.daily_start_hour),
                tzinfo=timezone_info,
            )
        unlock_times = [
            assessment.unlock_at
            for assessment in assessments
            if assessment.unlock_at is not None
        ]
        if unlock_times:
            first_unlock = min(unlock_times)
            timezone_info = first_unlock.tzinfo or timezone.utc
            return datetime.combine(
                first_unlock.date(),
                time(hour=self.daily_start_hour),
                tzinfo=timezone_info,
            )
        if assessments:
            first_deadline = min(item.deadline for item in assessments)
            timezone_info = first_deadline.tzinfo or timezone.utc
            return datetime.combine(
                first_deadline.date(),
                time(hour=self.daily_start_hour),
                tzinfo=timezone_info,
            )
        return datetime.now(timezone.utc)

    @staticmethod
    def _index_assessments(
        assessments: list[Assessment],
    ) -> dict[str, Assessment]:
        indexed: dict[str, Assessment] = {}
        for assessment in assessments:
            if assessment.id in indexed:
                raise ValueError(f"duplicate assessment id: {assessment.id}")
            indexed[assessment.id] = assessment
        return indexed

    @staticmethod
    def _validate_task_assessments(
        tasks: list[Task],
        assessments_by_id: Mapping[str, Assessment],
    ) -> None:
        for task in tasks:
            if task.assessment_id not in assessments_by_id:
                raise ValueError(
                    f"task {task.id} references unknown assessment "
                    f"{task.assessment_id}"
                )

    @staticmethod
    def _preserve_existing(
        existing_schedule: list[ScheduledTask],
        tasks_by_id: Mapping[str, Task],
        preserve_task_ids: set[str],
    ) -> list[ScheduledTask]:
        preserved: list[ScheduledTask] = []
        seen_task_ids: set[str] = set()
        for placement in existing_schedule:
            if placement.task_id not in tasks_by_id:
                continue
            if placement.task_id not in preserve_task_ids:
                continue
            if placement.task_id in seen_task_ids:
                raise ValueError(
                    f"multiple existing placements for task {placement.task_id}"
                )
            seen_task_ids.add(placement.task_id)
            preserved.append(placement.model_copy(deep=True))
        return preserved

    @staticmethod
    def _placement(
        task: Task,
        start_time: datetime,
        end_time: datetime,
    ) -> ScheduledTask:
        return ScheduledTask(
            id=f"scheduled-{task.id}",
            task_id=task.id,
            start_time=start_time,
            end_time=end_time,
            flexibility=Flexibility.FLEXIBLE,
        )

    @staticmethod
    def _validate_scheduled_dependencies(
        schedule: Sequence[ScheduledTask],
        tasks_by_id: Mapping[str, Task],
    ) -> None:
        """Reject a result that would make a preserved fixed task invalid."""

        placements_by_task = {item.task_id: item for item in schedule}
        for placement in schedule:
            task = tasks_by_id[placement.task_id]
            for dependency_id in task.dependencies:
                dependency = tasks_by_id[dependency_id]
                dependency_placement = placements_by_task.get(dependency_id)
                if dependency_placement is None:
                    if dependency.status is TaskStatus.COMPLETED:
                        continue
                    raise ValueError(
                        "Replanning would leave scheduled task "
                        f"{task.id} without prerequisite {dependency_id}"
                    )
                if dependency_placement.end_time > placement.start_time:
                    raise ValueError(
                        "Replanning would violate dependency order: "
                        f"{dependency_id} must finish before {task.id}"
                    )

    @classmethod
    def _fixed_dependency_deadlines(
        cls,
        tasks: Sequence[Task],
        existing_schedule: Sequence[ScheduledTask],
        target_task_ids: set[str],
    ) -> dict[str, datetime]:
        """Propagate fixed dependent start times back through moved work."""

        tasks_by_id = {task.id: task for task in tasks}
        deadlines: dict[str, datetime] = {}
        for placement in existing_schedule:
            if placement.flexibility is not Flexibility.HARD:
                continue
            task = tasks_by_id[placement.task_id]
            for dependency_id in task.dependencies:
                if dependency_id in target_task_ids:
                    deadlines[dependency_id] = min(
                        deadlines.get(dependency_id, placement.start_time),
                        placement.start_time,
                    )

        for task in reversed(cls._topological_sort(tasks)):
            deadline = deadlines.get(task.id)
            if deadline is None:
                continue
            for dependency_id in task.dependencies:
                if dependency_id in target_task_ids:
                    deadlines[dependency_id] = min(
                        deadlines.get(dependency_id, deadline),
                        deadline,
                    )
        return deadlines

    @staticmethod
    def _topological_sort(
        tasks: Sequence[Task],
        ordering_deadlines: Mapping[str, datetime] | None = None,
    ) -> list[Task]:
        """Kahn-sort by optional deadline, then descending task priority."""

        task_list = validate_task_graph(tasks)
        tasks_by_id = {task.id: task for task in task_list}
        input_order = {task.id: index for index, task in enumerate(task_list)}
        indegree = {task.id: len(task.dependencies) for task in task_list}
        dependents: dict[str, list[str]] = {task.id: [] for task in task_list}

        for task in task_list:
            for dependency_id in task.dependencies:
                dependents[dependency_id].append(task.id)

        ready: list[tuple[float, int, int, str]] = []
        for task in task_list:
            if indegree[task.id] == 0:
                heapq.heappush(
                    ready,
                    (
                        ordering_deadlines[task.id].timestamp()
                        if ordering_deadlines is not None else float("inf"),
                        -task.priority,
                        input_order[task.id],
                        task.id,
                    ),
                )

        ordered: list[Task] = []
        while ready:
            _, _, _, task_id = heapq.heappop(ready)
            ordered.append(tasks_by_id[task_id])
            for dependent_id in dependents[task_id]:
                indegree[dependent_id] -= 1
                if indegree[dependent_id] == 0:
                    dependent = tasks_by_id[dependent_id]
                    heapq.heappush(
                        ready,
                        (
                            ordering_deadlines[dependent_id].timestamp()
                            if ordering_deadlines is not None else float("inf"),
                            -dependent.priority,
                            input_order[dependent_id],
                            dependent_id,
                        ),
                    )

        if len(ordered) != len(task_list):
            raise ValueError("task dependency graph must be acyclic")
        return ordered

    @classmethod
    def _hard_busy_intervals(
        cls,
        calendar_blocks: Sequence[CalendarBlock],
        planning_timezone: tzinfo,
    ) -> list[BusyInterval]:
        hard_intervals = [
            (
                block.start_time.astimezone(planning_timezone),
                block.end_time.astimezone(planning_timezone),
            )
            for block in calendar_blocks
            if block.flexibility is Flexibility.HARD
        ]
        return cls._merge_intervals(hard_intervals)

    @staticmethod
    def _merge_intervals(intervals: list[BusyInterval]) -> list[BusyInterval]:
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
        latest_end: datetime | None,
    ) -> datetime | None:
        duration = timedelta(minutes=duration_minutes)
        planning_timezone = earliest_start.tzinfo or timezone.utc
        candidate = earliest_start
        candidate_day = candidate.date()

        while latest_end is None or candidate < latest_end:
            window_start, window_end = self._daily_window(
                candidate_day,
                planning_timezone,
            )
            if latest_end is not None:
                window_end = min(window_end, latest_end)
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
            candidate, _ = self._daily_window(
                candidate_day,
                planning_timezone,
            )
        return None

    def _daily_window(
        self,
        day: date,
        planning_timezone: tzinfo,
    ) -> BusyInterval:
        start_time = datetime.combine(
            day,
            time(hour=self.daily_start_hour),
            tzinfo=planning_timezone,
        )
        if self.daily_end_hour == 24:
            end_time = datetime.combine(
                day + timedelta(days=1),
                time.min,
                tzinfo=planning_timezone,
            )
        else:
            end_time = datetime.combine(
                day,
                time(hour=self.daily_end_hour),
                tzinfo=planning_timezone,
            )
        return start_time, end_time
