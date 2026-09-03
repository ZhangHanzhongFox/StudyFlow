"""Offline coverage of the Bedrock boundary and default API wiring."""

import asyncio
import json
import logging
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from backend.agents import ClassificationOutput, DecompositionOutput, StudyFlowAgent
from backend.agents.bedrock import BedrockStructuredLLM, TOOL_NAME, configured_llm
from backend.main import create_app
from backend.schemas import AssessmentType, validate_task_graph
from backend.services import MockDataStore


def tool_response(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "stopReason": "tool_use",
        "output": {"message": {"content": [{"toolUse": {
            "name": TOOL_NAME, "input": payload, "toolUseId": "test-call",
        }}]}},
        "usage": {"inputTokens": 20, "outputTokens": 30},
    }


def draft_payload() -> dict[str, Any]:
    return {"tasks": [
        {"step_key": "research", "name": "Research the topic",
         "duration_minutes": 60, "priority": 3},
        {"step_key": "outline", "name": "Draft an outline",
         "duration_minutes": 30, "priority": 4, "dependency_keys": ["research"]},
    ]}


class FakeConverse:
    def __init__(self, *responses: Any) -> None:
        self.responses = iter(responses)
        self.requests: list[dict[str, Any]] = []

    def converse(self, **kwargs: Any) -> dict[str, Any]:
        self.requests.append(kwargs)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.mark.parametrize("model,payload", [
    (ClassificationOutput, {"assessment_type": "presentation"}),
    (DecompositionOutput, draft_payload()),
])
def test_converse_schema_and_validation(model, payload, caplog) -> None:
    client = FakeConverse(tool_response(payload))
    llm = BedrockStructuredLLM(client=client)
    with caplog.at_level(logging.INFO):
        result = llm.generate(
            system_prompt="instructions", user_prompt="private assessment",
            response_model=model,
        )
    assert result == model.model_validate(payload)
    request = client.requests[0]
    config = request["toolConfig"]
    schema = config["tools"][0]["toolSpec"]["inputSchema"]["json"]
    assert set(schema) == {"type", "properties", "required"}
    assert "$ref" not in json.dumps(schema)
    assert config["toolChoice"] == {"tool": {"name": TOOL_NAME}}
    assert "private assessment" not in caplog.text
    assert "input_tokens=20 output_tokens=30" in caplog.text
    if model is ClassificationOutput:
        assert "presentation" in schema["properties"]["assessment_type"]["enum"]
    else:
        assert schema["properties"]["tasks"]["items"]["type"] == "object"


@pytest.mark.parametrize("stop_reason", [
    "max_tokens", "content_filtered", "guardrail_intervened", "end_turn", None,
])
def test_rejects_incomplete_output_even_if_payload_is_valid(stop_reason) -> None:
    response = tool_response(draft_payload())
    response["stopReason"] = stop_reason
    with pytest.raises(ValueError, match="did not finish"):
        BedrockStructuredLLM(client=FakeConverse(response)).generate(
            system_prompt="system", user_prompt="data",
            response_model=DecompositionOutput,
        )


@pytest.mark.parametrize("invalid", [
    {"tasks": []},
    {"tasks": [{"step_key": "research", "name": "Research",
                "duration_minutes": 0, "priority": 3}]},
    {**draft_payload(), "unexpected": "field"},
])
def test_rejects_invalid_pydantic_output(invalid) -> None:
    with pytest.raises(ValidationError):
        BedrockStructuredLLM(client=FakeConverse(tool_response(invalid))).generate(
            system_prompt="system", user_prompt="data",
            response_model=DecompositionOutput,
        )


@pytest.mark.parametrize("kind", ["missing", "wrong", "duplicate"])
def test_rejects_missing_wrong_or_duplicate_tool_calls(kind) -> None:
    response = tool_response(draft_payload())
    content = response["output"]["message"]["content"]
    if kind == "missing":
        content.clear()
    elif kind == "wrong":
        content[0]["toolUse"]["name"] = "some_other_tool"
    else:
        content.append(content[0])
    with pytest.raises(ValueError, match="exactly one"):
        BedrockStructuredLLM(client=FakeConverse(response)).generate(
            system_prompt="system", user_prompt="data",
            response_model=DecompositionOutput,
        )


@pytest.mark.parametrize("failure", ["credentials", "cycle", "unknown_dependency"])
def test_provider_and_dependency_failures_preserve_template_fallback(failure, caplog):
    payload = draft_payload()
    if failure == "cycle":
        payload["tasks"][0]["dependency_keys"] = ["outline"]
    elif failure == "unknown_dependency":
        payload["tasks"][0]["dependency_keys"] = ["missing"]
    response = (
        RuntimeError("secret credential details") if failure == "credentials"
        else tool_response(payload)
    )
    assessment = next(a for a in MockDataStore().list_assessments()
                      if a.type is AssessmentType.PRESENTATION)
    agent = StudyFlowAgent(BedrockStructuredLLM(client=FakeConverse(response)))
    tasks = agent.decompose_assessment(assessment)
    assert tasks == StudyFlowAgent().decompose_assessment(assessment)
    assert validate_task_graph(tasks) == tasks
    assert "using deterministic fallback" in caplog.text
    assert "secret credential details" not in caplog.text


def test_configuration_is_explicit_and_uses_no_aws_at_startup(monkeypatch):
    monkeypatch.delenv("STUDYFLOW_LLM_PROVIDER", raising=False)
    assert configured_llm() is None
    monkeypatch.setenv("STUDYFLOW_LLM_PROVIDER", "bedrock")
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0")
    monkeypatch.setenv("BEDROCK_MAX_TOKENS", "2048")
    llm = configured_llm()
    assert llm.region_name == "us-east-1"
    assert llm._client is None
    monkeypatch.setenv("STUDYFLOW_LLM_PROVIDER", "typo")
    with pytest.raises(ValueError, match="PROVIDER"):
        configured_llm()


@pytest.mark.parametrize("value", ["0", "5001", "not-a-number"])
def test_invalid_token_configuration_is_rejected(monkeypatch, value):
    monkeypatch.setenv("STUDYFLOW_LLM_PROVIDER", "bedrock")
    monkeypatch.setenv("BEDROCK_MAX_TOKENS", value)
    with pytest.raises(ValueError):
        configured_llm()


def test_default_api_uses_bedrock_results_and_schedules_dependencies(monkeypatch):
    assessments = MockDataStore.for_dynamic_provider_demo().list_assessments()
    client = FakeConverse(
        *(tool_response({"assessment_type": a.type.value}) for a in assessments),
        *(tool_response(draft_payload()) for _ in assessments),
    )
    monkeypatch.setenv("STUDYFLOW_LLM_PROVIDER", "bedrock")
    monkeypatch.setattr(BedrockStructuredLLM, "_get_client", lambda self: client)
    app = create_app()
    assert client.requests == []

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
        ) as api:
            result = await api.post("/plan")
            tasks = (await api.get("/tasks")).json()
            calendar = (await api.get("/calendar-blocks")).json()
            return result, tasks, calendar

    response, tasks, calendar = asyncio.run(run())
    assert response.status_code == 200
    result = response.json()
    assert result["unscheduled_tasks"] == []
    assert len(client.requests) == 2 * len(assessments)
    assert len(tasks) == 2 * len(assessments)
    assert {task["name"] for task in tasks} == {"Research the topic", "Draft an outline"}
    schedule = {s["task_id"]: s for s in result["scheduled_tasks"]}
    for task in tasks:
        entry = schedule[task["id"]]
        for dependency in task["dependencies"]:
            assert schedule[dependency]["end_time"] <= entry["start_time"]
        for block in calendar:
            if block["flexibility"] == "hard":
                assert (entry["end_time"] <= block["start_time"]
                        or entry["start_time"] >= block["end_time"])


def test_request_passes_real_sdk_validation_without_network() -> None:
    import boto3
    from botocore.stub import Stubber

    client = boto3.client(
        "bedrock-runtime", region_name="us-east-1",
        aws_access_key_id="offline-test", aws_secret_access_key="offline-test",
    )
    response = tool_response(draft_payload())
    response["output"]["message"]["role"] = "assistant"
    response["usage"]["totalTokens"] = 50
    response["metrics"] = {"latencyMs": 1}
    with Stubber(client) as stub:
        stub.add_response("converse", response)
        result = BedrockStructuredLLM(client=client).generate(
            system_prompt="system", user_prompt="data",
            response_model=DecompositionOutput,
        )
        assert len(result.tasks) == 2
        stub.assert_no_pending_responses()


@pytest.mark.parametrize("failure", [False, True])
def test_standalone_check_reports_failure_without_template(monkeypatch, capsys, failure):
    from backend.agents.check_bedrock import main

    monkeypatch.setenv("STUDYFLOW_LLM_PROVIDER", "bedrock")
    response = RuntimeError("private details") if failure else tool_response(draft_payload())
    client = FakeConverse(response)
    monkeypatch.setattr(BedrockStructuredLLM, "_get_client", lambda self: client)
    assert main() == (1 if failure else 0)
    output = capsys.readouterr().out
    assert "private details" not in output
    assert ("structured output OK" in output) is not failure
    assert len(client.requests) == 1
