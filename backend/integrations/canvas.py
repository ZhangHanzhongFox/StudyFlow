"""Normalize Canvas assignment payloads into canonical assessments."""

import json
import re
from collections.abc import Iterable
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.schemas import Assessment, AssessmentType


class CanvasNormalizationError(ValueError):
    """Raised when a Canvas record cannot safely cross the provider boundary."""


class CanvasStudyFlowMetadata(BaseModel):
    """Explicit mock metadata for facts not supplied by Canvas assignments."""

    model_config = ConfigDict(extra="forbid")

    assessment_id: str | None = None
    assessment_type: AssessmentType | None = None
    weightage: float | None = Field(default=None, ge=0)
    is_group: bool = False
    group_size: int | None = None


class CanvasAssignmentPayload(BaseModel):
    """Provider-facing subset of a Canvas assignment response."""

    model_config = ConfigDict(extra="ignore")

    id: int | str
    course_id: int | str
    course_code: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str | None = None
    due_at: datetime
    unlock_at: datetime | None = None
    points_possible: float | None = None
    quiz_id: int | str | None = None
    submission_types: list[str] = Field(default_factory=list)
    assignment_group_name: str | None = None
    group_category_id: int | str | None = None
    studyflow: CanvasStudyFlowMetadata = Field(
        default_factory=CanvasStudyFlowMetadata
    )


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.fragments: list[str] = []

    def handle_data(self, data: str) -> None:
        self.fragments.append(data)

    def text(self) -> str:
        return " ".join(" ".join(self.fragments).split())


def _plain_text(value: str | None) -> str:
    if not value:
        return ""
    extractor = _TextExtractor()
    extractor.feed(value)
    extractor.close()
    return extractor.text()


def _infer_assessment_type(payload: CanvasAssignmentPayload) -> AssessmentType:
    if payload.studyflow.assessment_type is not None:
        return payload.studyflow.assessment_type

    searchable = " ".join(
        filter(
            None,
            (
                payload.name,
                _plain_text(payload.description),
                payload.assignment_group_name,
            ),
        )
    ).lower()
    submission_types = {item.lower() for item in payload.submission_types}

    if re.search(r"\bmid[ -]?term\b", searchable):
        return AssessmentType.MIDTERM
    if payload.quiz_id is not None or "online_quiz" in submission_types:
        if re.search(r"\b(final|exam)\b", searchable):
            return AssessmentType.EXAM
        return AssessmentType.QUIZ
    if re.search(r"\b(presentation|pitch|slides?)\b", searchable):
        return AssessmentType.PRESENTATION
    if re.search(
        r"\b(code|coding|programming|implement|repository|software)\b",
        searchable,
    ):
        return AssessmentType.CODING_ASSIGNMENT
    raise CanvasNormalizationError(
        f"cannot infer assessment type for Canvas assignment {payload.id}; "
        "provide studyflow.assessment_type"
    )


def _normalize_one(record: dict[str, Any]) -> Assessment:
    payload = CanvasAssignmentPayload.model_validate(record)
    metadata = payload.studyflow
    is_group = metadata.is_group or payload.group_category_id is not None
    if is_group and metadata.group_size is None:
        raise CanvasNormalizationError(
            f"Canvas assignment {payload.id} is group work but group_size is missing"
        )

    assessment_id = metadata.assessment_id or (
        f"canvas-assessment-{payload.course_id}-{payload.id}"
    )
    return Assessment(
        id=assessment_id,
        course_code=payload.course_code,
        title=payload.name,
        description=_plain_text(payload.description),
        type=_infer_assessment_type(payload),
        unlock_at=payload.unlock_at,
        deadline=payload.due_at,
        weightage=metadata.weightage,
        is_group=is_group,
        group_size=metadata.group_size,
    )


def normalize_canvas_assignments(
    records: Iterable[dict[str, Any]],
) -> list[Assessment]:
    """Normalize Canvas records and reject duplicate canonical IDs."""

    assessments: list[Assessment] = []
    seen_ids: set[str] = set()
    for index, record in enumerate(records):
        try:
            assessment = _normalize_one(record)
        except (CanvasNormalizationError, ValidationError, TypeError) as error:
            raise CanvasNormalizationError(
                f"invalid Canvas assignment at index {index}: {error}"
            ) from error
        if assessment.id in seen_ids:
            raise CanvasNormalizationError(
                f"duplicate normalized assessment id: {assessment.id}"
            )
        seen_ids.add(assessment.id)
        assessments.append(assessment)
    return assessments


def load_canvas_assignments(path: str | Path) -> list[Assessment]:
    """Load a mock/recorded Canvas JSON array through the adapter."""

    source = Path(path)
    with source.open(encoding="utf-8") as payload_file:
        records = json.load(payload_file)
    if not isinstance(records, list):
        raise CanvasNormalizationError(f"{source} must contain a JSON array")
    return normalize_canvas_assignments(records)
