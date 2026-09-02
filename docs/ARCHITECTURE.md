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

The default FastAPI app starts with validated mock assessments and calendar
blocks, then injects `StudyFlowAgent` and `StudyScheduler` through
`PlanningPipeline`. `POST /plan` now generates and stores a real plan rather
than returning the baseline fixture. The scheduler respects assessment unlock
times and deadlines, dependency order, duration, priority, and hard calendar
blocks; work that cannot fit is returned explicitly as `UnscheduledTask`.

Canvas and Google Calendar-shaped mocks are normalized at
`backend/integrations/` and can populate the same canonical demo state without
changing stable IDs. `PlanningState` holds assessments, tasks, calendar blocks,
schedule entries, and events in process memory with atomic reference
validation. No endpoint writes to fixture files.

`create_app()` accepts an optional `PlanningPipeline`. Without one it retains
the explicit fixture fallback and `/replan` 501 behavior for isolated API
tests. `create_demo_app()` composes the runnable mock application with the real
Agent and Scheduler implementations, and stores planning and replan results
atomically.
