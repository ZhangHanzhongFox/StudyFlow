"""Validated access to the canonical shared mock scenario."""

import json
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from backend.schemas import (
    Assessment,
    CalendarBlock,
    PlanningEvent,
    PlanningEventType,
    ScheduledTask,
    Task,
    validate_task_graph,
)

ModelT = TypeVar("ModelT", bound=BaseModel)
DEFAULT_MOCK_DATA_DIR = Path(__file__).parents[2] / "data" / "mock"


class DuplicatePlanningEventError(ValueError):
    """Raised when an event would overwrite an existing stable ID."""


class UnknownPlanningEventReferenceError(ValueError):
    """Raised when an event points outside the current planning state."""


class MockDataStore:
    """Load canonical fixture files and keep posted events in memory."""

    def __init__(self, data_dir: Path = DEFAULT_MOCK_DATA_DIR) -> None:
        self.data_dir = data_dir
        self._assessments = self._load("assessments.json", Assessment)
        self._tasks = self._load("tasks.json", Task)
        self._calendar_blocks = self._load("calendar_blocks.json", CalendarBlock)
        self._scheduled_tasks = self._load("scheduled_tasks.json", ScheduledTask)
        self._planning_events = self._load("planning_events.json", PlanningEvent)
        validate_task_graph(self._tasks)

    def _load(self, filename: str, model: type[ModelT]) -> list[ModelT]:
        path = self.data_dir / filename
        with path.open(encoding="utf-8") as fixture_file:
            records: Any = json.load(fixture_file)
        if not isinstance(records, list):
            raise ValueError(f"{path} must contain a JSON array")
        return [model.model_validate(record) for record in records]

    def list_assessments(self) -> list[Assessment]:
        return list(self._assessments)

    def list_tasks(self) -> list[Task]:
        return list(self._tasks)

    def list_calendar_blocks(self) -> list[CalendarBlock]:
        return list(self._calendar_blocks)

    def list_scheduled_tasks(self) -> list[ScheduledTask]:
        return list(self._scheduled_tasks)

    def list_planning_events(self) -> list[PlanningEvent]:
        return list(self._planning_events)

    def add_planning_event(self, event: PlanningEvent) -> PlanningEvent:
        if any(existing.id == event.id for existing in self._planning_events):
            raise DuplicatePlanningEventError(
                f"planning event id already exists: {event.id}"
            )

        reference_ids_by_type = {
            PlanningEventType.TASK_COMPLETED: {task.id for task in self._tasks},
            PlanningEventType.TASK_MISSED: {task.id for task in self._tasks},
            PlanningEventType.NEW_ASSESSMENT: {
                assessment.id for assessment in self._assessments
            },
            PlanningEventType.ASSESSMENT_UPDATED: {
                assessment.id for assessment in self._assessments
            },
            PlanningEventType.CALENDAR_CHANGED: {
                block.id for block in self._calendar_blocks
            },
        }
        if event.reference_id not in reference_ids_by_type[event.event_type]:
            raise UnknownPlanningEventReferenceError(
                f"{event.event_type.value} references unknown id: {event.reference_id}"
            )

        self._planning_events.append(event)
        return event
