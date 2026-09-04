"""HTTP request wrappers; the five canonical domain models stay unchanged."""

from pydantic import model_validator

from . import StudyFlowBaseModel
from .calendar import CalendarBlock
from .assessment import Assessment
from .event import PlanningEvent, PlanningEventType


class CalendarChangeRequest(StudyFlowBaseModel):
    """Upsert one calendar block and observe the change in one transaction."""

    event: PlanningEvent
    calendar_block: CalendarBlock

    @model_validator(mode="after")
    def validate_event(self) -> "CalendarChangeRequest":
        if self.event.event_type is not PlanningEventType.CALENDAR_CHANGED:
            raise ValueError("event_type must be calendar_changed")
        if self.event.reference_id != self.calendar_block.id:
            raise ValueError("event.reference_id must equal calendar_block.id")
        return self


class AssessmentChangeRequest(StudyFlowBaseModel):
    event: PlanningEvent
    assessment: Assessment

    @model_validator(mode="after")
    def validate_event(self) -> "AssessmentChangeRequest":
        if self.event.event_type not in {
            PlanningEventType.NEW_ASSESSMENT, PlanningEventType.ASSESSMENT_UPDATED,
        }:
            raise ValueError("event_type must be new_assessment or assessment_updated")
        if self.event.reference_id != self.assessment.id:
            raise ValueError("event.reference_id must equal assessment.id")
        return self
