"""Shared plumbing for the benchmark scripts: throwaway databases, provenance, results."""

import json
import platform
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Engine, create_engine, make_url, text

from balancequeue.db import database_url, make_engine
from balancequeue.migrate import migrate, reset

REPO_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = REPO_ROOT / "benchmarks" / "results"


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


def environment(engine: Engine | None = None) -> dict:
    """Where and on which commit a result was measured.

    `git_dirty` ignores benchmarks/results/, which the scripts themselves write; any other
    uncommitted change means the numbers do not describe `git_commit` exactly.
    """
    env = {
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "machine": _command(["sysctl", "-n", "machdep.cpu.brand_string"]) or platform.processor(),
        "cpu_count": _command(["sysctl", "-n", "hw.ncpu"]),
        "os": platform.platform(),
        "python": platform.python_version(),
        "git_commit": _command(["git", "rev-parse", "HEAD"]),
        "git_dirty": _git_dirty(),
    }
    if engine is not None:
        with engine.connect() as conn:
            env["postgres"] = conn.execute(text("SHOW server_version")).scalar_one()
            env["postgres_settings"] = {
                name: conn.execute(text(f"SHOW {name}")).scalar_one()
                for name in ("shared_buffers", "work_mem", "max_parallel_workers_per_gather", "max_connections")
            }
    return env


def write_result(name: str, data: dict) -> Path:
    RESULTS_DIR.mkdir(exist_ok=True)
    path = RESULTS_DIR / f"{name}.json"
    path.write_text(json.dumps(data, indent=2, default=str) + "\n")
    return path


def _git_dirty() -> bool | None:
    status = _command(["git", "status", "--porcelain", "--", ".", ":(exclude)benchmarks/results"], allow_empty=True)
    return None if status is None else status != ""


def _command(argv: list[str], *, allow_empty: bool = False) -> str | None:
    try:
        out = subprocess.run(argv, capture_output=True, text=True, check=True, cwd=REPO_ROOT).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    return out if (out or allow_empty) else None
