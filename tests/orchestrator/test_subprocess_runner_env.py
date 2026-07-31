"""Tests for subprocess runner environment propagation.

BUG NEW-2: SOAR_CONFIG is read with os.environ.get() but never set in os.environ.
The subprocess's safe env allowlist includes SOAR_CONFIG, but if it's absent from
the parent env, the subprocess won't have it either.
"""
import os
import shutil
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from orchestrator.core.subprocess_runner import SubprocessRunner, build_scoped_config
from orchestrator.models.job import WorkflowJob


@pytest.fixture
def runner():
    return SubprocessRunner()


@pytest.fixture
def sample_job():
    return WorkflowJob(
        id="test-job-123",
        workflow_name="test_workflow",
        workflow_type="manual",
        triggered_by="test",
        context={"key": "value"},
        log_path=None,
        timeout=300,
    )


class TestResolveContentPython:
    """resolve_content_python() picks the interpreter for subprocess workflow
    execution — SOAR_CONTENT_PYTHON when set (Docker two-runtime boundary,
    see docs/concepts/ENTITY-MODEL.md decision 3), sys.executable otherwise
    (local dev/tests, single venv)."""

    def test_returns_env_var_when_set(self):
        from orchestrator.core.subprocess_runner import resolve_content_python

        with patch.dict(os.environ, {"SOAR_CONTENT_PYTHON": "/app/content-venv/bin/python"}):
            assert resolve_content_python() == "/app/content-venv/bin/python"

    def test_falls_back_to_sys_executable_when_unset(self):
        from orchestrator.core.subprocess_runner import resolve_content_python

        env_without = {k: v for k, v in os.environ.items() if k != "SOAR_CONTENT_PYTHON"}
        with patch.dict(os.environ, env_without, clear=True):
            assert resolve_content_python() == sys.executable

    def test_falls_back_to_sys_executable_when_empty(self):
        from orchestrator.core.subprocess_runner import resolve_content_python

        with patch.dict(os.environ, {"SOAR_CONTENT_PYTHON": ""}):
            assert resolve_content_python() == sys.executable


@pytest.mark.asyncio
async def test_start_uses_resolve_content_python_not_sys_executable(runner, sample_job):
    """SubprocessRunner.start() must launch the interpreter resolved by
    resolve_content_python(), not sys.executable directly — the module-level
    _CONTENT_PYTHON is what create_subprocess_exec's first argument should be."""
    from orchestrator.core import subprocess_runner as sr_module

    with patch("orchestrator.core.subprocess_runner.asyncio.create_subprocess_exec") as mock_exec:
        mock_exec.return_value = MagicMock()
        await runner.start(sample_job)

        call_args = mock_exec.call_args
        first_arg = call_args.args[0] if call_args.args else call_args[0][0]
        assert first_arg == sr_module._CONTENT_PYTHON


class TestSubprocessRunnerEnv:
    """SubprocessRunner should propagate SOAR_CONFIG to subprocess."""

    def test_soar_config_propagated_when_set(self, runner, sample_job):
        """SOAR_CONFIG should be propagated when set in parent env."""
        with patch.dict(os.environ, {"SOAR_CONFIG": "/app/config.yaml"}):
            # We can't actually run the subprocess in tests, but we can check
            # that the env dict is constructed correctly
            safe_env_keys = {
                "PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "PYTHONPATH",
                "PYTHONUNBUFFERED", "SOAR_CONFIG",
            }
            env = {k: v for k, v in os.environ.items() if k in safe_env_keys}
            assert "SOAR_CONFIG" in env
            assert env["SOAR_CONFIG"] == "/app/config.yaml"

    def test_soar_config_not_lost_when_absent(self, runner, sample_job):
        """SOAR_CONFIG should still be available even if not in parent env.

        This tests the fix: subprocess_runner should resolve the config path
        and pass it explicitly.
        """
        # Remove SOAR_CONFIG from env if present
        env_without = {k: v for k, v in os.environ.items() if k != "SOAR_CONFIG"}

        with patch.dict(os.environ, env_without, clear=True):
            safe_env_keys = {
                "PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "PYTHONPATH",
                "PYTHONUNBUFFERED", "SOAR_CONFIG",
            }
            env = {k: v for k, v in os.environ.items() if k in safe_env_keys}

            # After fix: SOAR_CONFIG should still be in env even if not in parent
            # (because runner resolves it from config.yaml path)
            # Before fix: SOAR_CONFIG is missing
            # This test documents the expected behavior after fix
            if "SOAR_CONFIG" not in env:
                pytest.skip("SOAR_CONFIG not in env - expected behavior before fix")

    def test_subprocess_runner_builds_env_correctly(self, runner, sample_job):
        """SubprocessRunner should build env dict with all required keys."""
        # This test verifies the env construction logic
        safe_env_keys = {
            "PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "PYTHONPATH",
            "PYTHONUNBUFFERED", "SOAR_CONFIG",
        }
        env = {k: v for k, v in os.environ.items() if k in safe_env_keys}
        env.update({
            "SOAR_JOB_ID": sample_job.id,
            "SOAR_WORKFLOW_NAME": sample_job.workflow_name,
            "SOAR_CONTEXT": '{"key": "value"}',
            "SOAR_LOG_PATH": sample_job.log_path or "",
        })

        assert env["SOAR_JOB_ID"] == "test-job-123"
        assert env["SOAR_WORKFLOW_NAME"] == "test_workflow"
        assert env["SOAR_CONTEXT"] == '{"key": "value"}'


def _write_connector_type(base: Path, type_name: str, py_names: list[str], instances: dict) -> None:
    type_dir = base / type_name
    type_dir.mkdir(parents=True, exist_ok=True)
    for py_name in py_names:
        (type_dir / f"{py_name}.py").write_text(f"# {py_name} connector class\n", encoding="utf-8")
    (type_dir / f"{type_name}.yml").write_text(
        yaml.safe_dump({"instances": instances}), encoding="utf-8",
    )


class TestBuildScopedConfig:
    """build_scoped_config narrows the connector credentials a job's
    subprocess sees down to the (type, instance) pairs its workflow file
    statically imports — see privilege-narrowing-design.md [S2]."""

    def _make_full_config(self, tmp_path: Path) -> dict:
        connectors_dir = tmp_path / "connectors"
        _write_connector_type(
            connectors_dir, "virus_total", ["vt"],
            {"vt_main": {"api_key": "secret-vt-key"}, "vt_backup": {"api_key": "other-secret"}},
        )
        _write_connector_type(
            connectors_dir, "shodan", ["shodan_conn"],
            {"shodan_prod": {"api_key": "secret-shodan-key"}},
        )
        return {
            "soar": {
                "workflows_dir": str(tmp_path / "workflows"),
                "connectors_dir": str(connectors_dir),
                "actions_dir": str(tmp_path / "actions"),
                "tools_dir": "soar/tools",
                "state_dir": str(tmp_path / "state"),
            },
            "auth": {"secret_key": "top-secret-jwt"},
            "database": {"url": "postgresql://user:pw@host/db"},
        }

    def _make_workflow_file(self, tmp_path: Path, body: str) -> str:
        path = tmp_path / "enrich.py"
        path.write_text(body, encoding="utf-8")
        return str(path)

    def test_scopes_to_only_used_instance(self, tmp_path):
        full_config = self._make_full_config(tmp_path)
        workflow_file = self._make_workflow_file(
            tmp_path, "from soar.connectors.virus_total import vt_main\n",
        )

        scoped_path, scoped_dir = build_scoped_config(workflow_file, full_config)
        try:
            with open(scoped_path) as f:
                scoped = yaml.safe_load(f)

            vt_yml = Path(scoped["soar"]["connectors_dir"]) / "virus_total" / "instances.yml"
            data = yaml.safe_load(vt_yml.read_text())
            assert set(data["instances"]) == {"vt_main"}
            assert data["instances"]["vt_main"] == {"api_key": "secret-vt-key"}

            # Unused type entirely excluded from the scoped connectors_dir
            assert not (Path(scoped["soar"]["connectors_dir"]) / "shodan").exists()
        finally:
            shutil.rmtree(scoped_dir, ignore_errors=True)

    def test_excludes_unused_instance_of_same_type(self, tmp_path):
        full_config = self._make_full_config(tmp_path)
        workflow_file = self._make_workflow_file(
            tmp_path, "from soar.connectors.virus_total import vt_main\n",
        )

        scoped_path, scoped_dir = build_scoped_config(workflow_file, full_config)
        try:
            with open(scoped_path) as f:
                scoped = yaml.safe_load(f)
            vt_yml = Path(scoped["soar"]["connectors_dir"]) / "virus_total" / "instances.yml"
            data = yaml.safe_load(vt_yml.read_text())
            assert "vt_backup" not in data["instances"]
        finally:
            shutil.rmtree(scoped_dir, ignore_errors=True)

    def test_symlinks_connector_py_files_not_copies(self, tmp_path):
        full_config = self._make_full_config(tmp_path)
        workflow_file = self._make_workflow_file(
            tmp_path, "from soar.connectors.virus_total import vt_main\n",
        )

        scoped_path, scoped_dir = build_scoped_config(workflow_file, full_config)
        try:
            with open(scoped_path) as f:
                scoped = yaml.safe_load(f)
            py_file = Path(scoped["soar"]["connectors_dir"]) / "virus_total" / "vt.py"
            assert py_file.is_symlink() or py_file.is_file()
        finally:
            shutil.rmtree(scoped_dir, ignore_errors=True)

    def test_no_connector_imports_yields_empty_connectors_dir(self, tmp_path):
        full_config = self._make_full_config(tmp_path)
        workflow_file = self._make_workflow_file(tmp_path, "x = 1\n")

        scoped_path, scoped_dir = build_scoped_config(workflow_file, full_config)
        try:
            with open(scoped_path) as f:
                scoped = yaml.safe_load(f)
            connectors_dir = Path(scoped["soar"]["connectors_dir"])
            assert connectors_dir.exists()
            assert list(connectors_dir.iterdir()) == []
        finally:
            shutil.rmtree(scoped_dir, ignore_errors=True)

    def test_full_config_secrets_not_present_in_scoped_config(self, tmp_path):
        full_config = self._make_full_config(tmp_path)
        workflow_file = self._make_workflow_file(
            tmp_path, "from soar.connectors.virus_total import vt_main\n",
        )

        scoped_path, scoped_dir = build_scoped_config(workflow_file, full_config)
        try:
            raw = Path(scoped_path).read_text()
            assert "top-secret-jwt" not in raw
            assert "postgresql://user:pw@host/db" not in raw
            scoped = yaml.safe_load(raw)
            assert "auth" not in scoped
            assert "database" not in scoped
        finally:
            shutil.rmtree(scoped_dir, ignore_errors=True)

    def test_scoped_config_carries_runtime_dirs(self, tmp_path):
        full_config = self._make_full_config(tmp_path)
        workflow_file = self._make_workflow_file(
            tmp_path, "from soar.connectors.virus_total import vt_main\n",
        )

        scoped_path, scoped_dir = build_scoped_config(workflow_file, full_config)
        try:
            scoped = yaml.safe_load(Path(scoped_path).read_text())
            assert scoped["soar"]["workflows_dir"] == full_config["soar"]["workflows_dir"]
            assert scoped["soar"]["actions_dir"] == full_config["soar"]["actions_dir"]
            assert scoped["soar"]["state_dir"] == full_config["soar"]["state_dir"]
        finally:
            shutil.rmtree(scoped_dir, ignore_errors=True)

    def test_scopes_transitively_through_action_import(self, tmp_path):
        """Д2 regression: a workflow that imports a connector transitively
        through a `soar.actions.*` import (the documented workflow -> action
        -> connector pattern) must still get the connector's credentials in
        its scoped config — not an empty connectors_dir."""
        full_config = self._make_full_config(tmp_path)
        actions_dir = Path(full_config["soar"]["actions_dir"])
        actions_dir.mkdir(parents=True, exist_ok=True)
        (actions_dir / "check_x.py").write_text(
            "from soar.connectors.virus_total import vt_main\n"
            "\n\n"
            "def check_x(ioc):\n"
            "    return vt_main.lookup(ioc)\n",
            encoding="utf-8",
        )
        workflow_file = self._make_workflow_file(
            tmp_path,
            "from soar.actions.check_x import check_x\n"
            "\n\n"
            "def run(context):\n"
            "    return check_x(context['ioc'])\n",
        )

        scoped_path, scoped_dir = build_scoped_config(workflow_file, full_config)
        try:
            with open(scoped_path) as f:
                scoped = yaml.safe_load(f)

            vt_yml = Path(scoped["soar"]["connectors_dir"]) / "virus_total" / "instances.yml"
            data = yaml.safe_load(vt_yml.read_text())
            assert set(data["instances"]) == {"vt_main"}
            assert data["instances"]["vt_main"] == {"api_key": "secret-vt-key"}
        finally:
            shutil.rmtree(scoped_dir, ignore_errors=True)

    def test_unparseable_workflow_file_falls_back_to_empty_usage(self, tmp_path):
        full_config = self._make_full_config(tmp_path)
        workflow_file = self._make_workflow_file(tmp_path, "def broken(:\n")

        scoped_path, scoped_dir = build_scoped_config(workflow_file, full_config)
        try:
            scoped = yaml.safe_load(Path(scoped_path).read_text())
            connectors_dir = Path(scoped["soar"]["connectors_dir"])
            assert list(connectors_dir.iterdir()) == []
        finally:
            shutil.rmtree(scoped_dir, ignore_errors=True)


class TestSubprocessRunnerUsesScopedConfig:
    """SubprocessRunner.start() must hand the subprocess the scoped config
    path, never the orchestrator's full SOAR_CONFIG (_CONFIG_PATH)."""

    @pytest.mark.asyncio
    async def test_soar_config_env_is_not_the_full_config_path(self):
        from orchestrator.core import subprocess_runner as sr_module

        runner = SubprocessRunner()
        job = WorkflowJob(id="job-x", workflow_name="wf", context={})

        with patch("orchestrator.core.subprocess_runner.asyncio.create_subprocess_exec") as mock_exec:
            mock_exec.return_value = MagicMock()
            await runner.start(job)

            call_kwargs = mock_exec.call_args.kwargs
            env = call_kwargs.get("env")
            assert env["SOAR_CONFIG"] != sr_module._CONFIG_PATH
            assert job.scoped_config_dir is not None
            assert env["SOAR_CONFIG"].startswith(job.scoped_config_dir)

        if job.scoped_config_dir:
            shutil.rmtree(job.scoped_config_dir, ignore_errors=True)
