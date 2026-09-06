# Final A/B/C/D sign-off checklist

Complete this together against one shared checkout before the submission freeze.

## A — Agent / assessment pipeline

- [ ] Canonical `Assessment` and `Task` fields remain unchanged.
- [ ] Presentation, exam/midterm, and coding-assignment decomposition works on the demo fixture.
- [ ] Task names, dependencies, durations, priorities, and statuses are valid and stable.
- [ ] `POST /assessment-changes` remains atomic and returns canonical `SchedulingResult`.

## B — Scheduler / replanning

- [ ] No scheduled task overlaps a hard calendar block.
- [ ] Dependencies and deadlines remain respected.
- [ ] Completed and unrelated valid placements are preserved when possible.
- [ ] Moved, removed, and unscheduled outcomes are accurate; unscheduled reason/message are populated canonically.
- [ ] The accepted missed and calendar-change scenarios pass.

## C — API / integration

- [ ] Existing endpoint paths and response shapes match `docs/API_CONTRACT.md`.
- [ ] `POST /demo/reset` is enabled only with the documented demo/development gates and restores the startup snapshot atomically.
- [ ] `POST /replan`, `POST /calendar-changes`, and `POST /assessment-changes` refresh consistent shared state.
- [ ] 409/422/500/501 responses keep structured, user-meaningful details.
- [ ] No mock IDs or shared schemas changed during final integration.

## D — Frontend / demo

- [ ] Dashboard GET data is live; no demo-domain mock mapping exists in the frontend.
- [ ] Complete/Missed, calendar add/edit, Generate Plan, Add Assessment, and Demo Reset work entirely in the UI.
- [ ] Duplicate writes are locked; rejected writes preserve the last usable result; uncertain-write recovery is read-only.
- [ ] Task status, Moved/Added/Removed/Preserved, cross-date before/after times, timezone, and Unscheduled reason/message are visible.
- [ ] Desktop/mobile visual pass, TypeScript, unit tests, browser acceptance tests, Vite build, backend tests, and `git diff --check` pass.
- [ ] Video script, runbook, editable deck, and handoff are reviewed by the presenter.

## Joint rehearsal

- [ ] Run reset → missed → calendar change → assessment add → reset without Swagger.
- [ ] Finish in under four minutes.
- [ ] Confirm fallback owner, local ports, screen sharing, and final baseline immediately before presenting.

