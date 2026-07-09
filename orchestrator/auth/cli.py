"""CLI for managing SOAR users.

Usage:
    python -m orchestrator.auth.cli create-user --username admin --role admin
"""

import argparse
import asyncio
import getpass
import os
import sys


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


def main() -> None:
    parser = argparse.ArgumentParser(description="SOAR auth CLI")
    sub = parser.add_subparsers(dest="cmd")

    create = sub.add_parser("create-user", help="Create a new user")
    create.add_argument("--username", required=True)
    create.add_argument("--role", default="analyst", choices=["admin", "analyst", "viewer", "service"])
    create.add_argument("--password", default=None, help="If omitted, prompted interactively")

    args = parser.parse_args()

    if args.cmd == "create-user":
        password = args.password or getpass.getpass("Password: ")
        db_url = os.environ.get("SOAR_DB_URL", "sqlite+aiosqlite:///./soar.db")
        asyncio.run(_create_user(args.username, password, args.role, db_url))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
