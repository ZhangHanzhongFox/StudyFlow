"""Repeatable HTTP smoke check for a disposable, reset-enabled local demo."""

import argparse
import json
from datetime import datetime, timedelta
from typing import Any

import httpx

from backend.main import current_study_time
from backend.schemas import Assessment, CalendarBlock, PlanningEvent, ScheduledTask, Task
from backend.services.state import validate_planning_state

COLLECTIONS = {
    "assessments": Assessment, "tasks": Task, "calendar-blocks": CalendarBlock,
    "schedule": ScheduledTask, "planning-events": PlanningEvent,
}


def snapshot(client: httpx.Client) -> dict[str, list[dict[str, Any]]]:
    result = {}
    for path in COLLECTIONS:
        response = client.get(f"/{path}")
        response.raise_for_status()
        result[path] = response.json()
    validate_planning_state(*[
        [COLLECTIONS[path].model_validate(item) for item in result[path]]
        for path in COLLECTIONS
    ])
    return result


def checked_post(client: httpx.Client, path: str, payload: dict | None = None,
                 expected: int = 200) -> Any:
    response = client.post(path, json=payload) if payload is not None else client.post(path)
    if response.status_code != expected:
        raise AssertionError(f"{path}: expected {expected}, got {response.status_code}: {response.text}")
    return response.json()


def verify_demo(client: httpx.Client, observed_at: datetime) -> dict[str, Any]:
    """Mutates/reset the target. Simulated missed time is reported explicitly."""
    health = client.get("/health")
    health.raise_for_status()
    assert health.json() == {"status": "ok", "data_mode": "mock"}
    spec = client.get("/openapi.json").json()
    assert {"/demo/reset", "/assessment-changes"} <= spec["paths"].keys()
    checked_post(client, "/demo/reset")
    baseline = snapshot(client)
    reports = []
    for cycle in range(3):
        plan = checked_post(client, "/plan")
        assert plan["scheduled_tasks"] and not plan["unscheduled_tasks"]
        state = snapshot(client)
        assert all(datetime.fromisoformat(s["start_time"]) >= observed_at
                   for s in state["schedule"])
        presentation = next(a for a in state["assessments"] if a["type"] == "presentation")
        tasks = [t for t in state["tasks"] if t["assessment_id"] == presentation["id"]]
        root = next(t for t in tasks if not t["dependencies"])
        placements = {s["task_id"]: s for s in state["schedule"]}
        completed_placement = placements[root["id"]]
        event = {"id": "demo-check-complete", "event_type": "task_completed",
                 "reference_id": root["id"], "timestamp": observed_at.isoformat()}
        checked_post(client, "/replan", event)
        missed = next(t for t in tasks if root["id"] in t["dependencies"])
        # Advance only this observation, never the product clock or fixtures.
        simulated_at = max(observed_at, datetime.fromisoformat(placements[missed["id"]]["end_time"])) + timedelta(minutes=5)
        event = {"id": "demo-check-missed", "event_type": "task_missed",
                 "reference_id": missed["id"], "timestamp": simulated_at.isoformat()}
        replanned = checked_post(client, "/replan", event)
        assert completed_placement in replanned["scheduled_tasks"]
        after_missed = snapshot(client)
        assert next(t for t in after_missed["tasks"] if t["id"] == root["id"])["status"] == "completed"
        checked_post(client, "/replan", event, 409)
        assert snapshot(client) == after_missed
        for kind in ("presentation", "exam", "coding_assignment"):
            identifier = f"demo-check-{kind}"
            assessment = {
                "id": identifier, "course_code": "DEMO", "title": f"Demo {kind}",
                "description": "Confirm the requirements before preparing the assessment.",
                "type": kind, "unlock_at": None,
                "deadline": (simulated_at + timedelta(days=7)).isoformat(),
                "weightage": None, "is_group": False, "group_size": None,
            }
            change = {"event": {"id": identifier, "event_type": "new_assessment",
                      "timestamp": simulated_at.isoformat(), "reference_id": identifier},
                      "assessment": assessment}
            added = checked_post(client, "/assessment-changes", change)
            added_state = snapshot(client)
            new_ids = {t["id"] for t in added_state["tasks"] if t["assessment_id"] == identifier}
            assert new_ids
            assert new_ids <= {s["task_id"] for s in added["scheduled_tasks"]}
            assert not new_ids & {u["task_id"] for u in added["unscheduled_tasks"]}
            checked_post(client, "/assessment-changes", change, 409)
            assert snapshot(client) == added_state
            change["event"] = {**change["event"], "id": identifier + "-tight", "event_type": "assessment_updated"}
            change["assessment"] = {**assessment, "deadline": (simulated_at + timedelta(minutes=1)).isoformat()}
            partial = checked_post(client, "/assessment-changes", change)
            assert partial["unscheduled_tasks"]
        before_error = snapshot(client)
        checked_post(client, "/assessment-changes", {"event": {}, "assessment": {}}, 422)
        assert snapshot(client) == before_error
        checked_post(client, "/demo/reset")
        checked_post(client, "/demo/reset")
        assert snapshot(client) == baseline
        reports.append({"cycle": cycle + 1, "planned": len(plan["scheduled_tasks"]),
                        "simulated_missed_at": simulated_at.isoformat(), "reset_matches_startup": True})
    return {"health": "ok", "cycles": reports, "new_assessment_types": 3,
            "final_collections": {key: len(value) for key, value in baseline.items()}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--allow-reset", action="store_true", required=True,
                        help="Acknowledge that demo changes on this server will be reset")
    args = parser.parse_args()
    with httpx.Client(base_url=args.base_url, timeout=60, trust_env=False) as client:
        print(json.dumps(verify_demo(client, current_study_time()), indent=2))


if __name__ == "__main__":
    main()
