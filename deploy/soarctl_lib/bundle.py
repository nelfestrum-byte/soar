"""Build-machine packaging + target-machine install — see spec [S2]
"Принцип: сборка и установка — разные машины". No registry: package()
produces one self-contained tar (compose file, config template, soarctl
itself, and all four runtime images via `docker save`); install() only
ever runs `docker load` + file extraction, no network calls.
"""

import shutil
import tarfile
import tempfile
from pathlib import Path

from .env import update_version
from .paths import read_version
from .runner import run

BASE_IMAGES = ("redis:7-alpine", "postgres:16-alpine")


def package(repo_root: Path, version: str, output: Path) -> Path:
    prod_dir = repo_root / "deploy" / "prod"
    orchestrator_tag = f"soar-orchestrator:{version}"
    ui_tag = f"soar-ui:{version}"

    run(["docker", "build", "-f", str(prod_dir / "Dockerfile.orchestrator"), "-t", orchestrator_tag, str(repo_root)])
    run(["docker", "build", "-f", str(prod_dir / "Dockerfile.ui"), "-t", ui_tag, str(repo_root)])
    for image in BASE_IMAGES:
        run(["docker", "pull", image])

    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp)
        shutil.copy(prod_dir / "docker-compose.yml", staging / "docker-compose.yml")
        shutil.copy(prod_dir / "config.yaml.template", staging / "config.yaml.template")
        shutil.copy(repo_root / "deploy" / "soarctl", staging / "soarctl")
        shutil.copytree(
            repo_root / "deploy" / "soarctl_lib",
            staging / "soarctl_lib",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        (staging / "VERSION").write_text(version + "\n")

        images_tar = staging / "images.tar"
        run(["docker", "save", orchestrator_tag, ui_tag, *BASE_IMAGES, "-o", str(images_tar)])

        with tarfile.open(output, "w:gz") as tar:
            for item in sorted(staging.iterdir()):
                tar.add(item, arcname=item.name)

    return output


def install(bundle_path: Path, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(bundle_path, "r:gz") as tar:
        tar.extractall(dest_dir, filter="data")

    images_tar = dest_dir / "images.tar"
    run(["docker", "load", "-i", str(images_tar)])
    images_tar.unlink()

    # Upgrade case: an existing .env means this instance was already
    # `init`-ed — bump SOAR_VERSION only, never regenerate secrets (that
    # would lock the instance out of its own Postgres database). First
    # install has no .env yet; `soarctl init` picks up VERSION on its own.
    if (dest_dir / ".env").exists():
        update_version(dest_dir, read_version(dest_dir))

    return dest_dir
