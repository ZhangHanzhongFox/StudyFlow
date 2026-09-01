"""Actionable task contract and dependency-graph validation."""

from collections.abc import Iterable
from enum import Enum

from pydantic import Field, model_validator

from . import NonEmptyStr, StudyFlowBaseModel


class TaskStatus(str, Enum):
    """Execution states for an actionable task."""

    PENDING = "pending"
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    MISSED = "missed"


class Task(StudyFlowBaseModel):
    """An actionable unit produced by decomposing one assessment."""

    id: NonEmptyStr
    assessment_id: NonEmptyStr
    name: NonEmptyStr
    duration_minutes: int = Field(gt=0)
    dependencies: list[NonEmptyStr]
    priority: int
    status: TaskStatus

    @model_validator(mode="after")
    def validate_local_dependencies(self) -> "Task":
        if self.id in self.dependencies:
            raise ValueError("a task cannot depend on itself")
        if len(self.dependencies) != len(set(self.dependencies)):
            raise ValueError("task dependencies must be unique")
        return self


def validate_task_graph(tasks: Iterable[Task]) -> list[Task]:
    """Validate task references, assessment boundaries, and graph acyclicity.

    This function must receive the complete task collection at an ingestion or
    planning boundary. A single ``Task`` cannot validate references to records
    that it cannot see.
    """

    task_list = list(tasks)
    tasks_by_id: dict[str, Task] = {}

    for task in task_list:
        if task.id in tasks_by_id:
            raise ValueError(f"duplicate task id: {task.id}")
        tasks_by_id[task.id] = task

    for task in task_list:
        for dependency_id in task.dependencies:
            dependency = tasks_by_id.get(dependency_id)
            if dependency is None:
                raise ValueError(
                    f"task {task.id} references unknown dependency {dependency_id}"
                )
            if dependency.assessment_id != task.assessment_id:
                raise ValueError(
                    f"task {task.id} depends on a task from another assessment"
                )

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str) -> None:
        if task_id in visiting:
            raise ValueError("task dependency graph must be acyclic")
        if task_id in visited:
            return

        visiting.add(task_id)
        for dependency_id in tasks_by_id[task_id].dependencies:
            visit(dependency_id)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in tasks_by_id:
        visit(task_id)

    return task_list
