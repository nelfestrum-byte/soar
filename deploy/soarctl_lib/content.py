"""Base connector content-pack install/list/remove (Phase 3,
docs/compose/specs/2026-07-30-content-as-contentpack-design.md [S6]).

Docker volume access follows the alpine tar-pipe pattern from backup.py —
one throwaway container piping tar over stdout/stdin, no bind-mounted temp
directory (same brittle host-path-translation problem backup.py's
docstring explains). soarctl has no direct filesystem access to the
soar-data volume, so "what's currently installed" has to be read back out
of the volume (a targeted tar dump of connectors/) before a plan can be
computed, and the install itself is a merge-write tar (never `rm -rf`
first — that would delete connectors this pack doesn't even mention).

plan_install()/sha256-modified-detection here is intentionally its own
implementation, not an import of orchestrator/core/pack_install.py: deploy/
has never imported orchestrator/ (checked before writing this — no
precedent in the codebase), and the two sides read the same shape of data
(manifest + marker) through different transports for a structural reason
(soarctl: docker volume, no direct disk access; orchestrator: direct disk
access to connectors_dir) — introducing the first cross-layer import here
would blur that boundary for the sake of ~40 lines. Keep the two in sync by
hand if the planning algorithm changes (see
docs/compose/reports/content-as-contentpack.md, Judgment calls).
"""

import hashlib
import io
import re
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import yaml

from .runner import run

_VOLUME_NAME = "soar-data"
_MARKER_NAME = ".soar-content.yaml"
_SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


class ContentError(RuntimeError):
    pass


def _validate_name(name: str) -> None:
    if not name or not _SAFE_NAME_RE.match(name):
        raise ContentError(f"invalid connector name: {name!r}")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _dump_connectors_tar() -> bytes:
    argv = [
        "docker", "run", "--rm",
        "-v", f"{_VOLUME_NAME}:/data",
        "alpine", "sh", "-c", "mkdir -p /data/connectors && tar czf - -C /data connectors",
    ]
    return run(argv, text=False).stdout


def _write_connectors_tar(tar_bytes: bytes) -> None:
    """Merge-write: extracting into an existing directory adds/overwrites
    matching paths, never deletes what's already there — unlike
    backup.restore_data_volume, which wipes /data first (a restore) rather
    than merges (an install)."""
    argv = [
        "docker", "run", "--rm", "-i",
        "-v", f"{_VOLUME_NAME}:/data",
        "alpine", "sh", "-c", "mkdir -p /data/connectors && tar xzf - -C /data",
    ]
    run(argv, input_text=tar_bytes, text=False)


def _remove_connector_dir(name: str) -> None:
    argv = [
        "docker", "run", "--rm",
        "-v", f"{_VOLUME_NAME}:/data",
        "alpine", "rm", "-rf", f"/data/connectors/{name}",
    ]
    run(argv)


def _read_current_state() -> tuple[dict, dict[str, bytes]]:
    """Returns (marker, files) — files maps tar member paths
    ('connectors/<name>/<name>.py') to bytes for everything currently in
    the volume's connectors/ directory."""
    tar_bytes = _dump_connectors_tar()
    marker: dict = {"entries": {}}
    files: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(tar_bytes)) as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            extracted = tar.extractfile(member)
            data = extracted.read() if extracted else b""
            if member.name == f"connectors/{_MARKER_NAME}":
                loaded = yaml.safe_load(data) or {}
                if isinstance(loaded, dict):
                    loaded.setdefault("entries", {})
                    marker = loaded
            else:
                files[member.name] = data
    return marker, files


def _current_sha256(files: dict[str, bytes], name: str) -> str | None:
    data = files.get(f"connectors/{name}/{name}.py")
    return _sha256(data) if data is not None else None


def _read_manifest(pack_dir: Path) -> dict:
    manifest_path = pack_dir / "manifest.yaml"
    if not manifest_path.is_file():
        raise ContentError(f"{pack_dir}: no manifest.yaml found — not a content pack")
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ContentError(f"{manifest_path}: manifest.yaml is not a mapping")
    return manifest


def _resolve_pack_dir(pack_path: str, ref: str | None) -> Path:
    if pack_path.startswith(("http://", "https://", "git@", "ssh://")) or pack_path.endswith(".git"):
        tmpdir = Path(tempfile.mkdtemp(prefix="soar-content-pack-"))
        argv = ["git", "clone", "--depth", "1"]
        if ref:
            argv += ["--branch", ref]
        argv += [pack_path, str(tmpdir)]
        run(argv)
        return tmpdir
    return Path(pack_path).resolve()


def plan_install(manifest: dict, marker: dict, files: dict[str, bytes]) -> dict:
    """Same three-way (+unchanged) categorization as
    orchestrator/core/pack_install.py::plan_install — see that module's
    docstring for the semantics of each category. `files` here plays the
    role connectors_dir plays there (a way to read the current on-disk
    sha256 of a connector), just sourced from a tar dump instead of a real
    filesystem."""
    entries = marker.get("entries", {})
    plan: dict[str, list[dict]] = {"new": [], "update": [], "unchanged": [], "skip_modified": []}
    for conn in manifest.get("connectors", []):
        name = conn["name"]
        entry = entries.get(name)
        if entry is None:
            plan["new"].append(conn)
            continue
        disk_sha = _current_sha256(files, name)
        if disk_sha is not None and disk_sha != entry.get("sha256"):
            plan["skip_modified"].append(conn)
            continue
        if entry.get("version") == manifest.get("version"):
            plan["unchanged"].append(conn)
        else:
            plan["update"].append(conn)
    return plan


def install(pack_path: str, ref: str | None = None) -> dict:
    pack_dir = _resolve_pack_dir(pack_path, ref)
    manifest = _read_manifest(pack_dir)
    marker, files = _read_current_state()
    plan = plan_install(manifest, marker, files)

    if plan["new"] or plan["update"]:
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
            for category in ("new", "update"):
                for conn in plan[category]:
                    name = conn["name"]
                    src_dir = pack_dir / "connectors" / name
                    for f in sorted(src_dir.rglob("*")):
                        if f.is_file():
                            arcname = f"connectors/{name}/{f.relative_to(src_dir).as_posix()}"
                            tar.add(f, arcname=arcname)
                    py_path = src_dir / f"{name}.py"
                    marker.setdefault("entries", {})[name] = {
                        "version": manifest.get("version"),
                        "sha256": _sha256(py_path.read_bytes()),
                    }
            marker["pack"] = manifest.get("name")
            marker["pack_version"] = manifest.get("version")
            marker["installed_at"] = datetime.now(UTC).isoformat()
            marker_bytes = yaml.safe_dump(marker, sort_keys=False).encode()
            info = tarfile.TarInfo(f"connectors/{_MARKER_NAME}")
            info.size = len(marker_bytes)
            tar.addfile(info, io.BytesIO(marker_bytes))

        _write_connectors_tar(buffer.getvalue())

    return {
        "new": [c["name"] for c in plan["new"]],
        "update": [c["name"] for c in plan["update"]],
        "unchanged": [c["name"] for c in plan["unchanged"]],
        "skip_modified": [c["name"] for c in plan["skip_modified"]],
    }


def list_installed() -> list[dict]:
    marker, files = _read_current_state()
    entries = marker.get("entries", {})
    rows = []
    for name, entry in sorted(entries.items()):
        disk_sha = _current_sha256(files, name)
        modified = disk_sha is not None and disk_sha != entry.get("sha256")
        rows.append({"name": name, "pack_version": entry.get("version"), "modified": modified})
    return rows


def remove(name: str, force: bool = False) -> None:
    _validate_name(name)
    marker, files = _read_current_state()
    entries = marker.get("entries", {})
    if name not in entries:
        raise ContentError(f"{name}: not installed ({_MARKER_NAME} has no entry for it)")

    disk_sha = _current_sha256(files, name)
    modified = disk_sha is not None and disk_sha != entries[name].get("sha256")
    if modified and not force:
        raise ContentError(f"{name}: modified since install — pass --force to remove anyway")

    del entries[name]
    marker["entries"] = entries

    _remove_connector_dir(name)

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        marker_bytes = yaml.safe_dump(marker, sort_keys=False).encode()
        info = tarfile.TarInfo(f"connectors/{_MARKER_NAME}")
        info.size = len(marker_bytes)
        tar.addfile(info, io.BytesIO(marker_bytes))
    _write_connectors_tar(buffer.getvalue())
