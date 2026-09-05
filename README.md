# StudyFlow

StudyFlow turns university assessment deadlines into executable study
workflows, schedules them around existing commitments, observes progress, and
replans when circumstances change.

```text
Plan → Act → Observe → Replan
```

The project is being developed for the SimplifyNext Agentic AI Hackathon 2026.

## Local setup

Run from the repository root. Use Python **3.12** and Node.js **24** with npm
(Python 3.12.14 / Node 24.19.0 / npm 11.6.0 were used for the September 5 clean
verification). Install dependencies while online; the offline demo makes no
Canvas, Google Calendar, or LLM requests.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Terminal 1 — normal offline API, using the current Singapore time:

```bash
STUDYFLOW_LLM_PROVIDER=none python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --workers 1 --log-config backend/logging.json --no-access-log
```

Then open `http://127.0.0.1:8000/docs` for the generated API documentation.

For the September 6 demo, stop the normal API and start this version instead:

```bash
STUDYFLOW_ENV=demo STUDYFLOW_ENABLE_DEMO_RESET=1 STUDYFLOW_LLM_PROVIDER=none python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --workers 1 --log-config backend/logging.json --no-access-log
```

Both demo settings are necessary for `POST /demo/reset`; otherwise it is absent
(404), including in production mode. Reset restores all **five startup collections**,
including assessments and events. Regenerate Plan only generates another plan.
This server has process-local state: use one worker, keep it local, and avoid
`--reload` during recording because a restart discards progress. The supplied log
configuration displays Agent decisions/fallback and final HTTP statuses without
logging request bodies or query strings. It does not add Activity API fields.

Terminal 2 — frontend, starting from the repository root:

```bash
cd frontend
npm ci
npm run dev -- --host 127.0.0.1 --strictPort
```

Open `http://127.0.0.1:5173`. Vite proxies `/api` to `http://127.0.0.1:8000`.
Leave `VITE_API_BASE_URL` unset for this same-origin setup. For a direct API origin,
configure `create_app(allowed_origins=...)` for that exact frontend origin; default
CORS allows `http://localhost:3000` and `http://localhost:5173`.
No frontend source changes are needed for local hosting. `npm run build` produces
`frontend/dist`; `vite preview` is a local preview, not an external deployment.

The default fixtures already have deadlines on September 10, 12 and 14 and were
verified for September 5–6 at 08:00, 14:00 and 23:00. No dates/IDs were changed.
After study hours, new sessions start in the next available study window. The
September 3 acceptance fixture is historical test data, not the current UI plan.

The default app loads Canvas- and Google Calendar-shaped mock payloads through
the integration adapters, then runs `StudyFlowAgent → PlanningPipeline →
StudyScheduler` when `POST /plan` is called. The generated tasks and schedule
are committed to the in-memory planning state and immediately appear from
`GET /tasks` and `GET /schedule`.

The normal API uses the current Singapore time when each plan is scheduled,
rounded up to the next minute when necessary. Old mock calendar dates and
previous plans do not move new tasks into the past. Daily study hours still
apply: a plan generated after the study window starts on the next available
day. Expired deadlines produce explicit unscheduled tasks.

For reproducible tests, inject `create_app(clock=...)` or use a scheduler with
an explicit `planning_start`. A standalone scheduler without either clock
option retains the fixture-based date inference used by the existing demos.

Run tests:

```bash
python -m pip check
python -m pytest -o addopts='' -q
cd frontend
npm test
npm run build
# Optional browser regression dependencies (no manifest/lockfile changes):
npm install --no-save --package-lock=false playwright@1.62.1
npx playwright install chromium
npm run test:e2e
```

Browser tests create their own isolated backend and Vite server. Set
`STUDYFLOW_TEST_PYTHON` to an absolute Python path if it is not `.venv/bin/python`.
They exercise the existing UI; reset/new-assessment controls still require D's
integration. The HTTP client helpers already exist.

For a **disposable reset-enabled demo server**, run from the root:

```bash
python -m backend.demo_check --base-url http://127.0.0.1:8000 --allow-reset
```

This performs three rounds of Plan → Complete → Missed → Replan → assessment
changes → Reset and validates all five collections. It resets existing demo
changes, prints the explicitly simulated missed-event time, and ends at startup
state. Product scheduling still uses the real clock. See
[September 5 C handoff](docs/SEPT5_C_HANDOFF.md) for copyable requests, verification
evidence, the recording runbook and slide-ready architecture/fallback content.

### Common startup problems

- `python`, `npm`, or a module is missing: install Python/Node first, activate the
  project venv and repeat `pip install -r requirements.txt` / `npm ci` in their
  respective directories. Do not install backend packages into system Python.
- Port busy: stop your previous server or select a port and update the proxy
  configuration together. `--strictPort` prevents silently opening a new UI port.
- Browser `/api` returns 502: confirm `GET http://127.0.0.1:8000/health` works and
  the backend terminal is still running. A CORS error usually means a direct URL
  bypassed the Vite proxy or an origin differs by hostname/port.
- Reset 404: check both demo settings and restart the backend. Reset is absent
  from OpenAPI when disabled. A successful reset requires a fresh GET of all
  five collections; do not submit another event to refresh.
- 409 duplicate: refresh events with the original ID before retrying. HTTP 200
  with `unscheduled_tasks` is partial success and must remain visible.
- No sessions today: check current time, study hours and deadlines; inspect the
  full schedule across dates. Expired deadlines are not a server startup fault.
- Invalid LLM configuration fails startup. Set `STUDYFLOW_LLM_PROVIDER=none` and
  restart for the deterministic demo. With Bedrock enabled, unavailable/invalid
  output falls back during requests but may first wait for provider timeouts.
- Clean tests may emit upstream Starlette/httpx/AnyIO deprecation warnings.
  They did not block the validated install; no new HTTP SDK was added at freeze.

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
