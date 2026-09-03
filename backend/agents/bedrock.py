"""Bedrock Converse adapter for validated assessment outputs."""

import logging
import os
from typing import Any, Protocol

from pydantic import BaseModel

from .llm import StructuredLLM, StructuredOutputT

logger = logging.getLogger(__name__)
TOOL_NAME = "submit_assessment_result"


class ConverseClient(Protocol):
    def converse(self, **kwargs: Any) -> dict[str, Any]: ...


def _tool_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Inline local references; Nova accepts only three root schema fields.

    This provider schema guides generation. The original Pydantic model still
    enforces every constraint locally, including extra-field rejection.
    """

    schema = model.model_json_schema()
    definitions = schema.get("$defs", {})

    def expand(value: Any, seen: frozenset[str] = frozenset()) -> Any:
        if isinstance(value, list):
            return [expand(item, seen) for item in value]
        if not isinstance(value, dict):
            return value
        if "$ref" in value:
            reference = value["$ref"]
            if not reference.startswith("#/$defs/") or reference in seen:
                raise ValueError("unsupported recursive or external tool schema")
            definition = definitions[reference.removeprefix("#/$defs/")]
            return expand(
                {**definition, **{k: v for k, v in value.items() if k != "$ref"}},
                seen | {reference},
            )
        return {
            key: expand(item, seen)
            for key, item in value.items()
            if key not in {"$defs", "title"}
        }

    expanded = expand(schema)
    if expanded.get("type") != "object":
        raise ValueError("Bedrock structured output requires an object schema")
    return {
        "type": "object",
        "properties": expanded.get("properties", {}),
        "required": expanded.get("required", []),
    }


class BedrockStructuredLLM:
    """Force one schema-only tool call; never execute model-supplied tools.

    SDK creation is lazy so importing the app does not resolve credentials or
    contact AWS. Clients and credentials stay backend-only.
    """

    def __init__(
        self,
        *,
        model_id: str = "amazon.nova-lite-v1:0",
        region_name: str = "us-east-1",
        max_tokens: int = 2048,
        client: ConverseClient | None = None,
    ) -> None:
        if not model_id.strip() or not region_name.strip():
            raise ValueError("Bedrock model and region must not be blank")
        if not 1 <= max_tokens <= 5000:
            raise ValueError("Bedrock max tokens must be between 1 and 5000")
        self.model_id = model_id
        self.region_name = region_name
        self.max_tokens = max_tokens
        self._client = client

    def _get_client(self) -> ConverseClient:
        if self._client is None:
            import boto3
            from botocore.config import Config

            self._client = boto3.client(
                "bedrock-runtime",
                region_name=self.region_name,
                config=Config(
                    connect_timeout=5,
                    read_timeout=45,
                    retries={"mode": "standard", "total_max_attempts": 2},
                ),
            )
        return self._client

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[StructuredOutputT],
    ) -> StructuredOutputT:
        response = self._get_client().converse(
            modelId=self.model_id,
            system=[{"text": system_prompt}],
            messages=[{"role": "user", "content": [{"text": user_prompt}]}],
            inferenceConfig={"maxTokens": self.max_tokens, "temperature": 0},
            toolConfig={
                "tools": [{"toolSpec": {
                    "name": TOOL_NAME,
                    "description": "Submit the complete assessment result in the required schema.",
                    "inputSchema": {"json": _tool_schema(response_model)},
                }}],
                "toolChoice": {"tool": {"name": TOOL_NAME}},
            },
        )
        # Even a parseable prefix must not enter the plan after truncation.
        if response.get("stopReason") != "tool_use":
            raise ValueError("Bedrock did not finish a structured tool response")
        content = response.get("output", {}).get("message", {}).get("content", [])
        calls = [block["toolUse"] for block in content if "toolUse" in block]
        if len(calls) != 1 or calls[0].get("name") != TOOL_NAME:
            raise ValueError("Bedrock must return exactly one assessment result")
        output = response_model.model_validate(calls[0]["input"])
        usage = response.get("usage", {})
        logger.info(
            "Bedrock structured output validated model=%s schema=%s "
            "input_tokens=%s output_tokens=%s",
            self.model_id,
            response_model.__name__,
            usage.get("inputTokens"),
            usage.get("outputTokens"),
        )
        return output


def configured_llm() -> StructuredLLM | None:
    """Enable paid requests explicitly; reject unknown provider settings."""

    provider = os.getenv("STUDYFLOW_LLM_PROVIDER", "none").strip().lower()
    if provider == "none":
        return None
    if provider != "bedrock":
        raise ValueError("STUDYFLOW_LLM_PROVIDER must be 'none' or 'bedrock'")
    return BedrockStructuredLLM(
        model_id=os.getenv("BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0"),
        region_name=(
            os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
        ),
        max_tokens=int(os.getenv("BEDROCK_MAX_TOKENS", "2048")),
    )
