"""Shared plumbing for the benchmark scripts: throwaway databases, environment capture, results."""

import json
import platform
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Engine, create_engine, make_url, text

from balancequeue.db import database_url, make_engine
from balancequeue.migrate import migrate, reset

RESULTS_DIR = Path(__file__).resolve().parent / "results"


def fresh_database(name: str, *, pool_size: int = 5, max_overflow: int = 0, until: str | None = None) -> Engine:
    """Create (if needed), wipe and migrate a dedicated benchmark database. Never touches the dev DB."""
    url = make_url(database_url())
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        if conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name}).first() is None:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
    admin.dispose()

    engine = make_engine(url.set(database=name).render_as_string(hide_password=False), pool_size=pool_size, max_overflow=max_overflow)
    reset(engine)
    migrate(engine, until=until)
    return engine


def environment(engine: Engine) -> dict:
    with engine.connect() as conn:
        postgres = conn.execute(text("SHOW server_version")).scalar_one()
        settings = {
            name: conn.execute(text(f"SHOW {name}")).scalar_one()
            for name in ("shared_buffers", "work_mem", "max_parallel_workers_per_gather", "max_connections")
        }
    return {
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "machine": _command(["sysctl", "-n", "machdep.cpu.brand_string"]) or platform.processor(),
        "cpu_count": _command(["sysctl", "-n", "hw.ncpu"]),
        "os": platform.platform(),
        "python": platform.python_version(),
        "postgres": postgres,
        "postgres_settings": settings,
        "git_commit": _command(["git", "rev-parse", "--short", "HEAD"]),
    }


def write_result(name: str, data: dict) -> Path:
    RESULTS_DIR.mkdir(exist_ok=True)
    path = RESULTS_DIR / f"{name}.json"
    path.write_text(json.dumps(data, indent=2, default=str) + "\n")
    return path


def _command(argv: list[str]) -> str | None:
    try:
        return subprocess.run(argv, capture_output=True, text=True, check=True).stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None
