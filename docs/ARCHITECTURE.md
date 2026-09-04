# StudyFlow Architecture

## Goal

StudyFlow converts assessment deadlines into executable work, places that work
around existing commitments, observes execution, and replans when conditions
change:

```text
Plan → Act → Observe → Replan
```

All boundaries use the five canonical models in `backend/schemas/`. Provider
payloads, LLM output, and HTTP input must be normalized and validated before
entering business logic.

## Module ownership

| Area | Owner | Responsibility |
|---|---|---|
| `backend/agents/` | A: Agent / Workflow | Classification, task decomposition, affected-task discovery |
| `backend/scheduler/` | B: Scheduling / Calendar | Availability, placement, conflicts, deadlines, dependency-aware rescheduling |
| `backend/services/`, `backend/main.py` | C: Data Integration / Backend | Canvas/calendar adapters, mock access, orchestration, HTTP API |
| `frontend/` | D: Frontend / Demo | Dashboard and interactions using the documented API |
| `backend/schemas/`, `data/mock/` | Shared contract | Change only with coordinated documentation, fixtures, tests, and consumer updates |

## Planning flow

```text
Canvas payload or mock
        │
        ▼
C: normalize and validate Assessment[]
        │
        ▼
A: classify and decompose
        │ Task[]
        ▼
validate_task_graph()
        │
        ▼
B: schedule against CalendarBlock[]
        │
        ▼
SchedulingResult
        ├── ScheduledTask[]
        └── UnscheduledTask[] with explicit reasons
        │
        ▼
C: API → D: dashboard
```

`SchedulingResult` and `UnscheduledTask` are operational response wrappers,
not additional persisted domain models.

## Replanning responsibility

A and B have deliberately separate responsibilities:

```text
PlanningEvent
      │
      ▼
A: determine affected task IDs and dependency consequences
      │
      ▼
B: choose new concrete times for those tasks
      │
      ▼
SchedulingResult
```

For example, when the slides task is missed, A identifies slides, script, and
rehearsal as affected. B preserves completed work and unaffected valid
placements, then moves only the necessary soft or flexible schedule entries.

B must return an `UnscheduledTask` with a machine-readable reason when a task
cannot be placed. It must not silently drop work. A may then decide whether to
decompose differently, adjust estimates, or ask the user for a decision.

Observation writes now use `PlanningState.replan`: under one state lock, C
stages task status and an optional calendar upsert, runs A/B, validates the
result, then commits tasks, calendar, schedule and event together. No state is
published on exceptions. `/replan` takes a bare event; `/calendar-changes`
takes the `CalendarChangeRequest` wrapper, without changing domain fields.

The pipeline passes `event.timestamp` as `replanning_start` to the Scheduler.
For calendar events it also sets `preserve_valid_affected=True`; A's broad
candidate set does not force all valid tasks to move. B checks actual time
constraints and propagates necessary dependency moves. See
[REPLAN_HANDOFF.md](REPLAN_HANDOFF.md) for the implemented shared baseline.

## Stable Python interfaces

- `AgentWorkflow` in `backend/agents/contracts.py`
  - `classify_assessment()`
  - `decompose_assessment()`
  - `find_affected_task_ids()`
- `Scheduler` in `backend/scheduler/contracts.py`
  - `schedule_tasks()`
  - `reschedule_tasks()`
- `PlanningPipeline` in `backend/services/planning.py`
  - `plan()`
  - `replan()`

Implementations may add private helpers, but should preserve these public
boundaries while parallel development is underway.

## Current runtime state

The Agent / Workflow implementation can classify and decompose assessments
using a provider-neutral structured-output boundary, a credential-free fake,
and deterministic templates. Its canonical task outputs and affected-task
analysis are ready to inject through `PlanningPipeline`.

The Agent revalidates provider model instances (including nested drafts) before
building canonical tasks. Invalid fields, numeric coercions, empty outputs and
invalid dependency graphs trigger a complete deterministic fallback. Templates
use generic preparation defaults, not invented assessment requirements; task
durations remain estimates. Decision reasons and dependency witness paths are
backend logs, not fields added to the domain models or HTTP responses.

Assessment events currently select incomplete work already present in the
supplied task collection. They do not ingest assessment payloads, compare old
and new requirements, or regenerate tasks inside `replan()`. The verified
composition of existing Agent methods, the conservative replacement policy,
and the remaining C/D integration gates are documented in the September 4 A
section of [REPLAN_HANDOFF.md](REPLAN_HANDOFF.md).

`StudyScheduler` implements the stable `Scheduler` protocol and is injected by
C through `PlanningPipeline`. It respects assessment unlock times and
deadlines, dependency order, duration, priority, and hard calendar blocks;
work that cannot fit is returned explicitly as `UnscheduledTask`.

The exported FastAPI app normalizes provider-shaped mock data and injects the
real `StudyFlowAgent` and `StudyScheduler` through `PlanningPipeline`.
`POST /plan` generates canonical tasks and a dynamic schedule, then atomically
publishes both through the planning state. `GET /tasks` and `GET /schedule`
therefore always reflect the latest successful run.

The default runtime injects a Singapore-time clock into `StudyScheduler`.
Each scheduling call reads it after decomposition and rounds up to a whole
minute, so an old mock calendar or previous plan cannot place new work before
the current time. It does not freeze the clock at application startup.
Tests can supply `create_app(clock=...)`; an explicit scheduler `planning_start`
takes precedence for fixed-date demos. Replan still uses the event timestamp
and preserves completed work and unaffected valid placements.

Canvas and Google Calendar-shaped mocks are normalized at
`backend/integrations/` and can populate the same canonical demo state without
changing stable IDs. `PlanningState` holds assessments, tasks, calendar blocks,
schedule entries, and events in process memory with atomic reference
validation. No endpoint writes to fixture files.

`create_app()` still accepts an explicit store and optional pipeline for tests.
Passing a store without a pipeline retains the stable fixture `/plan` and
explicit `/replan` 501 behavior, without changing the public API shape.
