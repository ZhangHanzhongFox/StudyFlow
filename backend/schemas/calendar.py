"""Existing calendar commitment contract."""

from datetime import datetime
from enum import Enum

from pydantic import model_validator

from . import NonEmptyStr, StudyFlowBaseModel, require_valid_time_range


class Flexibility(str, Enum):
    """How freely a calendar item may move during planning."""

    HARD = "hard"
    SOFT = "soft"
    FLEXIBLE = "flexible"


class CalendarBlock(StudyFlowBaseModel):
    """An existing commitment or unavailable time window."""

    id: NonEmptyStr
    title: NonEmptyStr
    start_time: datetime
    end_time: datetime
    flexibility: Flexibility

    @model_validator(mode="after")
    def validate_time_range(self) -> "CalendarBlock":
        require_valid_time_range(self.start_time, self.end_time)
        return self
