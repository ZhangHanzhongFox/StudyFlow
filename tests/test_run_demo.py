"""Launcher checks never contact AWS or start real services."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts import run_demo


@pytest.mark.parametrize("arguments", [["--llm"], []])
def test_failed_bedrock_check_prevents_service_start(monkeypatch, arguments):
    monkeypatch.setattr("sys.argv", ["run_demo", *arguments])
    monkeypatch.setenv("STUDYFLOW_LLM_PROVIDER", "bedrock")
    monkeypatch.setattr(run_demo.shutil, "which", lambda _: "/node")
    monkeypatch.setattr(run_demo.Path, "exists", lambda _: True)
    check = Mock(return_value=SimpleNamespace(returncode=1))
    launch = Mock()
    monkeypatch.setattr(run_demo.subprocess, "run", check)
    monkeypatch.setattr(run_demo.subprocess, "Popen", launch)
    with pytest.raises(SystemExit, match="Bedrock check failed"):
        run_demo.main()
    assert check.call_args.kwargs["env"]["STUDYFLOW_LLM_PROVIDER"] == "bedrock"
    launch.assert_not_called()


def test_offline_override_does_not_call_model(monkeypatch):
    monkeypatch.setattr("sys.argv", ["run_demo", "--offline"])
    monkeypatch.setenv("STUDYFLOW_LLM_PROVIDER", "bedrock")
    monkeypatch.setattr(run_demo.shutil, "which", lambda _: "/node")
    monkeypatch.setattr(run_demo.Path, "exists", lambda _: True)
    check = Mock()
    launch = Mock(side_effect=KeyboardInterrupt)
    monkeypatch.setattr(run_demo.subprocess, "run", check)
    monkeypatch.setattr(run_demo.subprocess, "Popen", launch)
    run_demo.main()
    check.assert_not_called()
    assert launch.call_args.kwargs["env"]["STUDYFLOW_LLM_PROVIDER"] == "none"
