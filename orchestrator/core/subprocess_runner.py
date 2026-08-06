import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import yaml

from orchestrator.core.introspect import parse_connector_usage
from orchestrator.models.job import WorkflowJob

if sys.platform != "win32":
    import resource

# Resolve config path once at import time — prefer actual file over env var
def _resolve_config_path() -> str:
    env_path = os.environ.get("SOAR_CONFIG", "")
    candidates = [env_path, "config.yaml", "/app/config.yaml"]
    for p in candidates:
        if p and os.path.isfile(p):
            return os.path.abspath(p)
    return env_path or "config.yaml"


_CONFIG_PATH = _resolve_config_path()


def resolve_content_python() -> str:
    """Interpreter for subprocess workflow execution. SOAR_CONTENT_PYTHON is
    set by the Dockerfiles to /app/content-venv/bin/python (two-runtime
    boundary, see docs/concepts/ENTITY-MODEL.md decision 3). Falls back to
    sys.executable when unset — local dev/tests run against a single venv
    without Docker, no second venv to point at."""
    return os.environ.get("SOAR_CONTENT_PYTHON") or sys.executable


_CONTENT_PYTHON = resolve_content_python()


def _load_full_config() -> dict:
    """Fresh read of the orchestrator's full config.yaml on every call — the
    real soar.runner subprocess itself re-reads this file fresh per job, so
    doing the same here keeps build_scoped_config's view of workflows_dir/
    connectors_dir current across git-driven content changes without
    needing a restart. This dict is only ever a *source* for
    build_scoped_config's slice — never written to SOAR_CONFIG directly
    (see build_scoped_config docstring, privilege-narrowing-design.md
    [S2])."""
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except OSError:
        return {}


def _symlink_or_copy(src: Path, dst: Path) -> None:
    """os.symlink when possible — avoids duplicating connector code per job
    (privilege-narrowing-design.md [S2] item 3). Falls back to a copy when
    symlinks aren't permitted (e.g. Windows without Developer Mode/admin —
    a dev-only fallback; Docker/Linux deploys always symlink)."""
    try:
        os.symlink(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def build_scoped_config(workflow_file: str | None, full_config: dict) -> tuple[str, str]:
    """Builds a temp directory + scoped YAML config containing only the
    connector instances the given workflow imports — directly, or
    transitively through `soar.actions.*` imports it uses (E6 static scan
    via parse_connector_usage, extended in
    docs/compose/specs/2026-07-31-workflow-connector-scoping-design.md [S3]
    to follow the documented "workflow -> actions -> connector" pattern) —
    never the orchestrator's full config.yaml, which carries
    auth.secret_key (JWT) and database.url.

    Returns (scoped_config_path, scoped_dir); the caller (SubprocessRunner.
    start()) stashes scoped_dir on the job so Worker._execute can
    shutil.rmtree() it once the job is done.

    Workflows for which parse_connector_usage returns nothing — file
    missing/unparseable, or the workflow only uses the old
    `connectors.<name>` registry-attribute form (still valid for content
    but not statically analyzable) — get a scoped config with an *empty*
    connectors_dir (zero connector credentials), not a fallback to the
    full set. Chosen deliberately: after Фаза 2 the direct-import form is
    the standard, and nothing in this repo's built-in workflows uses the
    old registry form (soar/workflows/ has no example of it) — a lenient
    fallback would create a silent full-credential escape hatch for any
    workflow an author simply forgot to migrate. Operators who hit this on
    legacy content see it immediately (job fails on the first connector
    call, not a silent overprivilege)."""
    scoped_dir = tempfile.mkdtemp(prefix="soar-job-")
    soar_cfg = (full_config or {}).get("soar") or {}

    usage: list[tuple[str, str]] = []
    if workflow_file:
        try:
            usage = parse_connector_usage(Path(workflow_file), actions_dir=soar_cfg.get("actions_dir"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            usage = []

    types_used: dict[str, set[str]] = {}
    for type_name, instance_name in usage:
        types_used.setdefault(type_name, set()).add(instance_name)

    scoped_connectors_dir = os.path.join(scoped_dir, "connectors")
    os.makedirs(scoped_connectors_dir, exist_ok=True)

    source_connectors_dir = soar_cfg.get("connectors_dir")
    if source_connectors_dir and types_used:
        source_root = Path(source_connectors_dir)
        for type_name, instance_names in types_used.items():
            source_type_dir = source_root / type_name
            if not source_type_dir.is_dir():
                continue
            dest_type_dir = Path(scoped_connectors_dir) / type_name
            dest_type_dir.mkdir(parents=True, exist_ok=True)

            for py_file in source_type_dir.glob("*.py"):
                _symlink_or_copy(py_file, dest_type_dir / py_file.name)

            merged_instances: dict = {}
            for yml_file in sorted(source_type_dir.glob("*.yml")):
                if yml_file.name.endswith(".example.yml"):
                    continue
                try:
                    data = yaml.safe_load(yml_file.read_text(encoding="utf-8")) or {}
                except yaml.YAMLError:
                    continue
                for inst_name, params in (data.get("instances") or {}).items():
                    if inst_name in instance_names:
                        merged_instances[inst_name] = params
            if merged_instances:
                (dest_type_dir / "instances.yml").write_text(
                    yaml.safe_dump({"instances": merged_instances}), encoding="utf-8",
                )

    scoped: dict = {
        "soar": {
            "workflows_dir": soar_cfg.get("workflows_dir", ""),
            "actions_dir": soar_cfg.get("actions_dir", ""),
            "tools_dir": soar_cfg.get("tools_dir", ""),
            "state_dir": soar_cfg.get("state_dir", ""),
            "connectors_dir": scoped_connectors_dir,
        },
    }
    http_cfg = (full_config or {}).get("http_client")
    if http_cfg:
        scoped["http_client"] = http_cfg
        if http_cfg.get("cache_backend") == "redis":
            redis_url = ((full_config or {}).get("queue") or {}).get("redis_url")
            if redis_url:
                scoped["queue"] = {"redis_url": redis_url}

    egress_cfg = (full_config or {}).get("egress")
    if egress_cfg:
        scoped["egress"] = egress_cfg

    scoped_config_path = os.path.join(scoped_dir, "config.yaml")
    with open(scoped_config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(scoped, f)

    _make_world_readable(scoped_dir)
    return scoped_config_path, scoped_dir


def _make_world_readable(scoped_dir: str) -> None:
    """tempfile.mkdtemp() creates scoped_dir mode 0700 — readable only by
    the orchestrator's own UID (`soar`). When jobs.runner_uid is set
    (privilege-narrowing-design.md [S3]), the runner subprocess drops to a
    *different* UID (soar-runner) via setpriv before it ever gets to read
    SOAR_CONFIG — without this, every job would fail closed the moment UID
    separation is turned on, unable to read its own scoped config or
    connector files. os.chown(..., runner_uid) is not an option here: the
    orchestrator itself runs unprivileged (no CAP_CHOWN in its effective
    set, same reasoning as _drop_privileges' docstring for CAP_SETUID) —
    chmod only needs ownership, which the orchestrator has since it just
    created these files, so that's the mechanism available to it. Scoped to
    an ephemeral, already-minimized per-job tempdir (deleted by
    Worker._execute's finally block) — the exposure this adds is "another
    local process on this container can read one job's narrowed connector
    slice for the ~duration of that job", not the full config.yaml this
    feature exists to keep away from the runner in the first place."""
    for root, _dirs, files in os.walk(scoped_dir):
        os.chmod(root, 0o755)
        for name in files:
            path = os.path.join(root, name)
            if not os.path.islink(path):
                os.chmod(path, 0o644)


def _drop_privileges(max_memory_bytes: int, max_cpu_seconds: int, max_procs: int):
    """Builds a preexec_fn that caps the runner subprocess's memory/CPU/
    process-count via RLIMIT_AS/RLIMIT_CPU/RLIMIT_NPROC (POSIX-only —
    callers must guard on sys.platform != "win32").

    Deviates from privilege-narrowing-design.md [S3]'s pseudocode, which
    also calls os.setgid/os.setuid here: verified in Docker (see the Phase
    4 report) that a non-root parent process (the orchestrator runs as
    `soar`, not root — deliberately, see USER soar in the Dockerfiles)
    cannot setuid/setgid to a different UID even with `docker run
    --cap-add=SETUID --cap-add=SETGID` — those only populate the
    container's capability *bounding* set; a non-root process's effective/
    permitted sets stay empty unless the specific binary being exec'd
    carries a file capability. Granting that file capability to the
    content-venv Python interpreter itself would let ANY code running under
    it (a compromised job, or a bug in the orchestrator's own request
    handling) call setuid(0) — a bigger privilege grant than this feature
    is meant to add. The UID/GID switch is instead done by wrapping the
    subprocess argv in `setpriv` (see _runner_argv), a small, separately
    file-capability-scoped binary — rlimits stay here since lowering your
    own rlimits never requires a capability and setrlimit survives exec."""

    def _preexec():
        resource.setrlimit(resource.RLIMIT_AS, (max_memory_bytes, max_memory_bytes))
        resource.setrlimit(resource.RLIMIT_CPU, (max_cpu_seconds, max_cpu_seconds))
        resource.setrlimit(resource.RLIMIT_NPROC, (max_procs, max_procs))

    return _preexec


def _runner_argv(content_python: str, jobs_config) -> list[str]:
    """Builds the argv for the runner subprocess. When jobs_config.
    runner_uid is set (POSIX only), wraps the real command in `setpriv
    --reuid=<uid> --regid=<gid> --clear-groups --` — see _drop_privileges
    docstring for why this replaces a direct os.setuid/setgid preexec_fn.
    `setpriv` (util-linux) must carry `cap_setuid,cap_setgid+ep` as a file
    capability in the image (Dockerfile: `setcap cap_setuid,cap_setgid+ep
    /usr/bin/setpriv`) — without it this exec fails closed (job errors out,
    does not silently run unprivileged)."""
    argv = [content_python, "-m", "soar.runner"]
    if sys.platform == "win32" or jobs_config is None or jobs_config.runner_uid is None:
        return argv
    gid = jobs_config.runner_gid if jobs_config.runner_gid is not None else jobs_config.runner_uid
    return [
        "setpriv",
        f"--reuid={jobs_config.runner_uid}",
        f"--regid={gid}",
        "--clear-groups",
        "--",
        *argv,
    ]


class SubprocessRunner:
    def __init__(self, config=None):
        # OrchestratorConfig | None — only jobs.runner_uid/gid/rlimits are
        # read from it; connectors_dir/workflows_dir etc. for the scoped
        # config always come from a fresh _load_full_config() read (see its
        # docstring), not from this object, to match what soar.runner
        # itself does per-job.
        self.config = config

    async def start(self, job: WorkflowJob) -> asyncio.subprocess.Process:
        safe_env_keys = {
            "PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "PYTHONPATH",
            "PYTHONUNBUFFERED",
        }
        env = {k: v for k, v in os.environ.items() if k in safe_env_keys}

        scoped_config_path, scoped_dir = build_scoped_config(job.workflow_file, _load_full_config())
        job.scoped_config_dir = scoped_dir

        env.update({
            "SOAR_CONFIG": scoped_config_path,
            "SOAR_JOB_ID": job.id,
            "SOAR_WORKFLOW_NAME": job.workflow_name,
            "SOAR_CONTEXT": json.dumps(job.context),
            "SOAR_LOG_PATH": job.log_path or "",
        })
        stdout_file = None
        if job.log_path:
            os.makedirs(os.path.dirname(job.log_path), exist_ok=True)
            stdout_file = open(job.log_path, "w")

        jobs_config = self.config.jobs if self.config is not None else None
        argv = _runner_argv(_CONTENT_PYTHON, jobs_config)

        kwargs = {}
        if (
            sys.platform != "win32"
            and jobs_config is not None
            and jobs_config.runner_uid is not None
        ):
            kwargs["preexec_fn"] = _drop_privileges(
                jobs_config.runner_max_memory_mb * 1024 * 1024,
                jobs_config.runner_max_cpu_seconds,
                jobs_config.runner_max_procs,
            )

        proc = await asyncio.create_subprocess_exec(
            *argv,
            env=env,
            stdout=stdout_file or asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            **kwargs,
        )
        if stdout_file:
            proc._log_file = stdout_file  # type: ignore[attr-defined]
        return proc
