"""C/D HTTP acceptance using the existing shared replan fixture."""
from copy import deepcopy
from datetime import datetime

import pytest

from backend.main import create_app
from backend.agents import StudyFlowAgent
from backend.scheduler import StudyScheduler
from backend.services import PlanningPipeline
from tests.test_replan_acceptance import setup, FIXTURE, snapshot
from tests.test_default_runtime import request


def full(app):
    return {**snapshot(app), "/assessments": request(app, "GET", "/assessments").json()}


def change(kind="new_assessment", assessment_type="presentation"):
    assessment = deepcopy(FIXTURE["initial_state"]["assessments"][0])
    assessment.update(id="assessment-new", type=assessment_type,
                      deadline="2026-09-06T18:00:00+08:00")
    return {"event": {"id": "event-new", "event_type": kind,
                      "reference_id": assessment["id"], "timestamp": "2026-09-03T11:00:00+08:00"},
            "assessment": assessment}


@pytest.mark.parametrize("kind", ["presentation", "exam", "coding_assignment"])
def test_new_update_and_partial_success(kind):
    app, _ = setup()
    before = full(app)
    payload = change(assessment_type=kind)
    response = request(app, "POST", "/assessment-changes", json=payload)
    assert response.status_code == 200, response.text
    after = full(app)
    assert all(t in after["/tasks"] for t in before["/tasks"])
    assert all(s in after["/schedule"] for s in before["/schedule"])
    assert len(after["/assessments"]) == len(before["/assessments"]) + 1
    assert request(app, "POST", "/assessment-changes", json=payload).status_code == 409
    assert full(app) == after
    payload["event"].update(id="event-deadline", event_type="assessment_updated")
    payload["assessment"]["deadline"] = "2026-09-03T11:01:00+08:00"
    response = request(app, "POST", "/assessment-changes", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["unscheduled_tasks"]
    assert {t["id"] for t in full(app)["/tasks"]} == {t["id"] for t in after["/tasks"]}


def test_requirements_redecomposition_preserves_completed_history():
    app, _ = setup()
    payload = change()
    assert request(app, "POST", "/assessment-changes", json=payload).status_code == 200
    task = next(t for t in full(app)["/tasks"] if t["assessment_id"] == "assessment-new")
    event = {**payload["event"], "id": "complete", "event_type": "task_completed", "reference_id": task["id"]}
    assert request(app, "POST", "/replan", json=event).status_code == 200
    before = full(app)
    payload["event"].update(id="requirements", event_type="assessment_updated")
    payload["assessment"]["description"] += " Revised requirements."
    response = request(app, "POST", "/assessment-changes", json=payload)
    assert response.status_code == 200, response.text
    after = full(app)
    completed = next(t for t in before["/tasks"] if t["id"] == task["id"])
    assert completed in after["/tasks"]
    assert next(s for s in before["/schedule"] if s["task_id"] == task["id"]) in after["/schedule"]
    assert after["/tasks"] != before["/tasks"]


@pytest.mark.parametrize("mode", ["unknown", "duplicate_entity", "bad_reference", "naive"])
def test_assessment_errors_are_atomic(mode):
    app, _ = setup()
    payload = change()
    expected = 422
    if mode == "unknown":
        payload["event"]["event_type"] = "assessment_updated"
    elif mode == "duplicate_entity":
        payload["assessment"] = deepcopy(FIXTURE["initial_state"]["assessments"][0])
        payload["event"]["reference_id"] = payload["assessment"]["id"]
        expected = 409
    elif mode == "bad_reference":
        payload["event"]["reference_id"] = "wrong"
    else:
        payload["assessment"]["deadline"] = "2026-09-06T18:00:00"
    before = full(app)
    assert request(app, "POST", "/assessment-changes", json=payload).status_code == expected
    assert full(app) == before


def test_runtime_failure_and_invalid_agent_are_atomic():
    class Failing(StudyScheduler):
        def reschedule_tasks(self, *args, **kwargs):
            raise RuntimeError("private provider details")
    app, _ = setup(Failing())
    before = full(app)
    response = request(app, "POST", "/assessment-changes", json=change())
    assert response.status_code == 500
    assert "private" not in response.text
    assert full(app) == before


@pytest.mark.parametrize("environment,enabled", [("production", True), ("demo", False)])
def test_reset_not_exposed(environment, enabled):
    _, state = setup()
    app = create_app(state, environment=environment, demo_reset_enabled=enabled)
    assert request(app, "POST", "/demo/reset").status_code == 404
    assert "/demo/reset" not in app.openapi()["paths"]


def test_reset_all_collections_repeated_and_replay():
    _, state = setup()
    app = create_app(state, PlanningPipeline(StudyFlowAgent(), StudyScheduler()),
                     environment="demo", demo_reset_enabled=True)
    baseline = full(app)
    for _ in range(2):
        assert request(app, "POST", "/assessment-changes", json=change()).status_code == 200
        scenario = FIXTURE["scenarios"]["calendar_changed"]
        assert request(app, "POST", scenario["endpoint"], json=scenario["request"]).status_code == 200
        assert request(app, "POST", "/demo/reset").json() == {"status": "reset"}
        assert full(app) == baseline


def test_invalid_reset_fixture_rolls_back():
    _, state = setup()
    def invalid():
        from backend.services import PlanningState
        tasks = state.list_tasks()
        tasks[0] = tasks[0].model_copy(update={"assessment_id": "missing"})
        return PlanningState(state.list_assessments(), tasks)
    app = create_app(state, environment="development", demo_reset_enabled=True, reset_factory=invalid)
    before = full(app)
    assert request(app, "POST", "/demo/reset").status_code == 500
    assert full(app) == before


def test_invalid_decomposition_rolls_back():
    class InvalidAgent(StudyFlowAgent):
        def decompose_assessment(self, assessment):
            return []
    _, state = setup()
    app = create_app(state, PlanningPipeline(InvalidAgent(), StudyScheduler()))
    before = full(app)
    response = request(app, "POST", "/assessment-changes", json=change())
    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "invalid_planning_state"
    assert full(app) == before


def test_requirements_change_rejects_removal_of_observed_work():
    app, _ = setup()
    scenario = FIXTURE["scenarios"]["missed"]
    assert request(app, "POST", scenario["endpoint"], json=scenario["request"]).status_code == 200
    payload = change("assessment_updated")
    payload["assessment"] = deepcopy(full(app)["/assessments"][0])
    payload["event"]["reference_id"] = payload["assessment"]["id"]
    payload["assessment"]["description"] += " Changed requirements."
    before = full(app)
    response = request(app, "POST", "/assessment-changes", json=payload)
    assert response.status_code == 409
    assert full(app) == before


def test_openapi_health_cors_and_unconnected_mode():
    _, state = setup()
    app = create_app(state)
    assert request(app, "GET", "/health").json()["status"] == "ok"
    assert "AssessmentChangeRequest" in app.openapi()["components"]["schemas"]
    assert request(app, "POST", "/assessment-changes", json=change()).status_code == 501
    for path in ("/replan", "/planning-events"):
        connected, _ = setup()
        payload = change("assessment_updated")
        payload["event"]["reference_id"] = FIXTURE["initial_state"]["assessments"][0]["id"]
        assert request(connected, "POST", path, json=payload["event"]).status_code == 422


def test_clean_dynamic_start_plan_complete_reset_plan():
    app = create_app(clock=lambda: datetime.fromisoformat("2026-09-03T08:00:00+08:00"),
                     environment="demo", demo_reset_enabled=True)
    initial = full(app)
    assert initial["/tasks"] == initial["/schedule"] == initial["/planning-events"] == []
    for _ in range(2):
        result = request(app, "POST", "/plan")
        assert result.status_code == 200
        first = result.json()["scheduled_tasks"][0]
        event = {"id": "repeat-after-reset", "event_type": "task_completed",
                 "reference_id": first["task_id"], "timestamp": first["end_time"]}
        assert request(app, "POST", "/replan", json=event).status_code == 200
        assert request(app, "POST", "/demo/reset").status_code == 200
        assert full(app) == initial


def test_cors_preflight_for_new_write():
    import asyncio
    import httpx
    app, _ = setup()
    async def preflight():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            return await client.options("/assessment-changes", headers={
                "Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type"})
    result = asyncio.run(preflight())
    assert result.status_code == 200
    assert result.headers["access-control-allow-origin"] == "http://localhost:5173"
