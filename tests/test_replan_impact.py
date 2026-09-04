"""Role A acceptance: exact dependency impact and its real replan handoff."""

from collections.abc import Sequence
from datetime import datetime, timedelta

import pytest

from backend.agents import StudyFlowAgent
from backend.main import create_app
from backend.scheduler import SchedulingResult, StudyScheduler
from backend.schemas import (
    Assessment,
    AssessmentType,
    CalendarBlock,
    Flexibility,
    PlanningEvent,
    PlanningEventType,
    ScheduledTask,
    Task,
    TaskStatus,
)
from backend.services import PlanningPipeline, PlanningState
from tests.test_default_runtime import request


def at(time: str) -> datetime:
    """Fixed September 3 demo clock in Singapore's UTC+08:00 offset."""
    return datetime.fromisoformat(f"2026-09-03T{time}:00+08:00")


def make_task(
    task_id: str,
    dependencies: tuple[str, ...] = (),
    status: TaskStatus = TaskStatus.SCHEDULED,
    assessment_id: str = "assessment-main",
) -> Task:
    return Task(
        id=task_id,
        assessment_id=assessment_id,
        name=task_id,
        duration_minutes=30,
        dependencies=list(dependencies),
        priority=3,
        status=status,
    )


@pytest.fixture
def complex_tasks() -> list[Task]:
    # root -> trigger -> {left, right} -> join -> tail
    # co-parent -> join; root -> sibling; independent and other are isolated.
    return [
        make_task("root", status=TaskStatus.COMPLETED),
        make_task("trigger", ("root",)),
        make_task("left", ("trigger",), TaskStatus.PENDING),
        make_task("right", ("trigger",), TaskStatus.IN_PROGRESS),
        make_task("join", ("left", "right", "co-parent")),
        make_task("tail", ("join",), TaskStatus.MISSED),
        make_task("co-parent"),
        make_task("sibling", ("root",)),
        make_task("independent"),
        make_task("other", assessment_id="assessment-other"),
    ]


def task_event(
    event_type: PlanningEventType,
    reference_id: str = "trigger",
) -> PlanningEvent:
    return PlanningEvent(
        id=f"event-impact-{event_type.value}-{reference_id}",
        event_type=event_type,
        timestamp=at("10:30"),
        reference_id=reference_id,
    )


def staged_tasks(tasks: Sequence[Task], event: PlanningEvent) -> list[Task]:
    """Prepare the already-applied task status required at A's boundary."""
    status = {
        PlanningEventType.TASK_MISSED: TaskStatus.MISSED,
        PlanningEventType.TASK_COMPLETED: TaskStatus.COMPLETED,
    }[event.event_type]
    return [
        task.model_copy(
            deep=True,
            update={"status": status} if task.id == event.reference_id else {},
        )
        for task in tasks
    ]


@pytest.mark.parametrize(
    ("event_type", "expected"),
    [
        (PlanningEventType.TASK_MISSED, {"trigger", "left", "right", "join", "tail"}),
        (PlanningEventType.TASK_COMPLETED, {"left", "right", "join", "tail"}),
    ],
)
@pytest.mark.parametrize("reverse_input", [False, True], ids=["forward", "reverse"])
def test_complex_impact_is_exact_stable_and_read_only(
    complex_tasks: list[Task],
    event_type: PlanningEventType,
    expected: set[str],
    reverse_input: bool,
) -> None:
    event = task_event(event_type)
    tasks = staged_tasks(complex_tasks, event)
    if reverse_input:
        tasks.reverse()
    before_tasks = [task.model_dump() for task in tasks]
    before_event = event.model_dump()
    agent = StudyFlowAgent()

    # Exact sets catch reverse propagation to co-parent, ancestors, siblings,
    # unrelated work in either assessment, and missed third-level descendants.
    assert agent.find_affected_task_ids(event, tasks) == expected
    assert agent.find_affected_task_ids(event, tasks) == expected
    assert [task.model_dump() for task in tasks] == before_tasks
    assert event.model_dump() == before_event


@pytest.mark.parametrize(
    ("event_type", "expected"),
    [
        (
            PlanningEventType.TASK_MISSED,
            {"trigger", "left", "right", "join", "tail", "after-bridge"},
        ),
        (
            PlanningEventType.TASK_COMPLETED,
            {"left", "right", "join", "tail", "after-bridge"},
        ),
    ],
)
def test_completed_descendants_are_excluded_without_cutting_traversal(
    complex_tasks: list[Task],
    event_type: PlanningEventType,
    expected: set[str],
) -> None:
    # This is a graph-analysis boundary case, not a chronological execution
    # example: completed work is trusted even when an ancestor is unfinished.
    tasks = [
        *complex_tasks,
        make_task("done-leaf", ("trigger",), TaskStatus.COMPLETED),
        make_task("done-bridge", ("trigger",), TaskStatus.COMPLETED),
        make_task("after-bridge", ("done-bridge",), TaskStatus.PENDING),
    ]
    event = task_event(event_type)

    affected = StudyFlowAgent().find_affected_task_ids(
        event, staged_tasks(tasks, event),
    )

    assert affected == expected


@pytest.mark.parametrize(
    ("event_type", "expected"),
    [
        (PlanningEventType.TASK_MISSED, {"tail"}),
        (PlanningEventType.TASK_COMPLETED, set()),
    ],
)
def test_leaf_event_does_not_propagate_upstream(
    complex_tasks: list[Task],
    event_type: PlanningEventType,
    expected: set[str],
) -> None:
    event = task_event(event_type, "tail")

    affected = StudyFlowAgent().find_affected_task_ids(
        event, staged_tasks(complex_tasks, event),
    )

    assert affected == expected


@pytest.mark.parametrize("event_type", [PlanningEventType.TASK_MISSED, PlanningEventType.TASK_COMPLETED])
def test_logged_impact_paths_are_real_and_cross_completed_bridges(
    complex_tasks: list[Task], event_type: PlanningEventType, caplog,
) -> None:
    tasks = [
        *complex_tasks,
        make_task("done-bridge", ("trigger",), TaskStatus.COMPLETED),
        make_task("after-bridge", ("done-bridge",), TaskStatus.PENDING),
    ]
    event = task_event(event_type)
    tasks = staged_tasks(tasks, event)
    tasks_by_id = {task.id: task for task in tasks}
    with caplog.at_level("INFO", logger="backend.agents.workflow"):
        affected = StudyFlowAgent().find_affected_task_ids(event, tasks)
    records = [record for record in caplog.records if record.msg.startswith("Agent impact candidate")]
    assert {record.args[1] for record in records} == affected
    paths = {record.args[1]: record.args[2] for record in records}
    assert paths["after-bridge"] == ["trigger", "done-bridge", "after-bridge"]
    assert paths["tail"] == ["trigger", "left", "join", "tail"]
    for task_id, path in paths.items():
        assert tasks_by_id[task_id].status is not TaskStatus.COMPLETED
        assert path[0] == "trigger" and path[-1] == task_id
        for parent, child in zip(path, path[1:]):
            assert parent in tasks_by_id[child].dependencies
    original_messages = [record.getMessage() for record in caplog.records]
    caplog.clear()
    with caplog.at_level("INFO", logger="backend.agents.workflow"):
        assert StudyFlowAgent().find_affected_task_ids(event, list(reversed(tasks))) == affected
    assert [record.getMessage() for record in caplog.records] == original_messages


def test_complex_missed_scope_reaches_real_scheduler_and_preserves_other_work(
    complex_tasks: list[Task],
) -> None:
    event = task_event(PlanningEventType.TASK_MISSED)
    expected_affected = {"trigger", "left", "right", "join", "tail"}
    agent_inputs: list[list[Task]] = []
    scheduler_scopes: list[set[str]] = []

    class InspectAgent(StudyFlowAgent):
        def find_affected_task_ids(
            self, event: PlanningEvent, tasks: Sequence[Task],
        ) -> set[str]:
            agent_inputs.append([task.model_copy(deep=True) for task in tasks])
            return super().find_affected_task_ids(event, tasks)

    class InspectScheduler(StudyScheduler):
        def reschedule_tasks(
            self,
            assessments: Sequence[Assessment],
            tasks: Sequence[Task],
            calendar_blocks: Sequence[CalendarBlock],
            existing_schedule: Sequence[ScheduledTask],
            affected_task_ids: set[str],
            *,
            replanning_start: datetime | None = None,
            preserve_valid_affected: bool = False,
        ) -> SchedulingResult:
            scheduler_scopes.append(set(affected_task_ids))
            assert replanning_start == event.timestamp
            assert preserve_valid_affected is False
            return super().reschedule_tasks(
                assessments, tasks, calendar_blocks, existing_schedule,
                affected_task_ids, replanning_start=replanning_start,
                preserve_valid_affected=preserve_valid_affected,
            )

    assessments = [
        Assessment(
            id=assessment_id,
            course_code="CS1000",
            title="Complex dependency presentation",
            description="Fixed role A replan acceptance example",
            type=AssessmentType.PRESENTATION,
            unlock_at=None,
            deadline=at("18:00"),
            weightage=None,
            is_group=False,
            group_size=None,
        )
        for assessment_id in ("assessment-main", "assessment-other")
    ]
    tasks = [
        task.model_copy(update={"status": TaskStatus.SCHEDULED})
        if task.status is not TaskStatus.COMPLETED else task.model_copy(deep=True)
        for task in complex_tasks
    ]
    starts = {
        "root": "08:00", "co-parent": "08:30", "trigger": "09:00",
        "left": "09:30", "right": "10:00", "join": "11:00", "tail": "11:30",
        "sibling": "15:00", "independent": "15:30", "other": "16:00",
    }
    schedule = [
        ScheduledTask(
            id=f"scheduled-{task.id}",
            task_id=task.id,
            start_time=at(starts[task.id]),
            end_time=at(starts[task.id]) + timedelta(minutes=task.duration_minutes),
            flexibility=Flexibility.FLEXIBLE,
        )
        for task in tasks
    ]
    blocks = [CalendarBlock(
        id="calendar-lecture", title="Lecture", start_time=at("10:30"),
        end_time=at("11:00"), flexibility=Flexibility.HARD,
    )]
    state = PlanningState(assessments, tasks, blocks, schedule)
    pipeline = PlanningPipeline(InspectAgent(), InspectScheduler())
    app = create_app(state, pipeline)

    response = request(app, "POST", "/replan", json=event.model_dump(mode="json"))

    assert response.status_code == 200, response.text
    result = SchedulingResult.model_validate(response.json())
    assert result.unscheduled_tasks == []
    assert len(agent_inputs) == 1
    staged = {task.id: task for task in agent_inputs[0]}
    assert staged["trigger"].status is TaskStatus.MISSED
    assert staged["root"].status is TaskStatus.COMPLETED
    assert scheduler_scopes == [expected_affected]
    before = {placement.task_id: placement for placement in schedule}
    after = {placement.task_id: placement for placement in result.scheduled_tasks}
    assert len(result.scheduled_tasks) == len(tasks)
    assert after.keys() == before.keys()
    assert {
        task_id for task_id in before
        if (before[task_id].start_time, before[task_id].end_time)
        != (after[task_id].start_time, after[task_id].end_time)
    } == expected_affected
    for task_id in {"root", "co-parent", "sibling", "independent", "other"}:
        assert after[task_id] == before[task_id]
    for task_id in expected_affected:
        assert after[task_id].start_time >= event.timestamp
    deadlines = {assessment.id: assessment.deadline for assessment in assessments}
    for task in tasks:
        placement = after[task.id]
        assert placement.end_time <= deadlines[task.assessment_id]
        assert placement.end_time - placement.start_time == timedelta(
            minutes=task.duration_minutes,
        )
        for dependency in task.dependencies:
            assert after[dependency].end_time <= placement.start_time
        for block in blocks:
            assert (
                placement.end_time <= block.start_time
                or placement.start_time >= block.end_time
            )
    ordered = sorted(after.values(), key=lambda placement: placement.start_time)
    assert all(
        left.end_time <= right.start_time
        for left, right in zip(ordered, ordered[1:])
    )
    stored_tasks = {task.id: task for task in state.list_tasks()}
    assert stored_tasks["root"] == next(task for task in tasks if task.id == "root")
    assert stored_tasks["trigger"].status is TaskStatus.SCHEDULED
    assert state.list_scheduled_tasks() == result.scheduled_tasks
    assert state.list_calendar_blocks() == blocks
    assert state.list_planning_events() == [event]
