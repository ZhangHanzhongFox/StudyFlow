"""Verified A/C handoff, not an implementation of an assessment-write API.

Tests explicitly stage canonical assessments/tasks before the existing replan
boundary. No helper below is a production ingestion or task replacement path.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta

import pytest

from backend.agents import FakeStructuredLLM, StudyFlowAgent
from backend.main import create_app
from backend.scheduler import SchedulingResult, StudyScheduler
from backend.schemas import (
    Assessment, AssessmentType, CalendarBlock, Flexibility, PlanningEvent,
    PlanningEventType, ScheduledTask, Task, TaskStatus, validate_task_graph,
)
from backend.services import PlanningPipeline, PlanningState
from backend.services.state import PlanningStateValidationError, validate_planning_state
from tests.test_agent_boundaries import WORKFLOW_TYPES, assessment_for
from tests.test_default_runtime import request


def at(time: str) -> datetime:
    return datetime.fromisoformat(f"2026-09-04T{time}:00+08:00")


def event(kind: PlanningEventType, reference: str) -> PlanningEvent:
    return PlanningEvent(
        id=f"event-handoff-{kind.value}-{reference}", event_type=kind,
        timestamp=at("09:00"), reference_id=reference,
    )


def task(
    task_id: str, assessment_id: str, *,
    status: TaskStatus = TaskStatus.SCHEDULED,
    dependencies: tuple[str, ...] = (),
) -> Task:
    return Task(
        id=task_id, assessment_id=assessment_id, name="Prepare assessment",
        duration_minutes=30, priority=3, status=status, dependencies=list(dependencies),
    )


def placement(task_id: str, start: str) -> ScheduledTask:
    return ScheduledTask(
        id=f"scheduled-{task_id}", task_id=task_id, start_time=at(start),
        end_time=at(start) + timedelta(minutes=30), flexibility=Flexibility.FLEXIBLE,
    )


class InspectReplanScheduler(StudyScheduler):
    def __init__(self) -> None:
        super().__init__(planning_start=at("08:00"))
        self.scopes: list[set[str]] = []
        self.inputs: list[list[Task]] = []

    def reschedule_tasks(
        self, assessments: Sequence[Assessment], tasks: Sequence[Task],
        calendar_blocks: Sequence[CalendarBlock], existing_schedule: Sequence[ScheduledTask],
        affected_task_ids: set[str], *, replanning_start: datetime | None = None,
        preserve_valid_affected: bool = False,
    ) -> SchedulingResult:
        self.scopes.append(set(affected_task_ids))
        self.inputs.append([item.model_copy(deep=True) for item in tasks])
        assert replanning_start == at("09:00")
        assert preserve_valid_affected is False
        return super().reschedule_tasks(
            assessments, tasks, calendar_blocks, existing_schedule, affected_task_ids,
            replanning_start=replanning_start, preserve_valid_affected=preserve_valid_affected,
        )


@pytest.mark.parametrize("kind", WORKFLOW_TYPES)
@pytest.mark.parametrize("llm_failure", [False, True], ids=["offline-default", "provider-fallback"])
def test_new_assessment_prepared_by_existing_agent_methods_reaches_replan(kind, llm_failure) -> None:
    existing = assessment_for(AssessmentType.CODING_ASSIGNMENT).model_copy(update={"id": "assessment-existing"})
    old_tasks = [
        task("done", existing.id, status=TaskStatus.COMPLETED),
        task("unrelated", existing.id, dependencies=("done",)),
    ]
    old_schedule = [placement("done", "08:00"), placement("unrelated", "15:00")]
    history = [event(PlanningEventType.TASK_COMPLETED, "done")]
    new = assessment_for(kind)
    agent = StudyFlowAgent(FakeStructuredLLM([
        RuntimeError("classification failed"), RuntimeError("decomposition failed"),
    ]) if llm_failure else None)

    # C's required precondition: normalize, classify/decompose only the new
    # assessment, then merge and validate in a staged snapshot.
    classified = new.model_copy(update={"type": agent.classify_assessment(new)})
    generated = agent.decompose_assessment(classified)
    staged_tasks = validate_task_graph([*old_tasks, *generated])
    blocks = [CalendarBlock(
        id="class", title="Class", start_time=at("10:00"), end_time=at("11:00"),
        flexibility=Flexibility.HARD,
    )]
    staged = PlanningState([existing, classified], staged_tasks, blocks, old_schedule, history)
    scheduler = InspectReplanScheduler()
    trigger = event(PlanningEventType.NEW_ASSESSMENT, new.id)

    result = staged.replan(trigger, PlanningPipeline(agent, scheduler))

    assert generated
    assert scheduler.scopes == [{item.id for item in generated}]
    assert scheduler.inputs == [staged_tasks]
    assert result.unscheduled_tasks == []
    placements = {item.task_id: item for item in result.scheduled_tasks}
    assert set(placements) == {item.id for item in staged_tasks}
    assert [placements[item.task_id] for item in old_schedule] == old_schedule
    for item in generated:
        slot = placements[item.id]
        assert slot.start_time >= trigger.timestamp
        assert slot.end_time <= new.deadline
        for dependency in item.dependencies:
            assert placements[dependency].end_time <= slot.start_time
        assert slot.end_time <= blocks[0].start_time or slot.start_time >= blocks[0].end_time
    assert staged.list_planning_events() == [*history, trigger]
    assert staged.list_tasks()[:2] == old_tasks


@pytest.mark.parametrize("kind", [PlanningEventType.NEW_ASSESSMENT, PlanningEventType.ASSESSMENT_UPDATED])
@pytest.mark.parametrize("case", ["mixed", "all-completed", "no-tasks"])
def test_assessment_event_scope_is_exact_and_read_only(kind, case, caplog) -> None:
    tasks = [
        task(f"task-{status.value}", "assessment-target", status=status)
        for status in TaskStatus
    ]
    if case == "all-completed":
        tasks = [item.model_copy(update={"status": TaskStatus.COMPLETED}) for item in tasks]
    elif case == "no-tasks":
        tasks = []
    tasks.append(task("other-assessment", "assessment-other"))
    before = [item.model_dump() for item in tasks]
    trigger = event(kind, "assessment-target")
    before_event = trigger.model_dump()
    expected = {
        item.id for item in tasks
        if item.assessment_id == trigger.reference_id and item.status is not TaskStatus.COMPLETED
    }
    with caplog.at_level("INFO", logger="backend.agents.workflow"):
        agent = StudyFlowAgent()
        assert agent.find_affected_task_ids(trigger, tasks) == expected
        assert agent.find_affected_task_ids(trigger, list(reversed(tasks))) == expected
    assert [item.model_dump() for item in tasks] == before
    assert trigger.model_dump() == before_event
    assert "event contains no requirement diff" in caplog.text
    assert "Candidates are not confirmed schedule moves" in caplog.text


def test_time_only_update_uses_staged_assessment_and_preserves_completed_history() -> None:
    original = assessment_for(AssessmentType.PRESENTATION)
    updated = original.model_copy(update={"deadline": at("11:00")})
    other = assessment_for(AssessmentType.EXAM)
    tasks = [
        task("done", updated.id, status=TaskStatus.COMPLETED),
        task("active", updated.id, dependencies=("done",)),
        task("independent-same-assessment", updated.id),
        task("other", other.id),
    ]
    schedule = [
        placement("done", "08:00"), placement("active", "12:00"),
        placement("independent-same-assessment", "12:30"), placement("other", "15:00"),
    ]
    history = [event(PlanningEventType.TASK_COMPLETED, "done")]
    state = PlanningState([updated, other], tasks, [], schedule, history)
    scheduler = InspectReplanScheduler()

    class ExistingTasksAgent(StudyFlowAgent):
        def classify_assessment(self, assessment: Assessment) -> AssessmentType:
            pytest.fail("time-only updates must not reclassify")

        def decompose_assessment(self, assessment: Assessment) -> list[Task]:
            pytest.fail("time-only updates must not regenerate tasks")

    trigger = event(PlanningEventType.ASSESSMENT_UPDATED, updated.id)
    result = state.replan(trigger, PlanningPipeline(ExistingTasksAgent(), scheduler))

    assert scheduler.scopes == [{"active", "independent-same-assessment"}]
    assert scheduler.inputs == [tasks]
    assert state.list_tasks() == tasks
    assert result.unscheduled_tasks == []
    placements = {item.task_id: item for item in result.scheduled_tasks}
    assert placements["done"] == schedule[0]
    assert placements["other"] == schedule[-1]
    for task_id in scheduler.scopes[0]:
        assert placements[task_id].start_time >= trigger.timestamp
        assert placements[task_id].end_time <= updated.deadline
        if updated.unlock_at:
            assert placements[task_id].start_time >= updated.unlock_at
    assert state.list_planning_events() == [*history, trigger]


def test_unlock_update_moves_incomplete_work_after_new_availability() -> None:
    updated = assessment_for(AssessmentType.PRESENTATION).model_copy(update={"unlock_at": at("10:00")})
    other = assessment_for(AssessmentType.EXAM)
    tasks = [task("active", updated.id), task("other", other.id)]
    schedule = [placement("active", "08:00"), placement("other", "15:00")]
    state = PlanningState([updated, other], tasks, [], schedule)
    scheduler = InspectReplanScheduler()
    result = state.replan(
        event(PlanningEventType.ASSESSMENT_UPDATED, updated.id),
        PlanningPipeline(StudyFlowAgent(), scheduler),
    )
    assert scheduler.scopes == [{"active"}]
    assert result.unscheduled_tasks == []
    placements = {item.task_id: item for item in result.scheduled_tasks}
    assert placements["active"].start_time == at("10:00")
    assert placements["other"] == schedule[-1]
    assert state.list_tasks() == tasks


def test_update_conflicting_with_completed_history_is_rejected_without_event_commit() -> None:
    updated = assessment_for(AssessmentType.EXAM).model_copy(update={"unlock_at": at("10:00")})
    done = task("done", updated.id, status=TaskStatus.COMPLETED)
    schedule = [placement("done", "08:00")]
    state = PlanningState([updated], [done], [], schedule)
    with pytest.raises(ValueError, match="immutable task"):
        state.replan(
            event(PlanningEventType.ASSESSMENT_UPDATED, updated.id),
            PlanningPipeline(StudyFlowAgent(), InspectReplanScheduler()),
        )
    assert state.list_tasks() == [done]
    assert state.list_scheduled_tasks() == schedule
    assert state.list_planning_events() == []


@pytest.mark.parametrize("kind", [
    PlanningEventType.TASK_MISSED, PlanningEventType.TASK_COMPLETED,
    PlanningEventType.NEW_ASSESSMENT, PlanningEventType.ASSESSMENT_UPDATED,
])
def test_unknown_references_are_rejected_before_scheduler_with_no_state_changes(kind) -> None:
    state = PlanningState([assessment_for(AssessmentType.EXAM)])
    scheduler = InspectReplanScheduler()
    response = request(
        create_app(state, PlanningPipeline(StudyFlowAgent(), scheduler)), "POST", "/replan",
        json=event(kind, "missing").model_dump(mode="json"),
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "unknown_reference"
    assert scheduler.scopes == []
    assert state.list_planning_events() == []
    assert state.list_tasks() == state.list_scheduled_tasks() == []


@pytest.mark.parametrize("kind", [PlanningEventType.TASK_COMPLETED, PlanningEventType.TASK_MISSED])
def test_unknown_task_reference_also_fails_at_direct_agent_boundary(kind) -> None:
    with pytest.raises(ValueError, match="references unknown task"):
        StudyFlowAgent().find_affected_task_ids(event(kind, "missing"), [])


@pytest.mark.parametrize("kind", [PlanningEventType.NEW_ASSESSMENT, PlanningEventType.ASSESSMENT_UPDATED])
def test_bare_assessment_event_is_not_a_task_generation_api(kind) -> None:
    assessment = assessment_for(AssessmentType.EXAM)
    state = PlanningState([assessment])
    scheduler = InspectReplanScheduler()
    trigger = event(kind, assessment.id)

    result = state.replan(trigger, PlanningPipeline(StudyFlowAgent(), scheduler))

    # Documents the existing limitation, not success of assessment ingestion.
    assert result == SchedulingResult()
    assert state.list_tasks() == []
    assert scheduler.inputs == [[]]
    assert state.list_planning_events() == [trigger]


def test_replacing_tasks_can_break_completed_dependencies_and_event_history() -> None:
    assessment = assessment_for(AssessmentType.PRESENTATION)
    tasks = [
        task("old-prerequisite", assessment.id),
        task("completed-downstream", assessment.id, status=TaskStatus.COMPLETED, dependencies=("old-prerequisite",)),
    ]
    history = [event(PlanningEventType.TASK_MISSED, "old-prerequisite")]
    validate_planning_state([assessment], tasks, [], [], history)
    with pytest.raises(PlanningStateValidationError, match="unknown dependency"):
        validate_planning_state([assessment], tasks[1:], [], [], history)
    with pytest.raises(PlanningStateValidationError, match="references unknown id"):
        validate_planning_state([assessment], [], [], [], history)
    # Retaining just completed records is insufficient: old task references
    # require a coordinated replacement policy before any production mutation.


def test_same_step_id_after_changed_requirements_does_not_prove_completed_equivalence() -> None:
    before = assessment_for(AssessmentType.PRESENTATION, "Present topic A.")
    after = before.model_copy(update={"description": "Present topic B instead."})
    agent = StudyFlowAgent()
    completed = [item.model_copy(update={"status": TaskStatus.COMPLETED}) for item in agent.decompose_assessment(before)]
    regenerated = agent.decompose_assessment(after)
    assert [item.id for item in regenerated] == [item.id for item in completed]
    assert all(item.status is TaskStatus.PENDING for item in regenerated)
    assert all(item.status is TaskStatus.COMPLETED for item in completed)
    assert agent.find_affected_task_ids(event(PlanningEventType.ASSESSMENT_UPDATED, after.id), completed) == set()


def test_new_assessment_with_no_room_reports_all_new_work_without_moving_old_work() -> None:
    existing = assessment_for(AssessmentType.PRESENTATION)
    old_task = task("other", existing.id)
    old_schedule = [placement(old_task.id, "15:00")]
    new = assessment_for(AssessmentType.EXAM).model_copy(update={"deadline": at("09:15")})
    agent = StudyFlowAgent()
    generated = agent.decompose_assessment(new)
    state = PlanningState([existing, new], [old_task, *generated], [], old_schedule)
    trigger = event(PlanningEventType.NEW_ASSESSMENT, new.id)

    result = state.replan(trigger, PlanningPipeline(agent, InspectReplanScheduler()))

    assert result.scheduled_tasks == old_schedule
    assert {item.task_id for item in result.unscheduled_tasks} == {item.id for item in generated}
    assert all(item.message for item in result.unscheduled_tasks)
    assert state.list_tasks() == [old_task, *generated]
    assert state.list_planning_events() == [trigger]


def test_duplicate_generated_tasks_cannot_be_merged_as_a_second_new_assessment() -> None:
    assessment = assessment_for(AssessmentType.EXAM)
    agent = StudyFlowAgent()
    tasks = agent.decompose_assessment(assessment)
    with pytest.raises(ValueError, match="duplicate task id"):
        validate_task_graph([*tasks, *agent.decompose_assessment(assessment)])
