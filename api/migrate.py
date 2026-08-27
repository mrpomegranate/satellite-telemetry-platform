"""Apply this repo's migrations (010+) using psycopg.

Each file is recorded once applied, so re-running is a no-op rather than a
replay. That matters because a later migration can change what an earlier one
depends on: 013 replaces `taxonomy.label_class`, which made re-running 011 fail
before tracking existed.

Files must still be written idempotently. Tracking removes the need to replay,
it does not make a half applied file safe.

telemetry-db's migrations must already be applied: 010_app.sql references
catalog.satellite and catalog.channel.

    uv run python -m api.migrate            # apply what is outstanding
    uv run python -m api.migrate --status   # show what has been applied
    uv run python -m api.migrate --force    # re-apply everything
    uv run python -m api.migrate --baseline # record all files without running
"""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import sys

import psycopg

from .config import database_url

MIGRATIONS_DIR = pathlib.Path(__file__).resolve().parents[1] / "migrations"

# Lives in public because it must exist before any of this repo's schemas do.
TRACKING_DDL = """
CREATE TABLE IF NOT EXISTS public.platform_migration (
    filename   text PRIMARY KEY,
    checksum   text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
)
"""


def checksum(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def migration_files() -> list[pathlib.Path]:
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def applied(conn) -> dict[str, str]:
    with conn.cursor() as cur:
        cur.execute("SELECT filename, checksum FROM public.platform_migration")
        return {row[0]: row[1] for row in cur.fetchall()}


def record(conn, path: pathlib.Path) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO public.platform_migration (filename, checksum)
            VALUES (%s, %s)
            ON CONFLICT (filename) DO UPDATE SET checksum = EXCLUDED.checksum,
                                                 applied_at = now()
            """,
            (path.name, checksum(path)),
        )


def show_status(conn) -> int:
    done = applied(conn)
    files = migration_files()
    if not files:
        print(f"no .sql files in {MIGRATIONS_DIR}")
        return 1
    print()
    for path in files:
        if path.name not in done:
            print(f"  pending  {path.name}")
        elif done[path.name] != checksum(path):
            print(f"  CHANGED  {path.name}  (file edited after it was applied)")
        else:
            print(f"  applied  {path.name}")
    print()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply platform migrations.")
    parser.add_argument("--status", action="store_true",
                        help="list migrations and exit")
    parser.add_argument("--force", action="store_true",
                        help="re-apply every file, ignoring tracking")
    parser.add_argument("--baseline", action="store_true",
                        help="record all files as applied without running them")
    args = parser.parse_args()

    files = migration_files()
    if not files:
        print(f"no .sql files in {MIGRATIONS_DIR}")
        return

    with psycopg.connect(database_url(), autocommit=True) as conn:
        conn.execute(TRACKING_DDL)

        if args.status:
            sys.exit(show_status(conn))

        if args.baseline:
            for path in files:
                record(conn, path)
            print(f"recorded {len(files)} file(s) as applied without running them")
            return

        done = applied(conn)
        pending = files if args.force else [f for f in files if f.name not in done]

        if not pending:
            print(f"nothing to do, {len(done)} migration(s) already applied")
            return

        for path in pending:
            print(f"apply {path.name}")
            try:
                conn.execute(path.read_text(encoding="utf-8"))
            except psycopg.Error as exc:
                sys.stderr.write(f"{exc}\n")
                raise SystemExit(f"failed: {path.name}")
            record(conn, path)

        print(f"done, {len(pending)} applied")


if __name__ == "__main__":
    main()