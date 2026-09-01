"""Integrity tests for the canonical shared mock scenario."""

import json
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, TypeVar

from backend.schemas import (
    Assessment,
    AssessmentType,
    CalendarBlock,
    PlanningEvent,
    PlanningEventType,
    ScheduledTask,
    Task,
    validate_task_graph,
)

MOCK_DATA_DIR = Path(__file__).parents[1] / "data" / "mock"
ModelT = TypeVar("ModelT")


def load_models(filename: str, validator: Callable[[Any], ModelT]) -> list[ModelT]:
    with (MOCK_DATA_DIR / filename).open(encoding="utf-8") as fixture_file:
        records = json.load(fixture_file)
    assert isinstance(records, list)
    return [validator(record) for record in records]


def load_scenario() -> tuple[
    list[Assessment],
    list[Task],
    list[CalendarBlock],
    list[ScheduledTask],
    list[PlanningEvent],
]:
    return (
        load_models("assessments.json", Assessment.model_validate),
        load_models("tasks.json", Task.model_validate),
        load_models("calendar_blocks.json", CalendarBlock.model_validate),
        load_models("scheduled_tasks.json", ScheduledTask.model_validate),
        load_models("planning_events.json", PlanningEvent.model_validate),
    )


def overlaps(
    first_start: datetime,
    first_end: datetime,
    second_start: datetime,
    second_end: datetime,
) -> bool:
    return first_start < second_end and second_start < first_end


def test_all_mock_records_validate_against_canonical_schemas() -> None:
    assessments, tasks, blocks, scheduled_tasks, events = load_scenario()

    assert len(assessments) == 3
    assert len(tasks) == 15
    assert len(blocks) == 8
    assert len(scheduled_tasks) == len(tasks)
    assert len(events) == 5
    assert {assessment.type for assessment in assessments} == {
        AssessmentType.PRESENTATION,
        AssessmentType.MIDTERM,
        AssessmentType.CODING_ASSIGNMENT,
    }
    assert {event.event_type for event in events} == set(PlanningEventType)


def test_mock_ids_and_cross_file_references_are_valid() -> None:
    assessments, tasks, blocks, scheduled_tasks, events = load_scenario()
    assessment_ids = {assessment.id for assessment in assessments}
    task_ids = {task.id for task in tasks}
    block_ids = {block.id for block in blocks}

    assert len(assessment_ids) == len(assessments)
    assert len(task_ids) == len(tasks)
    assert len(block_ids) == len(blocks)
    assert len({item.id for item in scheduled_tasks}) == len(scheduled_tasks)
    assert len({event.id for event in events}) == len(events)
    assert all(task.assessment_id in assessment_ids for task in tasks)
    assert all(item.task_id in task_ids for item in scheduled_tasks)

    expected_reference_sets = {
        PlanningEventType.TASK_COMPLETED: task_ids,
        PlanningEventType.TASK_MISSED: task_ids,
        PlanningEventType.NEW_ASSESSMENT: assessment_ids,
        PlanningEventType.ASSESSMENT_UPDATED: assessment_ids,
        PlanningEventType.CALENDAR_CHANGED: block_ids,
    }
    for event in events:
        assert event.reference_id in expected_reference_sets[event.event_type]


def test_mock_task_graph_is_valid() -> None:
    _, tasks, _, _, _ = load_scenario()

    assert validate_task_graph(tasks) == tasks


def test_baseline_schedule_matches_duration_dependencies_and_deadlines() -> None:
    assessments, tasks, _, scheduled_tasks, _ = load_scenario()
    assessments_by_id = {assessment.id: assessment for assessment in assessments}
    tasks_by_id = {task.id: task for task in tasks}
    placements_by_task_id = {item.task_id: item for item in scheduled_tasks}

    assert len(placements_by_task_id) == len(tasks)

    for task_id, placement in placements_by_task_id.items():
        task = tasks_by_id[task_id]
        assessment = assessments_by_id[task.assessment_id]
        assert placement.end_time - placement.start_time == timedelta(
            minutes=task.duration_minutes
        )
        assert placement.end_time <= assessment.deadline
        if assessment.unlock_at is not None:
            assert placement.start_time >= assessment.unlock_at
        for dependency_id in task.dependencies:
            assert placements_by_task_id[dependency_id].end_time <= placement.start_time


def test_baseline_schedule_has_no_calendar_or_task_conflicts() -> None:
    _, _, blocks, scheduled_tasks, _ = load_scenario()
    ordered_schedule = sorted(scheduled_tasks, key=lambda item: item.start_time)

    for previous, current in zip(ordered_schedule, ordered_schedule[1:]):
        assert previous.end_time <= current.start_time

    for placement in scheduled_tasks:
        for block in blocks:
            assert not overlaps(
                placement.start_time,
                placement.end_time,
                block.start_time,
                block.end_time,
            )


def test_planning_events_are_chronological_replay_inputs() -> None:
    _, _, _, _, events = load_scenario()

    assert events == sorted(events, key=lambda event: event.timestamp)
