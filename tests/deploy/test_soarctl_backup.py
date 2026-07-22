import tarfile
from pathlib import Path

import pytest

from deploy.soarctl_lib.backup import create, restore


def _make_instance(tmp_path: Path) -> Path:
    (tmp_path / "docker-compose.yml").write_text("services: {}\n")
    (tmp_path / ".env").write_text("SOAR_VERSION=1.2.3\n")
    return tmp_path


def test_create_writes_combined_archive(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    output = tmp_path / "backup.tar.gz"
    calls = []

    class _Result:
        def __init__(self, stdout):
            self.stdout = stdout

    def fake_run(argv, **kw):
        calls.append((argv, kw))
        if "pg_dump" in argv:
            return _Result("-- fake pg_dump output --\n")
        if argv[:2] == ["docker", "run"]:
            return _Result(b"fake-volume-tar-bytes")
        raise AssertionError(f"unexpected call: {argv}")

    monkeypatch.setattr("deploy.soarctl_lib.backup.run", fake_run)

    result_path = create(instance, output)

    assert result_path == output
    assert output.exists()
    with tarfile.open(output) as tar:
        names = tar.getnames()
        assert "db.sql" in names
        assert "soar-data.tar.gz" in names
        assert tar.extractfile("db.sql").read() == b"-- fake pg_dump output --\n"
        assert tar.extractfile("soar-data.tar.gz").read() == b"fake-volume-tar-bytes"

    pg_dump_calls = [c for c in calls if "pg_dump" in c[0]]
    volume_calls = [c for c in calls if c[0][:2] == ["docker", "run"]]
    assert len(pg_dump_calls) == 1
    assert len(volume_calls) == 1
    assert "soar-data:/data" in volume_calls[0][0]
    assert volume_calls[0][1].get("text") is False


def test_restore_refuses_without_confirm(tmp_path):
    instance = _make_instance(tmp_path)
    archive = tmp_path / "backup.tar.gz"
    with tarfile.open(archive, "w:gz"):
        pass
    with pytest.raises(ValueError):
        restore(instance, archive)


def test_restore_runs_psql_and_volume_restore(tmp_path, monkeypatch):
    instance = _make_instance(tmp_path)
    archive = tmp_path / "backup.tar.gz"
    db_sql = tmp_path / "db.sql"
    db_sql.write_bytes(b"-- sql --\n")
    volume_tar = tmp_path / "soar-data.tar.gz"
    volume_tar.write_bytes(b"fake-volume-tar-bytes")
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(db_sql, arcname="db.sql")
        tar.add(volume_tar, arcname="soar-data.tar.gz")

    calls = []

    def fake_run(argv, **kw):
        calls.append((argv, kw))

        class _R:
            stdout = ""

        return _R()

    monkeypatch.setattr("deploy.soarctl_lib.backup.run", fake_run)

    restore(instance, archive, confirm=True)

    psql_calls = [c for c in calls if "psql" in c[0]]
    volume_calls = [c for c in calls if c[0][:2] == ["docker", "run"]]
    assert len(psql_calls) == 1
    assert psql_calls[0][1].get("input_text") == "-- sql --\n"
    assert len(volume_calls) == 1
    assert volume_calls[0][1].get("input_text") == b"fake-volume-tar-bytes"
