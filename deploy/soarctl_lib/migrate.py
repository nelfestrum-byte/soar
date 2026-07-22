"""Explicit stamp/upgrade split — no auto-detect.

create_all() runs on every orchestrator boot and only ever creates missing
tables; it never alters existing ones. A migration that adds a brand-new
table is already satisfied by create_all() by the time `soarctl migrate`
would run, so `alembic upgrade head` on that migration would try to
CREATE TABLE on something that already exists and fail — `stamp head` is
the correct move there. A migration that alters an existing table needs
the opposite: `upgrade head` is the only path, `stamp` would silently skip
the DDL. Getting this wrong corrupts state, and there is no way to infer
which case applies from the migration file alone without parsing its
operations — see AGENTS.md "Database backend" and the deploy-cli spec
[S3]. Two explicit commands, operator picks, same as `make
migrate-stamp-initial` / `make migrate` in deploy/stage today.
"""

from pathlib import Path

from .compose import compose_argv
from .runner import run

_ALEMBIC_ARGV = ["exec", "orchestrator", "python", "-m", "alembic"]


def stamp_head(instance: Path) -> None:
    run(compose_argv(instance, *_ALEMBIC_ARGV, "stamp", "head"), stream=True)


def upgrade_head(instance: Path) -> None:
    run(compose_argv(instance, *_ALEMBIC_ARGV, "upgrade", "head"), stream=True)
