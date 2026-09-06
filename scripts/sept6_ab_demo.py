"""Offline A/B rehearsal and evidence export; never contacts a running server.

Run with python -m scripts.sept6_ab_demo. The optional Uvicorn factory serves
only the exported, explicitly simulated fallback snapshot on a separate port.
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.agents import StudyFlowAgent
from backend.demo_check import checked_post, snapshot
from backend.main import create_app, current_study_time
from backend.scheduler import StudyScheduler
from backend.schemas import Assessment, AssessmentType, CalendarBlock, PlanningEvent, ScheduledTask, Task, TaskStatus
from backend.services import PlanningPipeline, PlanningState

OUTPUT = Path(__file__).resolve().parents[1] / "docs/demo/ab-evidence"


def at(time: str) -> datetime:
    return datetime.fromisoformat(f"2026-09-06T{time}:00+08:00")


def chain_for(state: dict[str, Any], assessment_id: str) -> list[Task]:
    tasks = [Task.model_validate(t) for t in state["tasks"] if t["assessment_id"] == assessment_id]
    chain = [next(t for t in tasks if not t.dependencies)]
    while len(chain) < len(tasks):
        chain.append(next(t for t in tasks if t.dependencies == [chain[-1].id]))
    return chain


def validate_schedule(state: dict[str, Any]) -> None:
    """Check timing independently of scheduler implementation and HTTP success."""
    tasks = {t["id"]: Task.model_validate(t) for t in state["tasks"]}
    assessments = {a["id"]: Assessment.model_validate(a) for a in state["assessments"]}
    slots = {s["task_id"]: ScheduledTask.model_validate(s) for s in state["schedule"]}
    for identity, slot in slots.items():
        task = tasks[identity]
        assessment = assessments[task.assessment_id]
        assert slot.end_time - slot.start_time == timedelta(minutes=task.duration_minutes)
        assert slot.end_time <= assessment.deadline
        if assessment.unlock_at:
            assert slot.start_time >= assessment.unlock_at
        for parent in task.dependencies:
            assert slots[parent].end_time <= slot.start_time
        for raw in state["calendar-blocks"]:
            block = CalendarBlock.model_validate(raw)
            if block.flexibility == "hard":
                assert slot.end_time <= block.start_time or slot.start_time >= block.end_time
    ordered = sorted(slots.values(), key=lambda s: s.start_time)
    assert all(a.end_time <= b.start_time for a, b in zip(ordered, ordered[1:]))


def changes(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    old = {s["task_id"]: s for s in before["schedule"]}
    new = {s["task_id"]: s for s in after["schedule"]}
    names = {t["id"]: t["name"] for t in before["tasks"] + after["tasks"]}
    rows = []
    for identity in sorted(old.keys() | new.keys()):
        a, b = old.get(identity), new.get(identity)
        status = "added" if a is None else "removed" if b is None else "preserved"
        if a and b and any(a[key] != b[key] for key in ("start_time", "end_time", "flexibility")):
            status = "moved"
        rows.append({"task_id": identity, "name": names[identity], "outcome": status,
                     "before": a, "after": b})
    return rows


def missed_rehearsal(client: TestClient, chain: list[Task], timestamp: datetime,
                     event_id: str) -> dict[str, Any]:
    before = snapshot(client)
    event = PlanningEvent(id=event_id, event_type="task_missed",
                          reference_id=chain[2].id, timestamp=timestamp)
    candidates = StudyFlowAgent().find_affected_task_ids(
        event, [Task.model_validate(t) for t in before["tasks"]])
    assert candidates == {t.id for t in chain[2:]}
    result = checked_post(client, "/replan", event.model_dump(mode="json"))
    after = snapshot(client)
    validate_schedule(after)
    rows = changes(before, after)
    assert all(row["outcome"] == "preserved" for row in rows if row["task_id"] not in candidates)
    scheduled = {s["task_id"] for s in after["schedule"]}
    failures = {u["task_id"] for u in result["unscheduled_tasks"]}
    assert candidates <= scheduled | failures
    assert not scheduled & failures
    assert all(u["reason"] and u["message"] for u in result["unscheduled_tasks"])
    for slot in after["schedule"]:
        if slot["task_id"] in candidates:
            assert datetime.fromisoformat(slot["start_time"]) >= timestamp
    checked_post(client, "/replan", event.model_dump(mode="json"), 409)
    assert snapshot(client) == after
    return {"observation": event.model_dump(mode="json"), "affected_task_ids": sorted(candidates),
            "before": before, "after": after, "changes": rows, "result": result}


def default_rehearsal(observed_at: datetime) -> dict[str, Any]:
    # Select offline mode only for construction; no credential values are read/exported.
    previous = os.environ.get("STUDYFLOW_LLM_PROVIDER")
    os.environ["STUDYFLOW_LLM_PROVIDER"] = "none"
    try:
        app = create_app(clock=lambda: observed_at, environment="demo", demo_reset_enabled=True)
    finally:
        if previous is None:
            os.environ.pop("STUDYFLOW_LLM_PROVIDER", None)
        else:
            os.environ["STUDYFLOW_LLM_PROVIDER"] = previous
    with TestClient(app) as client:
        baseline = snapshot(client)
        assert not baseline["tasks"] and not baseline["schedule"]
        checked_post(client, "/demo/reset")
        result = checked_post(client, "/plan")
        assert not result["unscheduled_tasks"]
        planned = snapshot(client)
        validate_schedule(planned)
        agent = StudyFlowAgent()
        kinds = set()
        for raw in planned["assessments"]:
            assessment = Assessment.model_validate(raw)
            kinds.add(assessment.type.value)
            expected = agent.decompose_assessment(assessment)
            actual = [Task.model_validate(t) for t in planned["tasks"] if t["assessment_id"] == assessment.id]
            assert [t.model_copy(update={"status": TaskStatus.PENDING}).model_dump() for t in actual] == [t.model_dump() for t in expected]
            assert all(t.name.strip() and t.duration_minutes > 0 and 1 <= t.priority <= 5 for t in actual)
        assert {"presentation", "coding_assignment"} <= kinds and kinds & {"exam", "midterm"}
        presentation = next(a for a in planned["assessments"] if a["type"] == "presentation")
        chain = chain_for(planned, presentation["id"])
        # This reproduces the UI's immediate observation, without inventing elapsed work.
        immediate = missed_rehearsal(client, chain, observed_at, "ab-immediate-missed")
        checked_post(client, "/demo/reset")
        checked_post(client, "/plan")
        for task in chain[:2]:
            slot = next(s for s in planned["schedule"] if s["task_id"] == task.id)
            checked_post(client, "/replan", {"id": f"ab-complete-{task.id}",
                "event_type": "task_completed", "reference_id": task.id, "timestamp": slot["end_time"]})
        slot = next(s for s in planned["schedule"] if s["task_id"] == chain[2].id)
        simulated_at = datetime.fromisoformat(slot["end_time"]) + timedelta(minutes=5)
        simulated = missed_rehearsal(client, chain, simulated_at, "ab-simulated-missed")
        assert any(r["outcome"] == "moved" for r in simulated["changes"])
        completed = {t["id"] for t in simulated["after"]["tasks"] if t["status"] == "completed"}
        assert {t.id for t in chain[:2]} <= completed
        checked_post(client, "/demo/reset")
        assert snapshot(client) == baseline
    return {"planning_clock": observed_at.isoformat(), "mode": "offline template",
            "planned": planned, "immediate_missed": immediate,
            "simulated_later_missed": simulated, "reset_verified": True}


def fallback_rehearsal() -> dict[str, Any]:
    assessment = Assessment(id="ab-sept6-existing", course_code="DEMO", title="Existing study",
        description="Explicit synthetic study commitments", type="exam", unlock_at=None,
        deadline=at("18:00") + timedelta(days=1), weightage=None, is_group=False, group_size=None)
    tasks = [Task(id=identity, assessment_id=assessment.id, name=name, duration_minutes=30,
        priority=3, dependencies=[], status=status) for identity, name, status in (
            ("ab-done", "Completed course review", "completed"),
            ("ab-unrelated", "Independent course review", "scheduled"))]
    slots = [ScheduledTask(id=f"slot-{task.id}", task_id=task.id, start_time=at(start),
        end_time=at(start) + timedelta(minutes=30), flexibility="flexible")
        for task, start in zip(tasks, ("08:00", "16:00"))]
    state = PlanningState([assessment], tasks, [CalendarBlock(id="ab-lecture", title="Hard lecture",
        start_time=at("12:00"), end_time=at("13:00"), flexibility="hard")], slots,
        [PlanningEvent(id="ab-old-completion", event_type="task_completed", reference_id="ab-done", timestamp=at("08:30"))])
    app = create_app(state, PlanningPipeline(StudyFlowAgent(), StudyScheduler(clock=lambda: at("09:00"))))
    with TestClient(app) as client:
        presentation = assessment.model_copy(update={"id": "ab-sept6-presentation", "type": AssessmentType.PRESENTATION,
            "title": "Simulated presentation recovery", "description": "Prepare slides and speaker notes, then rehearse."})
        checked_post(client, "/assessment-changes", {"assessment": presentation.model_dump(mode="json"),
            "event": {"id": "ab-add-presentation", "event_type": "new_assessment",
                      "reference_id": presentation.id, "timestamp": at("09:00").isoformat()}})
        chain = chain_for(snapshot(client), presentation.id)
        for task in chain[:2]:
            slot = next(s for s in snapshot(client)["schedule"] if s["task_id"] == task.id)
            checked_post(client, "/replan", {"id": f"complete-{task.id}", "event_type": "task_completed",
                "reference_id": task.id, "timestamp": slot["end_time"]})
        report = missed_rehearsal(client, chain, at("11:30"), "ab-fallback-missed")
        assert not report["result"]["unscheduled_tasks"]
        assert {r["task_id"] for r in report["changes"] if r["outcome"] == "moved"} == {t.id for t in chain[2:]}
        report["disclosure"] = "Synthetic September 6 scenario; observation explicitly simulated at 11:30 +08:00."
        return report


def fallback_app() -> FastAPI:
    """Uvicorn --factory entrypoint; baseline is before the simulated missed event."""
    report = json.loads((OUTPUT / "fallback.json").read_text())
    before = report["before"]
    state = PlanningState(
        [Assessment.model_validate(a) for a in before["assessments"]],
        [Task.model_validate(t) for t in before["tasks"]],
        [CalendarBlock.model_validate(b) for b in before["calendar-blocks"]],
        [ScheduledTask.model_validate(s) for s in before["schedule"]],
        [PlanningEvent.model_validate(e) for e in before["planning-events"]])
    return create_app(state, PlanningPipeline(StudyFlowAgent(), StudyScheduler(clock=lambda: at("11:30"))),
                      environment="demo", demo_reset_enabled=True)


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    reports = [default_rehearsal(value) for value in (at("08:00"), at("14:00"), at("23:00"), current_study_time())]
    fallback = fallback_rehearsal()
    for name, content in (("default", reports), ("fallback", fallback), ("missed-request", fallback["observation"])):
        (OUTPUT / f"{name}.json").write_text(json.dumps(content, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"default_clocks": [r["planning_clock"] for r in reports],
        "planned_tasks": [len(r["planned"]["tasks"]) for r in reports],
        "immediate_moved": [sum(c["outcome"] == "moved" for c in r["immediate_missed"]["changes"]) for r in reports],
        "simulated_moved": [sum(c["outcome"] == "moved" for c in r["simulated_later_missed"]["changes"]) for r in reports],
        "fallback_moved": sum(c["outcome"] == "moved" for c in fallback["changes"])}, indent=2))


if __name__ == "__main__":
    main()
