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
    scheduled_task_ids: set[str] = set()
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
        if placement.task_id in scheduled_task_ids:
            raise PlanningStateValidationError(
                f"task {placement.task_id} has multiple scheduled placements"
            )
        scheduled_task_ids.add(placement.task_id)

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

    @staticmethod
    def _validate_replanning_result(
        tasks: Iterable[Task],
        result: "SchedulingResult",
    ) -> None:
        """Reject incomplete or contradictory scheduler output before commit."""

        task_list = list(tasks)
        task_ids = {task.id for task in task_list}
        completed_ids = {
            task.id for task in task_list if task.status is TaskStatus.COMPLETED
        }
        scheduled_ids = {item.task_id for item in result.scheduled_tasks}
        failure_ids = [item.task_id for item in result.unscheduled_tasks]
        failure_id_set = set(failure_ids)
        if (not failure_id_set <= task_ids
                or failure_id_set & scheduled_ids
                or failure_id_set & completed_ids
                or len(failure_ids) != len(failure_id_set)):
            raise PlanningStateValidationError(
                "invalid unscheduled task references"
            )
        omitted_ids = task_ids - completed_ids - scheduled_ids - failure_id_set
        if omitted_ids:
            raise PlanningStateValidationError(
                "scheduler result omitted active tasks: "
                + ", ".join(sorted(omitted_ids))
            )

    def add_planning_event(self, event: PlanningEvent) -> PlanningEvent:
        with self._lock:
            self.validate_planning_event(event)
            self._require_task_or_calendar_event(event)
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
            self._validate_replanning_result(tasks, result)
            tasks = self._apply_schedule_status(tasks, result.scheduled_tasks)
            validate_planning_state(
                self._assessments, tasks, blocks,
                result.scheduled_tasks, [*self._planning_events, event],
            )
            self._tasks = self._copies(tasks)
            self._calendar_blocks = self._copies(blocks)
            self._scheduled_tasks = self._copies(result.scheduled_tasks)
            self._planning_events.append(event.model_copy(deep=True))
            return result

    @staticmethod
    def _require_task_or_calendar_event(event: PlanningEvent) -> None:
        if event.event_type in {PlanningEventType.NEW_ASSESSMENT,
                                PlanningEventType.ASSESSMENT_UPDATED}:
            raise ValueError("assessment events require /assessment-changes with an assessment payload")

    def change_assessment(self, event: PlanningEvent, assessment: Assessment,
                          pipeline: "PlanningPipeline") -> "SchedulingResult":
        from .assessment_changes import AssessmentConflictError, reconcile
        with self._lock:
            if any(e.id == event.id for e in self._planning_events):
                raise DuplicatePlanningEventError(f"planning event id already exists: {event.id}")
            previous = next((a for a in self._assessments if a.id == assessment.id), None)
            if event.event_type is PlanningEventType.NEW_ASSESSMENT and previous:
                raise AssessmentConflictError("assessment id already exists")
            if event.event_type is PlanningEventType.ASSESSMENT_UPDATED and previous is None:
                raise UnknownPlanningEventReferenceError("assessment id does not exist")
            requirement_fields = ("title", "description", "type", "course_code", "is_group", "group_size")
            if previous is None or any(getattr(previous, f) != getattr(assessment, f)
                                       for f in requirement_fields):
                try:
                    assessment = Assessment.model_validate({**assessment.model_dump(),
                        "type": pipeline.agent.classify_assessment(assessment.model_copy(deep=True))})
                except ValueError as error:
                    raise PlanningStateValidationError("invalid assessment classification") from error
            assessments = [a for a in self.list_assessments() if a.id != assessment.id]
            assessments.append(assessment.model_copy(deep=True))
            tasks = reconcile(assessment, previous, self.list_tasks(),
                              self.list_scheduled_tasks(), self.list_planning_events(), event, pipeline)
            ids = {t.id for t in tasks}
            schedule = [s for s in self.list_scheduled_tasks() if s.task_id in ids]
            events = [*self.list_planning_events(), event.model_copy(deep=True)]
            validate_planning_state(assessments, tasks, self._calendar_blocks, schedule, events)
            affected = pipeline.agent.find_affected_task_ids(event.model_copy(deep=True), self._copies(tasks))
            # Include previously unplaced work so partial successes never silently disappear.
            affected |= {t.id for t in tasks if t.status is not TaskStatus.COMPLETED
                         and t.id not in {s.task_id for s in schedule}}
            result = pipeline.scheduler.reschedule_tasks(
                self._copies(assessments), self._copies(tasks), self.list_calendar_blocks(),
                self._copies(schedule), affected, replanning_start=event.timestamp,
                preserve_valid_affected=True,
            )
            from backend.schemas import Flexibility
            completed = {t.id for t in tasks if t.status is TaskStatus.COMPLETED}
            for placement in schedule:
                if (placement.task_id in completed or placement.flexibility is Flexibility.HARD):
                    if placement not in result.scheduled_tasks:
                        raise PlanningStateValidationError("scheduler changed protected history")
            self._validate_replanning_result(tasks, result)
            tasks = self._apply_schedule_status(tasks, result.scheduled_tasks)
            self.reset(assessments, tasks, self._calendar_blocks, result.scheduled_tasks, events)
            return result

    def generate_plan(self, pipeline: "PlanningPipeline") -> "SchedulingResult":
        with self._lock:
            run = pipeline.run_plan(self.list_assessments(), self.list_calendar_blocks(),
                                    self.list_scheduled_tasks())
            validate_planning_state(run.assessments, run.tasks, self._calendar_blocks,
                                    run.result.scheduled_tasks, self._planning_events)
            self._validate_replanning_result(run.tasks, run.result)
            self.replace_plan(run.assessments, run.tasks, run.result.scheduled_tasks)
            return run.result

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
