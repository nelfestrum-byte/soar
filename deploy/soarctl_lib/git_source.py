"""On-site install/update source: builds images from a live git checkout
instead of loading a transferred bundle — see
docs/compose/specs/2026-07-27-soarctl-onsite-update-design.md. Only valid
when the target machine has internet access itself (the whole point of the
air-gapped bundle path in bundle.py is to avoid needing that); a
`source.json` file in the instance directory is the marker that
distinguishes a git-sourced instance from a bundle-sourced one — `update()`
refuses to run without it.
"""

import json
import shutil
from pathlib import Path

from . import migrate as migrate_module
from .bundle import build_images
from .compose import up as compose_up
from .env import update_version
from .runner import run

_SOURCE_FILE = "source.json"


def resolve_version(checkout: Path) -> str:
    result = run(["git", "-C", str(checkout), "describe", "--tags", "--always", "--dirty"])
    return result.stdout.strip()


def _read_source(instance: Path) -> dict:
    source_path = instance / _SOURCE_FILE
    if not source_path.exists():
        raise FileNotFoundError(
            f"{source_path} not found — this instance wasn't installed via "
            "`soarctl install --repo`; bundle-based instances upgrade via "
            "`soarctl install <new-bundle>` instead, see deploy/prod/README.md"
        )
    return json.loads(source_path.read_text())


def _populate_instance_files(checkout: Path, dest_dir: Path, version: str, repo_arg: str) -> None:
    prod_dir = checkout / "deploy" / "prod"
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(prod_dir / "docker-compose.yml", dest_dir / "docker-compose.yml")
    shutil.copy(prod_dir / "config.yaml.template", dest_dir / "config.yaml.template")
    (dest_dir / "VERSION").write_text(version + "\n")
    (dest_dir / _SOURCE_FILE).write_text(json.dumps({"repo": repo_arg, "checkout": str(checkout)}))


def install(repo: str, ref: str | None, dest_dir: Path) -> Path:
    local_path = Path(repo)
    if local_path.exists():
        checkout = local_path.resolve()
    else:
        checkout = (dest_dir / "src").resolve()
        run(["git", "clone", repo, str(checkout)])

    if ref:
        run(["git", "-C", str(checkout), "checkout", ref])

    version = resolve_version(checkout)
    build_images(checkout, version)
    _populate_instance_files(checkout, dest_dir, version, repo)

    return dest_dir


def update(instance: Path, ref: str | None, migrate: str | None) -> None:
    source = _read_source(instance)
    checkout = Path(source["checkout"])

    run(["git", "-C", str(checkout), "fetch", "--tags"])
    if ref:
        run(["git", "-C", str(checkout), "checkout", ref])
    else:
        run(["git", "-C", str(checkout), "pull", "--ff-only"])

    version = resolve_version(checkout)
    build_images(checkout, version)
    update_version(instance, version)
    compose_up(instance)

    if migrate == "fresh":
        migrate_module.stamp_head(instance)
    elif migrate == "upgrade":
        migrate_module.upgrade_head(instance)
