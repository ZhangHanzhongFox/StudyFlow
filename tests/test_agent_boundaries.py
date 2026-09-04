"""A's defensive output boundary, conservative defaults and truthful reasons."""

import logging
from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import pytest
from pydantic import ValidationError

from backend.agents import (
    ClassificationOutput,
    DecompositionOutput,
    FakeStructuredLLM,
    StudyFlowAgent,
    TaskDraft,
)
from backend.agents.llm import StructuredOutputT
from backend.agents.prompts import DECOMPOSITION_SYSTEM_PROMPT, assessment_prompt
from backend.integrations.canvas import normalize_canvas_assignments
from backend.scheduler import SchedulingResult, StudyScheduler
from backend.schemas import (
    Assessment, AssessmentType, CalendarBlock, ScheduledTask, Task, TaskStatus,
    validate_task_graph,
)
from backend.services import MockDataStore, PlanningPipeline


WORKFLOW_TYPES = (
    AssessmentType.PRESENTATION, AssessmentType.EXAM,
    AssessmentType.MIDTERM, AssessmentType.CODING_ASSIGNMENT,
)


def assessment_for(kind: AssessmentType, description: str = "") -> Assessment:
    source = MockDataStore().list_assessments()[0].model_dump()
    source.update(
        id=f"assessment-boundary-{kind.value}", title=kind.value,
        description=description, type=kind, is_group=False, group_size=None,
        unlock_at=None, deadline="2026-09-07T18:00:00+08:00",
    )
    return Assessment.model_validate(source)


def draft(**overrides: Any) -> dict[str, Any]:
    return {
        "step_key": "prepare", "name": "Confirm requirements",
        "duration_minutes": 30, "priority": 3, "dependency_keys": [],
        **overrides,
    }


class RawStructuredLLM:
    """Deliberately broken provider: do not validate or repair its responses."""

    def __init__(self, responses: Sequence[Any]) -> None:
        self.responses = iter(responses)

    def generate(
        self, *, system_prompt: str, user_prompt: str,
        response_model: type[StructuredOutputT],
    ) -> StructuredOutputT:
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


class InspectingScheduler(StudyScheduler):
    """Observe canonical inputs, then exercise the real scheduling logic."""

    def __init__(self) -> None:
        super().__init__(planning_start=datetime.fromisoformat("2026-09-04T09:00:00+08:00"))
        self.received: list[Task] = []

    def schedule_tasks(
        self, assessments: Sequence[Assessment], tasks: Sequence[Task],
        calendar_blocks: Sequence[CalendarBlock],
        existing_schedule: Sequence[ScheduledTask] = (),
    ) -> SchedulingResult:
        self.received = list(tasks)
        assert tasks
        assert validate_task_graph(tasks) == list(tasks)
        return super().schedule_tasks(assessments, tasks, calendar_blocks, existing_schedule)


MALFORMED_OUTPUTS = [
    pytest.param(None, id="null"),
    pytest.param("{not-json", id="unparseable-text"),
    pytest.param('{"tasks": []}', id="unparsed-json-string"),
    pytest.param([], id="wrong-root"),
    pytest.param({}, id="missing-tasks"),
    pytest.param({"tasks": []}, id="empty-tasks"),
    pytest.param({"tasks": None}, id="null-tasks"),
    pytest.param({"tasks": [None]}, id="null-task"),
    pytest.param({"tasks": [draft()], "rationale": "unapproved"}, id="extra-root-field"),
    pytest.param({"tasks": [draft(deadline="invented")]}, id="extra-task-field"),
    pytest.param({"tasks": [{"step_key": "prepare"}]}, id="missing-task-fields"),
    pytest.param({"tasks": [draft(name=" \n ")]}, id="blank-name"),
    pytest.param({"tasks": [draft(duration_minutes=-1)]}, id="negative-duration"),
    pytest.param({"tasks": [draft(duration_minutes=0)]}, id="zero-duration"),
    pytest.param({"tasks": [draft(duration_minutes=True)]}, id="boolean-duration"),
    pytest.param({"tasks": [draft(duration_minutes="30")]}, id="string-duration"),
    pytest.param({"tasks": [draft(duration_minutes=30.0)]}, id="float-duration"),
    pytest.param({"tasks": [draft(priority=True)]}, id="boolean-priority"),
    pytest.param({"tasks": [draft(priority="3")]}, id="string-priority"),
    pytest.param({"tasks": [draft(priority=3.0)]}, id="float-priority"),
    pytest.param({"tasks": [draft(priority=0)]}, id="low-priority"),
    pytest.param({"tasks": [draft(priority=6)]}, id="high-priority"),
    pytest.param({"tasks": [draft(step_key="Not a key")]}, id="invalid-step-key"),
    pytest.param({"tasks": [draft(dependency_keys="prepare")]}, id="wrong-dependency-type"),
    pytest.param({"tasks": [draft(dependency_keys=[123])]}, id="non-string-dependency"),
    pytest.param({"tasks": [draft(dependency_keys=["unknown"])]}, id="unknown-dependency"),
    pytest.param({"tasks": [draft(dependency_keys=["prepare"])]}, id="self-dependency"),
    pytest.param({"tasks": [draft(), draft()]}, id="duplicate-key"),
    pytest.param({"tasks": [draft(), draft(step_key="review", dependency_keys=["prepare", "prepare"])]}, id="duplicate-dependency"),
    pytest.param({"tasks": [draft(dependency_keys=["review"]), draft(step_key="review", dependency_keys=["prepare"])]}, id="cycle"),
    pytest.param(RuntimeError("private provider failure"), id="provider-error"),
    pytest.param(DecompositionOutput.model_construct(tasks=[]), id="constructed-empty-model"),
    pytest.param(DecompositionOutput.model_construct(tasks=[TaskDraft.model_construct(**draft(duration_minutes=True))]), id="constructed-invalid-nested-model"),
]


@pytest.mark.parametrize("kind", WORKFLOW_TYPES)
@pytest.mark.parametrize("output", MALFORMED_OUTPUTS)
def test_bad_output_is_fully_replaced_before_real_scheduler(kind, output) -> None:
    assessment = assessment_for(kind)
    agent = StudyFlowAgent(RawStructuredLLM([
        {"assessment_type": kind.value}, output,
    ]))
    scheduler = InspectingScheduler()

    run = PlanningPipeline(agent, scheduler).run_plan([assessment], [])

    expected = StudyFlowAgent().decompose_assessment(assessment)
    assert run.tasks == scheduler.received == expected
    assert all(task.status is TaskStatus.PENDING for task in run.tasks)
    assert {item.task_id for item in run.result.scheduled_tasks} == {task.id for task in expected}
    assert run.result.unscheduled_tasks == []


@pytest.mark.parametrize("output", [
    None, "not JSON", {}, {"type": "exam"},
    {"assessment_type": "unsupported"},
    {"assessment_type": "exam", "extra": True},
    ClassificationOutput.model_construct(assessment_type="unsupported"),
    RuntimeError("private provider failure"),
])
def test_bad_classification_cannot_escape_agent(output) -> None:
    assessment = assessment_for(AssessmentType.PRESENTATION)
    assert StudyFlowAgent(RawStructuredLLM([output])).classify_assessment(assessment) is assessment.type


def test_mutated_nested_output_is_revalidated_without_serialization_warning() -> None:
    import warnings

    output = DecompositionOutput.model_validate({"tasks": [draft()]})
    output.tasks[0].duration_minutes = "private invalid value"
    assessment = assessment_for(AssessmentType.EXAM)
    with warnings.catch_warnings(record=True) as caught:
        tasks = StudyFlowAgent(RawStructuredLLM([output])).decompose_assessment(assessment)
    assert tasks == StudyFlowAgent().decompose_assessment(assessment)
    assert not caught


@pytest.mark.parametrize("field", ["duration_minutes", "priority"])
@pytest.mark.parametrize("value", [True, False, "3", 3.0, 3.5])
def test_provider_draft_rejects_coerced_numeric_values(field, value) -> None:
    with pytest.raises(ValidationError):
        TaskDraft.model_validate(draft(**{field: value}))


@pytest.mark.parametrize("kind", WORKFLOW_TYPES)
def test_valid_llm_steps_and_dependencies_reach_real_scheduler(kind) -> None:
    assessment = assessment_for(kind, "Confirm requirements and prepare the assessment.")
    payload = {"tasks": [
        draft(step_key="review", name="Review preparation", dependency_keys=["prepare"]),
        draft(),
    ]}
    agent = StudyFlowAgent(FakeStructuredLLM([{"assessment_type": kind.value}, payload]))
    scheduler = InspectingScheduler()

    run = PlanningPipeline(agent, scheduler).run_plan([assessment], [])

    assert len(run.tasks) == 2
    assert [task.name for task in run.tasks] == ["Review preparation", "Confirm requirements"]
    placements = {item.task_id: item for item in run.result.scheduled_tasks}
    assert placements[run.tasks[1].id].end_time <= placements[run.tasks[0].id].start_time
    assert run.result.unscheduled_tasks == []


@pytest.mark.parametrize("kind", WORKFLOW_TYPES)
@pytest.mark.parametrize("description", ["", " \n\t ", "Requirements to be confirmed."])
def test_sparse_description_uses_explicit_conservative_defaults(kind, description, caplog) -> None:
    assessment = assessment_for(kind, description)
    before = assessment.model_dump()
    with caplog.at_level(logging.INFO, logger="backend.agents.workflow"):
        tasks = StudyFlowAgent().decompose_assessment(assessment)
    assert tasks == validate_task_graph(tasks)
    assert tasks[0].name.startswith("Confirm")
    names = " ".join(task.name.lower() for task in tasks)
    assert not any(text in names for text in ("group", "roles", "demo script", "design note"))
    if kind in {AssessmentType.EXAM, AssessmentType.MIDTERM}:
        assert len(tasks) == 4
        assert not any(task.name.lower().startswith("take ") for task in tasks)
    assert assessment.model_dump() == before
    assert "planning estimates, not assessment facts" in caplog.text
    assert f"description={'provided' if description.strip() else 'missing'}" in caplog.text
    assert "reason=template_default" in caplog.text
    assert "failed" not in caplog.text


def test_group_wording_changes_only_names_not_ids_or_estimates() -> None:
    individual = assessment_for(AssessmentType.PRESENTATION)
    group = individual.model_copy(update={"is_group": True, "group_size": 3})
    agent = StudyFlowAgent()
    individual_tasks = agent.decompose_assessment(individual)
    group_tasks = agent.decompose_assessment(group)
    assert "group roles" in group_tasks[0].name
    assert "group rehearsal" in group_tasks[-1].name
    for first, second in zip(individual_tasks, group_tasks):
        assert first.model_dump(exclude={"name"}) == second.model_dump(exclude={"name"})
    # Lock down the existing public ID algorithm and original template keys.
    keys = ["requirements", "outline", "slides", "script", "rehearsal"]
    assert [task.id for task in individual_tasks] == [
        f"task-{uuid5(NAMESPACE_URL, f'https://studyflow.local/tasks/{individual.id}/{key}')}"
        for key in keys
    ]


@pytest.mark.parametrize(("output", "reason"), [
    (RuntimeError("private failure"), "provider_output_unavailable"),
    ({"tasks": [draft(duration_minutes="private invalid value")]}, "invalid_structure"),
    ({"tasks": [draft(dependency_keys=["private unknown key"])]}, "invalid_dependencies"),
])
def test_fallback_reasons_match_actual_failure_without_private_content(output, reason, caplog) -> None:
    assessment = assessment_for(AssessmentType.PRESENTATION, "private assessment description")
    with caplog.at_level(logging.INFO, logger="backend.agents.workflow"):
        StudyFlowAgent(RawStructuredLLM([output])).decompose_assessment(assessment)
    assert f"reason={reason}" in caplog.text
    assert "reason=template_fallback" in caplog.text
    assert "reason=validated_llm" not in caplog.text
    assert "private" not in caplog.text


def test_provider_validation_error_is_reported_as_structure_failure(caplog) -> None:
    agent = StudyFlowAgent(FakeStructuredLLM([{"tasks": []}]))
    agent.decompose_assessment(assessment_for(AssessmentType.EXAM))
    assert "reason=invalid_structure" in caplog.text


def test_success_logs_actual_edges_without_provider_task_text(caplog) -> None:
    assessment = assessment_for(AssessmentType.PRESENTATION)
    llm = FakeStructuredLLM([
        {"assessment_type": "presentation"},
        {"tasks": [draft(name="private task text"), draft(step_key="review", dependency_keys=["prepare"])]},
    ])
    agent = StudyFlowAgent(llm)
    with caplog.at_level(logging.INFO, logger="backend.agents.workflow"):
        agent.classify_assessment(assessment)
        tasks = agent.decompose_assessment(assessment)
    assert "reason=validated_llm" in caplog.text
    assert f"depends_on={[tasks[0].id]!r}" in caplog.text
    assert "private" not in caplog.text
    assert "fallback" not in caplog.text


def test_prompt_separates_unknown_facts_estimates_and_exam_preparation() -> None:
    assessment = assessment_for(AssessmentType.EXAM, "Only some requirements are available.")
    assert assessment_prompt(assessment) == assessment.model_dump_json()
    assert "missing or incomplete" in DECOMPOSITION_SYSTEM_PROMPT
    assert "durations as planning estimates" in DECOMPOSITION_SYSTEM_PROMPT
    assert "not a schedulable preparation task" in DECOMPOSITION_SYSTEM_PROMPT


@pytest.mark.parametrize("kind", WORKFLOW_TYPES)
@pytest.mark.parametrize("missing", ["omitted", "null"])
def test_missing_provider_description_is_normalized_before_agent(kind, missing) -> None:
    payload = {
        "id": 1, "course_id": 1, "course_code": "CS1000", "name": kind.value,
        "due_at": "2026-09-07T18:00:00+08:00",
        "studyflow": {"assessment_type": kind.value},
    }
    if missing == "null":
        payload["description"] = None
    assessment = normalize_canvas_assignments([payload])[0]
    assert assessment.description == ""
    tasks = StudyFlowAgent().decompose_assessment(assessment)
    assert tasks == validate_task_graph(tasks)
    assert tasks[0].name.startswith("Confirm")
