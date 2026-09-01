"""Tests for the orchestration boundary between Agent and Scheduler."""

from collections.abc import Sequence

from backend.scheduler import SchedulingResult
from backend.schemas import (
    Assessment,
    AssessmentType,
    CalendarBlock,
    PlanningEvent,
    ScheduledTask,
    Task,
)
from backend.services import MockDataStore, PlanningPipeline


class FixtureAgent:
    def __init__(self, tasks: Sequence[Task]) -> None:
        self.tasks = list(tasks)
        self.classified_assessment_ids: list[str] = []
        self.affected_task_ids = {
            "task-presentation-slides",
            "task-presentation-script",
            "task-presentation-rehearsal",
        }

    def classify_assessment(self, assessment: Assessment) -> AssessmentType:
        self.classified_assessment_ids.append(assessment.id)
        return assessment.type

    def decompose_assessment(self, assessment: Assessment) -> list[Task]:
        return [
            task for task in self.tasks if task.assessment_id == assessment.id
        ]

    def find_affected_task_ids(
        self,
        event: PlanningEvent,
        tasks: Sequence[Task],
    ) -> set[str]:
        return set(self.affected_task_ids)


class RecordingScheduler:
    def __init__(self, fixture_schedule: Sequence[ScheduledTask]) -> None:
        self.fixture_schedule = list(fixture_schedule)
        self.scheduled_tasks_received: list[Task] = []
        self.affected_task_ids_received: set[str] = set()

    def schedule_tasks(
        self,
        assessments: Sequence[Assessment],
        tasks: Sequence[Task],
        calendar_blocks: Sequence[CalendarBlock],
        existing_schedule: Sequence[ScheduledTask] = (),
    ) -> SchedulingResult:
        self.scheduled_tasks_received = list(tasks)
        return SchedulingResult(scheduled_tasks=self.fixture_schedule)

    def reschedule_tasks(
        self,
        assessments: Sequence[Assessment],
        tasks: Sequence[Task],
        calendar_blocks: Sequence[CalendarBlock],
        existing_schedule: Sequence[ScheduledTask],
        affected_task_ids: set[str],
    ) -> SchedulingResult:
        self.affected_task_ids_received = set(affected_task_ids)
        return SchedulingResult(scheduled_tasks=list(existing_schedule))


def test_plan_decomposes_all_assessments_then_calls_scheduler() -> None:
    store = MockDataStore()
    agent = FixtureAgent(store.list_tasks())
    scheduler = RecordingScheduler(store.list_scheduled_tasks())
    pipeline = PlanningPipeline(agent, scheduler)

    result = pipeline.plan(
        store.list_assessments(),
        store.list_calendar_blocks(),
    )

    assert scheduler.scheduled_tasks_received == store.list_tasks()
    assert agent.classified_assessment_ids == [
        assessment.id for assessment in store.list_assessments()
    ]
    assert result.scheduled_tasks == store.list_scheduled_tasks()
    assert result.unscheduled_tasks == []


def test_replan_separates_affected_task_discovery_from_time_placement() -> None:
    store = MockDataStore()
    agent = FixtureAgent(store.list_tasks())
    scheduler = RecordingScheduler(store.list_scheduled_tasks())
    pipeline = PlanningPipeline(agent, scheduler)
    event = next(
        event
        for event in store.list_planning_events()
        if event.event_type.value == "task_missed"
    )

    result = pipeline.replan(
        event,
        store.list_assessments(),
        store.list_tasks(),
        store.list_calendar_blocks(),
        store.list_scheduled_tasks(),
    )

    assert scheduler.affected_task_ids_received == agent.affected_task_ids
    assert result.scheduled_tasks == store.list_scheduled_tasks()
