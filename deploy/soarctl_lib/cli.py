"""argparse wiring only — every subcommand is a thin call into the matching
soarctl_lib module, no business logic here (same "engine vs behavior" split
as the rest of the project's API routes).
"""

import argparse
import sys
from pathlib import Path

from . import backup, bundle, compose, doctor, env, migrate, paths, status, users


def _add_dir_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dir", default=None, help="Instance directory (default: current directory)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="soarctl", description="SOAR deploy/lifecycle CLI")
    sub = parser.add_subparsers(dest="cmd")

    pkg = sub.add_parser("package", help="Build images + save into a self-contained bundle (build machine)")
    pkg.add_argument("--version", required=True)
    pkg.add_argument("--output", required=True)

    install = sub.add_parser("install", help="Extract a bundle + docker load its images (target machine)")
    install.add_argument("bundle")
    _add_dir_arg(install)

    init = sub.add_parser("init", help="Generate .env secrets + render config.yaml")
    init.add_argument("--force", action="store_true", help="Overwrite an existing .env")
    _add_dir_arg(init)

    for name, help_text in [("up", "Start the instance"), ("down", "Stop the instance"), ("restart", "Restart the instance")]:
        p = sub.add_parser(name, help=help_text)
        _add_dir_arg(p)

    st = sub.add_parser("status", help="Show container status + /health")
    _add_dir_arg(st)

    lg = sub.add_parser("logs", help="Follow logs")
    lg.add_argument("service", nargs="?", default=None)
    _add_dir_arg(lg)

    mig = sub.add_parser("migrate", help="Apply DB migrations")
    mig_group = mig.add_mutually_exclusive_group(required=True)
    mig_group.add_argument("--fresh", action="store_true", help="alembic stamp head (new tables only)")
    mig_group.add_argument("--upgrade", action="store_true", help="alembic upgrade head (altered tables)")
    _add_dir_arg(mig)

    usr = sub.add_parser("users", help="Manage users")
    usr_sub = usr.add_subparsers(dest="users_cmd", required=True)

    usr_create = usr_sub.add_parser("create")
    usr_create.add_argument("--username", required=True)
    usr_create.add_argument("--role", default="analyst")
    _add_dir_arg(usr_create)

    usr_deactivate = usr_sub.add_parser("deactivate")
    usr_deactivate.add_argument("--username", required=True)
    _add_dir_arg(usr_deactivate)

    usr_activate = usr_sub.add_parser("activate")
    usr_activate.add_argument("--username", required=True)
    _add_dir_arg(usr_activate)

    bkp = sub.add_parser("backup", help="Backup / restore DB + workflow data")
    bkp_sub = bkp.add_subparsers(dest="backup_cmd", required=True)

    bkp_create = bkp_sub.add_parser("create")
    bkp_create.add_argument("--output", required=True)
    _add_dir_arg(bkp_create)

    bkp_restore = bkp_sub.add_parser("restore")
    bkp_restore.add_argument("archive")
    bkp_restore.add_argument("--confirm", action="store_true")
    _add_dir_arg(bkp_restore)

    doc = sub.add_parser("doctor", help="Preflight checks")
    _add_dir_arg(doc)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.cmd is None:
        parser.print_help()
        sys.exit(1)

    if args.cmd == "package":
        bundle.package(paths.repo_root(Path(__file__)), version=args.version, output=Path(args.output))
        return

    if args.cmd == "install":
        bundle.install(Path(args.bundle), paths.instance_dir(args))
        return

    if args.cmd == "init":
        env.init_instance(paths.instance_dir(args), force=args.force)
        return

    if args.cmd == "up":
        compose.up(paths.instance_dir(args))
        return
    if args.cmd == "down":
        compose.down(paths.instance_dir(args))
        return
    if args.cmd == "restart":
        compose.restart(paths.instance_dir(args))
        return

    if args.cmd == "status":
        instance = paths.instance_dir(args)
        ps_output = compose.ps(instance)
        health = status.check_health("http://localhost:8000")
        print(status.summarize(ps_output, health))
        return

    if args.cmd == "logs":
        compose.logs(paths.instance_dir(args), service=args.service)
        return

    if args.cmd == "migrate":
        instance = paths.instance_dir(args)
        if args.fresh:
            migrate.stamp_head(instance)
        else:
            migrate.upgrade_head(instance)
        return

    if args.cmd == "users":
        instance = paths.instance_dir(args)
        if args.users_cmd == "create":
            users.create(instance, username=args.username, role=args.role)
        elif args.users_cmd == "deactivate":
            users.deactivate(instance, username=args.username)
        elif args.users_cmd == "activate":
            users.activate(instance, username=args.username)
        return

    if args.cmd == "backup":
        instance = paths.instance_dir(args)
        if args.backup_cmd == "create":
            backup.create(instance, Path(args.output))
        elif args.backup_cmd == "restore":
            backup.restore(instance, Path(args.archive), confirm=args.confirm)
        return

    if args.cmd == "doctor":
        instance = paths.instance_dir(args)
        results = doctor.run_checks(instance)
        failed = False
        for name, ok, message in results:
            print(f"[{'OK' if ok else 'FAIL'}] {name}: {message}")
            failed = failed or not ok
        if failed:
            sys.exit(1)
        return
