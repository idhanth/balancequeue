"""FR-5 / FR-6 under real contention: 100 matchmaking transactions at once (PRD §10)."""

import asyncio
import random
import threading
from concurrent.futures import ThreadPoolExecutor

import httpx
from helpers import queue_players
from sqlalchemy import text

from balancequeue.errors import InsufficientPlayers
from balancequeue.invariants import check_assignments
from balancequeue.services import matchmaking

CONCURRENT_REQUESTS = 100


def random_elos(n: int, seed: int) -> list[int]:
    rng = random.Random(seed)
    return [max(0, round(rng.gauss(1500, 300))) for _ in range(n)]


def race(db, attempts: int) -> list[matchmaking.CreatedMatch | None]:
    """Start `attempts` matchmaking transactions at the same instant, one connection each."""
    barrier = threading.Barrier(attempts)

    def attempt(_: int) -> matchmaking.CreatedMatch | None:
        with db() as session:
            session.connection()  # check out a connection before the start line
            barrier.wait()
            try:
                return matchmaking.create_match(session)
            except InsufficientPlayers:
                return None

    with ThreadPoolExecutor(max_workers=attempts) as pool:
        return list(pool.map(attempt, range(attempts)))


def matched_player_ids(created: list[matchmaking.CreatedMatch]) -> list[int]:
    return [p.player_id for match in created for p in match.split.team_a + match.split.team_b]


def test_100_simultaneous_transactions_never_double_assign(db, engine):
    queue_players(engine, random_elos(1000, seed=1))

    created = [result for result in race(db, CONCURRENT_REQUESTS) if result is not None]

    # 1000 players cover every request, and SKIP LOCKED means no request waits or fails.
    assert len(created) == CONCURRENT_REQUESTS
    player_ids = matched_player_ids(created)
    assert len(player_ids) == len(set(player_ids)) == 1000  # the PRD §10 assertion

    with engine.connect() as conn:
        report = check_assignments(conn)
    assert report.ok, report
    assert report.active_matches == CONCURRENT_REQUESTS
    assert report.assigned_players == 1000


def test_scarce_players_fail_cleanly_instead_of_double_assigning(db, engine):
    queue_players(engine, random_elos(250, seed=2))

    results = race(db, CONCURRENT_REQUESTS)
    created = [result for result in results if result is not None]

    with engine.connect() as conn:
        report = check_assignments(conn)
        available = conn.execute(text("SELECT count(*) FROM players WHERE status = 'AVAILABLE'")).scalar_one()
    assert report.ok, report
    assert 1 <= len(created) <= 25
    # Every player is either in exactly one match or still waiting; none are lost.
    assert len(created) * 10 + available == 250
    player_ids = matched_player_ids(created)
    assert len(player_ids) == len(set(player_ids))


def test_100_concurrent_http_requests_never_double_assign(live_server, engine):
    queue_players(engine, random_elos(1000, seed=3))

    async def fire() -> list[httpx.Response]:
        limits = httpx.Limits(max_connections=CONCURRENT_REQUESTS)
        async with httpx.AsyncClient(base_url=live_server, limits=limits, timeout=60) as http:
            return await asyncio.gather(*(http.post("/matches") for _ in range(CONCURRENT_REQUESTS)))

    responses = asyncio.run(fire())

    assert [r.status_code for r in responses].count(201) == CONCURRENT_REQUESTS
    player_ids = [m["player_id"] for r in responses for team in ("team_a", "team_b") for m in r.json()[team]]
    assert len(player_ids) == len(set(player_ids)) == 1000
    with engine.connect() as conn:
        assert check_assignments(conn).ok
