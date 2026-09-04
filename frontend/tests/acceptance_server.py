"""Isolated browser-test API; never mounted by the production application."""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ["STUDYFLOW_LLM_PROVIDER"] = "none"

import uvicorn

from backend.agents import StudyFlowAgent
from backend.main import create_app
from backend.scheduler import StudyScheduler
from backend.schemas import Assessment, CalendarBlock, ScheduledTask, Task
from backend.services import PlanningPipeline, PlanningState

fixture = json.loads((ROOT / "data/scenarios/replan_acceptance.json").read_text())
state = PlanningState()
app = create_app(state, PlanningPipeline(
    StudyFlowAgent(),
    StudyScheduler(planning_start=datetime.fromisoformat("2026-09-03T09:00:00+08:00")),
))
# Exercise default runtime wiring against a date later than the provider mocks.
app.mount("/live", create_app(
    clock=lambda: datetime.fromisoformat("2026-09-04T01:00:00+08:00"),
))


@app.post("/test/reset")
def reset(extended_deadline: bool = False) -> dict[str, bool]:
    initial = fixture["initial_state"]
    assessments = [Assessment.model_validate(item) for item in initial["assessments"]]
    if extended_deadline:
        assessments = [item.model_copy(update={
            "deadline": datetime.fromisoformat("2026-09-04T18:00:00+08:00"),
        }) for item in assessments]
    state.reset(
        assessments=assessments,
        tasks=[Task.model_validate(item) for item in initial["tasks"]],
        calendar_blocks=[CalendarBlock.model_validate(item) for item in initial["calendar_blocks"]],
        scheduled_tasks=[ScheduledTask.model_validate(item) for item in initial["scheduled_tasks"]],
    )
    return {"ok": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    reset()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
