"""Normalize Google Calendar-style events into canonical calendar blocks."""

import json
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.schemas import CalendarBlock, Flexibility


class CalendarNormalizationError(ValueError):
    """Raised when a calendar event cannot be normalized safely."""


class GoogleCalendarTime(BaseModel):
    model_config = ConfigDict(extra="ignore")

    dateTime: datetime | None = None
    date: str | None = None
    timeZone: str | None = None


class GoogleCalendarEventPayload(BaseModel):
    """Provider-facing subset of a Google Calendar event response."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    start: GoogleCalendarTime
    end: GoogleCalendarTime
    transparency: str = "opaque"
    extendedProperties: dict[str, dict[str, str]] = Field(default_factory=dict)


def _private_metadata(payload: GoogleCalendarEventPayload) -> dict[str, str]:
    return payload.extendedProperties.get("private", {})


def _normalize_one(record: dict[str, Any]) -> CalendarBlock:
    payload = GoogleCalendarEventPayload.model_validate(record)
    if payload.start.dateTime is None or payload.end.dateTime is None:
        raise CalendarNormalizationError(
            f"all-day calendar event {payload.id} is not supported by the MVP"
        )

    private = _private_metadata(payload)
    block_id = private.get("studyflow_id") or f"google-calendar-{payload.id}"
    flexibility_value = private.get("studyflow_flexibility")
    if flexibility_value is None:
        flexibility_value = (
            Flexibility.FLEXIBLE.value
            if payload.transparency == "transparent"
            else Flexibility.HARD.value
        )

    return CalendarBlock(
        id=block_id,
        title=payload.summary,
        start_time=payload.start.dateTime,
        end_time=payload.end.dateTime,
        flexibility=Flexibility(flexibility_value),
    )


def normalize_google_calendar_events(
    records: Iterable[dict[str, Any]],
) -> list[CalendarBlock]:
    """Normalize Google Calendar records and reject duplicate IDs."""

    blocks: list[CalendarBlock] = []
    seen_ids: set[str] = set()
    for index, record in enumerate(records):
        try:
            block = _normalize_one(record)
        except (
            CalendarNormalizationError,
            ValidationError,
            TypeError,
            ValueError,
        ) as error:
            raise CalendarNormalizationError(
                f"invalid calendar event at index {index}: {error}"
            ) from error
        if block.id in seen_ids:
            raise CalendarNormalizationError(
                f"duplicate normalized calendar block id: {block.id}"
            )
        seen_ids.add(block.id)
        blocks.append(block)
    return blocks


def load_google_calendar_events(path: str | Path) -> list[CalendarBlock]:
    """Load a mock/recorded Google Calendar JSON array through the adapter."""

    source = Path(path)
    with source.open(encoding="utf-8") as payload_file:
        records = json.load(payload_file)
    if not isinstance(records, list):
        raise CalendarNormalizationError(f"{source} must contain a JSON array")
    return normalize_google_calendar_events(records)
