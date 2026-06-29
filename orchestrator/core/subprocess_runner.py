import sys
import json
import asyncio
import os
from orchestrator.models.job import WorkflowJob


class SubprocessRunner:
    async def start(self, job: WorkflowJob) -> asyncio.subprocess.Process:
        env = {
            **os.environ,
            "SOAR_JOB_ID": job.id,
            "SOAR_WORKFLOW_NAME": job.workflow_name,
            "SOAR_CONTEXT": json.dumps(job.context),
            "SOAR_LOG_PATH": job.log_path or "",
        }
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
            proc._log_file = stdout_file
        return proc
