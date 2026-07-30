"""Synthetic connector fixtures only (not real vendor code) — this exercises
the install pipeline itself, per docs/compose/specs/2026-07-30-content-as-
contentpack-design.md [S10]: the 24 real connectors' own tests moved to the
sibling pack repo (D:/projects/soar-content-pack), this file is the
"one smoke/example test on the pipeline" that stays behind.
"""

import io
import zipfile

import pytest
import yaml

from orchestrator.core import pack_install

_CONTRACT = {
    "vt-py": {"import_names": ["vt"], "kind": "vendor"},
    "requests": {"import_names": ["requests"], "kind": "protocol"},
}


def _manifest(version="1.0.0", runtime_version="1", connectors=None):
    return {
        "name": "test-pack",
        "version": version,
        "runtime_version": runtime_version,
        "connectors": connectors if connectors is not None else [
            {
                "name": "fake_conn",
                "path": "connectors/fake_conn/fake_conn.py",
                "imports": ["vt"],
                "mutating_methods": ["do_thing"],
            },
        ],
    }


_FAKE_CONN_SRC = (
    "from typing import ClassVar\n\n"
    "import vt\n\n"
    "from soar.connectors.base import BaseConnector\n\n\n"
    "class FakeConnConnector(BaseConnector):\n"
    "    MUTATING_METHODS: ClassVar[set[str]] = {'do_thing'}\n\n"
    "    def _connect_impl(self):\n"
    "        self._connected = True\n\n"
    "    def disconnect(self):\n"
    "        self._connected = False\n"
)


def _build_pack_zip(manifest: dict, connector_src: str = _FAKE_CONN_SRC) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("manifest.yaml", yaml.safe_dump(manifest))
        for conn in manifest["connectors"]:
            zf.writestr(conn["path"], connector_src)
            zf.writestr(f"{conn['path'].rsplit('/', 1)[0]}/__init__.py", "")
    return buffer.getvalue()


# ── read_manifest ──


def test_read_manifest_parses_manifest_yaml():
    pack_bytes = _build_pack_zip(_manifest())
    manifest = pack_install.read_manifest(pack_bytes)
    assert manifest["name"] == "test-pack"
    assert manifest["connectors"][0]["name"] == "fake_conn"


def test_read_manifest_missing_manifest_raises():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("connectors/fake_conn/fake_conn.py", _FAKE_CONN_SRC)
    with pytest.raises(ValueError, match="manifest.yaml"):
        pack_install.read_manifest(buffer.getvalue())


def test_read_manifest_not_a_zip_raises():
    with pytest.raises(ValueError, match="ZIP"):
        pack_install.read_manifest(b"not a zip file")


def test_read_manifest_from_dir(tmp_path):
    pack_dir = tmp_path / "pack"
    pack_dir.mkdir()
    (pack_dir / "manifest.yaml").write_text(yaml.safe_dump(_manifest()), encoding="utf-8")
    manifest = pack_install.read_manifest_from_dir(str(pack_dir))
    assert manifest["name"] == "test-pack"


def test_read_manifest_from_dir_missing_raises(tmp_path):
    with pytest.raises(ValueError, match="manifest.yaml"):
        pack_install.read_manifest_from_dir(str(tmp_path))


# ── check_runtime_compat ──


def test_check_runtime_compat_matching_major_ok():
    pack_install.check_runtime_compat(_manifest(runtime_version="1"), runtime_version="1")


def test_check_runtime_compat_mismatched_major_raises():
    with pytest.raises(ValueError, match="incompatible"):
        pack_install.check_runtime_compat(_manifest(runtime_version="2"), runtime_version="1")


def test_check_runtime_compat_missing_raises():
    with pytest.raises(ValueError):
        pack_install.check_runtime_compat({"name": "x"}, runtime_version="1")


# ── check_dependencies ──


def test_check_dependencies_all_guaranteed_returns_empty():
    missing = pack_install.check_dependencies(_manifest(), _CONTRACT)
    assert missing == []


def test_check_dependencies_missing_import_returned():
    manifest = _manifest(connectors=[
        {"name": "x", "path": "connectors/x/x.py", "imports": ["not_a_real_sdk"], "mutating_methods": []},
    ])
    missing = pack_install.check_dependencies(manifest, _CONTRACT)
    assert missing == ["not_a_real_sdk"]


# ── plan_install ──


def test_plan_install_empty_marker_all_new(tmp_path):
    marker = {"entries": {}}
    plan = pack_install.plan_install(_manifest(), marker, str(tmp_path))
    assert [c["name"] for c in plan["new"]] == ["fake_conn"]
    assert plan["update"] == plan["skip_modified"] == plan["unchanged"] == []


def test_plan_install_same_version_same_sha_is_unchanged(tmp_path):
    conn_dir = tmp_path / "fake_conn"
    conn_dir.mkdir()
    py_path = conn_dir / "fake_conn.py"
    py_path.write_text(_FAKE_CONN_SRC, encoding="utf-8")
    sha = pack_install.compute_sha256(py_path.read_bytes())
    marker = {"entries": {"fake_conn": {"version": "1.0.0", "sha256": sha}}}

    plan = pack_install.plan_install(_manifest(version="1.0.0"), marker, str(tmp_path))
    assert [c["name"] for c in plan["unchanged"]] == ["fake_conn"]
    assert plan["new"] == plan["update"] == plan["skip_modified"] == []


def test_plan_install_new_version_same_sha_is_update(tmp_path):
    conn_dir = tmp_path / "fake_conn"
    conn_dir.mkdir()
    py_path = conn_dir / "fake_conn.py"
    py_path.write_text(_FAKE_CONN_SRC, encoding="utf-8")
    sha = pack_install.compute_sha256(py_path.read_bytes())
    marker = {"entries": {"fake_conn": {"version": "1.0.0", "sha256": sha}}}

    plan = pack_install.plan_install(_manifest(version="2.0.0"), marker, str(tmp_path))
    assert [c["name"] for c in plan["update"]] == ["fake_conn"]


def test_plan_install_modified_file_is_skip_modified(tmp_path):
    conn_dir = tmp_path / "fake_conn"
    conn_dir.mkdir()
    py_path = conn_dir / "fake_conn.py"
    py_path.write_text(_FAKE_CONN_SRC, encoding="utf-8")
    marker = {"entries": {"fake_conn": {"version": "1.0.0", "sha256": "deadbeef" * 8}}}

    plan = pack_install.plan_install(_manifest(version="2.0.0"), marker, str(tmp_path))
    assert [c["name"] for c in plan["skip_modified"]] == ["fake_conn"]
    assert plan["new"] == plan["update"] == plan["unchanged"] == []


# ── apply_install (zip) ──


def test_apply_install_writes_new_connector_and_marker(tmp_path):
    manifest = _manifest()
    pack_bytes = _build_pack_zip(manifest)
    connectors_dir = tmp_path / "connectors"

    plan = pack_install.plan_install(manifest, {"entries": {}}, str(connectors_dir))
    written = pack_install.apply_install(plan, pack_bytes, str(connectors_dir), manifest)

    assert written["new"] == ["fake_conn"]
    py_path = connectors_dir / "fake_conn" / "fake_conn.py"
    assert py_path.is_file()
    assert py_path.read_text(encoding="utf-8") == _FAKE_CONN_SRC

    marker = pack_install.read_marker(str(connectors_dir))
    assert marker["entries"]["fake_conn"]["version"] == "1.0.0"
    assert marker["entries"]["fake_conn"]["sha256"] == pack_install.compute_sha256(_FAKE_CONN_SRC.encode())
    assert marker["pack"] == "test-pack"


def test_apply_install_skips_modified_connector(tmp_path):
    manifest = _manifest(version="2.0.0")
    pack_bytes = _build_pack_zip(manifest)
    connectors_dir = tmp_path / "connectors"
    conn_dir = connectors_dir / "fake_conn"
    conn_dir.mkdir(parents=True)
    (conn_dir / "fake_conn.py").write_text("# user-edited\n", encoding="utf-8")

    marker = {"entries": {"fake_conn": {"version": "1.0.0", "sha256": "deadbeef" * 8}}}
    pack_install.write_marker(str(connectors_dir), marker)

    plan = pack_install.plan_install(manifest, marker, str(connectors_dir))
    written = pack_install.apply_install(plan, pack_bytes, str(connectors_dir), manifest)

    assert written["new"] == []
    assert written["update"] == []
    # File on disk untouched
    assert (conn_dir / "fake_conn.py").read_text(encoding="utf-8") == "# user-edited\n"


def test_apply_install_noop_leaves_marker_untouched(tmp_path):
    manifest = _manifest(version="1.0.0")
    pack_bytes = _build_pack_zip(manifest)
    connectors_dir = tmp_path / "connectors"

    plan = pack_install.plan_install(manifest, {"entries": {}}, str(connectors_dir))
    pack_install.apply_install(plan, pack_bytes, str(connectors_dir), manifest)
    marker_before = pack_install.read_marker(str(connectors_dir))

    # Re-install same version — everything should land in "unchanged"
    plan2 = pack_install.plan_install(manifest, marker_before, str(connectors_dir))
    assert plan2["new"] == plan2["update"] == plan2["skip_modified"] == []
    assert [c["name"] for c in plan2["unchanged"]] == ["fake_conn"]

    written2 = pack_install.apply_install(plan2, pack_bytes, str(connectors_dir), manifest)
    assert written2 == {"new": [], "update": []}
    marker_after = pack_install.read_marker(str(connectors_dir))
    assert marker_after == marker_before


# ── apply_install_dir ──


def test_apply_install_dir_writes_from_local_pack(tmp_path):
    manifest = _manifest()
    pack_dir = tmp_path / "pack"
    conn_src_dir = pack_dir / "connectors" / "fake_conn"
    conn_src_dir.mkdir(parents=True)
    (conn_src_dir / "fake_conn.py").write_text(_FAKE_CONN_SRC, encoding="utf-8")
    (conn_src_dir / "__init__.py").write_text("", encoding="utf-8")

    connectors_dir = tmp_path / "connectors_dir"
    plan = pack_install.plan_install(manifest, {"entries": {}}, str(connectors_dir))
    written = pack_install.apply_install_dir(plan, str(pack_dir), str(connectors_dir), manifest)

    assert written["new"] == ["fake_conn"]
    assert (connectors_dir / "fake_conn" / "fake_conn.py").is_file()
    marker = pack_install.read_marker(str(connectors_dir))
    assert marker["entries"]["fake_conn"]["version"] == "1.0.0"
