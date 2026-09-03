"""Keep the default test runtime offline even in a Bedrock-enabled shell."""

import pytest


@pytest.fixture(autouse=True)
def offline_llm_by_default(monkeypatch):
    monkeypatch.setenv("STUDYFLOW_LLM_PROVIDER", "none")
