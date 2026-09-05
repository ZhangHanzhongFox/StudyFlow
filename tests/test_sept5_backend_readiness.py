"""Date availability, reset replay, and operational visibility for the demo."""

import logging
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from backend.demo_check import verify_demo
from backend.main import create_app
from backend.services import MockDataStore


@pytest.mark.parametrize("day", [5, 6])
@pytest.mark.parametrize("hour", [8, 14, 23])
def test_demo_dates_and_three_complete_reset_cycles(day, hour):
    observed = datetime.fromisoformat(f"2026-09-{day:02d}T{hour:02d}:00:00+08:00")
    app = create_app(clock=lambda: observed, environment="demo", demo_reset_enabled=True)
    with TestClient(app) as client:
        report = verify_demo(client, observed)
    assert len(report["cycles"]) == 3
    assert report["final_collections"] == {
        "assessments": 3, "tasks": 0, "calendar-blocks": 8, "schedule": 0, "planning-events": 0,
    }


def test_http_logs_report_failures_without_payload_or_query(caplog):
    with TestClient(create_app()) as client, caplog.at_level(logging.INFO, logger="backend.main"):
        client.get("/health?secret=not-for-logs")
        client.post("/assessment-changes", json={"private_description": "not-for-logs"})
    records = [r.message for r in caplog.records if r.name == "backend.main"]
    assert any("route=/health status=200" in line for line in records)
    assert any("route=/assessment-changes status=422" in line for line in records)
    assert all("not-for-logs" not in line for line in records)


def test_reset_restores_nonempty_baseline_and_is_idempotent():
    state = MockDataStore()
    from backend.demo_check import snapshot
    app = create_app(state, environment="demo", demo_reset_enabled=True)
    with TestClient(app) as client:
        initial = snapshot(client)
        # Change every collection, then restore all five nonempty fixture sets.
        state.reset([], [], [], [], [])
        for _ in range(2):
            assert client.post("/demo/reset").status_code == 200
            assert snapshot(client) == initial
