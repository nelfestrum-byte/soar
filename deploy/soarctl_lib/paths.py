"""Path resolution shared by soarctl subcommands.

repo_root() is used by `soarctl package` and by instance_dir()'s
auto-discovery for checkout-based (on-site) instances. Every other command
operates on an instance directory — either a bundle extracted by
`soarctl install <bundle>` (self-contained, no checkout above it) or
`<repo_root>/deploy/prod` inside a git checkout (on-site, see
docs/compose/specs/2026-07-29-soarctl-inplace-onsite-design.md).
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
    """Resolves the instance directory the way `git` resolves its repo root:
    `--dir` always wins when passed; otherwise walk up from cwd looking for
    a self-contained instance (`docker-compose.yml` directly present —
    covers bundle installs, from any subdirectory), then for a checkout root
    (`pyproject.toml`) whose `deploy/prod/` is itself an instance; falls
    back to cwd if neither marker is found.
    """
    explicit = getattr(args, "dir", None)
    if explicit:
        return Path(explicit).resolve()

    cwd = Path.cwd().resolve()

    for candidate in [cwd, *cwd.parents]:
        if (candidate / "docker-compose.yml").exists():
            return candidate

    try:
        root = repo_root(cwd)
    except RuntimeError:
        return cwd

    prod = root / "deploy" / "prod"
    if (prod / "docker-compose.yml").exists():
        return prod
    return cwd
