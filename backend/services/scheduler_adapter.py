"""Adapter from B's concrete scheduler to the shared Scheduler contract."""

from collections.abc import Sequence
from datetime import datetime, timezone

from backend.scheduler import (
    SchedulingFailureReason,
    SchedulingResult,
    StudyScheduler,
    UnscheduledTask,
)
from backend.schemas import (
    Assessment,
    CalendarBlock,
    Flexibility,
    ScheduledTask,
    Task,
    TaskStatus,
)


DEFAULT_PROVIDER_MOCK_PLANNING_START = datetime(
    2026,
    9,
    2,
    8,
    0,
    tzinfo=timezone.utc,
)


class StudySchedulerAdapter:
    """Expose ``StudyScheduler`` through the stable scheduler protocol.

    The concrete scheduler owns placement. This adapter only supplies the
    reproducible mock clock, maps deadline misses into ``SchedulingResult``,
    and preserves unaffected placements during replanning.
    """

    def __init__(
        self,
        scheduler: StudyScheduler | None = None,
        planning_start: datetime = DEFAULT_PROVIDER_MOCK_PLANNING_START,
    ) -> None:
        if planning_start.tzinfo is None or planning_start.utcoffset() is None:
            raise ValueError("planning_start must be timezone-aware")
        self.scheduler = scheduler or StudyScheduler()
        self.planning_start = planning_start

    def schedule_tasks(
        self,
        assessments: Sequence[Assessment],
        tasks: Sequence[Task],
        calendar_blocks: Sequence[CalendarBlock],
        existing_schedule: Sequence[ScheduledTask] = (),
    ) -> SchedulingResult:
        """Schedule canonical tasks and report placements after deadlines."""

        del existing_schedule
        task_list = list(tasks)
        try:
            placements = self.scheduler.schedule(
                task_list,
                list(calendar_blocks),
                self.planning_start,
            )
        except ValueError as error:
            return SchedulingResult(
                unscheduled_tasks=[
                    UnscheduledTask(
                        task_id=task.id,
                        reason=SchedulingFailureReason.INVALID_INPUT,
                        message=str(error),
                    )
                    for task in task_list
                ]
            )

        return self._apply_deadlines(assessments, task_list, placements)

    def reschedule_tasks(
        self,
        assessments: Sequence[Assessment],
        tasks: Sequence[Task],
        calendar_blocks: Sequence[CalendarBlock],
        existing_schedule: Sequence[ScheduledTask],
        affected_task_ids: set[str],
    ) -> SchedulingResult:
        """Re-place affected incomplete tasks around preserved placements."""

        tasks_by_id = {task.id: task for task in tasks}
        unknown_ids = affected_task_ids - tasks_by_id.keys()
        if unknown_ids:
            unknown = ", ".join(sorted(unknown_ids))
            return SchedulingResult(
                unscheduled_tasks=[
                    UnscheduledTask(
                        task_id=task_id,
                        reason=SchedulingFailureReason.INVALID_INPUT,
                        message=f"affected task id is unknown: {task_id}",
                    )
                    for task_id in sorted(unknown_ids)
                ]
            )

        rescheduled_ids = {
            task_id
            for task_id in affected_task_ids
            if tasks_by_id[task_id].status is not TaskStatus.COMPLETED
        }
        preserved = [
            placement
            for placement in existing_schedule
            if placement.task_id not in rescheduled_ids
        ]
        if not rescheduled_ids:
            return SchedulingResult(scheduled_tasks=preserved)

        preserved_blocks = [
            CalendarBlock(
                id=f"preserved-{placement.id}",
                title=f"Preserved placement for {placement.task_id}",
                start_time=placement.start_time,
                end_time=placement.end_time,
                flexibility=Flexibility.HARD,
            )
            for placement in preserved
        ]
        affected_tasks = [
            task.model_copy(
                update={
                    "dependencies": [
                        dependency_id
                        for dependency_id in task.dependencies
                        if dependency_id in rescheduled_ids
                    ]
                }
            )
            for task in tasks
            if task.id in rescheduled_ids
        ]
        affected_result = self.schedule_tasks(
            assessments,
            affected_tasks,
            [*calendar_blocks, *preserved_blocks],
        )
        return SchedulingResult(
            scheduled_tasks=[*preserved, *affected_result.scheduled_tasks],
            unscheduled_tasks=affected_result.unscheduled_tasks,
        )

    @staticmethod
    def _apply_deadlines(
        assessments: Sequence[Assessment],
        tasks: Sequence[Task],
        placements: Sequence[ScheduledTask],
    ) -> SchedulingResult:
        assessments_by_id = {
            assessment.id: assessment for assessment in assessments
        }
        tasks_by_id = {task.id: task for task in tasks}
        scheduled: list[ScheduledTask] = []
        unscheduled: list[UnscheduledTask] = []
        unscheduled_task_ids: set[str] = set()

        for placement in placements:
            task = tasks_by_id[placement.task_id]
            assessment = assessments_by_id.get(task.assessment_id)
            if assessment is None:
                unscheduled.append(
                    UnscheduledTask(
                        task_id=task.id,
                        reason=SchedulingFailureReason.INVALID_INPUT,
                        message=(
                            f"Task references unknown assessment "
                            f"{task.assessment_id}."
                        ),
                    )
                )
                unscheduled_task_ids.add(task.id)
            elif any(
                dependency_id in unscheduled_task_ids
                for dependency_id in task.dependencies
            ):
                unscheduled.append(
                    UnscheduledTask(
                        task_id=task.id,
                        reason=SchedulingFailureReason.DEPENDENCY_CONFLICT,
                        message=(
                            "A prerequisite task could not be scheduled before "
                            "the assessment deadline."
                        ),
                    )
                )
                unscheduled_task_ids.add(task.id)
            elif placement.end_time > assessment.deadline:
                unscheduled.append(
                    UnscheduledTask(
                        task_id=task.id,
                        reason=SchedulingFailureReason.DEADLINE_CONSTRAINT,
                        message=(
                            "No scheduler placement finishes before the "
                            f"assessment deadline {assessment.deadline.isoformat()}."
                        ),
                    )
                )
                unscheduled_task_ids.add(task.id)
            else:
                scheduled.append(placement)

        return SchedulingResult(
            scheduled_tasks=scheduled,
            unscheduled_tasks=unscheduled,
        )
