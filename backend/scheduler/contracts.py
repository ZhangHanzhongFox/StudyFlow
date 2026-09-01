"""Stable inputs and outputs for deterministic scheduling."""

from collections.abc import Sequence
from enum import Enum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from backend.schemas import Assessment, CalendarBlock, ScheduledTask, Task


class SchedulingFailureReason(str, Enum):
    """Machine-readable reasons why a task could not be placed."""

    NO_AVAILABLE_SLOT = "no_available_slot"
    DEADLINE_CONSTRAINT = "deadline_constraint"
    DEPENDENCY_CONFLICT = "dependency_conflict"
    INVALID_INPUT = "invalid_input"


class UnscheduledTask(BaseModel):
    """A task that the scheduler could not place, with an explicit reason."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    task_id: str = Field(min_length=1)
    reason: SchedulingFailureReason
    message: str = Field(min_length=1)


class SchedulingResult(BaseModel):
    """Operational scheduler result wrapping canonical schedule records.

    This is a service response, not a sixth persisted domain model.
    """

    model_config = ConfigDict(extra="forbid")

    scheduled_tasks: list[ScheduledTask] = Field(default_factory=list)
    unscheduled_tasks: list[UnscheduledTask] = Field(default_factory=list)


class Scheduler(Protocol):
    """Contract implemented by the Scheduling / Calendar workstream."""

    def schedule_tasks(
        self,
        assessments: Sequence[Assessment],
        tasks: Sequence[Task],
        calendar_blocks: Sequence[CalendarBlock],
        existing_schedule: Sequence[ScheduledTask] = (),
    ) -> SchedulingResult:
        """Place tasks while respecting dependencies, deadlines, and blocks."""

        ...

    def reschedule_tasks(
        self,
        assessments: Sequence[Assessment],
        tasks: Sequence[Task],
        calendar_blocks: Sequence[CalendarBlock],
        existing_schedule: Sequence[ScheduledTask],
        affected_task_ids: set[str],
    ) -> SchedulingResult:
        """Re-place affected tasks while preserving valid unaffected work."""

        ...
