"""Tests for classification, decomposition, fallback, and dependency analysis."""

from collections.abc import Sequence

import pytest

from backend.agents import FakeStructuredLLM, StudyFlowAgent
from backend.schemas import (
    Assessment,
    AssessmentType,
    PlanningEvent,
    PlanningEventType,
    Task,
    TaskStatus,
    validate_task_graph,
)
from backend.services import MockDataStore


def assessment_of_type(
    assessments: Sequence[Assessment],
    assessment_type: AssessmentType,
) -> Assessment:
    return next(item for item in assessments if item.type is assessment_type)


@pytest.mark.parametrize(
    ("assessment_type", "expected_task_count"),
    [
        (AssessmentType.PRESENTATION, 5),
        (AssessmentType.MIDTERM, 4),
        (AssessmentType.CODING_ASSIGNMENT, 6),
    ],
)
def test_fixture_assessments_generate_valid_fallback_workflows(
    assessment_type: AssessmentType,
    expected_task_count: int,
) -> None:
    assessment = assessment_of_type(
        MockDataStore().list_assessments(),
        assessment_type,
    )

    tasks = StudyFlowAgent().decompose_assessment(assessment)

    assert len(tasks) == expected_task_count
    assert validate_task_graph(tasks) == tasks
    assert all(task.assessment_id == assessment.id for task in tasks)
    assert all(task.status is TaskStatus.PENDING for task in tasks)
    assert all(task.duration_minutes > 0 for task in tasks)
    assert all(1 <= task.priority <= 5 for task in tasks)


@pytest.mark.parametrize(
    ("assessment_type", "expected_task_count"),
    [
        (AssessmentType.PRESENTATION, 5),
        (AssessmentType.EXAM, 4),
        (AssessmentType.MIDTERM, 4),
        (AssessmentType.CODING_ASSIGNMENT, 6),
        (AssessmentType.QUIZ, 2),
    ],
)
def test_missing_description_still_uses_valid_type_fallback(
    assessment_type: AssessmentType,
    expected_task_count: int,
) -> None:
    assessments = MockDataStore().list_assessments()
    source_type = (
        AssessmentType.MIDTERM
        if assessment_type in {AssessmentType.EXAM, AssessmentType.QUIZ}
        else assessment_type
    )
    source = assessment_of_type(assessments, source_type)
    assessment = source.model_copy(
        update={
            "id": f"assessment-empty-description-{assessment_type.value}",
            "description": "",
            "type": assessment_type,
        }
    )
    agent = StudyFlowAgent()

    tasks = agent.decompose_assessment(assessment)

    assert agent.classify_assessment(assessment) is assessment_type
    assert len(tasks) == expected_task_count
    assert validate_task_graph(tasks) == tasks
    assert all(task.assessment_id == assessment.id for task in tasks)
    assert all(task.name and task.duration_minutes > 0 for task in tasks)
    assert all(1 <= task.priority <= 5 for task in tasks)


def test_exam_uses_the_exam_midterm_workflow_family() -> None:
    midterm = assessment_of_type(
        MockDataStore().list_assessments(),
        AssessmentType.MIDTERM,
    )
    exam = midterm.model_copy(
        update={"id": "assessment-exam-demo", "type": AssessmentType.EXAM}
    )

    tasks = StudyFlowAgent().decompose_assessment(exam)

    assert len(tasks) == 4
    assert tasks[0].name == "Confirm assessment scope and learning outcomes"
    assert tasks[-1].name == "Complete a final review of weak topics"
    assert [task.duration_minutes for task in tasks] == [30, 120, 180, 60]
    assert tasks[0].dependencies == []
    for previous, current in zip(tasks, tasks[1:]):
        assert current.dependencies == [previous.id]
    assert validate_task_graph(tasks) == tasks


def test_presentation_template_has_required_dependency_chain() -> None:
    presentation = assessment_of_type(
        MockDataStore().list_assessments(),
        AssessmentType.PRESENTATION,
    )

    tasks = StudyFlowAgent().decompose_assessment(presentation)

    assert [task.name for task in tasks] == [
        "Confirm presentation requirements, missing details and group roles",
        "Create the presentation storyline and outline",
        "Prepare and review presentation materials",
        "Write and review speaker notes",
        "Run a timed group rehearsal and revise",
    ]
    assert [task.duration_minutes for task in tasks] == [30, 30, 60, 90, 60]
    assert tasks[0].dependencies == []
    for previous, current in zip(tasks, tasks[1:]):
        assert current.dependencies == [previous.id]


def test_coding_assignment_template_uses_revised_durations() -> None:
    coding_assignment = assessment_of_type(
        MockDataStore().list_assessments(),
        AssessmentType.CODING_ASSIGNMENT,
    )

    tasks = StudyFlowAgent().decompose_assessment(coding_assignment)

    assert [task.duration_minutes for task in tasks] == [15, 30, 120, 60, 60, 30]
    assert tasks[0].dependencies == []
    for previous, current in zip(tasks, tasks[1:]):
        assert current.dependencies == [previous.id]


def test_quiz_template_has_review_then_take_quiz() -> None:
    source = assessment_of_type(
        MockDataStore().list_assessments(),
        AssessmentType.MIDTERM,
    )
    quiz_data = source.model_dump()
    quiz_data.update(
        {
            "id": "assessment-quiz-demo",
            "title": "Week 3 Review Quiz",
            "description": "Complete the short quiz after reviewing the lesson.",
            "type": "quiz",
        }
    )
    quiz = Assessment.model_validate(quiz_data)

    tasks = StudyFlowAgent().decompose_assessment(quiz)

    assert quiz.type is AssessmentType.QUIZ
    assert [task.name for task in tasks] == [
        "Review the relevant course material",
        "Take the quiz",
    ]
    assert [task.duration_minutes for task in tasks] == [30, 30]
    assert tasks[0].dependencies == []
    assert tasks[1].dependencies == [tasks[0].id]
    assert validate_task_graph(tasks) == tasks


def test_generated_task_ids_are_stable_and_assessment_scoped() -> None:
    assessments = MockDataStore().list_assessments()
    presentation = assessment_of_type(assessments, AssessmentType.PRESENTATION)
    midterm = assessment_of_type(assessments, AssessmentType.MIDTERM)
    agent = StudyFlowAgent()

    first_ids = [task.id for task in agent.decompose_assessment(presentation)]
    repeated_ids = [task.id for task in agent.decompose_assessment(presentation)]
    midterm_ids = [task.id for task in agent.decompose_assessment(midterm)]

    assert first_ids == repeated_ids
    assert set(first_ids).isdisjoint(midterm_ids)
    assert len(first_ids) == len(set(first_ids))


def test_fake_llm_classifies_to_canonical_assessment_type() -> None:
    presentation = assessment_of_type(
        MockDataStore().list_assessments(),
        AssessmentType.PRESENTATION,
    )
    agent = StudyFlowAgent(
        FakeStructuredLLM([{"assessment_type": "coding_assignment"}])
    )

    assert (
        agent.classify_assessment(presentation)
        is AssessmentType.CODING_ASSIGNMENT
    )


def test_invalid_classification_falls_back_to_normalized_type() -> None:
    presentation = assessment_of_type(
        MockDataStore().list_assessments(),
        AssessmentType.PRESENTATION,
    )
    agent = StudyFlowAgent(
        FakeStructuredLLM([{"assessment_type": "not-a-supported-type"}])
    )

    assert agent.classify_assessment(presentation) is AssessmentType.PRESENTATION


def test_valid_structured_decomposition_becomes_canonical_tasks() -> None:
    presentation = assessment_of_type(
        MockDataStore().list_assessments(),
        AssessmentType.PRESENTATION,
    )
    agent = StudyFlowAgent(
        FakeStructuredLLM(
            [
                {
                    "tasks": [
                        {
                            "step_key": "research",
                            "name": "Research the presentation topic",
                            "duration_minutes": 75,
                            "priority": 3,
                            "dependency_keys": [],
                        },
                        {
                            "step_key": "draft",
                            "name": "Draft the presentation storyline",
                            "duration_minutes": 60,
                            "priority": 4,
                            "dependency_keys": ["research"],
                        },
                        {
                            "step_key": "slides",
                            "name": "Build the presentation slides",
                            "duration_minutes": 90,
                            "priority": 4,
                            "dependency_keys": ["draft"],
                        },
                        {
                            "step_key": "rehearsal",
                            "name": "Rehearse the presentation",
                            "duration_minutes": 45,
                            "priority": 5,
                            "dependency_keys": ["slides"],
                        },
                    ]
                }
            ]
        )
    )

    tasks = agent.decompose_assessment(presentation)

    assert [task.name for task in tasks] == [
        "Research the presentation topic",
        "Draft the presentation storyline",
        "Build the presentation slides",
        "Rehearse the presentation",
    ]
    assert tasks[0].dependencies == []
    for previous, current in zip(tasks, tasks[1:]):
        assert current.dependencies == [previous.id]
    assert validate_task_graph(tasks) == tasks


@pytest.mark.parametrize(
    "fake_response",
    [
        RuntimeError("provider unavailable"),
        {
            "tasks": [
                {
                    "step_key": "invalid_duration",
                    "name": "Attempt an invalid task",
                    "duration_minutes": 0,
                    "priority": 3,
                    "dependency_keys": [],
                }
            ]
        },
        {
            "tasks": [
                {
                    "step_key": "outline",
                    "name": "Create the outline",
                    "duration_minutes": 60,
                    "priority": 3,
                    "dependency_keys": ["missing"],
                }
            ]
        },
        {
            "tasks": [
                {
                    "step_key": "outline",
                    "name": "Create the outline",
                    "duration_minutes": 60,
                    "priority": 3,
                    "dependency_keys": ["slides"],
                },
                {
                    "step_key": "slides",
                    "name": "Build the slides",
                    "duration_minutes": 120,
                    "priority": 4,
                    "dependency_keys": ["outline"],
                },
            ]
        },
        {
            "tasks": [
                {
                    "step_key": "outline",
                    "name": "Create the outline",
                    "duration_minutes": 60,
                    "priority": 3,
                    "dependency_keys": [],
                    "unexpected_field": "must be rejected",
                }
            ]
        },
        {
            "tasks": [
                {
                    "step_key": "outline",
                    "name": "Create the outline",
                    "duration_minutes": 60,
                    "priority": 3,
                    "dependency_keys": [],
                },
                {
                    "step_key": "outline",
                    "name": "Create another outline",
                    "duration_minutes": 30,
                    "priority": 2,
                    "dependency_keys": [],
                },
            ]
        },
        {
            "tasks": [
                {
                    "step_key": "outline",
                    "name": "Create the outline",
                    "duration_minutes": 60,
                    "priority": 3,
                    "dependency_keys": ["outline"],
                }
            ]
        },
        {
            "tasks": [
                {
                    "step_key": "outline",
                    "name": "Create the outline",
                    "duration_minutes": 60,
                    "priority": 3,
                    "dependency_keys": [],
                },
                {
                    "step_key": "slides",
                    "name": "Build the slides",
                    "duration_minutes": 120,
                    "priority": 4,
                    "dependency_keys": ["outline", "outline"],
                },
            ]
        },
    ],
    ids=[
        "provider_error",
        "invalid_schema",
        "unknown_dependency",
        "cycle",
        "extra_field",
        "duplicate_step_key",
        "self_dependency",
        "duplicate_dependency",
    ],
)
def test_llm_failures_and_invalid_graphs_use_complete_fallback(
    fake_response: object,
) -> None:
    presentation = assessment_of_type(
        MockDataStore().list_assessments(),
        AssessmentType.PRESENTATION,
    )
    agent = StudyFlowAgent(FakeStructuredLLM([fake_response]))

    tasks = agent.decompose_assessment(presentation)

    assert len(tasks) == 5
    assert tasks[0].name == "Confirm presentation requirements, missing details and group roles"
    assert tasks[-1].name == "Run a timed group rehearsal and revise"
    assert validate_task_graph(tasks) == tasks


def task_event(event_type: PlanningEventType, reference_id: str) -> PlanningEvent:
    return PlanningEvent(
        id=f"test-{event_type.value}",
        event_type=event_type,
        timestamp="2026-09-04T12:05:00+08:00",
        reference_id=reference_id,
    )


def test_missed_task_affects_itself_and_transitive_dependents() -> None:
    tasks = [
        task.model_copy(update={"status": TaskStatus.MISSED})
        if task.id == "task-presentation-slides" else task
        for task in MockDataStore().list_tasks()
    ]
    agent = StudyFlowAgent()

    affected = agent.find_affected_task_ids(
        task_event(PlanningEventType.TASK_MISSED, "task-presentation-slides"),
        tasks,
    )

    assert affected == {
        "task-presentation-slides",
        "task-presentation-script",
        "task-presentation-rehearsal",
    }


def test_missed_task_excludes_completed_and_unrelated_tasks() -> None:
    statuses = {
        "task-presentation-rehearsal": TaskStatus.COMPLETED,
        "task-presentation-slides": TaskStatus.MISSED,
    }
    tasks = [
        task.model_copy(update={"status": statuses.get(task.id, task.status)})
        for task in MockDataStore().list_tasks()
    ]

    affected = StudyFlowAgent().find_affected_task_ids(
        task_event(PlanningEventType.TASK_MISSED, "task-presentation-slides"),
        tasks,
    )

    assert affected == {
        "task-presentation-slides",
        "task-presentation-script",
    }


def test_completed_task_affects_only_incomplete_dependents() -> None:
    tasks = [
        task.model_copy(update={"status": TaskStatus.COMPLETED})
        if task.id == "task-presentation-outline" else task
        for task in MockDataStore().list_tasks()
    ]
    agent = StudyFlowAgent()

    affected = agent.find_affected_task_ids(
        task_event(
            PlanningEventType.TASK_COMPLETED,
            "task-presentation-outline",
        ),
        tasks,
    )

    assert affected == {
        "task-presentation-slides",
        "task-presentation-script",
        "task-presentation-rehearsal",
    }


def test_assessment_and_calendar_events_select_incomplete_work() -> None:
    tasks = MockDataStore().list_tasks()
    agent = StudyFlowAgent()

    assessment_affected = agent.find_affected_task_ids(
        task_event(
            PlanningEventType.ASSESSMENT_UPDATED,
            "assessment-presentation-ai-ethics",
        ),
        tasks,
    )
    calendar_affected = agent.find_affected_task_ids(
        task_event(PlanningEventType.CALENDAR_CHANGED, "calendar-lecture-mon"),
        tasks,
    )

    assert "task-presentation-requirements" not in assessment_affected
    assert assessment_affected == {
        task.id
        for task in tasks
        if task.assessment_id == "assessment-presentation-ai-ethics"
        and task.status is not TaskStatus.COMPLETED
    }
    assert calendar_affected == {
        task.id for task in tasks if task.status is not TaskStatus.COMPLETED
    }


def test_task_event_rejects_unknown_reference() -> None:
    with pytest.raises(ValueError, match="references unknown task"):
        StudyFlowAgent().find_affected_task_ids(
            task_event(PlanningEventType.TASK_MISSED, "task-missing"),
            MockDataStore().list_tasks(),
        )
