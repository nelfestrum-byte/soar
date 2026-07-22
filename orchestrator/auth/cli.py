"""CLI for managing SOAR users.

Reads the same config the running service reads (SOAR_CONFIG, default
config.yaml) so the DB URL and table_prefix always match what the app
actually queries — do not reintroduce a separate DB URL env var here, see
docs/compose/specs/2026-07-21-auth-cli-user-lifecycle-design.md [S1].

Usage:
    python -m orchestrator.auth.cli create-user --username admin --role admin
    python -m orchestrator.auth.cli deactivate-user --username alice
    python -m orchestrator.auth.cli activate-user --username alice
"""

import argparse
import asyncio
import getpass
import os
import sys

from orchestrator.config import load_config
from orchestrator.db.base import configure_table_prefix


async def _create_user(username: str, password: str, role: str, db_url: str) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from orchestrator.auth.models import User  # noqa: F401 — registers with Base
    from orchestrator.auth.service import create_user
    from orchestrator.db.base import Base

    engine = create_async_engine(db_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        user = await create_user(session, username, password, role)
        print(f"Created user: id={user.id} username={user.username} role={user.role}")

    await engine.dispose()


async def _set_user_active(username: str, is_active: bool, db_url: str) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from orchestrator.auth.models import User  # noqa: F401 — registers with Base
    from orchestrator.auth.service import set_user_active

    engine = create_async_engine(db_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        try:
            user = await set_user_active(session, username, is_active)
        except LookupError as e:
            print(str(e), file=sys.stderr)
            await engine.dispose()
            sys.exit(1)
        state = "activated" if is_active else "deactivated"
        print(f"User {state}: id={user.id} username={user.username}")

    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="SOAR auth CLI")
    sub = parser.add_subparsers(dest="cmd")

    create = sub.add_parser("create-user", help="Create a new user")
    create.add_argument("--username", required=True)
    create.add_argument("--role", default="analyst", choices=["admin", "analyst", "viewer", "service"])
    create.add_argument("--password", default=None, help="If omitted, prompted interactively")
    create.add_argument("--db-url", default=None, help="Override database.url from config")

    deactivate = sub.add_parser("deactivate-user", help="Deny login for an existing user")
    deactivate.add_argument("--username", required=True)
    deactivate.add_argument("--db-url", default=None, help="Override database.url from config")

    activate = sub.add_parser("activate-user", help="Re-allow login for a deactivated user")
    activate.add_argument("--username", required=True)
    activate.add_argument("--db-url", default=None, help="Override database.url from config")

    args = parser.parse_args()

    if args.cmd is None:
        parser.print_help()
        sys.exit(1)

    config = load_config(os.environ.get("SOAR_CONFIG", "config.yaml"))
    configure_table_prefix(config.database.table_prefix)
    db_url = args.db_url or config.database.url

    if args.cmd == "create-user":
        password = args.password or getpass.getpass("Password: ")
        asyncio.run(_create_user(args.username, password, args.role, db_url))
    elif args.cmd == "deactivate-user":
        asyncio.run(_set_user_active(args.username, False, db_url))
    elif args.cmd == "activate-user":
        asyncio.run(_set_user_active(args.username, True, db_url))


if __name__ == "__main__":
    main()
