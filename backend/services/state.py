"""Validated, process-local planning state for the hackathon MVP."""

from collections.abc import Iterable
from threading import RLock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.scheduler import SchedulingResult
    from .planning import PlanningPipeline

from backend.schemas import (
    Assessment,
    CalendarBlock,
    PlanningEvent,
    PlanningEventType,
    ScheduledTask,
    Task,
    TaskStatus,
    validate_task_graph,
)


class PlanningStateValidationError(ValueError):
    """Raised before invalid references enter the planning state."""


class DuplicatePlanningEventError(ValueError):
    """Raised when an event would overwrite an existing stable ID."""


class UnknownPlanningEventReferenceError(PlanningStateValidationError):
    """Raised when an event points outside the current planning state."""


def _unique_by_id(records: Iterable[object], label: str) -> dict[str, object]:
    indexed: dict[str, object] = {}
    for record in records:
        record_id = getattr(record, "id")
        if record_id in indexed:
            raise PlanningStateValidationError(f"duplicate {label} id: {record_id}")
        indexed[record_id] = record
    return indexed


def validate_planning_state(
    assessments: Iterable[Assessment],
    tasks: Iterable[Task],
    calendar_blocks: Iterable[CalendarBlock],
    scheduled_tasks: Iterable[ScheduledTask],
    planning_events: Iterable[PlanningEvent] = (),
) -> None:
    """Validate IDs and cross-collection references atomically."""

    assessment_list = list(assessments)
    task_list = list(tasks)
    block_list = list(calendar_blocks)
    schedule_list = list(scheduled_tasks)
    event_list = list(planning_events)
    assessments_by_id = _unique_by_id(assessment_list, "assessment")
    tasks_by_id = _unique_by_id(task_list, "task")
    blocks_by_id = _unique_by_id(block_list, "calendar block")
    _unique_by_id(schedule_list, "scheduled task")
    _unique_by_id(event_list, "planning event")
    for task in task_list:
        if task.assessment_id not in assessments_by_id:
            raise PlanningStateValidationError(
                f"task {task.id} references unknown assessment {task.assessment_id}"
            )
    try:
        validate_task_graph(task_list)
    except ValueError as error:
        raise PlanningStateValidationError(str(error)) from error
    for placement in schedule_list:
        if placement.task_id not in tasks_by_id:
            raise PlanningStateValidationError(
                f"scheduled task {placement.id} references unknown task "
                f"{placement.task_id}"
            )

    reference_ids_by_type = {
        PlanningEventType.TASK_COMPLETED: set(tasks_by_id),
        PlanningEventType.TASK_MISSED: set(tasks_by_id),
        PlanningEventType.NEW_ASSESSMENT: set(assessments_by_id),
        PlanningEventType.ASSESSMENT_UPDATED: set(assessments_by_id),
        PlanningEventType.CALENDAR_CHANGED: set(blocks_by_id),
    }
    for event in event_list:
        if event.reference_id not in reference_ids_by_type[event.event_type]:
            raise UnknownPlanningEventReferenceError(
                f"{event.event_type.value} references unknown id: "
                f"{event.reference_id}"
            )


class PlanningState:
    """Thread-safe in-memory state with validated atomic replacements."""

    def __init__(
        self,
        assessments: Iterable[Assessment] = (),
        tasks: Iterable[Task] = (),
        calendar_blocks: Iterable[CalendarBlock] = (),
        scheduled_tasks: Iterable[ScheduledTask] = (),
        planning_events: Iterable[PlanningEvent] = (),
    ) -> None:
        self._lock = RLock()
        self.reset(
            assessments,
            tasks,
            calendar_blocks,
            scheduled_tasks,
            planning_events,
        )

    @staticmethod
    def _copies(records: Iterable[object]) -> list:
        return [record.model_copy(deep=True) for record in records]

    def reset(
        self,
        assessments: Iterable[Assessment],
        tasks: Iterable[Task],
        calendar_blocks: Iterable[CalendarBlock],
        scheduled_tasks: Iterable[ScheduledTask],
        planning_events: Iterable[PlanningEvent] = (),
    ) -> None:
        assessment_list = list(assessments)
        task_list = list(tasks)
        block_list = list(calendar_blocks)
        schedule_list = list(scheduled_tasks)
        event_list = list(planning_events)
        validate_planning_state(
            assessment_list,
            task_list,
            block_list,
            schedule_list,
            event_list,
        )
        with self._lock:
            self._assessments = self._copies(assessment_list)
            self._tasks = self._copies(task_list)
            self._calendar_blocks = self._copies(block_list)
            self._scheduled_tasks = self._copies(schedule_list)
            self._planning_events = self._copies(event_list)

    def list_assessments(self) -> list[Assessment]:
        with self._lock:
            return self._copies(self._assessments)

    def list_tasks(self) -> list[Task]:
        with self._lock:
            return self._copies(self._tasks)

    def list_calendar_blocks(self) -> list[CalendarBlock]:
        with self._lock:
            return self._copies(self._calendar_blocks)

    def list_scheduled_tasks(self) -> list[ScheduledTask]:
        with self._lock:
            return self._copies(self._scheduled_tasks)

    def list_planning_events(self) -> list[PlanningEvent]:
        with self._lock:
            return self._copies(self._planning_events)

    @staticmethod
    def _apply_task_event(
        tasks: Iterable[Task],
        event: PlanningEvent,
    ) -> list[Task]:
        status_by_event = {
            PlanningEventType.TASK_COMPLETED: TaskStatus.COMPLETED,
            PlanningEventType.TASK_MISSED: TaskStatus.MISSED,
        }
        tasks = list(tasks)
        updated_status = status_by_event.get(event.event_type)
        if updated_status is TaskStatus.MISSED and any(
            task.id == event.reference_id and task.status is TaskStatus.COMPLETED
            for task in tasks
        ):
            raise ValueError("a completed task cannot be marked missed")
        return [
            task.model_copy(update={"status": updated_status})
            if updated_status is not None and task.id == event.reference_id
            else task.model_copy(deep=True)
            for task in tasks
        ]

    @staticmethod
    def _apply_schedule_status(
        tasks: Iterable[Task],
        scheduled_tasks: Iterable[ScheduledTask],
    ) -> list[Task]:
        scheduled_task_ids = {
            placement.task_id for placement in scheduled_tasks
        }
        return [
            task.model_copy(update={"status": TaskStatus.SCHEDULED})
            if task.id in scheduled_task_ids
            and task.status in {TaskStatus.PENDING, TaskStatus.MISSED}
            else task.model_copy(update={"status": TaskStatus.PENDING})
            if task.id not in scheduled_task_ids and task.status is TaskStatus.SCHEDULED
            else task.model_copy(deep=True)
            for task in tasks
        ]

    def add_planning_event(self, event: PlanningEvent) -> PlanningEvent:
        with self._lock:
            self.validate_planning_event(event)
            stored = event.model_copy(deep=True)
            self._tasks = self._apply_task_event(self._tasks, stored)
            self._planning_events.append(stored)
            return stored.model_copy(deep=True)

    def replan(
        self,
        event: PlanningEvent,
        pipeline: "PlanningPipeline",
        calendar_block: CalendarBlock | None = None,
    ) -> "SchedulingResult":
        """Stage an observation, run planning, and commit all state together.

        Serialize read/compute/commit so simultaneous observations cannot plan
        against an obsolete snapshot. Exceptions leave the live state intact;
        explicit unscheduled tasks are normal results and are committed.
        """

        with self._lock:
            if any(item.id == event.id for item in self._planning_events):
                raise DuplicatePlanningEventError(
                    f"planning event id already exists: {event.id}"
                )
            blocks = self.list_calendar_blocks()
            if calendar_block is not None:
                if (event.event_type is not PlanningEventType.CALENDAR_CHANGED
                        or event.reference_id != calendar_block.id):
                    raise ValueError("calendar change event must reference its block")
                blocks = [item for item in blocks if item.id != calendar_block.id]
                blocks.append(calendar_block.model_copy(deep=True))
            validate_planning_state(
                self._assessments, self._tasks, blocks,
                self._scheduled_tasks, [*self._planning_events, event],
            )
            tasks = self._apply_task_event(self._tasks, event)
            result = pipeline.replan(
                event.model_copy(deep=True), self.list_assessments(), tasks,
                blocks, self.list_scheduled_tasks(),
            )
            tasks = self._apply_schedule_status(tasks, result.scheduled_tasks)
            validate_planning_state(
                self._assessments, tasks, blocks,
                result.scheduled_tasks, [*self._planning_events, event],
            )
            task_ids = {task.id for task in tasks}
            scheduled_ids = {item.task_id for item in result.scheduled_tasks}
            failure_ids = [item.task_id for item in result.unscheduled_tasks]
            if (not set(failure_ids) <= task_ids
                    or set(failure_ids) & scheduled_ids
                    or len(failure_ids) != len(set(failure_ids))):
                raise PlanningStateValidationError("invalid unscheduled task references")
            self._tasks = self._copies(tasks)
            self._calendar_blocks = self._copies(blocks)
            self._scheduled_tasks = self._copies(result.scheduled_tasks)
            self._planning_events.append(event.model_copy(deep=True))
            return result

    def validate_planning_event(self, event: PlanningEvent) -> None:
        """Check an event without mutating state, for transactional workflows."""

        with self._lock:
            if any(existing.id == event.id for existing in self._planning_events):
                raise DuplicatePlanningEventError(
                    f"planning event id already exists: {event.id}"
                )
            validate_planning_state(
                self._assessments,
                self._tasks,
                self._calendar_blocks,
                self._scheduled_tasks,
                [*self._planning_events, event],
            )

    def replace_plan(
        self,
        assessments: Iterable[Assessment],
        tasks: Iterable[Task],
        scheduled_tasks: Iterable[ScheduledTask],
    ) -> None:
        assessment_list = list(assessments)
        task_list = list(tasks)
        schedule_list = list(scheduled_tasks)
        task_list = self._apply_schedule_status(task_list, schedule_list)
        with self._lock:
            validate_planning_state(
                assessment_list,
                task_list,
                self._calendar_blocks,
                schedule_list,
                self._planning_events,
            )
            self._assessments = self._copies(assessment_list)
            self._tasks = self._copies(task_list)
            self._scheduled_tasks = self._copies(schedule_list)

    def replace_schedule(
        self,
        scheduled_tasks: Iterable[ScheduledTask],
    ) -> None:
        self.replace_plan(
            self.list_assessments(),
            self.list_tasks(),
            scheduled_tasks,
        )

    def replace_schedule_and_add_event(
        self,
        scheduled_tasks: Iterable[ScheduledTask],
        event: PlanningEvent,
    ) -> PlanningEvent:
        """Atomically commit a replan result and its triggering event."""

        schedule_list = list(scheduled_tasks)
        with self._lock:
            if any(existing.id == event.id for existing in self._planning_events):
                raise DuplicatePlanningEventError(
                    f"planning event id already exists: {event.id}"
                )
            updated_tasks = self._apply_task_event(self._tasks, event)
            updated_tasks = self._apply_schedule_status(
                updated_tasks,
                schedule_list,
            )
            validate_planning_state(
                self._assessments,
                updated_tasks,
                self._calendar_blocks,
                schedule_list,
                [*self._planning_events, event],
            )
            stored = event.model_copy(deep=True)
            self._tasks = self._copies(updated_tasks)
            self._scheduled_tasks = self._copies(schedule_list)
            self._planning_events.append(stored)
            return stored.model_copy(deep=True)
