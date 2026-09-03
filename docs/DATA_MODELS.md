# StudyFlow Shared Data Models

These five models are the canonical contracts between StudyFlow modules. Implement them as Pydantic models in `backend/schemas/` and use them consistently in agents, services, API routes, fixtures, tests, and persistence adapters.

## Shared conventions

- IDs and references are strings.
- Datetimes are timezone-aware and use ISO 8601 at API and storage boundaries.
- Durations are integer minutes.
- A time range must satisfy `end_time > start_time`.
- `flexibility` is one of `hard`, `soft`, or `flexible`.
- Dependencies contain `Task.id` values and must not contain the task's own ID.

## 1. Assessment

Normalized academic assessment received from Canvas or mock input.

| Field | Suggested type | Meaning |
|---|---|---|
| `id` | `str` | Unique assessment ID |
| `course_code` | `str` | Course identifier, such as `CS1010` |
| `title` | `str` | Assessment title |
| `description` | `str` | Requirements or source description |
| `type` | `str` or enum | Assessment category, initially presentation, exam/midterm, or coding assignment |
| `unlock_at` | `datetime \| None` | Earliest time the assessment becomes available |
| `deadline` | `datetime` | Submission or assessment deadline |
| `weightage` | `float \| None` | Contribution to the course grade |
| `is_group` | `bool` | Whether this is group work |
| `group_size` | `int \| None` | Number of group members; applicable when `is_group` is true |

`Assessment` does not contain `lock_at`, scheduled start/end times, or `source`.

Supported `AssessmentType` values:

- `presentation`
- `exam`
- `midterm`
- `coding_assignment`
- `quiz`

For an exam or midterm, preparatory work is represented as `Task` records, but
the formal exam itself remains the `Assessment` at its deadline. It is not a
zero-duration or nullable-duration task. When an integration provides an exact
exam start and end time, that immovable event may also be represented as a
`hard` `CalendarBlock`.

Recommended validation:

- `deadline` must be later than `unlock_at` when `unlock_at` is present.
- `weightage`, when present, must be non-negative.
- `group_size` should be greater than one for group work and otherwise be `None`.

## 2. Task

An actionable unit produced by decomposing one assessment.

| Field | Suggested type | Meaning |
|---|---|---|
| `id` | `str` | Unique task ID |
| `assessment_id` | `str` | Parent `Assessment.id` |
| `name` | `str` | Clear action-oriented task name |
| `duration_minutes` | `int` | Estimated focused work time |
| `dependencies` | `list[str]` | IDs of tasks that must finish first |
| `priority` | `int` | Relative scheduling priority |
| `status` | `str` or enum | Execution state, such as pending, scheduled, in progress, completed, or missed |

Initial `TaskStatus` values:

- `pending`
- `scheduled`
- `in_progress`
- `completed`
- `missed`

Recommended validation:

- `duration_minutes` must be positive.
- Dependencies must refer to tasks in the same assessment unless explicitly supported later.
- The dependency graph must be acyclic.

Validate reference existence, assessment boundaries, and acyclicity by passing
the complete task collection to `validate_task_graph()` at ingestion and
planning boundaries.

## 3. CalendarBlock

An existing calendar commitment or unavailable/partly movable time window.

| Field | Suggested type | Meaning |
|---|---|---|
| `id` | `str` | Unique calendar block ID |
| `title` | `str` | Human-readable event title |
| `start_time` | `datetime` | Block start |
| `end_time` | `datetime` | Block end |
| `flexibility` | `Flexibility` | How freely the block may move |

## 4. ScheduledTask

A concrete placement of a task on the study schedule.

| Field | Suggested type | Meaning |
|---|---|---|
| `id` | `str` | Unique scheduled placement ID |
| `task_id` | `str` | Scheduled `Task.id` |
| `start_time` | `datetime` | Planned start |
| `end_time` | `datetime` | Planned end |
| `flexibility` | `Flexibility` | How freely this placement may move during replanning |

`ScheduledTask` does not contain `calendar_event_id` or a `locked` boolean. Immutability is represented by `flexibility = hard`.

## Flexibility semantics

| Value | Scheduling behavior |
|---|---|
| `hard` | Must not be moved or overlapped automatically |
| `soft` | May move when necessary, with a preference to preserve it |
| `flexible` | May be freely rearranged during planning or replanning |

## 5. PlanningEvent

An observation that may trigger a planning-state update or replan.

| Field | Suggested type | Meaning |
|---|---|---|
| `id` | `str` | Unique event ID |
| `event_type` | `PlanningEventType` | Kind of observed change |
| `timestamp` | `datetime` | Time the event occurred or was recorded |
| `reference_id` | `str` | ID of the affected task, assessment, calendar block, or other relevant record |

Initial event types:

- `task_completed`
- `task_missed`
- `new_assessment`
- `assessment_updated`
- `calendar_changed`

`PlanningEvent` deliberately contains no calendar payload. The HTTP-only
`CalendarChangeRequest` wrapper pairs an unchanged `PlanningEvent` with an
unchanged `CalendarBlock` for atomic calendar updates. It is not a sixth domain
model. See `docs/API_CONTRACT.md` for request validation and transaction rules.

## Contract relationships

```text
Assessment
  └── Task[]
        └── ScheduledTask[]

CalendarBlock[] + Task[]
  └── scheduling/replanning
        └── ScheduledTask[]

PlanningEvent
  └── observe affected reference
        └── update state and replan when required
```

## End-to-end data flow

```text
Canvas or mock assessment data
  → Assessment
  → assessment understanding and decomposition
  → Task[] with durations, dependencies, and priorities

Task[] + CalendarBlock[]
  → scheduler
  → ScheduledTask[]

User progress or external change
  → PlanningEvent
  → state update
  → affected Task[] + CalendarBlock[] + existing ScheduledTask[]
  → revised ScheduledTask[]
```

The scheduler must respect task dependencies, assessment deadlines, and `hard` blocks. Replanning should preserve completed tasks and valid unaffected placements while moving `soft` and `flexible` items only as needed.
