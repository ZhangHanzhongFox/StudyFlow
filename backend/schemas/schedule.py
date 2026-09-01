"""Concrete task placement contract."""

from datetime import datetime

from pydantic import model_validator

from . import NonEmptyStr, StudyFlowBaseModel, require_valid_time_range
from .calendar import Flexibility


class ScheduledTask(StudyFlowBaseModel):
    """A concrete placement of a task on the study schedule."""

    id: NonEmptyStr
    task_id: NonEmptyStr
    start_time: datetime
    end_time: datetime
    flexibility: Flexibility

    @model_validator(mode="after")
    def validate_time_range(self) -> "ScheduledTask":
        require_valid_time_range(self.start_time, self.end_time)
        return self
