# Final A/B/C/D sign-off checklist

Technical checks below were verified automatically on September 6; see [VALIDATION_SEPT6.md](VALIDATION_SEPT6.md). Checked boxes are technical evidence, not signatures by A/B/C/D. Presenter and spoken-rehearsal items remain open.

## A — Agent / assessment pipeline

- [x] Canonical `Assessment` and `Task` fields remain unchanged.
- [x] Presentation, exam/midterm, and coding-assignment decomposition works on the demo fixture.
- [x] Task names, dependencies, durations, priorities, and statuses are valid and stable.
- [x] `POST /assessment-changes` remains atomic and returns canonical `SchedulingResult`.

## B — Scheduler / replanning

- [x] No scheduled task overlaps a hard calendar block.
- [x] Dependencies and deadlines remain respected.
- [x] Completed and unrelated valid placements are preserved when possible.
- [x] Moved, removed, and unscheduled outcomes are accurate; unscheduled reason/message are populated canonically.
- [x] The accepted missed and calendar-change scenarios pass.

## C — API / integration

- [x] Existing endpoint paths and response shapes match `docs/API_CONTRACT.md`.
- [x] `POST /demo/reset` is enabled only with the documented demo/development gates and restores the startup snapshot atomically.
- [x] `POST /replan`, `POST /calendar-changes`, and `POST /assessment-changes` refresh consistent shared state.
- [x] 409/422/500/501 responses keep structured, user-meaningful details.
- [x] No mock IDs or shared schemas changed during final integration.

## D — Frontend / demo

- [x] Dashboard GET data is live; no demo-domain mock mapping exists in the frontend.
- [x] Complete/Missed, calendar add/edit, Generate Plan, Add Assessment, and Demo Reset work entirely in the UI.
- [x] Duplicate writes are locked; rejected writes preserve the last usable result; uncertain event writes check saved IDs before resubmission; confirmed-write refresh recovery is read-only.
- [x] Task status, Moved/Added/Removed/Preserved, cross-date before/after times, timezone, and Unscheduled reason/message are visible.
- [x] Desktop/mobile visual pass, TypeScript, unit tests, browser acceptance tests, Vite build, backend tests, and `git diff --check` pass.
- [ ] Presenter has rehearsed with the revised video script, runbook and September 6 deck.

## Joint rehearsal

- [ ] Perform three spoken rehearsals: Reset → Generate Plan → Complete → Missed → calendar conflict → assessment add → Reset.
- [ ] Finish the spoken main demo in under four minutes.
- [ ] C/D confirm live screen sharing, audio and the final baseline immediately before presenting.
- [ ] D records the primary and backup videos; C/D verify playback and audio.

