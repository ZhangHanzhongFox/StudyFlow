# StudyFlow Provider Integrations

Provider payloads are untrusted boundary data. Canvas and calendar records must
pass through the adapters in `backend/integrations/` before any Agent,
Scheduler, API route, or planning-state operation receives them.

## Mock provider payloads

The realistic provider-shaped demo inputs live separately from the canonical
fixtures:

| Provider-shaped input | Adapter | Canonical output |
|---|---|---|
| `data/providers/mock_canvas_assignments.json` | `load_canvas_assignments()` | `Assessment[]` |
| `data/providers/mock_google_calendar_events.json` | `load_google_calendar_events()` | `CalendarBlock[]` |

The provider fixtures normalize to the same stable IDs and values as
`data/mock/assessments.json` and `data/mock/calendar_blocks.json`. This lets the
frontend and parallel workstreams keep using the shared scenario while C tests
the actual provider boundary.

Use the provider-backed mock state with:

```python
from backend.services import MockDataStore

store = MockDataStore.from_provider_fixtures()
```

For an end-to-end dynamic plan, omit the precomputed task, schedule, and event
fixtures while retaining provider-normalized assessments and calendar blocks:

```python
from backend.services import MockDataStore

store = MockDataStore.for_dynamic_provider_demo()
```

This is the store used by the exported `backend.main:app`. The default
`PlanningPipeline` injects `StudyFlowAgent` and `StudySchedulerAdapter`; the
adapter implements the stable Scheduler protocol around B's concrete
`StudyScheduler`, supplies a reproducible mock planning clock, reports deadline
and dependency failures through `UnscheduledTask`, and preserves unaffected
placements during replanning.

## Canvas normalization

Canvas assignment payloads are normalized by
`backend.integrations.canvas.normalize_canvas_assignments()`.

The adapter:

- validates required provider fields;
- converts Canvas HTML descriptions to plain text;
- produces timezone-aware canonical assessment dates;
- uses explicit `studyflow` mock metadata for grade weightage, stable demo IDs,
  and group size because those facts are not reliably available on a single
  Canvas assignment response;
- deterministically identifies presentation, exam/midterm, quiz, and coding
  assignment records when explicit type metadata is absent;
- rejects ambiguous assessment types instead of inventing a category;
- rejects duplicate canonical IDs.

Real Canvas OAuth is intentionally outside the MVP. A future client only needs
to fetch assignment JSON and pass it to the same normalization function.

## Google Calendar normalization

Google Calendar-style events are normalized by
`backend.integrations.calendar.normalize_google_calendar_events()`.

The adapter reads `start.dateTime`, `end.dateTime`, and optional private
extended properties:

```json
{
  "studyflow_id": "calendar-team-meeting-0904",
  "studyflow_flexibility": "soft"
}
```

Without explicit flexibility, opaque events default to `hard` and transparent
events default to `flexible`. This is conservative: an unknown commitment is
never silently treated as movable. All-day events are rejected until the team
defines their blocking semantics.

## Planning state

`backend.services.PlanningState` owns the current in-memory assessments, tasks,
calendar blocks, schedule, and planning events. It validates cross-collection
references before atomically replacing a plan or schedule. List operations
return defensive copies so API consumers cannot mutate state accidentally.
Successful placements update pending tasks to `scheduled`; task progress events
update the referenced task state in the same in-memory transaction.

This state is intentionally process-local for the hackathon. It can later be
replaced with persistent storage without changing the canonical schemas or the
Agent/Scheduler contracts.
