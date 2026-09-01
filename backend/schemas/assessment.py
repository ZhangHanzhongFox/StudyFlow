"""Normalized academic assessment contract."""

from datetime import datetime
from enum import Enum

from pydantic import Field, ValidationInfo, field_validator, model_validator

from . import NonEmptyStr, StudyFlowBaseModel, require_timezone_aware


class AssessmentType(str, Enum):
    """Assessment categories supported by the MVP."""

    PRESENTATION = "presentation"
    EXAM = "exam"
    MIDTERM = "midterm"
    CODING_ASSIGNMENT = "coding_assignment"
    QUIZ = "quiz"


class Assessment(StudyFlowBaseModel):
    """An assessment normalized from Canvas or stable mock input."""

    id: NonEmptyStr
    course_code: NonEmptyStr
    title: NonEmptyStr
    description: str
    type: AssessmentType
    unlock_at: datetime | None
    deadline: datetime
    weightage: float | None = Field(ge=0)
    is_group: bool
    group_size: int | None

    @field_validator("unlock_at", "deadline")
    @classmethod
    def datetimes_must_be_timezone_aware(
        cls,
        value: datetime | None,
        info: ValidationInfo,
    ) -> datetime | None:
        if value is None:
            return None
        return require_timezone_aware(value, info.field_name)

    @model_validator(mode="after")
    def validate_assessment_constraints(self) -> "Assessment":
        if self.unlock_at is not None and self.deadline <= self.unlock_at:
            raise ValueError("deadline must be later than unlock_at")

        if self.is_group:
            if self.group_size is None or self.group_size <= 1:
                raise ValueError("group work requires group_size greater than one")
        elif self.group_size is not None:
            raise ValueError("group_size must be None when is_group is false")

        return self
