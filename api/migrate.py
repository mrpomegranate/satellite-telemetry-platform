"""Apply this repo's migrations (010+) using psycopg.

telemetry-db's migrations must already be applied: 010_app.sql references
catalog.satellite and catalog.channel.

Uses psycopg rather than shelling out to psql so no client binary is needed on
the host. Each file is sent as a single statement string; Postgres parses the
multi-statement body itself, which keeps dollar-quoted DO blocks intact.
"""
import pathlib
import sys

import psycopg

from .config import database_url

MIGRATIONS_DIR = pathlib.Path(__file__).resolve().parents[1] / "migrations"


def main() -> None:
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        print(f"no .sql files in {MIGRATIONS_DIR}")
        return

    with psycopg.connect(database_url(), autocommit=True) as conn:
        for path in files:
            print(f"apply {path.name}")
            sql = path.read_text(encoding="utf-8")
            try:
                conn.execute(sql)
            except psycopg.Error as exc:
                sys.stderr.write(f"{exc}\n")
                raise SystemExit(f"failed: {path.name}")
    print("done")


if __name__ == "__main__":
    main()