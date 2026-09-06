# Frontend validation — September 6

Current evidence: [VALIDATION_SEPT6.md](../docs/demo/VALIDATION_SEPT6.md).

Run `npm ci`, `npm test`, `npm run build`, and `npx tsc --noEmit -p tsconfig.json`.
Playwright 1.62.1 is pinned in the manifest/lockfile. Install its browser once
with `npx playwright install chromium`, then run `npm run test:e2e`.
Alternatively set STUDYFLOW_TEST_BROWSER to an installed browser executable.
Set STUDYFLOW_TEST_PYTHON if the Python environment is not root/.venv/bin/python.

The suite starts isolated API/Vite servers and fresh browser contexts. Historical
September 3 fixture tests and September 6 default-startup tests are distinct.
The latter reset to empty tasks/schedule, generate 15 tasks, complete one,
miss future materials without falsely asserting movement, add an overlapping
hard block and verify a move, add an assessment, then restore all five startup
collections. That sequence runs three times through the UI.

Reset and Add Assessment forms are implemented. Reset restores the configured
startup snapshot; it does not generate tasks. Writes lock controls through
refresh. Failed writes retain the usable result; uncertain event writes check
the original ID before retrying. Saved-write/failed-read recovery issues GETs
only. Coverage includes 404, 422 details, partial scheduling, write locking,
cross-date comparison and recovery.

Task actions show course, duration, priority, dependency names and full placement
dates/times. Comparison uses task identity and absolute timestamps; flexibility
changes are Updated. Unscheduled reason/message remain visible. Activity displays
event facts, not invented model reasoning. Five GET requests are not a multiuser
atomic snapshot; backend state changes commit atomically before refresh.

Set STUDYFLOW_QA_DIR to an existing directory for desktop/mobile screenshots.
The suite also checks mobile horizontal overflow. Human speaking rehearsals
and recording are separate from automated acceptance.
