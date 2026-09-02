"""Canonical shared data contracts for StudyFlow.

All backend modules, integrations, fixtures, and API routes should import the
shared models from this package instead of defining local variants.
"""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class StudyFlowBaseModel(BaseModel):
    """Common strictness shared by the canonical contracts."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def require_timezone_aware(value: datetime, field_name: str) -> datetime:
    """Reject datetimes that do not identify an absolute point in time."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def require_valid_time_range(
    start_time: datetime,
    end_time: datetime,
) -> tuple[datetime, datetime]:
    """Validate a canonical start/end time range."""

    require_timezone_aware(start_time, "start_time")
    require_timezone_aware(end_time, "end_time")
    if end_time <= start_time:
        raise ValueError("end_time must be later than start_time")
    return start_time, end_time


from .assessment import Assessment, AssessmentType
from .calendar import CalendarBlock, Flexibility
from .event import PlanningEvent, PlanningEventType
from .schedule import ScheduledTask
from .task import Task, TaskStatus, validate_task_graph
from .requests import CalendarChangeRequest

__all__ = [
    "Assessment",
    "AssessmentType",
    "CalendarBlock",
    "CalendarChangeRequest",
    "Flexibility",
    "PlanningEvent",
    "PlanningEventType",
    "ScheduledTask",
    "Task",
    "TaskStatus",
    "validate_task_graph",
]
