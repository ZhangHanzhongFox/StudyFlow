# StudyFlow — Codex Instructions

## Project overview

StudyFlow is an Agentic AI project for the SimplifyNext Agentic AI Hackathon 2026. It turns university assessment deadlines into executable study workflows, schedules them around a student's existing commitments, observes execution, and replans when circumstances change.

The core agent loop is:

**Plan → Act → Observe → Replan**

The product is an adaptive academic execution system—not a generic to-do list, chatbot, deadline tracker, or simple AI calendar scheduler.

## Core problem

A deadline tells a student when work is due, but not:

- when to start;
- which preparation steps are required;
- which steps depend on others;
- how to distribute work across available time;
- how to recover after missed work or changed commitments.

StudyFlow closes this execution gap.

## MVP scope

Support at least these assessment types:

1. Presentation
2. Exam / Midterm
3. Coding Assignment

Use Canvas data when integration is available; otherwise use realistic mock Canvas data. Calendar input may likewise use a real integration or a stable mock.

## End-to-end flow

1. Ingest and normalize assessment data into `Assessment`.
2. Interpret the assessment type, description, requirements, and deadline.
3. Decompose it into actionable `Task` records.
4. Add task dependencies, duration estimates, and priorities.
5. Read existing commitments as `CalendarBlock` records.
6. Schedule tasks into available time as `ScheduledTask` records.
7. Observe user and calendar changes through `PlanningEvent` records.
8. Replan affected work while respecting dependencies, deadlines, completed work, and hard calendar constraints.

## Shared data contracts

The five canonical shared models are:

- `Assessment`
- `Task`
- `CalendarBlock`
- `ScheduledTask`
- `PlanningEvent`

Their authoritative definitions are in [`docs/DATA_MODELS.md`](docs/DATA_MODELS.md). Implement them as Pydantic models under `backend/schemas/`. All agents, services, API routes, mocks, tests, and persistence adapters must use these contracts rather than creating incompatible local variants.

Do not add, rename, or remove shared fields without updating the data-model document, schemas, fixtures, and consumers together.

## Architecture boundaries

Keep the pipeline modular:

- assessment ingestion and normalization;
- assessment understanding and task decomposition;
- dependency and priority generation;
- calendar availability and scheduling;
- event observation and replanning.

Business logic should depend on shared schemas, not on provider-specific Canvas or calendar payloads. Normalize external data at system boundaries.

Replanning should preserve completed tasks and unaffected valid schedule entries whenever possible. It must never overlap `hard` calendar blocks or violate task dependencies.

## Coding instructions

- Use Python type hints and Pydantic for shared models.
- Keep datetime handling timezone-aware and serialize datetimes consistently.
- Use stable string IDs across references.
- Represent durations in integer minutes.
- Validate references and time ranges at boundaries.
- Keep LLM prompts separate from deterministic validation and scheduling logic.
- Prefer deterministic scheduling and validation where possible; use AI for interpretation and decomposition.
- Add focused tests for schema validation, dependency ordering, scheduling conflicts, and replanning triggers.
- Keep mocks aligned with the canonical schemas.
- Do not silently invent missing assessment facts; use explicit defaults or surface missing data.

## Definition of done for changes

A change is complete when it:

- respects the canonical shared contracts;
- preserves the Plan → Act → Observe → Replan loop;
- includes proportionate tests;
- updates relevant documentation and fixtures;
- does not turn the product into a generic task or calendar app.
