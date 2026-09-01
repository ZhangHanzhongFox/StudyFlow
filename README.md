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

## Project references

- [Architecture](docs/ARCHITECTURE.md)
- [API contract](docs/API_CONTRACT.md)
- [Canonical data models](docs/DATA_MODELS.md)
- [Shared mock data](data/README.md)
