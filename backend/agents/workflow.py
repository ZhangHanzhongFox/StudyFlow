"""Concrete StudyFlow assessment classification and decomposition workflow."""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ValidationError

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
        "Confirm presentation requirements and missing details",
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
        "Prepare and review presentation materials",
        60,
        4,
        ("outline",),
    ),
    TemplateStep(
        "script",
        "Write and review speaker notes",
        90,
        4,
        ("slides",),
    ),
    TemplateStep(
        "rehearsal",
        "Run a timed rehearsal and revise",
        60,
        5,
        ("script",),
    ),
)

EXAM_TEMPLATE = (
    TemplateStep(
        "scope",
        "Confirm assessment scope and learning outcomes",
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
        "Confirm the assignment specification and missing requirements",
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
        "Debug edge cases and review the implementation",
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
            logger.info(
                "Agent classification assessment_id=%r reason=normalized_type "
                "assessment_type=%s: Using the supplied normalized type; no LLM configured.",
                assessment.id, assessment.type.value,
            )
            return assessment.type

        failure_reason = "provider_output_unavailable"
        try:
            output = self.llm.generate(
                system_prompt=CLASSIFICATION_SYSTEM_PROMPT,
                user_prompt=assessment_prompt(assessment),
                response_model=ClassificationOutput,
            )
            failure_reason = "invalid_structure"
            output = ClassificationOutput.model_validate(
                output.model_dump(warnings="none")
                if isinstance(output, BaseModel) else output
            )
            logger.info(
                "Agent classification assessment_id=%r reason=validated_llm "
                "assessment_type=%s: Structured classification passed validation.",
                assessment.id, output.assessment_type.value,
            )
            return output.assessment_type
        except Exception as error:  # Provider and schema failures share fallback.
            self._log_fallback(assessment.id, "classification", error, failure_reason)
            return assessment.type

    def decompose_assessment(self, assessment: Assessment) -> list[Task]:
        """Produce canonical tasks from structured output or a stable template."""

        if self.llm is not None:
            failure_reason = "provider_output_unavailable"
            try:
                output = self.llm.generate(
                    system_prompt=DECOMPOSITION_SYSTEM_PROMPT,
                    user_prompt=assessment_prompt(assessment),
                    response_model=DecompositionOutput,
                )
                # A provider's model instance may have been constructed or mutated
                # without validation. Rebuild nested drafts from plain data too.
                failure_reason = "invalid_structure"
                output = DecompositionOutput.model_validate(
                    output.model_dump(warnings="none")
                    if isinstance(output, BaseModel) else output
                )
                failure_reason = "invalid_dependencies"
                tasks = self._build_tasks(assessment, output.tasks)
                self._log_decomposition(assessment, tasks, "validated_llm")
                return tasks
            except Exception as error:  # Invalid graphs also use full fallback.
                self._log_fallback(assessment.id, "decomposition", error, failure_reason)

        template_drafts = [
            TaskDraft(
                step_key=step.step_key,
                name=self._template_name(assessment, step),
                duration_minutes=step.duration_minutes,
                priority=step.priority,
                dependency_keys=list(step.dependency_keys),
            )
            for step in TEMPLATES[assessment.type]
        ]
        tasks = self._build_tasks(assessment, template_drafts)
        self._log_decomposition(
            assessment, tasks,
            "template_default" if self.llm is None else "template_fallback",
        )
        return tasks

    @staticmethod
    def _template_name(assessment: Assessment, step: TemplateStep) -> str:
        if assessment.type is AssessmentType.PRESENTATION and assessment.is_group:
            if step.step_key == "requirements":
                return "Confirm presentation requirements, missing details and group roles"
            if step.step_key == "rehearsal":
                return "Run a timed group rehearsal and revise"
        return step.name

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
            self._log_impact(event, incomplete_ids, "calendar_candidates")
            return incomplete_ids

        if event.event_type in {
            PlanningEventType.NEW_ASSESSMENT,
            PlanningEventType.ASSESSMENT_UPDATED,
        }:
            affected = {
                task.id
                for task in task_list
                if task.assessment_id == event.reference_id
                and task.status is not TaskStatus.COMPLETED
            }
            self._log_impact(event, affected, "assessment_candidates")
            return affected

        referenced_task = tasks_by_id.get(event.reference_id)
        if referenced_task is None:
            raise ValueError(
                f"{event.event_type.value} references unknown task: "
                f"{event.reference_id}"
            )

        parents: dict[str, str] = {}
        descendants = self._find_descendant_ids(
            referenced_task.id, task_list, parents=parents,
        )
        affected_descendants = descendants & incomplete_ids
        if event.event_type is PlanningEventType.TASK_MISSED:
            if referenced_task.id in incomplete_ids:
                affected_descendants.add(referenced_task.id)
        self._log_impact(event, affected_descendants, "dependency_candidates", parents)
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
    def _find_descendant_ids(
        task_id: str,
        tasks: Sequence[Task],
        *,
        parents: dict[str, str] | None = None,
    ) -> set[str]:
        dependents_by_id: dict[str, set[str]] = {
            task.id: set() for task in tasks
        }
        for task in tasks:
            for dependency_id in task.dependencies:
                dependents_by_id[dependency_id].add(task.id)

        descendants: set[str] = set()
        pending = [
            (task_id, child)
            for child in sorted(dependents_by_id[task_id], reverse=True)
        ]
        while pending:
            parent_id, descendant_id = pending.pop()
            if descendant_id in descendants:
                continue
            descendants.add(descendant_id)
            if parents is not None:
                parents[descendant_id] = parent_id
            pending.extend(
                (descendant_id, child)
                for child in sorted(dependents_by_id[descendant_id], reverse=True)
            )
        return descendants

    @staticmethod
    def _log_decomposition(
        assessment: Assessment, tasks: Sequence[Task], source: str,
    ) -> None:
        template_reasons = {
            AssessmentType.PRESENTATION: (
                "Confirm requirements, outline, prepare materials and notes, then rehearse."
            ),
            AssessmentType.EXAM: "Confirm scope, consolidate notes, practise, then review weak topics.",
            AssessmentType.MIDTERM: "Confirm scope, consolidate notes, practise, then review weak topics.",
            AssessmentType.CODING_ASSIGNMENT: (
                "Confirm requirements, design, implement, test, review, then submit."
            ),
            AssessmentType.QUIZ: "Review course material before taking the quiz.",
        }
        explanation = (
            "Using validated LLM preparation steps and their dependency order."
            if source == "validated_llm" else
            "Using the assessment-type template: " + template_reasons[assessment.type]
        )
        logger.info(
            "Agent decomposition assessment_id=%r assessment_type=%s reason=%s "
            "task_count=%d description=%s: %s Durations are planning estimates, "
            "not assessment facts.",
            assessment.id, assessment.type.value, source, len(tasks),
            "provided" if assessment.description.strip() else "missing",
            explanation,
        )
        # IDs/edges describe the actual output, without logging provider task text.
        for task in tasks:
            logger.info(
                "Agent preparation assessment_id=%r task_id=%r depends_on=%r: %s",
                assessment.id, task.id, task.dependencies,
                "Prepare after these prerequisites." if task.dependencies
                else "Preparation can start without task prerequisites.",
            )

    @staticmethod
    def _log_impact(
        event: PlanningEvent,
        affected: set[str],
        reason: str,
        parents: dict[str, str] | None = None,
    ) -> None:
        explanations = {
            "calendar_candidates": "Recheck incomplete work against the supplied calendar.",
            "assessment_candidates": (
                "Recheck this assessment's incomplete work; the event contains no requirement diff."
            ),
            "dependency_candidates": "Recheck the referenced missed task and/or incomplete downstream work.",
        }
        logger.info(
            "Agent impact event_id=%r event_type=%s reference_id=%r reason=%s "
            "candidate_count=%d: %s Candidates are not confirmed schedule moves.",
            event.id, event.event_type.value, event.reference_id, reason,
            len(affected), explanations[reason],
        )
        if parents is None or not logger.isEnabledFor(logging.INFO):
            return
        for task_id in sorted(affected):
            path = [task_id]
            while path[-1] in parents:
                path.append(parents[path[-1]])
            logger.info(
                "Agent impact candidate event_id=%r task_id=%r dependency_path=%r: %s",
                event.id, task_id, list(reversed(path)),
                "The missed event directly references this incomplete task."
                if task_id == event.reference_id else
                "This incomplete task depends transitively on the referenced task.",
            )

    @staticmethod
    def _log_fallback(
        assessment_id: str,
        operation: str,
        error: Exception,
        reason: str,
    ) -> None:
        if isinstance(error, ValidationError):
            reason = "invalid_structure"
        explanations = {
            "provider_output_unavailable": "The provider could not supply a usable structured result.",
            "invalid_structure": "The structured result failed field or value validation.",
            "invalid_dependencies": "The generated dependency graph failed validation.",
        }
        logger.warning(
            "structured LLM %s failed; using deterministic fallback "
            "assessment_id=%r error_type=%s reason=%s: %s",
            operation,
            assessment_id,
            type(error).__name__,
            reason,
            explanations[reason],
        )
