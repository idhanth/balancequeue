"""PRD §13-14: GET /players/{id}/matches latency before and after the history index.

    uv run python benchmarks/history.py
    uv run python benchmarks/history.py --players 50000 --matches 500000 --requests 500

1. Build balancequeue_bench_history with migration 001 only (no history index) and seed
   it deterministically: `--matches` completed matches x 10 match_players rows each.
2. Serve the real app with uvicorn and time sequential requests from one keep-alive
   client for random players (limit=20, offset=0). Record p50/p95/p99 and EXPLAIN ANALYZE.
3. Apply migration 002 (exactly the shipped index), ANALYZE, restart the server, repeat.

Writes benchmarks/results/history.json.
"""

import argparse
import os
import random
import statistics
import subprocess
import sys
import time

import httpx
from _bench import environment, fresh_database, write_result
from sqlalchemy import create_engine, text
from sqlalchemy.dialects import postgresql

from balancequeue.migrate import migrate
from balancequeue.services.history import history_query
from balancequeue.simulation import percentile

DATABASE = "balancequeue_bench_history"
PORT = 8011


def seed(engine, players: int, matches: int) -> dict:
    started = time.perf_counter()
    with engine.begin() as conn:
        conn.execute(text("SELECT setseed(0.42)"))
        conn.execute(
            text(
                """
                INSERT INTO players (username, elo, status, created_at)
                SELECT 'bench-' || g,
                       greatest(0, round(1500 + 300 * sqrt(-2 * ln(1 - random())) * cos(2 * pi() * random())))::int,
                       'IDLE', timestamptz '2025-01-01 00:00:00+00'
                FROM generate_series(1, :players) AS g
                """
            ),
            {"players": players},
        )
        # One match per minute; totals are filled in from the rosters below.
        conn.execute(
            text(
                """
                INSERT INTO matches (id, status, team_a_elo, team_b_elo, elo_difference, winner_team, created_at, completed_at)
                SELECT g, 'COMPLETED', 0, 0, 0,
                       CASE WHEN random() < 0.5 THEN 'A' ELSE 'B' END,
                       timestamptz '2025-09-13 00:00:00+00' + g * interval '1 minute',
                       timestamptz '2025-09-13 00:00:00+00' + g * interval '1 minute' + interval '35 minutes'
                FROM generate_series(1, :matches) AS g
                """
            ),
            {"matches": matches},
        )
        conn.execute(text("SELECT setval('matches_id_seq', :matches)"), {"matches": matches})
        # Ten distinct players per match: 7919 is coprime with the player count so every
        # player recurs about equally often, and slot * 4729 keeps the ten slots distinct.
        conn.execute(
            text(
                """
                INSERT INTO match_players (match_id, player_id, team, elo_at_match, created_at)
                SELECT m.id, p.id, CASE WHEN s.slot < 5 THEN 'A' ELSE 'B' END, p.elo, m.created_at
                FROM matches m
                CROSS JOIN generate_series(0, 9) AS s(slot)
                JOIN players p ON p.id = ((m.id * 7919 + s.slot * 4729) % :players) + 1
                """
            ),
            {"players": players},
        )
        conn.execute(
            text(
                """
                UPDATE matches m
                SET team_a_elo = t.a, team_b_elo = t.b, elo_difference = abs(t.a - t.b)
                FROM (
                    SELECT match_id,
                           sum(elo_at_match) FILTER (WHERE team = 'A') AS a,
                           sum(elo_at_match) FILTER (WHERE team = 'B') AS b
                    FROM match_players GROUP BY match_id
                ) t
                WHERE t.match_id = m.id
                """
            )
        )
    vacuum_analyze(engine)
    with engine.connect() as conn:
        counts = conn.execute(
            text(
                """
                SELECT (SELECT count(*) FROM players), (SELECT count(*) FROM matches),
                       (SELECT count(*) FROM match_players),
                       pg_size_pretty(pg_total_relation_size('match_players'))
                """
            )
        ).one()
    return {
        "players": counts[0],
        "matches": counts[1],
        "match_players_rows": counts[2],
        "match_players_total_size": counts[3],
        "matches_per_player": counts[2] / counts[0],
        "seed_seconds": round(time.perf_counter() - started, 1),
    }


def vacuum_analyze(engine) -> None:
    with create_engine(engine.url, isolation_level="AUTOCOMMIT").connect() as conn:
        conn.execute(text("VACUUM ANALYZE"))


def explain(engine, player_id: int) -> str:
    sql = str(
        history_query(player_id, limit=20, offset=0).compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    with engine.connect() as conn:
        rows = conn.execute(text("EXPLAIN (ANALYZE, BUFFERS) " + sql)).scalars()
        return "\n".join(rows)


def serve(engine) -> subprocess.Popen:
    env = {**os.environ, "DATABASE_URL": engine.url.render_as_string(hide_password=False)}
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "balancequeue.api:create_app", "--factory",
         "--host", "127.0.0.1", "--port", str(PORT), "--log-level", "warning"],
        env=env,
    )
    deadline = time.monotonic() + 20
    while True:
        try:
            if httpx.get(f"http://127.0.0.1:{PORT}/health", timeout=1).status_code == 200:
                return server
        except httpx.TransportError:
            pass
        if time.monotonic() > deadline or server.poll() is not None:
            server.kill()
            raise RuntimeError("benchmark server did not start")
        time.sleep(0.1)


def measure(engine, *, players: int, requests: int, warmup: int, seed_value: int) -> dict:
    rng = random.Random(seed_value)
    server = serve(engine)
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{PORT}", timeout=30) as client:
            for _ in range(warmup):
                client.get(f"/players/{rng.randint(1, players)}/matches", params={"limit": 20}).raise_for_status()
            latencies = []
            for _ in range(requests):
                player_id = rng.randint(1, players)
                started = time.perf_counter()
                response = client.get(f"/players/{player_id}/matches", params={"limit": 20})
                latencies.append((time.perf_counter() - started) * 1000)
                response.raise_for_status()
                assert len(response.json()["matches"]) == 20
    finally:
        server.terminate()
        server.wait(timeout=10)
    latencies.sort()
    return {
        "requests": requests,
        "warmup_requests": warmup,
        "p50_ms": round(percentile(latencies, 50), 2),
        "p95_ms": round(percentile(latencies, 95), 2),
        "p99_ms": round(percentile(latencies, 99), 2),
        "mean_ms": round(statistics.fmean(latencies), 2),
        "max_ms": round(latencies[-1], 2),
        "explain_analyze": explain(engine, player_id=rng.randint(1, players)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--players", type=int, default=50_000)
    parser.add_argument("--matches", type=int, default=500_000)
    parser.add_argument("--requests", type=int, default=500)
    parser.add_argument("--warmup", type=int, default=50)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    engine = fresh_database(DATABASE, until="001_initial_schema")
    print("seeding ...", flush=True)
    dataset = seed(engine, args.players, args.matches)
    print(f"dataset: {dataset}", flush=True)

    before = measure(engine, players=args.players, requests=args.requests, warmup=args.warmup, seed_value=args.seed)
    print(f"without index: p50 {before['p50_ms']} ms  p95 {before['p95_ms']} ms  p99 {before['p99_ms']} ms", flush=True)

    migrate(engine)  # applies 002_player_history_index
    vacuum_analyze(engine)
    after = measure(engine, players=args.players, requests=args.requests, warmup=args.warmup, seed_value=args.seed)
    print(f"with index:    p50 {after['p50_ms']} ms  p95 {after['p95_ms']} ms  p99 {after['p99_ms']} ms")

    p95_reduction = (before["p95_ms"] - after["p95_ms"]) / before["p95_ms"]
    print(f"p95 reduction: {p95_reduction:.1%}")

    path = write_result(
        "history",
        {
            "command": "uv run python benchmarks/history.py "
            + f"--players {args.players} --matches {args.matches} --requests {args.requests} "
            + f"--warmup {args.warmup} --seed {args.seed}",
            "environment": environment(engine),
            "dataset": dataset,
            "method": "sequential GET /players/{id}/matches?limit=20 from one keep-alive httpx client "
            "against a single uvicorn worker on the same machine; random player per request",
            "without_index": before,
            "with_index": after,
            "p95_reduction": round(p95_reduction, 4),
        },
    )
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
