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

Run the fixture-backed API:

```bash
uvicorn backend.main:app --reload
```

Then open `http://127.0.0.1:8000/docs` for the generated API documentation.

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

The API uses validated, process-local planning state. Its default `/plan`
fixture fallback remains available for frontend development. When A and B are
both supplied through an injected `PlanningPipeline`, `/plan` and `/replan`
atomically update the current tasks, schedule, and events. See
[`docs/INTEGRATIONS.md`](docs/INTEGRATIONS.md).

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
graphs cause the entire assessment to use its deterministic fallback. A future
OpenAI adapter only needs to implement `StructuredLLM`; do not commit real API
keys to the repository.

For a `task_missed` event, the agent marks the referenced task and every
incomplete transitive dependent as affected. Completed, upstream, and unrelated
tasks stay outside the replanning scope.

## Project references

- [Architecture](docs/ARCHITECTURE.md)
- [API contract](docs/API_CONTRACT.md)
- [Canonical data models](docs/DATA_MODELS.md)
- [Provider integrations](docs/INTEGRATIONS.md)
- [Shared mock data](data/README.md)
