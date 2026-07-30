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


def build_images(repo_root: Path, version: str) -> tuple[str, str]:
    """Builds orchestrator/ui images tagged with `version` and pulls the base
    images — shared by `package()` (which also `docker save`s the result)
    and `git_source.install()`/`update()` (which use the images locally,
    no save/load involved at all).

    Dockerfile.orchestrator COPYs the base connector content-pack from an
    extra named build context ("basepack", Phase 3 of the entity-model
    plan — see docs/compose/specs/2026-07-30-content-as-contentpack-design.md).
    That pack lives in its own repo, a sibling of `repo_root`
    (`<repo_root>/../soar-content-pack` locally) — not fetched, just
    expected to already be checked out there. UNVERIFIED against a real
    `docker build`: see docs/compose/reports/content-as-contentpack.md.
    """
    prod_dir = repo_root / "deploy" / "prod"
    orchestrator_tag = f"soar-orchestrator:{version}"
    ui_tag = f"soar-ui:{version}"
    base_pack_dir = repo_root.parent / "soar-content-pack"

    run([
        "docker", "build",
        "-f", str(prod_dir / "Dockerfile.orchestrator"),
        "--build-context", f"basepack={base_pack_dir}",
        "-t", orchestrator_tag, str(repo_root),
    ])
    run(["docker", "build", "-f", str(prod_dir / "Dockerfile.ui"), "-t", ui_tag, str(repo_root)])
    for image in BASE_IMAGES:
        run(["docker", "pull", image])

    return orchestrator_tag, ui_tag


def package(repo_root: Path, version: str, output: Path) -> Path:
    prod_dir = repo_root / "deploy" / "prod"
    orchestrator_tag, ui_tag = build_images(repo_root, version)

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
