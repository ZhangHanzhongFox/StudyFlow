"""Acceptance of A/B's default-runtime and explicit simulated fallback handoff."""

import json

import pytest
from fastapi.testclient import TestClient

from backend.demo_check import checked_post, snapshot
from scripts import sept6_ab_demo as demo


@pytest.mark.parametrize("time", ["08:00", "14:00", "23:00"])
def test_default_templates_and_immediate_versus_elapsed_missed(time):
    report = demo.default_rehearsal(demo.at(time))
    assert len(report["planned"]["tasks"]) == 15
    assert all(c["outcome"] == "preserved" for c in report["immediate_missed"]["changes"])
    simulated = report["simulated_later_missed"]
    assert {c["task_id"] for c in simulated["changes"] if c["outcome"] == "moved"} == set(simulated["affected_task_ids"])
    assert report["reset_verified"]


def test_fallback_has_exact_moves_and_completed_unrelated_preservation(tmp_path, monkeypatch):
    report = demo.fallback_rehearsal()
    moved = [c for c in report["changes"] if c["outcome"] == "moved"]
    by_name = {c["name"]: c["after"]["start_time"] for c in moved}
    assert by_name == {
        "Prepare and review presentation materials": demo.at("13:00").isoformat(),
        "Write and review speaker notes": demo.at("14:00").isoformat(),
        "Run a timed rehearsal and revise": demo.at("16:30").isoformat(),
    }
    assert sum(c["outcome"] == "preserved" for c in report["changes"]) == 4
    monkeypatch.setattr(demo, "OUTPUT", tmp_path)
    (tmp_path / "fallback.json").write_text(json.dumps(report))
    # Exported snapshot starts before the missed event and restores that exact state.
    with TestClient(demo.fallback_app()) as client:
        assert snapshot(client) == report["before"]
        response = checked_post(client, "/replan", report["observation"])
        assert response == report["result"]
        assert snapshot(client) == report["after"]
        checked_post(client, "/demo/reset")
        assert snapshot(client) == report["before"]
        assert checked_post(client, "/replan", report["observation"]) == response
