"""StudyFlow's mock-backed FastAPI planning application."""

from collections.abc import Sequence

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from backend.agents import StudyFlowAgent
from backend.scheduler import SchedulingResult, StudyScheduler
from backend.schemas import (
    Assessment,
    CalendarBlock,
    PlanningEvent,
    ScheduledTask,
    Task,
)
from backend.services import (
    DuplicatePlanningEventError,
    MockDataStore,
    PlanningPipeline,
    PlanningState,
    PlanningStateValidationError,
    UnknownPlanningEventReferenceError,
)

DEFAULT_DEVELOPMENT_ORIGINS = (
    "http://localhost:3000",
    "http://localhost:5173",
)


def create_app(
    store: PlanningState | None = None,
    pipeline: PlanningPipeline | None = None,
    allowed_origins: Sequence[str] = DEFAULT_DEVELOPMENT_ORIGINS,
) -> FastAPI:
    """Create an API app with an injectable data store for tests and adapters."""

    selected_store = store or MockDataStore()
    app = FastAPI(
        title="StudyFlow API",
        version="0.1.0",
        description="Plan → Act → Observe → Replan API skeleton",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(allowed_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "data_mode": "mock"}

    @app.get("/assessments", response_model=list[Assessment])
    def list_assessments() -> list[Assessment]:
        return selected_store.list_assessments()

    @app.get("/tasks", response_model=list[Task])
    def list_tasks() -> list[Task]:
        return selected_store.list_tasks()

    @app.get("/calendar-blocks", response_model=list[CalendarBlock])
    def list_calendar_blocks() -> list[CalendarBlock]:
        return selected_store.list_calendar_blocks()

    @app.get("/schedule", response_model=list[ScheduledTask])
    def list_schedule() -> list[ScheduledTask]:
        return selected_store.list_scheduled_tasks()

    @app.get("/planning-events", response_model=list[PlanningEvent])
    def list_planning_events() -> list[PlanningEvent]:
        return selected_store.list_planning_events()

    @app.post(
        "/planning-events",
        response_model=PlanningEvent,
        status_code=status.HTTP_201_CREATED,
    )
    def add_planning_event(event: PlanningEvent) -> PlanningEvent:
        try:
            return selected_store.add_planning_event(event)
        except DuplicatePlanningEventError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "duplicate_event_id", "message": str(error)},
            ) from error
        except UnknownPlanningEventReferenceError as error:
            raise HTTPException(
                status_code=422,
                detail={"code": "unknown_reference", "message": str(error)},
            ) from error

    @app.post("/plan", response_model=SchedulingResult)
    def create_plan() -> SchedulingResult:
        """Run an injected pipeline or preserve the demo-safe fallback."""

        if pipeline is not None:
            planning_run = pipeline.run_plan(
                selected_store.list_assessments(),
                selected_store.list_calendar_blocks(),
                selected_store.list_scheduled_tasks(),
            )
            try:
                selected_store.replace_plan(
                    planning_run.assessments,
                    planning_run.tasks,
                    planning_run.result.scheduled_tasks,
                )
            except PlanningStateValidationError as error:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail={
                        "code": "invalid_planning_state",
                        "message": str(error),
                    },
                ) from error
            return planning_run.result

        return SchedulingResult(
            scheduled_tasks=selected_store.list_scheduled_tasks(),
            unscheduled_tasks=[],
        )

    @app.post("/replan", response_model=SchedulingResult)
    def replan(event: PlanningEvent) -> SchedulingResult:
        """Run an injected replan pipeline or keep the explicit placeholder."""

        if pipeline is None:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail={
                    "code": "replanning_not_implemented",
                    "message": (
                        "The interface is stable, but Agent and Scheduler "
                        "implementations have not been connected yet."
                    ),
                    "event_id": event.id,
                },
            )

        try:
            selected_store.validate_planning_event(event)
            result = pipeline.replan(
                event,
                selected_store.list_assessments(),
                selected_store.list_tasks(),
                selected_store.list_calendar_blocks(),
                selected_store.list_scheduled_tasks(),
            )
            selected_store.replace_schedule_and_add_event(
                result.scheduled_tasks,
                event,
            )
            return result
        except DuplicatePlanningEventError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "duplicate_event_id", "message": str(error)},
            ) from error
        except UnknownPlanningEventReferenceError as error:
            raise HTTPException(
                status_code=422,
                detail={"code": "unknown_reference", "message": str(error)},
            ) from error
        except PlanningStateValidationError as error:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "code": "invalid_planning_state",
                    "message": str(error),
                },
            ) from error

    return app


def create_demo_app() -> FastAPI:
    """Build the runnable mock app with the real Agent and Scheduler pipeline."""

    fixture_store = MockDataStore.from_provider_fixtures()
    planning_store = PlanningState(
        assessments=fixture_store.list_assessments(),
        calendar_blocks=fixture_store.list_calendar_blocks(),
    )
    pipeline = PlanningPipeline(
        agent=StudyFlowAgent(),
        scheduler=StudyScheduler(),
    )
    return create_app(planning_store, pipeline)


app = create_demo_app()
