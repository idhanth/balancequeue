import os

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_DATABASE_URL = "postgresql+psycopg://127.0.0.1:5434/balancequeue"


def database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


def make_engine(url: str | None = None, *, pool_size: int | None = None, max_overflow: int | None = None) -> Engine:
    return create_engine(
        url or database_url(),
        pool_size=pool_size if pool_size is not None else int(os.environ.get("DB_POOL_SIZE", "20")),
        max_overflow=max_overflow if max_overflow is not None else int(os.environ.get("DB_MAX_OVERFLOW", "30")),
        pool_pre_ping=True,
    )


def make_sessionmaker(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)
