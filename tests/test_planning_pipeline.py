"""Tests for the orchestration boundary between Agent and Scheduler."""

from collections.abc import Sequence

from backend.agents import StudyFlowAgent
from backend.scheduler import SchedulingResult
from backend.schemas import (
    Assessment,
    AssessmentType,
    CalendarBlock,
    PlanningEvent,
    ScheduledTask,
    Task,
    validate_task_graph,
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


def test_studyflow_agent_is_directly_injectable_for_all_workflow_types() -> None:
    store = MockDataStore()
    midterm = next(
        assessment
        for assessment in store.list_assessments()
        if assessment.type is AssessmentType.MIDTERM
    )
    quiz = midterm.model_copy(
        update={
            "id": "assessment-quiz-pipeline-test",
            "title": "Week 3 Review Quiz",
            "description": "",
            "type": AssessmentType.QUIZ,
        }
    )
    assessments = [*store.list_assessments(), quiz]
    scheduler = RecordingScheduler([])
    pipeline = PlanningPipeline(StudyFlowAgent(), scheduler)

    result = pipeline.plan(assessments, store.list_calendar_blocks())

    tasks = scheduler.scheduled_tasks_received
    assert result == SchedulingResult()
    assert validate_task_graph(tasks) == tasks
    assert {task.assessment_id for task in tasks} == {
        assessment.id for assessment in assessments
    }
    assert all(task.duration_minutes > 0 for task in tasks)
    assert all(1 <= task.priority <= 5 for task in tasks)

    quiz_tasks = [task for task in tasks if task.assessment_id == quiz.id]
    assert [task.name for task in quiz_tasks] == [
        "Review the relevant course material",
        "Take the quiz",
    ]
    assert quiz_tasks[0].dependencies == []
    assert quiz_tasks[1].dependencies == [quiz_tasks[0].id]


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
