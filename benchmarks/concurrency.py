"""PRD §10: 100 simultaneous matchmaking transactions, repeated, under three locking strategies.

    uv run python benchmarks/concurrency.py --trials 20

  skip_locked  the shipped strategy: SELECT ... FOR UPDATE SKIP LOCKED
  for_update   SELECT ... FOR UPDATE (blocks instead of skipping)
  none         plain SELECT, the race condition from PRD §9

Each trial queues 1,000 players (enough for all 100 requests), releases 100 threads
from a barrier at the same instant, each on its own connection, then audits the
database with balancequeue.invariants. Uses its own database, balancequeue_bench_concurrency.
Writes benchmarks/results/concurrency.json.
"""

import argparse
import random
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from _bench import environment, fresh_database, write_result
from sqlalchemy import text

from balancequeue.db import make_sessionmaker
from balancequeue.errors import InsufficientPlayers
from balancequeue.invariants import check_assignments
from balancequeue.services import matchmaking
from balancequeue.simulation import percentile

REQUESTS = 100
PLAYERS = 1000
MODES = ("skip_locked", "for_update", "none")


def queue_players(engine, rng: random.Random) -> None:
    elos = [max(0, round(rng.gauss(1500, 300))) for _ in range(PLAYERS)]
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE match_players, matches, players RESTART IDENTITY"))
        conn.execute(
            text(
                """
                INSERT INTO players (username, elo, status, queued_at)
                SELECT 'bench-' || n, elo, 'AVAILABLE', now() + n * interval '1 millisecond'
                FROM unnest(CAST(:elos AS integer[])) WITH ORDINALITY AS t(elo, n)
                """
            ),
            {"elos": elos},
        )


def trial(engine, session_factory, mode: str) -> dict:
    barrier = threading.Barrier(REQUESTS)

    def attempt(_: int) -> tuple[str, float]:
        with session_factory() as session:
            session.connection()
            barrier.wait()
            started = time.perf_counter()
            try:
                matchmaking.create_match(session, lock_mode=mode)
                outcome = "created"
            except InsufficientPlayers:
                outcome = "insufficient_players"
            except Exception as exc:  # deadlocks, serialization failures: count, don't crash the run
                outcome = f"error:{type(exc).__name__}"
            return outcome, (time.perf_counter() - started) * 1000

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=REQUESTS) as pool:
        results = list(pool.map(attempt, range(REQUESTS)))
    wall_ms = (time.perf_counter() - started) * 1000

    with engine.connect() as conn:
        report = check_assignments(conn)
        rows = conn.execute(text("SELECT count(*), count(DISTINCT player_id) FROM match_players")).one()

    outcomes: dict[str, int] = {}
    for outcome, _ in results:
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
    latencies = sorted(ms for _, ms in results)
    return {
        "outcomes": outcomes,
        "assignments": rows[0],
        "distinct_players_assigned": rows[1],
        "duplicate_players": len(report.duplicate_assignments),
        "excess_assignments": rows[0] - rows[1],
        "status_mismatches": len(report.status_mismatches),
        "malformed_matches": len(report.malformed_matches),
        "wall_ms": wall_ms,
        "request_p50_ms": percentile(latencies, 50),
        "request_p95_ms": percentile(latencies, 95),
    }


def summarize(trials: list[dict]) -> dict:
    def total(key: str) -> int:
        return sum(t[key] for t in trials)

    outcomes: dict[str, int] = {}
    for t in trials:
        for outcome, count in t["outcomes"].items():
            outcomes[outcome] = outcomes.get(outcome, 0) + count
    return {
        "trials": len(trials),
        "requests": len(trials) * REQUESTS,
        "outcomes": outcomes,
        "trials_with_duplicates": sum(1 for t in trials if t["duplicate_players"]),
        "duplicate_players_total": total("duplicate_players"),
        "excess_assignments_total": total("excess_assignments"),
        "malformed_matches_total": total("malformed_matches"),
        "median_wall_ms": statistics.median(t["wall_ms"] for t in trials),
        "median_request_p95_ms": statistics.median(t["request_p95_ms"] for t in trials),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--trials", type=int, default=20)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--modes", nargs="+", choices=MODES, default=list(MODES))
    args = parser.parse_args()

    engine = fresh_database("balancequeue_bench_concurrency", pool_size=REQUESTS, max_overflow=10)
    session_factory = make_sessionmaker(engine)
    rng = random.Random(args.seed)

    by_mode = {}
    for mode in args.modes:
        trials = []
        for _ in range(args.trials):
            queue_players(engine, rng)
            trials.append(trial(engine, session_factory, mode))
        by_mode[mode] = {"summary": summarize(trials), "trials": trials}
        s = by_mode[mode]["summary"]
        print(
            f"{mode:>12}: {s['requests']} requests, outcomes={s['outcomes']}, "
            f"duplicate players={s['duplicate_players_total']} "
            f"(in {s['trials_with_duplicates']}/{s['trials']} trials), "
            f"median wall={s['median_wall_ms']:.0f} ms"
        )

    path = write_result(
        "concurrency",
        {
            "command": f"uv run python benchmarks/concurrency.py --trials {args.trials} --seed {args.seed}",
            "environment": environment(engine),
            "setup": {"concurrent_requests": REQUESTS, "queued_players_per_trial": PLAYERS},
            "modes": by_mode,
        },
    )
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
