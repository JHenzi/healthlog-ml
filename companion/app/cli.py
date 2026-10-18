"""The ``companion`` operator CLI.

companion check-upstream                 # verify the HealthLog read contract (exit 1 on problems)
companion migrate                        # alembic upgrade head (schema companion)
companion set-password                   # set the operator password (prompted, or --stdin)
companion token create NAME --scope all|read|log:<tracker_key>
companion token list
companion token revoke ID
companion refresh                        # seed metric settings, sync mood, rebuild daily features
companion web                            # migrate, then serve on :8000
companion jobs                           # run the nightly job scheduler
"""

from __future__ import annotations

import argparse
import getpass
import logging
import sys
from pathlib import Path

import sqlalchemy as sa

from . import auth, upstream
from .db import session_scope
from .models import ApiToken

ROOT = Path(__file__).resolve().parents[1]


def _check_upstream(_args: argparse.Namespace) -> int:
    with session_scope() as db:
        problems = upstream.check_upstream(db)
    for problem in problems:
        print(f"PROBLEM  {problem}")
    if problems:
        return 1
    print(f"ok: {len(upstream.CONTRACT)} HealthLog tables match the read contract")
    return 0


def _migrate(_args: argparse.Namespace | None = None) -> int:
    from alembic import command
    from alembic.config import Config

    from .config import get_settings

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.attributes["database_url"] = get_settings().database_url
    command.upgrade(cfg, "head")
    return 0


def _set_password(args: argparse.Namespace) -> int:
    if args.stdin:
        password = sys.stdin.readline().rstrip("\n")
    else:
        password = getpass.getpass("New password: ")
        if getpass.getpass("Repeat: ") != password:
            print("Passwords don't match.", file=sys.stderr)
            return 1
    try:
        with session_scope() as db:
            auth.set_password(db, password)
    except ValueError as exc:
        print(f"Not set: {exc}", file=sys.stderr)
        return 1
    print("Password set. Existing sessions were signed out.")
    return 0


def _token_create(args: argparse.Namespace) -> int:
    try:
        with session_scope() as db:
            raw, row = auth.create_token(db, args.name, args.scope)
            token_id = row.id
    except ValueError as exc:
        print(f"Not created: {exc}", file=sys.stderr)
        return 1
    print(f"Token #{token_id} ({args.scope}). Shown once, store it now:\n{raw}")
    return 0


def _token_list(_args: argparse.Namespace) -> int:
    with session_scope() as db:
        rows = db.execute(sa.select(ApiToken).order_by(ApiToken.id)).scalars().all()
        for r in rows:
            state = f"revoked {r.revoked_at:%Y-%m-%d}" if r.revoked_at else "active"
            used = f"last used {r.last_used_at:%Y-%m-%d %H:%M}" if r.last_used_at else "never used"
            print(f"#{r.id}  {r.name}  scope={r.scope}  {state}  {used}")
    return 0


def _token_revoke(args: argparse.Namespace) -> int:
    with session_scope() as db:
        ok = auth.revoke_token(db, args.id)
    print("Revoked." if ok else "No active token with that id.")
    return 0 if ok else 1


def _refresh(_args: argparse.Namespace) -> int:
    from . import jobs

    with session_scope() as db:
        result = jobs.refresh(db)
    f = result.features
    print(
        f"metric settings: +{result.seeded.added} new, {result.seeded.refreshed} refreshed; "
        f"mood: {result.mood.entries} entries from {result.mood.payloads} payloads; "
        f"features: {f.features} ({f.rows} day values, {f.first_day} to {f.last_day})"
    )
    return 0


def _web(args: argparse.Namespace) -> int:
    import uvicorn

    _migrate()
    uvicorn.run("app.main:app", host="0.0.0.0", port=args.port, proxy_headers=False)
    return 0


def _jobs(_args: argparse.Namespace) -> int:
    from . import jobs

    return jobs.run()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="companion", description="HealthLog Companion operator CLI.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("check-upstream", help="verify the HealthLog read contract").set_defaults(func=_check_upstream)
    sub.add_parser("migrate", help="apply companion migrations").set_defaults(func=_migrate)

    pw = sub.add_parser("set-password", help="set the operator password")
    pw.add_argument("--stdin", action="store_true", help="read the password from stdin (one line)")
    pw.set_defaults(func=_set_password)

    tok = sub.add_parser("token", help="manage API tokens")
    tok_sub = tok.add_subparsers(dest="token_command", required=True)
    create = tok_sub.add_parser("create", help="create a token (printed once)")
    create.add_argument("name")
    create.add_argument("--scope", default="read", help="all | read | log:<tracker_key> (default: read)")
    create.set_defaults(func=_token_create)
    tok_sub.add_parser("list", help="list tokens").set_defaults(func=_token_list)
    revoke = tok_sub.add_parser("revoke", help="revoke a token")
    revoke.add_argument("id", type=int)
    revoke.set_defaults(func=_token_revoke)

    sub.add_parser("refresh", help="seed metric settings, sync mood, rebuild daily features").set_defaults(
        func=_refresh
    )

    web = sub.add_parser("web", help="migrate, then serve the web app")
    web.add_argument("--port", type=int, default=8000)
    web.set_defaults(func=_web)

    sub.add_parser("jobs", help="run the job scheduler").set_defaults(func=_jobs)
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
