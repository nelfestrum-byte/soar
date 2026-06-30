import pytest
from unittest.mock import patch, MagicMock
from orchestrator.core.subprocess_runner import SubprocessRunner
from orchestrator.models.job import WorkflowJob


@pytest.mark.asyncio
async def test_env_whitelist():
    runner = SubprocessRunner()
    job = WorkflowJob(id="test-id", workflow_name="test", context={"key": "val"})

    with patch("orchestrator.core.subprocess_runner.asyncio.create_subprocess_exec") as mock_exec:
        mock_proc = MagicMock()
        mock_exec.return_value = mock_proc

        await runner.start(job)

        call_kwargs = mock_exec.call_args
        env = call_kwargs.kwargs.get("env") or call_kwargs[1].get("env")

        assert "SOAR_JOB_ID" in env
        assert env["SOAR_JOB_ID"] == "test-id"
        assert "SOAR_CONTEXT" in env
        assert "PATH" in env

        assert "DATABASE_URL" not in env
        assert "AWS_SECRET" not in env
        assert "CUSTOM_VAR" not in env


@pytest.mark.asyncio
async def test_env_preserves_path():
    runner = SubprocessRunner()
    job = WorkflowJob(id="x", workflow_name="test", context={})

    with patch("orchestrator.core.subprocess_runner.asyncio.create_subprocess_exec") as mock_exec:
        mock_exec.return_value = MagicMock()
        await runner.start(job)

        env = mock_exec.call_args.kwargs.get("env") or mock_exec.call_args[1].get("env")
        assert "PATH" in env
        assert len(env["PATH"]) > 0
