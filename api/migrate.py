"""Apply this repo's migrations (010+) via psql.

telemetry-db's migrations must already be applied: 010_app.sql references
catalog.satellite and catalog.channel.
"""
import pathlib
import subprocess
import sys

from .config import database_url

MIGRATIONS_DIR = pathlib.Path(__file__).resolve().parents[1] / "migrations"


def main() -> None:
    dsn = database_url()
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        print(f"no .sql files in {MIGRATIONS_DIR}")
        return
    for path in files:
        print(f"apply {path.name}")
        result = subprocess.run(
            ["psql", dsn, "-v", "ON_ERROR_STOP=1", "-q", "-f", str(path)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            sys.stderr.write(result.stdout)
            sys.stderr.write(result.stderr)
            raise SystemExit(f"failed: {path.name}")
    print("done")


if __name__ == "__main__":
    main()
