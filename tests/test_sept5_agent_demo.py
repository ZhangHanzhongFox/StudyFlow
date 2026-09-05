"""A's offline September 5 acceptance through the production HTTP boundary."""

from collections.abc import Sequence
from datetime import datetime, timedelta
import logging
from typing import Any

import pytest
from fastapi import FastAPI

from backend.agents import StudyFlowAgent
from backend.main import create_app
from backend.scheduler import StudyScheduler
from backend.schemas import (
    Assessment, CalendarBlock, PlanningEvent, ScheduledTask,
    Task, TaskStatus, validate_task_graph,
)
from backend.services import PlanningPipeline, PlanningState
from tests.test_agent_boundaries import RawStructuredLLM, draft
from tests.test_default_runtime import request


def at(time: str) -> datetime:
    return datetime.fromisoformat(f"2026-09-05T{time}:00+08:00")


def assessment_payload(kind: str = "presentation") -> dict[str, Any]:
    descriptions = {
        "presentation": "Prepare an individual presentation with slides and speaker notes.",
        "exam": "Prepare for the exam. Confirm the assessed topics with the instructor.",
        "midterm": "Prepare for the midterm. Confirm the assessed topics with the instructor.",
        "coding_assignment": "Implement the assignment and test it against the provided specification.",
    }
    return {
        "id": f"sept5-{kind}", "course_code": "DEMO1000",
        "title": f"September 5 {kind.replace('_', ' ')} demo",
        "description": descriptions[kind], "type": kind, "unlock_at": None,
        "deadline": "2026-09-07T18:00:00+08:00", "weightage": None,
        "is_group": False, "group_size": None,
    }


def addition(payload: dict[str, Any]) -> dict[str, Any]:
    return {"assessment": payload, "event": {
        "id": f"add-{payload['id']}", "event_type": "new_assessment",
        "reference_id": payload["id"], "timestamp": at("09:00").isoformat(),
    }}


def setup(agent: StudyFlowAgent | None = None) -> tuple[FastAPI, PlanningState]:
    old = Assessment.model_validate({**assessment_payload("exam"), "id": "existing"})
    tasks = [Task(
        id=identity, assessment_id=old.id, name="Review existing course notes",
        duration_minutes=30, priority=3, dependencies=[], status=status,
    ) for identity, status in (("done", "completed"), ("unrelated", "scheduled"))]
    schedule = [ScheduledTask(
        id=f"slot-{task.id}", task_id=task.id, start_time=at(start),
        end_time=at(start) + timedelta(minutes=30), flexibility="flexible",
    ) for task, start in zip(tasks, ("08:00", "16:00"))]
    state = PlanningState(
        [old], tasks, [CalendarBlock(
            id="lecture", title="Existing lecture", start_time=at("12:00"),
            end_time=at("13:00"), flexibility="hard",
        )], schedule, [PlanningEvent(
            id="old-completion", event_type="task_completed", reference_id="done",
            timestamp=at("08:30"),
        )],
    )
    return create_app(state, PlanningPipeline(agent or StudyFlowAgent(), StudyScheduler())), state


def snapshot(app: FastAPI) -> dict[str, Any]:
    return {path: request(app, "GET", path).json() for path in (
        "/assessments", "/tasks", "/schedule", "/calendar-blocks", "/planning-events",
    )}


def assert_valid_schedule(state: PlanningState) -> None:
    tasks = validate_task_graph(state.list_tasks())
    placements = {s.task_id: s for s in state.list_scheduled_tasks()}
    deadlines = {a.id: a.deadline for a in state.list_assessments()}
    for task in tasks:
        if task.id not in placements:
            continue
        slot = placements[task.id]
        assert slot.end_time - slot.start_time == timedelta(minutes=task.duration_minutes)
        assert slot.end_time <= deadlines[task.assessment_id]
        for dependency in task.dependencies:
            assert placements[dependency].end_time <= slot.start_time
        for block in state.list_calendar_blocks():
            assert slot.end_time <= block.start_time or slot.start_time >= block.end_time
    ordered = sorted(placements.values(), key=lambda s: s.start_time)
    assert all(a.end_time <= b.start_time for a, b in zip(ordered, ordered[1:]))


@pytest.mark.parametrize("kind", ["presentation", "exam", "midterm", "coding_assignment"])
@pytest.mark.parametrize("mode", [
    "template", "blank", "incomplete", "provider_failure", "classification_failure",
    "invalid_field", "cycle",
])
def test_new_assessment_generates_valid_complete_workflow(kind, mode, caplog):
    payload = assessment_payload(kind)
    agent = StudyFlowAgent()
    if mode in {"blank", "incomplete"}:
        payload["description"] = "  \n " if mode == "blank" else "Details will follow."
    elif mode in {"provider_failure", "classification_failure", "invalid_field", "cycle"}:
        output = {
            "provider_failure": RuntimeError("offline provider"),
            "classification_failure": RuntimeError("offline decomposition"),
            "invalid_field": {"tasks": [draft(duration_minutes=True)]},
            "cycle": {"tasks": [draft(dependency_keys=["review"]),
                                   draft(step_key="review", dependency_keys=["prepare"])]},
        }[mode]
        classification = (RuntimeError("offline classification") if mode == "classification_failure"
                          else {"assessment_type": kind})
        agent = StudyFlowAgent(RawStructuredLLM([classification, output]))
    app, state = setup(agent)
    before = snapshot(app)
    response = request(app, "POST", "/assessment-changes", json=addition(payload))
    assert response.status_code == 200, response.text
    assert response.json()["unscheduled_tasks"] == []
    actual = [t for t in state.list_tasks() if t.assessment_id == payload["id"]]
    expected = StudyFlowAgent().decompose_assessment(Assessment.model_validate(payload))
    assert [t.model_copy(update={"status": TaskStatus.PENDING}) for t in actual] == expected
    assert len(actual) == {"presentation": 5, "exam": 4, "midterm": 4, "coding_assignment": 6}[kind]
    assert all(t.name.strip() and type(t.duration_minutes) is int and t.duration_minutes > 0
               and type(t.priority) is int and 1 <= t.priority <= 5 for t in actual)
    assert all(t.status is TaskStatus.SCHEDULED for t in actual)
    after = snapshot(app)
    for path in ("/tasks", "/schedule", "/planning-events", "/assessments"):
        assert all(item in after[path] for item in before[path])
    assert after["/calendar-blocks"] == before["/calendar-blocks"]
    assert len(after["/planning-events"]) == len(before["/planning-events"]) + 1
    assert_valid_schedule(state)
    if mode in {"provider_failure", "classification_failure", "invalid_field", "cycle"}:
        reason = {"invalid_field": "invalid_structure", "cycle": "invalid_dependencies"}.get(
            mode, "provider_output_unavailable",
        )
        assert f"reason={reason}" in caplog.text
    else:
        assert "using deterministic fallback" not in caplog.text
    assert request(app, "POST", "/assessment-changes", json=addition(payload)).status_code == 409
    assert snapshot(app) == after


@pytest.mark.parametrize("field,value", [
    ("type", "unsupported"), ("description", None),
    ("deadline", "2026-09-07T18:00:00"), ("extra_requirement", "invented"),
])
def test_invalid_assessment_is_rejected_without_fallback_or_mutation(field, value, caplog):
    caplog.set_level(logging.INFO, logger="backend.agents.workflow")
    app, _ = setup()
    before = snapshot(app)
    payload = {**assessment_payload(), field: value}
    assert request(app, "POST", "/assessment-changes", json=addition(payload)).status_code == 422
    assert snapshot(app) == before
    assert "Agent decomposition" not in caplog.text


def test_new_assessment_with_no_time_keeps_every_new_task_explicit():
    app, state = setup()
    before = snapshot(app)
    payload = {**assessment_payload(), "deadline": at("09:01").isoformat()}
    response = request(app, "POST", "/assessment-changes", json=addition(payload))
    assert response.status_code == 200, response.text
    result = response.json()
    new_ids = {t.id for t in state.list_tasks() if t.assessment_id == payload["id"]}
    failures = result["unscheduled_tasks"]
    assert len(failures) == len(new_ids) == 5
    assert {item["task_id"] for item in failures} == new_ids
    assert all(item["reason"] and item["message"] for item in failures)
    assert snapshot(app)["/schedule"] == before["/schedule"]
    assert len(state.list_planning_events()) == 2


def test_added_presentation_missed_materials_replans_real_downstream_only():
    class RecordingAgent(StudyFlowAgent):
        def find_affected_task_ids(self, event: PlanningEvent, tasks: Sequence[Task]) -> set[str]:
            result = super().find_affected_task_ids(event, tasks)
            self.last_event = event
            self.last_tasks = list(tasks)
            self.last_candidates = result
            return result

    agent = RecordingAgent()
    app, state = setup(agent)
    payload = assessment_payload()
    response = request(app, "POST", "/assessment-changes", json=addition(payload))
    assert response.status_code == 200, response.text
    # Identify the linear template by dependencies, not display-name substrings.
    remaining = [t for t in state.list_tasks() if t.assessment_id == payload["id"]]
    chain = [next(t for t in remaining if not t.dependencies)]
    while len(chain) < len(remaining):
        chain.append(next(t for t in remaining if t.dependencies == [chain[-1].id]))
    assert len(chain) == 5
    for task in chain[:2]:
        slot = next(s for s in state.list_scheduled_tasks() if s.task_id == task.id)
        result = request(app, "POST", "/replan", json={
            "id": f"complete-{task.id}", "event_type": "task_completed",
            "reference_id": task.id, "timestamp": slot.end_time.isoformat(),
        })
        assert result.status_code == 200, result.text
    before = snapshot(app)
    placements = {s.task_id: s for s in state.list_scheduled_tasks()}
    trigger_time = placements[chain[2].id].end_time + timedelta(minutes=30)
    event = {"id": "missed-generated-slides", "event_type": "task_missed",
             "reference_id": chain[2].id, "timestamp": trigger_time.isoformat()}
    response = request(app, "POST", "/replan", json=event)
    assert response.status_code == 200, response.text
    assert response.json()["unscheduled_tasks"] == []
    expected = {t.id for t in chain[2:]}
    assert agent.last_candidates == expected
    assert next(t for t in agent.last_tasks if t.id == chain[2].id).status is TaskStatus.MISSED
    new = {s.task_id: s for s in state.list_scheduled_tasks()}
    assert {identity for identity, slot in placements.items() if slot != new[identity]} == expected
    for identity in expected:
        assert new[identity].start_time >= trigger_time
    for task in chain[:2]:
        assert next(t for t in state.list_tasks() if t.id == task.id).status is TaskStatus.COMPLETED
    assert next(t for t in state.list_tasks() if t.id == chain[2].id).status is TaskStatus.SCHEDULED
    assert_valid_schedule(state)
    after = snapshot(app)
    assert after["/calendar-blocks"] == before["/calendar-blocks"]
    assert after["/assessments"] == before["/assessments"]
    assert all(e in after["/planning-events"] for e in before["/planning-events"])
    assert sum(e["id"] == event["id"] for e in after["/planning-events"]) == 1
    assert request(app, "POST", "/replan", json=event).status_code == 409
    assert snapshot(app) == after
