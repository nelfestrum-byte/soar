"""soarctl content install/list/remove — mocked docker/subprocess, same
pattern as tests/deploy/test_soarctl_backup.py. No real docker involved:
`run()` is monkeypatched, tar bytes are built/parsed in-memory."""

import io
import tarfile

import pytest
import yaml

from deploy.soarctl_lib import content

_FAKE_CONN_SRC = (
    "from typing import ClassVar\n\n"
    "from soar.connectors.base import BaseConnector\n\n\n"
    "class FakeConnConnector(BaseConnector):\n"
    "    MUTATING_METHODS: ClassVar[set[str]] = set()\n\n"
    "    def _connect_impl(self):\n"
    "        self._connected = True\n\n"
    "    def disconnect(self):\n"
    "        self._connected = False\n"
)


def _make_pack(tmp_path, version="1.0.0", name="test-pack", connector_src=_FAKE_CONN_SRC):
    pack_dir = tmp_path / "pack"
    conn_dir = pack_dir / "connectors" / "fake_conn"
    conn_dir.mkdir(parents=True)
    (conn_dir / "fake_conn.py").write_text(connector_src, encoding="utf-8")
    (conn_dir / "__init__.py").write_text("", encoding="utf-8")
    manifest = {
        "name": name,
        "version": version,
        "runtime_version": "1",
        "connectors": [
            {"name": "fake_conn", "path": "connectors/fake_conn/fake_conn.py", "imports": [], "mutating_methods": []},
        ],
    }
    (pack_dir / "manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    return pack_dir


def _empty_volume_tar() -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        info = tarfile.TarInfo("connectors/")
        info.type = tarfile.DIRTYPE
        tar.addfile(info)
    return buffer.getvalue()


def _volume_tar_with(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


class _FakeVolume:
    """Stateful fake docker volume — records the tar it was last written
    with, and serves it back on the next dump, so successive install()
    calls in one test see each other's writes (same shape as a real
    volume, without touching docker)."""

    def __init__(self, initial: bytes | None = None):
        self.data = initial if initial is not None else _empty_volume_tar()
        self.calls: list[list[str]] = []

    def run(self, argv, **kw):
        self.calls.append(argv)

        class _R:
            pass

        r = _R()
        if argv[:2] == ["docker", "run"] and "tar czf" in " ".join(argv):
            r.stdout = self.data
            return r
        if argv[:2] == ["docker", "run"] and "tar xzf" in " ".join(argv):
            self.data = kw["input_text"]
            r.stdout = b""
            return r
        if argv[:2] == ["docker", "run"] and "rm" in argv:
            # Rebuild self.data without the removed connector's directory.
            name = argv[-1].rsplit("/", 1)[-1]
            buffer = io.BytesIO()
            with tarfile.open(fileobj=io.BytesIO(self.data)) as src, \
                 tarfile.open(fileobj=buffer, mode="w:gz") as dst:
                for member in src.getmembers():
                    if member.name.startswith(f"connectors/{name}/"):
                        continue
                    extracted = src.extractfile(member) if member.isfile() else None
                    dst.addfile(member, extracted)
            self.data = buffer.getvalue()
            r.stdout = ""
            return r
        raise AssertionError(f"unexpected call: {argv}")


@pytest.fixture
def volume(monkeypatch):
    vol = _FakeVolume()
    monkeypatch.setattr(content, "run", vol.run)
    return vol


def test_install_fresh_pack_all_new(tmp_path, volume):
    pack_dir = _make_pack(tmp_path)
    result = content.install(str(pack_dir))
    assert result["new"] == ["fake_conn"]
    assert result["update"] == result["skip_modified"] == []

    # A write happened (docker run ... tar xzf)
    write_calls = [c for c in volume.calls if "tar xzf" in " ".join(c)]
    assert len(write_calls) == 1

    rows = content.list_installed()
    assert rows == [{"name": "fake_conn", "pack_version": "1.0.0", "modified": False}]


def test_install_same_version_twice_is_noop(tmp_path, volume):
    pack_dir = _make_pack(tmp_path)
    content.install(str(pack_dir))
    marker_before, _ = content._read_current_state()

    result = content.install(str(pack_dir))
    assert result["new"] == result["update"] == result["skip_modified"] == []
    assert result["unchanged"] == ["fake_conn"]

    marker_after, _ = content._read_current_state()
    assert marker_after == marker_before  # installed_at untouched on a true no-op


def test_install_after_manual_edit_skips_that_connector(tmp_path, volume):
    pack_dir = _make_pack(tmp_path)
    content.install(str(pack_dir))

    # Simulate a user editing the connector on disk (in the volume) directly —
    # dump, patch the file's bytes, write back, bypassing content.install().
    marker, files = content._read_current_state()
    files["connectors/fake_conn/fake_conn.py"] = b"# hand-edited\n"
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        marker_bytes = yaml.safe_dump(marker).encode()
        info = tarfile.TarInfo("connectors/.soar-content.yaml")
        info.size = len(marker_bytes)
        tar.addfile(info, io.BytesIO(marker_bytes))
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    volume.data = buffer.getvalue()

    # New pack version — the untouched connector would normally update,
    # but this one was hand-edited.
    pack_dir_v2 = _make_pack(tmp_path / "v2", version="2.0.0")
    result = content.install(str(pack_dir_v2))
    assert result["skip_modified"] == ["fake_conn"]
    assert result["new"] == result["update"] == []

    _, files_after = content._read_current_state()
    assert files_after["connectors/fake_conn/fake_conn.py"] == b"# hand-edited\n"


def test_install_new_version_updates_unmodified_connector(tmp_path, volume):
    pack_dir = _make_pack(tmp_path, version="1.0.0")
    content.install(str(pack_dir))

    pack_dir_v2 = _make_pack(tmp_path / "v2", version="2.0.0")
    result = content.install(str(pack_dir_v2))
    assert result["update"] == ["fake_conn"]

    rows = content.list_installed()
    assert rows == [{"name": "fake_conn", "pack_version": "2.0.0", "modified": False}]


def test_list_installed_empty_volume(volume):
    assert content.list_installed() == []


def test_remove_unmodified_connector(tmp_path, volume):
    pack_dir = _make_pack(tmp_path)
    content.install(str(pack_dir))

    content.remove("fake_conn")
    assert content.list_installed() == []


def test_remove_modified_without_force_refuses(tmp_path, volume):
    pack_dir = _make_pack(tmp_path)
    content.install(str(pack_dir))

    marker, files = content._read_current_state()
    files["connectors/fake_conn/fake_conn.py"] = b"# edited\n"
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        marker_bytes = yaml.safe_dump(marker).encode()
        info = tarfile.TarInfo("connectors/.soar-content.yaml")
        info.size = len(marker_bytes)
        tar.addfile(info, io.BytesIO(marker_bytes))
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    volume.data = buffer.getvalue()

    with pytest.raises(content.ContentError, match="modified"):
        content.remove("fake_conn")
    assert content.list_installed() != []


def test_remove_modified_with_force_removes(tmp_path, volume):
    pack_dir = _make_pack(tmp_path)
    content.install(str(pack_dir))

    marker, files = content._read_current_state()
    files["connectors/fake_conn/fake_conn.py"] = b"# edited\n"
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        marker_bytes = yaml.safe_dump(marker).encode()
        info = tarfile.TarInfo("connectors/.soar-content.yaml")
        info.size = len(marker_bytes)
        tar.addfile(info, io.BytesIO(marker_bytes))
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    volume.data = buffer.getvalue()

    content.remove("fake_conn", force=True)
    assert content.list_installed() == []


def test_remove_unknown_connector_raises(volume):
    with pytest.raises(content.ContentError, match="not installed"):
        content.remove("nope")


def test_remove_rejects_unsafe_name(volume):
    with pytest.raises(content.ContentError, match="invalid connector name"):
        content.remove("../../etc")
