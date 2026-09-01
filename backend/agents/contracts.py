"""Stable interface between agent reasoning and deterministic services."""

from collections.abc import Sequence
from typing import Protocol

from backend.schemas import Assessment, AssessmentType, PlanningEvent, Task


class AgentWorkflow(Protocol):
    """Contract implemented by the Agent / Workflow workstream.

    Implementations may use an LLM for interpretation and decomposition, but
    every output must pass the canonical schema and deterministic validation.
    """

    def classify_assessment(self, assessment: Assessment) -> AssessmentType:
        """Confirm or refine the normalized assessment category."""

        ...

    def decompose_assessment(self, assessment: Assessment) -> list[Task]:
        """Produce actionable tasks for one assessment."""

        ...

    def find_affected_task_ids(
        self,
        event: PlanningEvent,
        tasks: Sequence[Task],
    ) -> set[str]:
        """Return tasks whose planning state must be reconsidered."""

        ...
