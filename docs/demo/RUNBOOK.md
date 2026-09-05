# StudyFlow live demo runbook

## Preflight (10 minutes before)

1. From the repository root, start the API with demo reset enabled:

   ```bash
   STUDYFLOW_ENV=demo STUDYFLOW_ENABLE_DEMO_RESET=1 STUDYFLOW_LLM_PROVIDER=none .venv/bin/python -m uvicorn backend.main:app
   ```

2. In a second terminal:

   ```bash
   cd frontend
   npm run dev
   ```

3. Open the Vite URL, verify no console/page errors, and click **Demo Reset** once.
4. Confirm all three dashboard sections load and **Task status & actions**, calendar, and assessment forms expand.
5. Open [StudyFlow-Hackathon-Demo.pptx](./StudyFlow-Hackathon-Demo.pptx) and presenter notes.

## Golden path

1. **Reset:** click **Demo Reset** → confirm → wait for “baseline restored.”
2. **Missed:** expand task actions → locate the slides task → click **Missed** → show status + Moved/Preserved comparison.
3. **Calendar:** add `Extra lecture` as a hard block overlapping a visible placement → submit → show before/after and cross-date information.
4. **Assessment:** add `CS9999 / Demo presentation` with a future deadline → show new assessment/work or explicit unscheduled reason.
5. **Reset again:** restore baseline for the next judge.

## Recovery rules

- A write error leaves the last usable schedule and comparison visible. Read the specific backend message; use **Retry** only when offered.
- If a write succeeded but the following refresh failed, use the refresh retry. It performs GET requests only.
- A 404 from **Demo Reset** means the server was not started with both demo/development environment and the reset flag. Restart with the preflight command; do not use `/test/reset` or `/plan` as reset.
- A 422 should show field/location details. Correct the input; do not alter the API contract.
- If a new task is unscheduled, present it as partial scheduling with its canonical reason/message, not as a broken demo.
- If the live app becomes unusable, stay on the deck’s dashboard and flow slides while the technical teammate restarts the two local processes.

## Timing checkpoints

- 0:55: task actions open
- 1:50: missed comparison shown
- 2:35: calendar comparison shown
- 3:10: assessment result shown
- 3:30: baseline restored

