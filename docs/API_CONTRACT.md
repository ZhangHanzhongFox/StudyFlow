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

## Runtime modes

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
generated tasks, and schedule in the in-memory planning state. `/replan`
pre-validates the event, invokes the pipeline, atomically replaces the
schedule, and then appends the event.

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
