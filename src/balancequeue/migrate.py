"""Plain-SQL migrations, applied in filename order and recorded in schema_migrations.

    uv run python -m balancequeue.migrate            # apply pending migrations
    uv run python -m balancequeue.migrate --reset    # drop everything first
"""

import argparse
from importlib import resources

from sqlalchemy import Engine, text

from balancequeue.db import make_engine

_MIGRATION_LOCK_KEY = 0x42515545  # "BQUE": serializes concurrent migrators


def migration_files() -> list[tuple[str, str]]:
    directory = resources.files("balancequeue").joinpath("migrations")
    files = sorted((f for f in directory.iterdir() if f.name.endswith(".sql")), key=lambda f: f.name)
    return [(f.name.removesuffix(".sql"), f.read_text()) for f in files]


def migration_sql(version: str) -> str:
    for name, sql in migration_files():
        if name == version:
            return sql
    raise KeyError(version)


def migrate(engine: Engine, *, until: str | None = None) -> list[str]:
    """Apply pending migrations, optionally stopping after version `until`."""
    applied = []
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                " version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
            )
        )
    for version, sql in migration_files():
        with engine.begin() as conn:
            conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _MIGRATION_LOCK_KEY})
            done = conn.execute(text("SELECT 1 FROM schema_migrations WHERE version = :v"), {"v": version}).first()
            if not done:
                conn.exec_driver_sql(sql)
                conn.execute(text("INSERT INTO schema_migrations (version) VALUES (:v)"), {"v": version})
                applied.append(version)
        if version == until:
            break
    return applied


def reset(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reset", action="store_true", help="drop and recreate the public schema first")
    parser.add_argument("--until", help="stop after this migration version")
    args = parser.parse_args()
    engine = make_engine(pool_size=1, max_overflow=0)
    if args.reset:
        reset(engine)
    applied = migrate(engine, until=args.until)
    print("applied: " + (", ".join(applied) if applied else "nothing pending"))


if __name__ == "__main__":
    main()
