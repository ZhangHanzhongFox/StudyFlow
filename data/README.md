# StudyFlow shared mock data

The files in `data/mock/` form one canonical, normalized demo scenario shared by
the agent, scheduler, backend, and frontend workstreams. They use the models in
`backend/schemas/`; they are not raw Canvas or Google Calendar payloads.

## Scenario

- Reference timezone: Asia/Singapore (`+08:00`).
- Reference date: 2026-09-01.
- Assessments: one presentation, one midterm, and one coding assignment.
- Calendar: realistic hard, soft, and flexible commitments across one week.
- Tasks: an expected baseline decomposition with durations and dependencies.
- Schedule: one complete, conflict-free baseline placement for every task.
- Planning events: replayable examples for all initial event types.

`planning_events.json` contains events to replay against the baseline. It is not
a snapshot in which every event has already been applied. For example,
`event-presentation-slides-missed` is intended to trigger the demo replan that
moves the dependent script and rehearsal tasks.

## Files

| File | Canonical model | Primary consumers |
|---|---|---|
| `assessments.json` | `Assessment` | Canvas adapter, agent, dashboard |
| `tasks.json` | `Task` | Agent, scheduler, task UI |
| `calendar_blocks.json` | `CalendarBlock` | Calendar adapter, scheduler |
| `scheduled_tasks.json` | `ScheduledTask` | Scheduler, Today's Plan UI |
| `planning_events.json` | `PlanningEvent` | Observer/replanner, Agent Activity UI |

IDs are stable cross-file references. Keep them unchanged unless every consumer
and fixture reference is updated together. Provider-specific mock payloads may
be added separately under `data/providers/`, but must be normalized into these
contracts before entering business logic.

## Provider-shaped fixtures

`data/providers/` contains realistic Canvas and Google Calendar-style payloads,
not canonical models. The C workstream adapters normalize them to the exact
assessment and calendar records above. They deliberately preserve the shared
stable IDs so provider-boundary testing does not disrupt Agent, Scheduler, or
Frontend development. See `docs/INTEGRATIONS.md` for the mapping rules.
