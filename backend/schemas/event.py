"""Planning-state observation contract."""

from datetime import datetime
from enum import Enum

from pydantic import field_validator

from . import NonEmptyStr, StudyFlowBaseModel, require_timezone_aware


class PlanningEventType(str, Enum):
    """Observed changes that may trigger a planning-state update."""

    TASK_COMPLETED = "task_completed"
    TASK_MISSED = "task_missed"
    NEW_ASSESSMENT = "new_assessment"
    ASSESSMENT_UPDATED = "assessment_updated"
    CALENDAR_CHANGED = "calendar_changed"


class PlanningEvent(StudyFlowBaseModel):
    """An observation that may trigger replanning."""

    id: NonEmptyStr
    event_type: PlanningEventType
    timestamp: datetime
    reference_id: NonEmptyStr

    @field_validator("timestamp")
    @classmethod
    def timestamp_must_be_timezone_aware(cls, value: datetime) -> datetime:
        return require_timezone_aware(value, "timestamp")
