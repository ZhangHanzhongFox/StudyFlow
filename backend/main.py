"""StudyFlow's fixture-backed FastAPI application skeleton."""

from collections.abc import Callable, Sequence
from datetime import datetime
from zoneinfo import ZoneInfo
import os
import logging

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware

from backend.agents import StudyFlowAgent
from backend.agents.bedrock import configured_llm
from backend.scheduler import SchedulingResult, StudyScheduler
from backend.schemas import (
    Assessment,
    CalendarBlock,
    CalendarChangeRequest,
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
from backend.schemas.requests import AssessmentChangeRequest
from backend.services.assessment_changes import AssessmentConflictError

logger = logging.getLogger(__name__)

DEFAULT_DEVELOPMENT_ORIGINS = (
    "http://localhost:3000",
    "http://localhost:5173",
)


def current_study_time() -> datetime:
    """The current MVP uses Singapore time for its daily study window."""

    return datetime.now(ZoneInfo("Asia/Singapore"))


def create_app(
    store: PlanningState | None = None,
    pipeline: PlanningPipeline | None = None,
    allowed_origins: Sequence[str] = DEFAULT_DEVELOPMENT_ORIGINS,
    *,
    clock: Callable[[], datetime] | None = None,
    environment: str | None = None,
    demo_reset_enabled: bool | None = None,
    reset_factory: Callable[[], PlanningState] | None = None,
) -> FastAPI:
    """Create an API app with an injectable data store for tests and adapters."""

    use_default_runtime = store is None and pipeline is None
    selected_store = store or MockDataStore.for_dynamic_provider_demo()
    environment = environment or os.getenv("STUDYFLOW_ENV", "production")
    reset_enabled = (demo_reset_enabled if demo_reset_enabled is not None
                     else os.getenv("STUDYFLOW_ENABLE_DEMO_RESET") == "1")
    reset_enabled = reset_enabled and environment in {"demo", "development"}
    baseline = (selected_store.list_assessments(), selected_store.list_tasks(),
                selected_store.list_calendar_blocks(), selected_store.list_scheduled_tasks(),
                selected_store.list_planning_events())
    selected_pipeline = (
        PlanningPipeline(
            StudyFlowAgent(configured_llm()),
            StudyScheduler(clock=clock or current_study_time),
        )
        if use_default_runtime
        else pipeline
    )
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

    if reset_enabled:
        @app.post("/demo/reset")
        def reset_demo() -> dict[str, str]:
            """Restore all five startup collections; available only in demo/development."""
            try:
                fresh = reset_factory() if reset_factory else PlanningState(*baseline)
                selected_store.reset(
                    fresh.list_assessments(), fresh.list_tasks(), fresh.list_calendar_blocks(),
                    fresh.list_scheduled_tasks(), fresh.list_planning_events(),
                )
            except Exception as error:
                logger.error("demo_reset_failed error_type=%s", type(error).__name__)
                raise HTTPException(500, detail={"code": "demo_reset_failed",
                                    "message": "Demo reset failed; state was not changed."}) from error
            logger.info("demo_reset_completed")
            return {"status": "reset"}

    @app.post("/assessment-changes", response_model=SchedulingResult)
    def change_assessment(change: AssessmentChangeRequest) -> SchedulingResult:
        if selected_pipeline is None:
            raise HTTPException(501, detail={"code": "replanning_not_implemented",
                                "message": "Agent and Scheduler are not connected."})
        try:
            result = selected_store.change_assessment(change.event, change.assessment, selected_pipeline)
            logger.info("assessment_change_completed event_type=%s", change.event.event_type.value)
            return result
        except DuplicatePlanningEventError as error:
            raise HTTPException(409, detail={"code": "duplicate_event_id", "message": str(error)}) from error
        except AssessmentConflictError as error:
            raise HTTPException(409, detail={"code": "assessment_conflict", "message": str(error)}) from error
        except UnknownPlanningEventReferenceError as error:
            raise HTTPException(422, detail={"code": "unknown_reference", "message": str(error)}) from error
        except PlanningStateValidationError as error:
            logger.error("assessment_change_invalid_result")
            raise HTTPException(500, detail={"code": "invalid_planning_state", "message": str(error)}) from error
        except ValueError as error:
            raise HTTPException(422, detail={"code": "invalid_replanning_input", "message": str(error)}) from error
        except Exception as error:
            logger.error("assessment_change_failed error_type=%s", type(error).__name__)
            raise HTTPException(500, detail={"code": "assessment_change_failed",
                                "message": "Assessment change failed; state was not changed."}) from error

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
        except ValueError as error:
            raise HTTPException(
                status_code=422,
                detail={"code": "invalid_planning_event", "message": str(error)},
            ) from error

    @app.post("/plan", response_model=SchedulingResult)
    def create_plan() -> SchedulingResult:
        """Run an injected pipeline or preserve the demo-safe fallback."""

        if selected_pipeline is not None:
            try:
                result = selected_store.generate_plan(selected_pipeline)
            except PlanningStateValidationError as error:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail={
                        "code": "invalid_planning_state",
                        "message": str(error),
                    },
                ) from error
            except ValueError as error:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "invalid_planning_input",
                        "message": str(error),
                    },
                ) from error
            except Exception as error:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail={
                        "code": "planning_failed",
                        "message": "The planning pipeline could not complete.",
                    },
                ) from error
            return result

        return SchedulingResult(
            scheduled_tasks=selected_store.list_scheduled_tasks(),
            unscheduled_tasks=[],
        )

    @app.post("/replan", response_model=SchedulingResult)
    def replan(event: PlanningEvent) -> SchedulingResult:
        """Observe and replan once; do not pre-post this event elsewhere."""

        return run_replan(event)

    @app.post("/calendar-changes", response_model=SchedulingResult)
    def change_calendar(change: CalendarChangeRequest) -> SchedulingResult:
        """Upsert one block and replan atomically, including new block IDs."""

        return run_replan(change.event, change.calendar_block)

    def run_replan(
        event: PlanningEvent,
        calendar_block: CalendarBlock | None = None,
    ) -> SchedulingResult:

        if selected_pipeline is None:
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
            return selected_store.replan(
                event, selected_pipeline, calendar_block,
            )
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
        except ValueError as error:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "invalid_replanning_input",
                    "message": str(error),
                },
            ) from error
        except Exception as error:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "code": "replanning_failed",
                    "message": "The replanning pipeline could not complete.",
                },
            ) from error

    return app


app = create_app()
