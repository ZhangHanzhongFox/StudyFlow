# StudyFlow API Contract

The API entrypoint is `backend.main:app`. Datetimes are timezone-aware ISO 8601
strings and enums are serialized as their lowercase string values.

Local browser clients at `http://localhost:3000` and
`http://localhost:5173` are allowed by default. Other origins can be supplied
to `create_app()` by the deployment or test configuration.

## Endpoints

| Method | Path | Response | Current behavior |
|---|---|---|---|
| `GET` | `/health` | status object | Reports mock data mode |
| `GET` | `/assessments` | `Assessment[]` | Validated shared fixtures |
| `GET` | `/tasks` | `Task[]` | Latest generated planning state |
| `GET` | `/calendar-blocks` | `CalendarBlock[]` | Validated shared fixtures |
| `GET` | `/schedule` | `ScheduledTask[]` | Latest generated planning state |
| `GET` | `/planning-events` | `PlanningEvent[]` | Current in-memory observation history |
| `POST` | `/planning-events` | `PlanningEvent` | Validates and stores an event in memory |
| `POST` | `/plan` | `SchedulingResult` | Runs the default or injected Agent → Scheduler pipeline |
| `POST` | `/replan` | `SchedulingResult` | Runs affected-task discovery and dependency-injected rescheduling |
| `POST` | `/calendar-changes` | `SchedulingResult` | Upserts one calendar block and replans in one transaction |

FastAPI also provides generated OpenAPI documentation at `/docs` while the
application is running.

## Scheduling result

```json
{
  "scheduled_tasks": [
    {
      "id": "scheduled-presentation-outline",
      "task_id": "task-presentation-outline",
      "start_time": "2026-09-03T08:00:00+08:00",
      "end_time": "2026-09-03T09:00:00+08:00",
      "flexibility": "flexible"
    }
  ],
  "unscheduled_tasks": []
}
```

An unsuccessful placement must be explicit:

```json
{
  "task_id": "task-midterm-review",
  "reason": "deadline_constraint",
  "message": "No dependency-valid slot exists before the assessment deadline."
}
```

Allowed failure reasons are:

- `no_available_slot`
- `deadline_constraint`
- `dependency_conflict`
- `invalid_input`

## Posting an observation

For UI actions that must replan, **POST the event directly to `/replan`**.
Do not first POST the same event to `/planning-events`: `/replan` also records
the event, and duplicate IDs return 409. `/planning-events` remains the
observation-only endpoint; it updates task status but does not reschedule.

```http
POST /planning-events
Content-Type: application/json
```

```json
{
  "id": "event-demo-task-missed",
  "event_type": "task_missed",
  "timestamp": "2026-09-04T12:05:00+08:00",
  "reference_id": "task-presentation-slides"
}
```

A duplicate event ID returns HTTP 409:

```json
{
  "detail": {
    "code": "duplicate_event_id",
    "message": "planning event id already exists: event-demo-task-missed"
  }
}
```

Invalid schema input returns FastAPI's standard HTTP 422 validation response.
An event with a valid shape but an unknown `reference_id` also returns HTTP 422
with `detail.code = unknown_reference`.

## September 3 integration contract

### Task observation and replanning

`POST /replan` takes a bare canonical `PlanningEvent`. For task actions use
`task_missed` or `task_completed`, and take `reference_id` from `GET /tasks`.
Generate one event ID per user action (for example, `crypto.randomUUID()`).
Use the actual observation time, including timezone. Fixed demo timestamps
must be visibly identified as simulation data.

The backend stages task status **before** invoking the Agent and Scheduler.
`PlanningPipeline.replan` passes `event.timestamp` as the keyword argument
`replanning_start` to `Scheduler.reschedule_tasks`. New placements cannot
start before that instant. UTC (`Z`) and offset timestamps representing the
same instant produce the same result; daily study hours use the schedule's
timezone, not the timestamp's serialization offset. Existing valid history
does not move merely because it precedes the event.

Completed work stays completed. Marking a completed task missed is rejected
with 422 `invalid_replanning_input` (or `invalid_planning_event` through the
observation-only endpoint). A missed task successfully placed again becomes
`scheduled`; its missed observation remains in event history. A missed task
that cannot fit stays `missed`. Other formerly scheduled tasks that lose their
placement become `pending` rather than incorrectly remaining `scheduled`.

### Calendar changes

`POST /calendar-changes` accepts the `CalendarChangeRequest` HTTP wrapper:

```json
{
  "event": {
    "id": "event-calendar-extra-lecture-1",
    "event_type": "calendar_changed",
    "timestamp": "2026-09-03T09:00:00+08:00",
    "reference_id": "calendar-extra-lecture"
  },
  "calendar_block": {
    "id": "calendar-extra-lecture",
    "title": "Extra lecture",
    "start_time": "2026-09-03T09:00:00+08:00",
    "end_time": "2026-09-03T10:00:00+08:00",
    "flexibility": "hard"
  }
}
```

This inserts a new block ID or replaces the complete block with that ID.
It does not delete other blocks. Deletion is outside this contract.
The event must be `calendar_changed`, its reference must match the supplied
block ID, and the block must have a valid timezone-aware time range. Invalid
wrappers return standard FastAPI 422 validation details.

The backend stages the new calendar before reference validation and planning,
so a new block does not have to exist in the old state. Calendar, new-assessment,
and assessment-update events set `preserve_valid_affected=True` on the Scheduler:
A may return a broad incomplete candidate set, while B keeps valid placements
and moves conflicting work and necessary dependents. Hard placements and
completed history are immutable. A change that would overlap them is rejected with 422
`invalid_replanning_input`, with no calendar or event mutation.
Likewise, a missed task with a hard placement cannot be moved automatically;
the request is rejected rather than falsely reporting a successful recovery.

A preserved future hard task may depend on a task that needs to move. The
scheduler keeps the hard placement and first attempts to place its prerequisite
before it. If no result can satisfy that dependency order, replanning is
rejected with 422 `invalid_replanning_input`; the backend never commits a
schedule in which a fixed task starts before an incomplete prerequisite ends.

A bare `calendar_changed` event sent to `/replan` only re-evaluates the existing
calendar; it cannot convey a new block or new times. Use `/calendar-changes`
for user edits.

### Results, failure and refresh

Both endpoints return the existing `SchedulingResult` shape:

- `scheduled_tasks` is the **complete resulting schedule**, including preserved
  entries, not just the moved tasks.
- `unscheduled_tasks` describes placement failures found in this run. A lack of
  available time is a normal 200 result: save the valid partial schedule,
  calendar changes, task states, and event together.
- Every non-completed task must appear exactly once in either the complete
  schedule or `unscheduled_tasks`. Duplicate placements, contradictory entries,
  and silently omitted active tasks are rejected as an invalid planning state.
- Invalid input (422), duplicate event IDs (409), or runtime failures (500)
  leave all four collections unchanged. Duplicate IDs are rejected, not
  automatically replayed. After an uncertain network failure, refresh state
  and check `/planning-events` for the original ID before creating another
  observation. Retrying that ID returns 409 if it already committed.

For this single-process demo, observation transactions serialize snapshot,
planning and commit under the state lock. Separate GET requests are not a
versioned snapshot across concurrent users. Automatic polling, persistent
storage, and multi-user isolation are outside this contract.

D saves the old schedule before submitting, compares by `task_id`, absolute
start/end times, and `flexibility`, and shows added/moved/preserved/removed
tasks plus failure messages. A changed placement `id` alone is not a move.
After success, refresh `/tasks`, `/schedule`, `/planning-events`, and
`/calendar-blocks`. Do not call `/plan` to refresh: that route regenerates
tasks. Failure details should remain visible until the next planning action;
`GET /schedule` alone cannot reconstruct the previous failure list.

`frontend/src/api.ts` exports `replan`, `changeCalendar`, `compareSchedules`,
and `ApiError` (`status`, `code`, `message`). `getDashboardData` also includes
`calendarBlocks`. D has wired these functions into the completed/missed buttons
and calendar form; see the browser acceptance notes in the handoff document.

See [REPLAN_HANDOFF.md](REPLAN_HANDOFF.md) for ownership, common test inputs,
expected times, and the reproducible verification command.

## Runtime modes

### Assessment-event limitation (September 4)

`new_assessment` and `assessment_updated` are valid event types, but a bare
event supplies only a reference ID, not an assessment payload or requirement
diff. The assessment must already exist for reference validation to succeed.
Neither `/planning-events` nor `/replan` inserts or updates an Assessment or
decomposes new tasks. In particular, an existing assessment with no tasks can
yield an empty successful replan; this is not proof of successful ingestion.

A has verified a composition of existing methods in which C stages a normalized
Assessment and generated canonical Task[] before replanning. No assessment-write
endpoint or automatic task-replacement transaction is introduced in this work.
See [REPLAN_HANDOFF.md](REPLAN_HANDOFF.md) for prerequisites and preservation
rules. Agent decision/fallback reasons remain backend logs; neither
`PlanningEvent` nor `SchedulingResult` exposes them to the frontend.

### Existing runtime behavior

`backend.main:app` is the provider-backed dynamic demo runtime. It normalizes
provider-shaped mocks into canonical assessments and calendar blocks, starts
with no precomputed tasks or schedule, and runs the real Agent and Scheduler
after `POST /plan`.

Passing an explicit store without a pipeline, such as
`create_app(MockDataStore())`, preserves the baseline fixture behavior for
contract tests and isolated frontend work. In that explicit fallback mode,
`POST /replan` returns HTTP 501 with
`detail.code = replanning_not_implemented`.

In dynamic mode, `/plan` stores the pipeline's classified assessments,
generated tasks, and schedule in the in-memory planning state. `/replan` and
`/calendar-changes` stage changes, validate input, invoke the pipeline, and
atomically commit task states, calendar blocks, schedule and event.

If an injected Agent or Scheduler returns references that cannot form a valid
planning state, the API rejects the result with HTTP 500:

```json
{
  "detail": {
    "code": "invalid_planning_state",
    "message": "scheduled task ... references unknown task ..."
  }
}
```

Pipeline input failures return HTTP 422 with
`detail.code = invalid_planning_input` or `invalid_replanning_input`.
Unexpected runtime failures return HTTP 500 with `detail.code = planning_failed`
or `replanning_failed`. Failed runs do not partially replace tasks, schedules,
or planning events. Duplicate event IDs continue to return HTTP 409.
