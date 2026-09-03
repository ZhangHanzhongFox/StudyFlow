"""Provider-neutral structured LLM boundary used by the agent workflow.

The fake implementation supports offline tests. The Bedrock adapter implements
the same protocol without changing the workflow service or canonical schemas.
"""

from collections.abc import Iterable, Mapping
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.schemas import AssessmentType, NonEmptyStr

StructuredOutputT = TypeVar("StructuredOutputT", bound=BaseModel)


class ClassificationOutput(BaseModel):
    """Structured result returned when classifying an assessment."""

    model_config = ConfigDict(extra="forbid")

    assessment_type: AssessmentType


class TaskDraft(BaseModel):
    """Provider output for a task before canonical IDs are assigned."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    step_key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    name: NonEmptyStr
    duration_minutes: int = Field(gt=0)
    priority: int = Field(ge=1, le=5)
    dependency_keys: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_local_dependencies(self) -> "TaskDraft":
        if self.step_key in self.dependency_keys:
            raise ValueError("a task draft cannot depend on itself")
        if len(self.dependency_keys) != len(set(self.dependency_keys)):
            raise ValueError("task draft dependencies must be unique")
        return self


class DecompositionOutput(BaseModel):
    """Structured result returned when decomposing one assessment."""

    model_config = ConfigDict(extra="forbid")

    tasks: list[TaskDraft] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_step_keys(self) -> "DecompositionOutput":
        step_keys = [task.step_key for task in self.tasks]
        if len(step_keys) != len(set(step_keys)):
            raise ValueError("task draft step keys must be unique")
        return self


class StructuredLLM(Protocol):
    """Minimal interface for any provider that returns Pydantic output."""

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[StructuredOutputT],
    ) -> StructuredOutputT:
        """Generate and validate one structured response."""

        ...


FakeResponse = BaseModel | Mapping[str, Any] | Exception


class FakeStructuredLLM:
    """Queue-backed structured LLM for local development and unit tests.

    Mapping responses are validated with the requested Pydantic model before
    they are returned. Exception entries simulate provider or network failure.
    """

    def __init__(self, responses: Iterable[FakeResponse]) -> None:
        self._responses = iter(responses)

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[StructuredOutputT],
    ) -> StructuredOutputT:
        del system_prompt, user_prompt

        try:
            response = next(self._responses)
        except StopIteration as error:
            raise RuntimeError("fake structured LLM has no response queued") from error

        if isinstance(response, Exception):
            raise response
        if isinstance(response, BaseModel):
            return response_model.model_validate(response.model_dump())
        return response_model.model_validate(response)
