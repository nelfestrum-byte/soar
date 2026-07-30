"""Privilege narrowing — separate runner UID + rlimits
(docs/compose/specs/2026-07-30-privilege-narrowing-design.md [S3]).

POSIX-only: `resource` isn't importable on Windows, and preexec_fn isn't
supported by asyncio's subprocess implementation there either — the whole
feature is gated on sys.platform != "win32" and is a no-op on Windows dev
machines by design (see JobsConfig.runner_uid docstring).

Real UID/rlimit enforcement is verified in Docker (see
docs/compose/reports/privilege-narrowing.md) — these are unit tests against
mocked os/resource, per the plan's testing strategy.
"""
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only: resource module")


class TestDropPrivileges:
    def test_sets_rlimit_as_cpu_nproc_with_configured_values(self):
        from orchestrator.core.subprocess_runner import _drop_privileges

        preexec = _drop_privileges(
            max_memory_bytes=512 * 1024 * 1024,
            max_cpu_seconds=300,
            max_procs=32,
        )

        with patch("orchestrator.core.subprocess_runner.resource") as mock_resource:
            preexec()

            calls = {c.args[0]: c.args[1] for c in mock_resource.setrlimit.call_args_list}
            assert calls[mock_resource.RLIMIT_AS] == (512 * 1024 * 1024, 512 * 1024 * 1024)
            assert calls[mock_resource.RLIMIT_CPU] == (300, 300)
            assert calls[mock_resource.RLIMIT_NPROC] == (32, 32)

    def test_does_not_touch_uid_gid(self):
        """_drop_privileges only sets rlimits — the UID/GID switch is done
        by wrapping argv in `setpriv` (_runner_argv), not by os.setuid/
        setgid here. See _drop_privileges docstring for why: verified in
        Docker that a non-root orchestrator process cannot setuid/setgid
        even with --cap-add=SETUID/SETGID unless the *exec'd binary* itself
        carries the file capability — granting that to the python
        interpreter broadly would be a bigger privilege grant than this
        feature should make."""
        from orchestrator.core.subprocess_runner import _drop_privileges

        preexec = _drop_privileges(max_memory_bytes=1, max_cpu_seconds=1, max_procs=1)

        with patch("orchestrator.core.subprocess_runner.resource"), \
             patch("orchestrator.core.subprocess_runner.os") as mock_os:
            preexec()
            mock_os.setuid.assert_not_called()
            mock_os.setgid.assert_not_called()


class TestRunnerArgv:
    def test_no_wrapping_when_runner_uid_none(self):
        from orchestrator.core.subprocess_runner import _runner_argv

        jobs_config = SimpleNamespace(runner_uid=None, runner_gid=None)
        argv = _runner_argv("/app/content-venv/bin/python", jobs_config)
        assert argv == ["/app/content-venv/bin/python", "-m", "soar.runner"]

    def test_no_wrapping_when_config_is_none(self):
        from orchestrator.core.subprocess_runner import _runner_argv

        argv = _runner_argv("/app/content-venv/bin/python", None)
        assert argv == ["/app/content-venv/bin/python", "-m", "soar.runner"]

    def test_wraps_with_setpriv_when_runner_uid_set(self):
        from orchestrator.core.subprocess_runner import _runner_argv

        jobs_config = SimpleNamespace(runner_uid=5002, runner_gid=5002)
        argv = _runner_argv("/app/content-venv/bin/python", jobs_config)
        assert argv == [
            "setpriv", "--reuid=5002", "--regid=5002", "--clear-groups", "--",
            "/app/content-venv/bin/python", "-m", "soar.runner",
        ]

    def test_gid_defaults_to_uid_when_gid_unset(self):
        from orchestrator.core.subprocess_runner import _runner_argv

        jobs_config = SimpleNamespace(runner_uid=5002, runner_gid=None)
        argv = _runner_argv("/app/content-venv/bin/python", jobs_config)
        assert "--regid=5002" in argv


@pytest.mark.asyncio
class TestSubprocessRunnerPreexecGating:
    async def test_no_preexec_fn_when_runner_uid_none(self):
        """runner_uid=None (default) — preexec_fn must not be passed at
        all, matching today's behavior exactly (no rlimits, no argv
        wrapping)."""
        from orchestrator.core.subprocess_runner import SubprocessRunner
        from orchestrator.models.job import WorkflowJob

        config = MagicMock()
        config.jobs.runner_uid = None
        runner = SubprocessRunner(config=config)
        job = WorkflowJob(id="j1", workflow_name="wf", context={})

        with patch("orchestrator.core.subprocess_runner.asyncio.create_subprocess_exec") as mock_exec:
            mock_exec.return_value = MagicMock()
            await runner.start(job)

            assert "preexec_fn" not in mock_exec.call_args.kwargs
            assert mock_exec.call_args.args[0] != "setpriv"

        import shutil
        if job.scoped_config_dir:
            shutil.rmtree(job.scoped_config_dir, ignore_errors=True)

    async def test_preexec_fn_passed_when_runner_uid_set_posix(self):
        from orchestrator.core.subprocess_runner import SubprocessRunner
        from orchestrator.models.job import WorkflowJob

        config = MagicMock()
        config.jobs.runner_uid = 5002
        config.jobs.runner_gid = 5002
        config.jobs.runner_max_memory_mb = 512
        config.jobs.runner_max_cpu_seconds = 300
        config.jobs.runner_max_procs = 32
        runner = SubprocessRunner(config=config)
        job = WorkflowJob(id="j2", workflow_name="wf", context={})

        with patch("orchestrator.core.subprocess_runner.asyncio.create_subprocess_exec") as mock_exec:
            mock_exec.return_value = MagicMock()
            await runner.start(job)

            assert "preexec_fn" in mock_exec.call_args.kwargs
            assert mock_exec.call_args.args[0] == "setpriv"

        import shutil
        if job.scoped_config_dir:
            shutil.rmtree(job.scoped_config_dir, ignore_errors=True)
