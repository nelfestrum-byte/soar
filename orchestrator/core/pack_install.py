"""Install planning for connector content-packs (Phase 3,
docs/concepts/ENTITY-MODEL.md / docs/compose/specs/2026-07-30-content-as-
contentpack-design.md). Two entry points share this module:

- orchestrator/api/packs.py (POST /connectors/pack/install — zip upload)
- orchestrator/main.py::seed_connector_pack (base pack baked into the
  image at SOAR_BASE_PACK_PATH, a plain directory, no zip)

Both read the same soar/runtime_contract.py::CONTRACT to reject an install
whose declared imports aren't guaranteed by the content-venv — before
anything is written to disk (see [S5] in the spec above).

deploy/soarctl_lib/content.py intentionally does NOT import this module —
deploy/ has never imported orchestrator/ (grepped before writing this: no
precedent). soarctl talks to a docker volume it has no direct filesystem
access to (alpine tar-pipe, like backup.py); orchestrator has direct disk
access to connectors_dir. The planning algorithm
(plan_install/sha256-modified-detection) is duplicated there in pure form
rather than shared across that boundary — small and stable, see the
Judgment calls section of docs/compose/reports/content-as-contentpack.md.
"""

import hashlib
import io
import os
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import yaml

MARKER_FILENAME = ".soar-content.yaml"


def compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_manifest(pack_bytes: bytes) -> dict:
    """manifest.yaml out of an uploaded pack zip (POST /connectors/pack/install
    — same "read the upload into memory, open as ZipFile" shape as
    /transfer/import)."""
    buffer = io.BytesIO(pack_bytes)
    try:
        zf = zipfile.ZipFile(buffer, "r")
    except zipfile.BadZipFile as exc:
        raise ValueError("Invalid pack: not a valid ZIP archive") from exc
    with zf:
        if "manifest.yaml" not in zf.namelist():
            raise ValueError("Invalid pack: missing manifest.yaml")
        manifest = yaml.safe_load(zf.read("manifest.yaml"))
    if not isinstance(manifest, dict):
        raise ValueError("Invalid pack: manifest.yaml is not a mapping")
    return manifest


def read_manifest_from_dir(pack_dir: str) -> dict:
    """manifest.yaml straight off disk — used for the base pack baked into
    the image (SOAR_BASE_PACK_PATH), never fetched over the network."""
    manifest_path = Path(pack_dir) / "manifest.yaml"
    if not manifest_path.is_file():
        raise ValueError(f"Invalid pack: {manifest_path} not found")
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError(f"Invalid pack: {manifest_path} is not a mapping")
    return manifest


def check_runtime_compat(manifest: dict, runtime_version: str) -> None:
    """Major version of manifest['runtime_version'] must match the
    installed platform's soar/runtime_contract.py::RUNTIME_VERSION — a pack
    built against an incompatible content-venv contract must be refused,
    not partially installed."""
    pack_rv = str(manifest.get("runtime_version", ""))
    installed_major = str(runtime_version).split(".")[0]
    pack_major = pack_rv.split(".")[0] if pack_rv else ""
    if not pack_major or pack_major != installed_major:
        raise ValueError(
            f"pack runtime_version {pack_rv!r} is incompatible with the "
            f"installed platform runtime_version {runtime_version!r} "
            "(major version must match)"
        )


def check_dependencies(manifest: dict, contract: dict) -> list[str]:
    """Every import a connector in the manifest declares must already be
    guaranteed by the content-venv contract — returns the sorted list of
    import names that are not (empty list = pack is installable). Not an
    exception: the caller decides what a non-empty list means (400 for the
    API route, skip-with-log for startup seeding)."""
    guaranteed: set[str] = set()
    for entry in contract.values():
        guaranteed.update(entry.get("import_names", []))
    missing: set[str] = set()
    for conn in manifest.get("connectors", []):
        for imp in conn.get("imports", []):
            if imp not in guaranteed:
                missing.add(imp)
    return sorted(missing)


def read_marker(connectors_dir: str) -> dict:
    path = Path(connectors_dir) / MARKER_FILENAME
    if not path.is_file():
        return {"entries": {}}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return {"entries": {}}
    data.setdefault("entries", {})
    return data


def write_marker(connectors_dir: str, marker: dict) -> None:
    path = Path(connectors_dir) / MARKER_FILENAME
    path.write_text(yaml.safe_dump(marker, sort_keys=False), encoding="utf-8")


def _current_sha256(connectors_dir: str, name: str) -> str | None:
    py_path = Path(connectors_dir) / name / f"{name}.py"
    if not py_path.is_file():
        return None
    return compute_sha256(py_path.read_bytes())


def plan_install(manifest: dict, existing_marker: dict, connectors_dir: str) -> dict:
    """Categorizes every connector in the manifest:

    - new: no marker entry — nothing installed yet
    - update: marker entry, on-disk file matches the recorded sha256
      (untouched since install), manifest version differs from the
      recorded one
    - unchanged: same as update but manifest version also matches — no-op
    - skip_modified: marker entry, on-disk file's sha256 no longer matches
      the recorded one (edited via PUT /connectors/{name}/code or by hand)
      — never silently overwritten, see [S4]
    """
    entries = existing_marker.get("entries", {})
    plan: dict[str, list[dict]] = {"new": [], "update": [], "unchanged": [], "skip_modified": []}
    for conn in manifest.get("connectors", []):
        name = conn["name"]
        entry = entries.get(name)
        if entry is None:
            plan["new"].append(conn)
            continue
        disk_sha = _current_sha256(connectors_dir, name)
        if disk_sha is not None and disk_sha != entry.get("sha256"):
            plan["skip_modified"].append(conn)
            continue
        if entry.get("version") == manifest.get("version"):
            plan["unchanged"].append(conn)
        else:
            plan["update"].append(conn)
    return plan


def _write_connector(dest_dir: Path, name: str, members: list[tuple[str, bytes]]) -> str | None:
    """Writes (relpath, data) pairs under dest_dir, returns the sha256 of
    `<name>.py` if present among them."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    file_sha = None
    for relpath, data in members:
        target = dest_dir / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        if relpath == f"{name}.py":
            file_sha = compute_sha256(data)
    return file_sha


def _update_marker_entries(
    marker: dict, manifest: dict, written: dict[str, list[str]], sha_by_name: dict[str, str],
) -> None:
    entries = marker.setdefault("entries", {})
    for category in ("new", "update"):
        for name in written[category]:
            entries[name] = {"version": manifest.get("version"), "sha256": sha_by_name.get(name)}
    marker["pack"] = manifest.get("name")
    marker["pack_version"] = manifest.get("version")
    marker["installed_at"] = datetime.now(UTC).isoformat()


def apply_install(plan: dict, pack_zip_bytes: bytes, connectors_dir: str, manifest: dict) -> dict:
    """Copies plan['new'] + plan['update'] connectors out of the pack zip
    into connectors_dir, updates the marker for exactly the connectors
    written. plan['skip_modified'] is never touched."""
    os.makedirs(connectors_dir, exist_ok=True)
    marker = read_marker(connectors_dir)
    written: dict[str, list[str]] = {"new": [], "update": []}
    sha_by_name: dict[str, str] = {}

    with zipfile.ZipFile(io.BytesIO(pack_zip_bytes), "r") as zf:
        names_in_zip = zf.namelist()
        for category in ("new", "update"):
            for conn in plan[category]:
                name = conn["name"]
                conn_prefix = str(Path(conn["path"]).parent).replace("\\", "/") + "/"
                members = [
                    (member[len(conn_prefix):], zf.read(member))
                    for member in names_in_zip
                    if member.startswith(conn_prefix) and not member.endswith("/")
                ]
                dest_dir = Path(connectors_dir) / name
                file_sha = _write_connector(dest_dir, name, members)
                sha_by_name[name] = file_sha
                written[category].append(name)

    if written["new"] or written["update"]:
        _update_marker_entries(marker, manifest, written, sha_by_name)
        write_marker(connectors_dir, marker)
    return written


def apply_install_dir(plan: dict, pack_dir: str, connectors_dir: str, manifest: dict) -> dict:
    """Same as apply_install, but the pack source is a plain directory
    (SOAR_BASE_PACK_PATH — baked into the image, never a zip) instead of an
    uploaded archive."""
    os.makedirs(connectors_dir, exist_ok=True)
    marker = read_marker(connectors_dir)
    written: dict[str, list[str]] = {"new": [], "update": []}
    sha_by_name: dict[str, str] = {}

    pack_root = Path(pack_dir)
    for category in ("new", "update"):
        for conn in plan[category]:
            name = conn["name"]
            src_dir = pack_root / "connectors" / name
            members = [
                (f.relative_to(src_dir).as_posix(), f.read_bytes())
                for f in sorted(src_dir.rglob("*"))
                if f.is_file()
            ]
            dest_dir = Path(connectors_dir) / name
            file_sha = _write_connector(dest_dir, name, members)
            sha_by_name[name] = file_sha
            written[category].append(name)

    if written["new"] or written["update"]:
        _update_marker_entries(marker, manifest, written, sha_by_name)
        write_marker(connectors_dir, marker)
    return written
