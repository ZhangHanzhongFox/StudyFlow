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
`PlanningPipeline` injects `StudyFlowAgent` and B's concrete `StudyScheduler`
directly through their stable protocols. The scheduler derives a reproducible
planning start from the provider-backed mock calendar, reports failures through
`UnscheduledTask`, and preserves unaffected placements during replanning.

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

## Amazon Bedrock

`backend.agents.bedrock.BedrockStructuredLLM` implements the existing
`StructuredLLM` protocol using `boto3` and the Bedrock Converse API. The default
model is `amazon.nova-lite-v1:0` in `us-east-1`, matching the initial successful
local connection. `STUDYFLOW_LLM_PROVIDER=bedrock` enables injection into the
default app; `none` (the default) keeps the deterministic runtime. Invalid
provider or token-limit settings fail at startup instead of silently disabling
the LLM. Explicitly injected pipelines and stores retain their existing behavior.

The adapter forces one `submit_assessment_result` tool call whose input schema
comes from `ClassificationOutput` or `DecompositionOutput`. The tool is only a
structured-result envelope; no model-generated tool is executed. Local schema
references are expanded and the root schema contains only `type`, `properties`
and `required`, as required by Nova. The original Pydantic validation remains
authoritative, followed by the agent's canonical Task conversion and graph
validation. A truncated or filtered response never enters a plan as partial
tasks. Ordinary text responses are also rejected. Prompts distinguish assessment
delivery time from the student's preparation effort; these estimates are not
guaranteed accurate by schema validation.

The client resolves credentials lazily using boto3, including the portal's
access key, secret key and session token. Importing or starting the API makes
no inference request. Connection/read timeouts are 5/45 seconds, with two total
SDK attempts per call; there is no additional application retry loop. Provider
and validation failures use the existing deterministic fallback. Logs include
model/schema and token counts on validated output (INFO), and exception type
on fallback (WARNING); they do not include credentials or assessment bodies.

The standalone `python -m backend.agents.check_bedrock` command makes a single
structured-output request and fails visibly instead of falling back. See the
[README](../README.md#connect-amazon-bedrock-nova-lite) for the same-terminal
credential setup and startup sequence. Tests mock Converse and make no paid
requests. Shared schemas, fixtures, scheduling and replanning rules are unchanged.

AWS references:
- [Nova tool schema and tool choice](https://docs.aws.amazon.com/nova/latest/userguide/tool-use-definition.html)
- [Converse with Nova](https://docs.aws.amazon.com/bedrock/latest/userguide/bedrock-runtime_example_bedrock-runtime_Converse_AmazonNovaText_section.html)
