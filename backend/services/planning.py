"""Application-level orchestration across agent and scheduler boundaries."""

from collections.abc import Sequence
from dataclasses import dataclass

from backend.agents import AgentWorkflow
from backend.scheduler import Scheduler, SchedulingResult
from backend.schemas import (
    Assessment,
    CalendarBlock,
    PlanningEvent,
    PlanningEventType,
    ScheduledTask,
    Task,
    validate_task_graph,
)


@dataclass(frozen=True)
class PlanningRun:
    """Non-persisted artifacts from one complete planning run."""

    assessments: list[Assessment]
    tasks: list[Task]
    result: SchedulingResult


class PlanningPipeline:
    """Connect normalized assessments, agent decomposition, and scheduling."""

    def __init__(self, agent: AgentWorkflow, scheduler: Scheduler) -> None:
        self.agent = agent
        self.scheduler = scheduler

    def plan(
        self,
        assessments: Sequence[Assessment],
        calendar_blocks: Sequence[CalendarBlock],
        existing_schedule: Sequence[ScheduledTask] = (),
    ) -> SchedulingResult:
        return self.run_plan(
            assessments,
            calendar_blocks,
            existing_schedule,
        ).result

    def run_plan(
        self,
        assessments: Sequence[Assessment],
        calendar_blocks: Sequence[CalendarBlock],
        existing_schedule: Sequence[ScheduledTask] = (),
    ) -> PlanningRun:
        """Return generated tasks as well as the scheduler response for state."""

        classified_assessments = [
            assessment.model_copy(
                update={"type": self.agent.classify_assessment(assessment)}
            )
            for assessment in assessments
        ]
        tasks = [
            task
            for assessment in classified_assessments
            for task in self.agent.decompose_assessment(assessment)
        ]
        validate_task_graph(tasks)
        result = self.scheduler.schedule_tasks(
            classified_assessments,
            tasks,
            calendar_blocks,
            existing_schedule,
        )
        return PlanningRun(
            assessments=classified_assessments,
            tasks=tasks,
            result=result,
        )

    def replan(
        self,
        event: PlanningEvent,
        assessments: Sequence[Assessment],
        tasks: Sequence[Task],
        calendar_blocks: Sequence[CalendarBlock],
        existing_schedule: Sequence[ScheduledTask],
    ) -> SchedulingResult:
        validate_task_graph(tasks)
        affected_task_ids = self.agent.find_affected_task_ids(event, tasks)
        return self.scheduler.reschedule_tasks(
            assessments,
            tasks,
            calendar_blocks,
            existing_schedule,
            affected_task_ids,
            replanning_start=event.timestamp,
            preserve_valid_affected=(
                event.event_type is PlanningEventType.CALENDAR_CHANGED
            ),
        )
