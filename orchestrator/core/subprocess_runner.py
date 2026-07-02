import asyncio
import json
import os
import sys
from pathlib import Path

from orchestrator.models.job import WorkflowJob

# Resolve config path once at import time — prefer actual file over env var
def _resolve_config_path() -> str:
    env_path = os.environ.get("SOAR_CONFIG", "")
    candidates = [env_path, "config.yaml", "/app/config.yaml"]
    for p in candidates:
        if p and os.path.isfile(p):
            return os.path.abspath(p)
    return env_path or "config.yaml"


_CONFIG_PATH = _resolve_config_path()


class SubprocessRunner:
    async def start(self, job: WorkflowJob) -> asyncio.subprocess.Process:
        safe_env_keys = {
            "PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "PYTHONPATH",
            "PYTHONUNBUFFERED",
        }
        env = {k: v for k, v in os.environ.items() if k in safe_env_keys}
        env.update({
            "SOAR_CONFIG": _CONFIG_PATH,
            "SOAR_JOB_ID": job.id,
            "SOAR_WORKFLOW_NAME": job.workflow_name,
            "SOAR_CONTEXT": json.dumps(job.context),
            "SOAR_LOG_PATH": job.log_path or "",
        })
        stdout_file = None
        if job.log_path:
            os.makedirs(os.path.dirname(job.log_path), exist_ok=True)
            stdout_file = open(job.log_path, "w")
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "soar.runner",
            env=env,
            stdout=stdout_file or asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        if stdout_file:
            proc._log_file = stdout_file  # type: ignore[attr-defined]
        return proc
