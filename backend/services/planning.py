"""Application-level orchestration across agent and scheduler boundaries."""

from collections.abc import Sequence

from backend.agents import AgentWorkflow
from backend.scheduler import Scheduler, SchedulingResult
from backend.schemas import (
    Assessment,
    CalendarBlock,
    PlanningEvent,
    ScheduledTask,
    Task,
    validate_task_graph,
)


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
        return self.scheduler.schedule_tasks(
            classified_assessments,
            tasks,
            calendar_blocks,
            existing_schedule,
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
        )
