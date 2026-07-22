"""Path resolution shared by soarctl subcommands.

repo_root() is only used by `soarctl package` (build-machine command, run
from a full source checkout). Every other command operates on an instance
directory (a bundle extracted by `soarctl install`, self-contained — no
source checkout required there).
"""

import argparse
from pathlib import Path


def repo_root(start: Path) -> Path:
    current = start.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    raise RuntimeError(f"no pyproject.toml found above {start} — not inside the soar repo")


def read_version(directory: Path) -> str:
    version_file = directory / "VERSION"
    if not version_file.exists():
        raise FileNotFoundError(f"VERSION file not found in {directory}")
    return version_file.read_text().strip()


def instance_dir(args: argparse.Namespace) -> Path:
    raw = getattr(args, "dir", None) or "."
    return Path(raw).resolve()
