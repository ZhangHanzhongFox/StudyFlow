# StudyFlow

StudyFlow turns university assessment deadlines into executable study
workflows, schedules them around existing commitments, observes progress, and
replans when circumstances change.

```text
Plan → Act → Observe → Replan
```

The project is being developed for the SimplifyNext Agentic AI Hackathon 2026.

## Local setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Run the provider-backed dynamic API:

```bash
uvicorn backend.main:app --reload
```

Then open `http://127.0.0.1:8000/docs` for the generated API documentation.

The default app loads Canvas- and Google Calendar-shaped mock payloads through
the integration adapters, then runs `StudyFlowAgent → PlanningPipeline →
StudyScheduler` when `POST /plan` is called. The generated tasks and schedule
are committed to the in-memory planning state and immediately appear from
`GET /tasks` and `GET /schedule`.

Run tests:

```bash
python -m pytest -q
```

## Data integration and backend state

Realistic Canvas and Google Calendar-shaped mocks live under `data/providers/`
and normalize into the five canonical Pydantic contracts before entering
business logic. To exercise the same boundary without OAuth credentials:

```python
from backend.services import MockDataStore

store = MockDataStore.from_provider_fixtures()
```

The API uses validated, process-local planning state. The exported FastAPI app
now uses the real deterministic Agent and Scheduler implementations by default.
Tests and isolated consumers can still pass `create_app(MockDataStore())` to
exercise the original baseline response without a dynamic pipeline. `/plan`
and `/replan` atomically update the current tasks, schedule, and events. See
[`docs/INTEGRATIONS.md`](docs/INTEGRATIONS.md).

## Deterministic scheduling

`StudyScheduler` implements the shared `Scheduler` contract. It schedules
incomplete tasks within a configurable daily study window while respecting:

- assessment unlock times and deadlines;
- task durations, dependencies, and priority;
- hard calendar blocks;
- completed work and preserved placements.

Tasks that cannot fit are returned in `unscheduled_tasks` with a stable reason
instead of being silently dropped.

## Agent workflow without an API key

The Agent / Workflow implementation works deterministically without network
access or provider credentials. With no LLM supplied, it classifies from the
already-normalized assessment type and decomposes presentation, exam/midterm,
coding-assignment, and quiz assessments using validated fallback templates:

```python
from backend.agents import StudyFlowAgent
from backend.services import MockDataStore

store = MockDataStore()
agent = StudyFlowAgent()
tasks = agent.decompose_assessment(store.list_assessments()[0])
```

If a provider supplies no assessment description, the normalized empty string
is preserved and the agent still uses the assessment type's deterministic
template. It does not infer missing requirements from unavailable text.

Use `FakeStructuredLLM` to exercise the same Pydantic structured-output path
during development without a real model:

```python
from backend.agents import FakeStructuredLLM, StudyFlowAgent
from backend.services import MockDataStore

fake_llm = FakeStructuredLLM([
    {"assessment_type": "presentation"},
    {
        "tasks": [
            {
                "step_key": "outline",
                "name": "Create the presentation outline",
                "duration_minutes": 60,
                "priority": 3,
                "dependency_keys": [],
            }
        ]
    },
])
store = MockDataStore()
agent = StudyFlowAgent(fake_llm)
assessment_type = agent.classify_assessment(store.list_assessments()[0])
tasks = agent.decompose_assessment(store.list_assessments()[0])
```

Mapping responses are validated with Pydantic before they enter business
logic. Provider exceptions, invalid fields, unknown dependencies, and cyclic
graphs cause the entire assessment to use its deterministic fallback. Provider
adapters implement `StructuredLLM`; do not commit real API keys to the repository.

For a `task_missed` event, the agent marks the referenced task and every
incomplete transitive dependent as affected. Completed, upstream, and unrelated
tasks stay outside the replanning scope.

## Connect Amazon Bedrock (Nova Lite)

The default is offline (`STUDYFLOW_LLM_PROVIDER=none`). To enable the real LLM,
first export the three temporary credentials from the AWS access portal into
your terminal: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and
`AWS_SESSION_TOKEN`. The hackathon guide specifies `us-east-1`; portal
credentials expire after approximately 12 hours and must be renewed.

Run these commands from the project root in that **same terminal**:

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
export STUDYFLOW_LLM_PROVIDER=bedrock
export AWS_DEFAULT_REGION=us-east-1
export AWS_REGION=us-east-1
export BEDROCK_MODEL_ID=amazon.nova-lite-v1:0
python -m backend.agents.check_bedrock
```

The check makes one paid request using a mock presentation. It prints validated
structured output and exits nonzero on failure; it never silently uses a
template. After it succeeds, start (or restart) the API from the same terminal:

```bash
python -m uvicorn backend.main:app --reload --log-level info
```

Open `http://127.0.0.1:8000/docs` and run `POST /plan`, then `GET /tasks` and
`GET /schedule`. The frontend's plan action uses the same pipeline. Each full
plan currently makes two LLM calls per assessment (six for the three demo
assessments), with at most two SDK attempts per call. Replanning existing
tasks remains deterministic. The original Canvas/calendar fixtures remain mocks.

`BEDROCK_MAX_TOKENS` optionally controls each response limit (default 2048,
range 1-5000). The adapter rejects truncated responses, invalid fields and
missing tool results; the agent validates dependencies and falls back to the
existing template on provider or validation failures. A successful `/plan`
response alone therefore does not prove the LLM worked. Look for the warning
`using deterministic fallback`; use the standalone check to diagnose the live
structured-output boundary without fallback. Preparation durations are model
estimates and still need human review.

Credentials are read through the standard boto3 credential chain. Shell exports
do not propagate into another terminal or an already running backend. `.env`
is **not automatically loaded**; if you choose to use one, explicitly start
Uvicorn with `--env-file .env`. Keep all credentials on the backend. Unit tests
default to offline mode even when run in your Bedrock-enabled terminal.

See [Bedrock integration details](docs/INTEGRATIONS.md#amazon-bedrock).

## Project references

- [September 3 Replan handoff and acceptance scenarios](docs/REPLAN_HANDOFF.md)
- [Architecture](docs/ARCHITECTURE.md)
- [API contract](docs/API_CONTRACT.md)
- [Canonical data models](docs/DATA_MODELS.md)
- [Provider integrations](docs/INTEGRATIONS.md)
- [Shared mock data](data/README.md)
