"""DB + workflow/actions/connectors data in one archive, one command in,
one out. The `soar-data` volume is read/written through a throwaway alpine
container piping tar over stdout/stdin — no bind-mounted temp directory,
which would need host-path translation into the container that's brittle
across platforms (Windows drive letters collide with the `host:container`
`-v` syntax's own colon separator).
"""

import io
import tarfile
from pathlib import Path

from .compose import compose_argv
from .runner import run

_DB_ARGV = ["exec", "-T", "postgres"]
_VOLUME_NAME = "soar-data"


def dump_database(instance: Path) -> str:
    argv = compose_argv(instance, *_DB_ARGV, "pg_dump", "-U", "soar", "soar")
    return run(argv).stdout


def dump_data_volume() -> bytes:
    argv = [
        "docker", "run", "--rm",
        "-v", f"{_VOLUME_NAME}:/data",
        "alpine", "tar", "czf", "-", "-C", "/data", ".",
    ]
    return run(argv, text=False).stdout


def restore_database(instance: Path, sql_text: str) -> None:
    argv = compose_argv(instance, *_DB_ARGV, "psql", "-U", "soar", "-d", "soar")
    run(argv, input_text=sql_text)


def restore_data_volume(tar_bytes: bytes) -> None:
    argv = [
        "docker", "run", "--rm", "-i",
        "-v", f"{_VOLUME_NAME}:/data",
        "alpine", "sh", "-c", "rm -rf /data/* && tar xzf - -C /data",
    ]
    run(argv, input_text=tar_bytes, text=False)


def create(instance: Path, output: Path) -> Path:
    db_sql = dump_database(instance)
    volume_bytes = dump_data_volume()

    with tarfile.open(output, "w:gz") as tar:
        db_bytes = db_sql.encode()
        db_info = tarfile.TarInfo("db.sql")
        db_info.size = len(db_bytes)
        tar.addfile(db_info, io.BytesIO(db_bytes))

        volume_info = tarfile.TarInfo("soar-data.tar.gz")
        volume_info.size = len(volume_bytes)
        tar.addfile(volume_info, io.BytesIO(volume_bytes))

    return output


def restore(instance: Path, archive: Path, confirm: bool = False) -> None:
    if not confirm:
        raise ValueError(
            "restore overwrites the running database and workflow/actions/"
            "connectors data — pass confirm=True to proceed"
        )

    with tarfile.open(archive, "r:gz") as tar:
        sql_text = tar.extractfile("db.sql").read().decode()
        tar_bytes = tar.extractfile("soar-data.tar.gz").read()

    restore_database(instance, sql_text)
    restore_data_volume(tar_bytes)
