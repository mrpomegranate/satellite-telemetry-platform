"""Runtime configuration from the environment."""
import os


def database_url() -> str:
    return os.environ.get(
        "DATABASE_URL", "postgresql://telemetry:telemetry@localhost:5432/esa"
    )


def cors_origins() -> list[str]:
    raw = os.environ.get("CORS_ORIGINS", "http://localhost:5173")
    return [o.strip() for o in raw.split(",") if o.strip()]


def max_points() -> int:
    return int(os.environ.get("MAX_POINTS", "2000"))
