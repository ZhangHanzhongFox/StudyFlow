"""Assessment reconciliation using the existing Agent and Scheduler contracts."""

from uuid import NAMESPACE_URL, uuid5
from typing import TYPE_CHECKING

from backend.schemas import Assessment, Flexibility, PlanningEvent, ScheduledTask, Task, TaskStatus, validate_task_graph
from .state import PlanningStateValidationError

if TYPE_CHECKING:
    from .planning import PlanningPipeline


class AssessmentConflictError(ValueError):
    """A change requires an explicit decision about protected work."""


def reconcile(assessment: Assessment, previous: Assessment | None,
              tasks: list[Task], schedule: list[ScheduledTask], events: list[PlanningEvent],
              event: PlanningEvent, pipeline: "PlanningPipeline") -> list[Task]:
    # Timing/grade metadata changes do not reinterpret requirements.
    fields = ("title", "description", "type", "course_code", "is_group", "group_size")
    if previous is not None and all(
        getattr(previous, field) == getattr(assessment, field) for field in fields
    ):
        return tasks
    old = {t.id: t for t in tasks if t.assessment_id == assessment.id}
    if any(t.status is TaskStatus.IN_PROGRESS for t in old.values()) or any(
        s.task_id in old and s.flexibility is Flexibility.HARD
        and old[s.task_id].status is not TaskStatus.COMPLETED for s in schedule
    ):
        raise AssessmentConflictError("requirements change conflicts with in-progress or hard work")
    try:
        generated = [Task.model_validate(t.model_dump())
                     for t in pipeline.agent.decompose_assessment(assessment.model_copy(deep=True))]
        if not generated or any(t.assessment_id != assessment.id or
                                t.status is not TaskStatus.PENDING for t in generated):
            raise ValueError("invalid generated tasks")
        validate_task_graph(generated)
    except (ValueError, AttributeError) as error:
        raise PlanningStateValidationError("invalid assessment decomposition") from error
    protected = {t.id for t in old.values() if t.status is TaskStatus.COMPLETED}
    # Historical completed task graphs remain intact, never rewritten by an Agent.
    pending = list(protected)
    while pending:
        for dependency in old[pending.pop()].dependencies:
            if dependency not in protected:
                protected.add(dependency)
                pending.append(dependency)
    removed = set(old) - protected
    if any(e.reference_id in removed for e in events):
        raise AssessmentConflictError("requirements change would remove observed task history")
    if previous is not None:
        ids = {t.id: "task-" + str(uuid5(NAMESPACE_URL, f"{event.id}/{t.id}"))
               for t in generated}
        generated = [t.model_copy(update={"id": ids[t.id],
                     "dependencies": [ids[d] for d in t.dependencies]}) for t in generated]
    return [t for t in tasks if t.assessment_id != assessment.id or t.id in protected] + generated
