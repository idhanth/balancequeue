import os
import threading
import time
from collections.abc import Iterator

import pytest
import uvicorn
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from balancequeue.api import create_app
from balancequeue.db import make_engine, make_sessionmaker
from balancequeue.migrate import migrate, reset

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://127.0.0.1:5434/balancequeue_test")


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    # Sized so 100 matchmaking transactions can each hold their own connection.
    engine = make_engine(TEST_DATABASE_URL, pool_size=10, max_overflow=140)
    reset(engine)
    migrate(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db(engine: Engine) -> sessionmaker[Session]:
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE match_players, matches, players RESTART IDENTITY"))
    return make_sessionmaker(engine)


@pytest.fixture
def client(db: sessionmaker[Session]) -> Iterator[TestClient]:
    with TestClient(create_app(db)) as test_client:
        yield test_client


@pytest.fixture
def live_server(db: sessionmaker[Session]) -> Iterator[str]:
    """A real uvicorn server on a free port, for tests that need true concurrent HTTP."""
    server = uvicorn.Server(uvicorn.Config(create_app(db), host="127.0.0.1", port=0, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("uvicorn did not start")
        time.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)
