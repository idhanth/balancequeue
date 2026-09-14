# Contributing

Thanks for taking a look. Setup is in the [README](README.md#quick-start); the specification
is [docs/PRD.md](docs/PRD.md).

## Layout

```
src/balancequeue/
  balance.py        pure 126-partition balancer (no DB), used by the API and the simulation
  services/         matchmaking transaction, players/queue, history
  api.py            FastAPI routes; thin, no business logic
  migrations/*.sql  schema of record; models.py only mirrors it
  invariants.py     database audits shared by tests and benchmarks
  simulation.py     random vs. optimized disparity
benchmarks/         reproducible scripts, raw output in results/*.json, report.py renders the docs
tests/              pytest; needs PostgreSQL 16 (see README)
```

## Before opening a pull request

```bash
source scripts/env.sh && ./scripts/services.sh start
uv run pytest                        # CI runs the same suite against PostgreSQL 16
docker compose up --build -d && scripts/smoke.sh && docker compose down -v
```

## Benchmarks and published numbers

Only measured figures may appear in this repository.

1. Commit your change first. The scripts record the commit hash and whether the tree was clean.
2. Run the benchmark commands listed in [docs/benchmarks.md](docs/benchmarks.md).
3. Run `uv run python benchmarks/report.py` to regenerate `docs/benchmarks.md`. Never edit it by hand.
4. Update any headline figures quoted in `README.md` and `docs/PRD.md`.

`tests/test_docs.py` fails if the benchmarks page is stale, or if the README or PRD quote
figures that differ from `benchmarks/results/*.json`.

## Design rules that are easy to break

- **The simulation must call `balance.balance`**, the production function. A faster copy
  would make the simulated numbers describe different code.
- **`balance()` has no early exit.** FR-2 requires all 126 partitions to be evaluated, and
  the API reports `partitions_evaluated`.
- **Matchmaking locks go through `services/matchmaking.py:_lock_lobby`** with
  `FOR UPDATE SKIP LOCKED`. The `lock_mode="for_update"|"none"` options exist only for
  `benchmarks/concurrency.py`; routes must never pass them.
- **Every status change happens under a row lock or a guarded `UPDATE ... WHERE status = ...`.**
- **`match_players.created_at` must equal `matches.created_at`.** It is denormalized so
  player history is a single index scan (migration 002).
- **Schema changes go in a new numbered SQL file.** Never edit an applied migration;
  `benchmarks/history.py` depends on 002 being exactly the history index.
- **Errors are `AppError` subclasses** in `errors.py`, rendered as
  `{"error": CODE, "message": ..., **extra}` to match PRD §18.
