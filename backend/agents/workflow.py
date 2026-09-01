"""Concrete StudyFlow assessment classification and decomposition workflow."""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

from backend.schemas import (
    Assessment,
    AssessmentType,
    PlanningEvent,
    PlanningEventType,
    Task,
    TaskStatus,
    validate_task_graph,
)

from .llm import (
    ClassificationOutput,
    DecompositionOutput,
    StructuredLLM,
    TaskDraft,
)
from .prompts import (
    CLASSIFICATION_SYSTEM_PROMPT,
    DECOMPOSITION_SYSTEM_PROMPT,
    assessment_prompt,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TemplateStep:
    """One deterministic step in an assessment workflow template."""

    step_key: str
    name: str
    duration_minutes: int
    priority: int
    dependency_keys: tuple[str, ...] = ()


PRESENTATION_TEMPLATE = (
    TemplateStep(
        "requirements",
        "Extract presentation requirements and assign roles",
        30,
        3,
    ),
    TemplateStep(
        "outline",
        "Create the presentation storyline and outline",
        30,
        3,
        ("requirements",),
    ),
    TemplateStep(
        "slides",
        "Build and review the presentation slides",
        60,
        4,
        ("outline",),
    ),
    TemplateStep(
        "script",
        "Write speaker notes and demo script",
        90,
        4,
        ("slides",),
    ),
    TemplateStep(
        "rehearsal",
        "Run a timed group rehearsal",
        60,
        5,
        ("script",),
    ),
)

EXAM_TEMPLATE = (
    TemplateStep(
        "scope",
        "Review the assessment scope and learning outcomes",
        30,
        4,
    ),
    TemplateStep(
        "notes",
        "Consolidate notes and topic summaries",
        120,
        4,
        ("scope",),
    ),
    TemplateStep(
        "practice_and_mock",
        "Complete practice problems and a mock exam",
        180,
        5,
        ("notes",),
    ),
    TemplateStep(
        "final_review",
        "Complete a final review of weak topics",
        60,
        5,
        ("practice_and_mock",),
    ),
)

CODING_ASSIGNMENT_TEMPLATE = (
    TemplateStep(
        "read_spec",
        "Read the assignment specification and acceptance criteria",
        15,
        2,
    ),
    TemplateStep(
        "design",
        "Design the implementation and interfaces",
        30,
        3,
        ("read_spec",),
    ),
    TemplateStep(
        "implement",
        "Implement the assignment requirements",
        120,
        3,
        ("design",),
    ),
    TemplateStep(
        "tests",
        "Write automated tests for the implementation",
        60,
        3,
        ("implement",),
    ),
    TemplateStep(
        "refine",
        "Debug edge cases and write the design note",
        60,
        4,
        ("tests",),
    ),
    TemplateStep(
        "submit",
        "Run final checks and submit the assignment",
        30,
        5,
        ("refine",),
    ),
)

QUIZ_TEMPLATE = (
    TemplateStep(
        "review",
        "Review the relevant course material",
        30,
        3,
    ),
    TemplateStep(
        "take_quiz",
        "Take the quiz",
        30,
        4,
        ("review",),
    ),
)

TEMPLATES = {
    AssessmentType.PRESENTATION: PRESENTATION_TEMPLATE,
    AssessmentType.EXAM: EXAM_TEMPLATE,
    AssessmentType.MIDTERM: EXAM_TEMPLATE,
    AssessmentType.CODING_ASSIGNMENT: CODING_ASSIGNMENT_TEMPLATE,
    AssessmentType.QUIZ: QUIZ_TEMPLATE,
}


class StudyFlowAgent:
    """Agent workflow with validated LLM output and deterministic fallback."""

    def __init__(self, llm: StructuredLLM | None = None) -> None:
        self.llm = llm

    def classify_assessment(self, assessment: Assessment) -> AssessmentType:
        """Return a canonical assessment type, falling back to normalized input."""

        if self.llm is None:
            return assessment.type

        try:
            output = self.llm.generate(
                system_prompt=CLASSIFICATION_SYSTEM_PROMPT,
                user_prompt=assessment_prompt(assessment),
                response_model=ClassificationOutput,
            )
            return output.assessment_type
        except Exception as error:  # Provider and schema failures share fallback.
            self._log_fallback(assessment.id, "classification", error)
            return assessment.type

    def decompose_assessment(self, assessment: Assessment) -> list[Task]:
        """Produce canonical tasks from structured output or a stable template."""

        if self.llm is not None:
            try:
                output = self.llm.generate(
                    system_prompt=DECOMPOSITION_SYSTEM_PROMPT,
                    user_prompt=assessment_prompt(assessment),
                    response_model=DecompositionOutput,
                )
                return self._build_tasks(assessment, output.tasks)
            except Exception as error:  # Invalid graphs also use full fallback.
                self._log_fallback(assessment.id, "decomposition", error)

        template_drafts = [
            TaskDraft(
                step_key=step.step_key,
                name=step.name,
                duration_minutes=step.duration_minutes,
                priority=step.priority,
                dependency_keys=list(step.dependency_keys),
            )
            for step in TEMPLATES[assessment.type]
        ]
        return self._build_tasks(assessment, template_drafts)

    def find_affected_task_ids(
        self,
        event: PlanningEvent,
        tasks: Sequence[Task],
    ) -> set[str]:
        """Find incomplete tasks whose placements may need reconsideration."""

        task_list = validate_task_graph(tasks)
        tasks_by_id = {task.id: task for task in task_list}
        incomplete_ids = {
            task.id for task in task_list if task.status is not TaskStatus.COMPLETED
        }

        if event.event_type is PlanningEventType.CALENDAR_CHANGED:
            return incomplete_ids

        if event.event_type in {
            PlanningEventType.NEW_ASSESSMENT,
            PlanningEventType.ASSESSMENT_UPDATED,
        }:
            return {
                task.id
                for task in task_list
                if task.assessment_id == event.reference_id
                and task.status is not TaskStatus.COMPLETED
            }

        referenced_task = tasks_by_id.get(event.reference_id)
        if referenced_task is None:
            raise ValueError(
                f"{event.event_type.value} references unknown task: "
                f"{event.reference_id}"
            )

        descendants = self._find_descendant_ids(referenced_task.id, task_list)
        affected_descendants = descendants & incomplete_ids
        if event.event_type is PlanningEventType.TASK_MISSED:
            affected_descendants.add(referenced_task.id)
        return affected_descendants

    @staticmethod
    def _task_id(assessment_id: str, step_key: str) -> str:
        stable_uuid = uuid5(
            NAMESPACE_URL,
            f"https://studyflow.local/tasks/{assessment_id}/{step_key}",
        )
        return f"task-{stable_uuid}"

    def _build_tasks(
        self,
        assessment: Assessment,
        drafts: Sequence[TaskDraft],
    ) -> list[Task]:
        ids_by_key = {
            draft.step_key: self._task_id(assessment.id, draft.step_key)
            for draft in drafts
        }

        tasks: list[Task] = []
        for draft in drafts:
            unknown_keys = set(draft.dependency_keys) - ids_by_key.keys()
            if unknown_keys:
                unknown = ", ".join(sorted(unknown_keys))
                raise ValueError(
                    f"task draft {draft.step_key} references unknown "
                    f"dependencies: {unknown}"
                )
            tasks.append(
                Task(
                    id=ids_by_key[draft.step_key],
                    assessment_id=assessment.id,
                    name=draft.name,
                    duration_minutes=draft.duration_minutes,
                    dependencies=[
                        ids_by_key[key] for key in draft.dependency_keys
                    ],
                    priority=draft.priority,
                    status=TaskStatus.PENDING,
                )
            )

        return validate_task_graph(tasks)

    @staticmethod
    def _find_descendant_ids(task_id: str, tasks: Sequence[Task]) -> set[str]:
        dependents_by_id: dict[str, set[str]] = {
            task.id: set() for task in tasks
        }
        for task in tasks:
            for dependency_id in task.dependencies:
                dependents_by_id[dependency_id].add(task.id)

        descendants: set[str] = set()
        pending = list(dependents_by_id[task_id])
        while pending:
            descendant_id = pending.pop()
            if descendant_id in descendants:
                continue
            descendants.add(descendant_id)
            pending.extend(dependents_by_id[descendant_id])
        return descendants

    @staticmethod
    def _log_fallback(
        assessment_id: str,
        operation: str,
        error: Exception,
    ) -> None:
        logger.warning(
            "structured LLM %s failed; using deterministic fallback "
            "assessment_id=%s error_type=%s",
            operation,
            assessment_id,
            type(error).__name__,
        )
