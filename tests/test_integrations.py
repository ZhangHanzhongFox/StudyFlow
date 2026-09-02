"""Provider-boundary tests for Canvas and Google Calendar mocks."""

from pathlib import Path

import pytest

from backend.integrations import (
    CalendarNormalizationError,
    CanvasNormalizationError,
    load_canvas_assignments,
    load_google_calendar_events,
    normalize_canvas_assignments,
    normalize_google_calendar_events,
)
from backend.schemas import AssessmentType, Flexibility
from backend.services import MockDataStore

PROVIDER_DIR = Path(__file__).parents[1] / "data" / "providers"


def test_provider_fixtures_normalize_to_shared_canonical_scenario() -> None:
    canonical = MockDataStore()
    provider_backed = MockDataStore.from_provider_fixtures()

    assert provider_backed.list_assessments() == canonical.list_assessments()
    assert (
        provider_backed.list_calendar_blocks()
        == canonical.list_calendar_blocks()
    )
    assert provider_backed.list_tasks() == canonical.list_tasks()
    assert (
        provider_backed.list_scheduled_tasks()
        == canonical.list_scheduled_tasks()
    )


def test_canvas_loader_covers_all_required_mvp_types() -> None:
    assessments = load_canvas_assignments(
        PROVIDER_DIR / "mock_canvas_assignments.json"
    )

    assert {assessment.type for assessment in assessments} == {
        AssessmentType.PRESENTATION,
        AssessmentType.MIDTERM,
        AssessmentType.CODING_ASSIGNMENT,
    }
    assert "Q&A" in assessments[0].description


@pytest.mark.parametrize(
    ("name", "extra", "expected_type"),
    [
        ("Final Exam", {"quiz_id": 20}, AssessmentType.EXAM),
        ("Week 4 Quiz", {"quiz_id": 21}, AssessmentType.QUIZ),
        ("Product Pitch", {}, AssessmentType.PRESENTATION),
        ("Implement API", {}, AssessmentType.CODING_ASSIGNMENT),
    ],
)
def test_canvas_type_inference_is_deterministic(
    name: str,
    extra: dict,
    expected_type: AssessmentType,
) -> None:
    payload = {
        "id": name,
        "course_id": 1,
        "course_code": "CS1000",
        "name": name,
        "description": "Assessment instructions",
        "due_at": "2026-09-12T16:00:00+08:00",
        **extra,
    }

    assert normalize_canvas_assignments([payload])[0].type is expected_type


def test_canvas_rejects_ambiguous_type_instead_of_inventing_one() -> None:
    with pytest.raises(CanvasNormalizationError, match="cannot infer"):
        normalize_canvas_assignments(
            [
                {
                    "id": 1,
                    "course_id": 1,
                    "course_code": "CS1000",
                    "name": "Coursework",
                    "due_at": "2026-09-12T16:00:00+08:00",
                }
            ]
        )


def test_canvas_rejects_duplicate_stable_ids() -> None:
    record = {
        "id": 1,
        "course_id": 1,
        "course_code": "CS1000",
        "name": "Coding assignment",
        "due_at": "2026-09-12T16:00:00+08:00",
        "studyflow": {"assessment_id": "assessment-one"},
    }
    with pytest.raises(CanvasNormalizationError, match="duplicate"):
        normalize_canvas_assignments([record, record])


def test_calendar_loader_preserves_explicit_flexibility() -> None:
    blocks = load_google_calendar_events(
        PROVIDER_DIR / "mock_google_calendar_events.json"
    )

    assert len(blocks) == 8
    assert {block.flexibility for block in blocks} == {
        Flexibility.HARD,
        Flexibility.SOFT,
    }


def test_transparent_calendar_event_defaults_to_flexible() -> None:
    block = normalize_google_calendar_events(
        [
            {
                "id": "focus",
                "summary": "Optional focus block",
                "start": {"dateTime": "2026-09-03T08:00:00+08:00"},
                "end": {"dateTime": "2026-09-03T09:00:00+08:00"},
                "transparency": "transparent",
            }
        ]
    )[0]

    assert block.flexibility is Flexibility.FLEXIBLE


def test_calendar_rejects_all_day_events_until_semantics_are_defined() -> None:
    with pytest.raises(CalendarNormalizationError, match="all-day"):
        normalize_google_calendar_events(
            [
                {
                    "id": "holiday",
                    "summary": "Holiday",
                    "start": {"date": "2026-09-03"},
                    "end": {"date": "2026-09-04"},
                }
            ]
        )
