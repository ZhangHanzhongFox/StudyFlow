"""Validated access to the canonical shared mock scenario."""

import json
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from backend.schemas import (
    Assessment,
    CalendarBlock,
    PlanningEvent,
    ScheduledTask,
    Task,
)
from backend.integrations import (
    load_canvas_assignments,
    load_google_calendar_events,
)
from .state import PlanningState

ModelT = TypeVar("ModelT", bound=BaseModel)
DEFAULT_MOCK_DATA_DIR = Path(__file__).parents[2] / "data" / "mock"
DEFAULT_PROVIDER_DATA_DIR = Path(__file__).parents[2] / "data" / "providers"


class MockDataStore(PlanningState):
    """Load canonical fixture files and keep posted events in memory."""

    def __init__(
        self,
        data_dir: Path = DEFAULT_MOCK_DATA_DIR,
        canvas_payload_path: Path | None = None,
        calendar_payload_path: Path | None = None,
        include_baseline_plan: bool = True,
    ) -> None:
        self.data_dir = data_dir
        assessments = (
            load_canvas_assignments(canvas_payload_path)
            if canvas_payload_path is not None
            else self._load("assessments.json", Assessment)
        )
        calendar_blocks = (
            load_google_calendar_events(calendar_payload_path)
            if calendar_payload_path is not None
            else self._load("calendar_blocks.json", CalendarBlock)
        )
        super().__init__(
            assessments=assessments,
            tasks=(
                self._load("tasks.json", Task) if include_baseline_plan else []
            ),
            calendar_blocks=calendar_blocks,
            scheduled_tasks=(
                self._load("scheduled_tasks.json", ScheduledTask)
                if include_baseline_plan
                else []
            ),
            planning_events=(
                self._load("planning_events.json", PlanningEvent)
                if include_baseline_plan
                else []
            ),
        )

    @classmethod
    def from_provider_fixtures(
        cls,
        data_dir: Path = DEFAULT_MOCK_DATA_DIR,
        provider_data_dir: Path = DEFAULT_PROVIDER_DATA_DIR,
    ) -> "MockDataStore":
        """Build the demo state through the provider normalization boundary."""

        return cls(
            data_dir=data_dir,
            canvas_payload_path=provider_data_dir
            / "mock_canvas_assignments.json",
            calendar_payload_path=provider_data_dir
            / "mock_google_calendar_events.json",
        )

    @classmethod
    def for_dynamic_provider_demo(
        cls,
        data_dir: Path = DEFAULT_MOCK_DATA_DIR,
        provider_data_dir: Path = DEFAULT_PROVIDER_DATA_DIR,
    ) -> "MockDataStore":
        """Load provider inputs without seeding precomputed plan outputs."""

        return cls(
            data_dir=data_dir,
            canvas_payload_path=provider_data_dir
            / "mock_canvas_assignments.json",
            calendar_payload_path=provider_data_dir
            / "mock_google_calendar_events.json",
            include_baseline_plan=False,
        )

    def _load(self, filename: str, model: type[ModelT]) -> list[ModelT]:
        path = self.data_dir / filename
        with path.open(encoding="utf-8") as fixture_file:
            records: Any = json.load(fixture_file)
        if not isinstance(records, list):
            raise ValueError(f"{path} must contain a JSON array")
        return [model.model_validate(record) for record in records]
