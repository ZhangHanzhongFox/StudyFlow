# Frontend validation and remaining dependencies

Run `npm test` for client/comparison tests without a backend or reset endpoint.
Run `npm run build` for application/config typechecks and production compilation.
The root solution config can also be checked with `tsc --noEmit -p tsconfig.json`.

Manual regression checks on an initialized disposable runtime:

- Complete a task, then miss another task: unchanged completed and unrelated
  placements appear as Preserved with their current canonical task status.
- Check cross-date changes: both ends show dates, times and timezone; the page
  identifies the browser display timezone. Flexibility-only changes are Updated.
- Produce an unscheduled result, then submit an invalid calendar time range.
  The previous comparison and failure details must remain visible with the error.
- Reject Generate Plan: the specific API error and last saved result remain visible.
- Activity shows event type, referenced entity name (or reference ID), and time,
  not a fabricated scheduling explanation.

Remaining A/C dependency: canonical PlanningEvent does not supply a reasoning
field. Rich backend explanations cannot be displayed until an agreed data source
exists; do not add frontend reason/message fields to that model.

Current main supplies `resetDemo` (`POST /demo/reset`, when enabled) and
`changeAssessment` (`POST /assessment-changes`). Their upstream implementations
are retained; this merge does not add reset or assessment-edit forms.
`/plan` remains generation, not reset. The browser integration suite requires
Playwright and a Python environment and uses only an isolated test-server reset;
it does not reset the product server. `npm test` remains backend-free.
