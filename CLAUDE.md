# BalanceQueue - working notes

Specification: `docs/PRD.md`. Measured results: `docs/benchmarks.md`.

## Layout

```
src/balancequeue/
  balance.py        pure 126-partition balancer (no DB) - used by the API AND the simulation
  services/         matchmaking (the locking transaction), players/queue, history
  api.py            FastAPI routes; thin, no business logic
  migrations/*.sql  schema of record; models.py only mirrors it
  invariants.py     DB audits shared by tests and benchmarks
  simulation.py     random vs. optimized disparity
benchmarks/         reproducible scripts; raw output in benchmarks/results/*.json
tests/              pytest; needs the local Postgres
```

## Running

```
source scripts/env.sh
./scripts/services.sh start          # Postgres 16 on :5434 (pg_ctl on PATH or BQ_PG_BIN; BQ_PGPORT to move it)
uv run pytest
uv run balancequeue                  # API on :8010
```

Benchmarks create their own databases (`balancequeue_bench_*`) and never touch dev data.

## Rules that are easy to break

- **Never quote a metric that is not in `docs/benchmarks.md`**, and never edit that file
  by hand without re-running the command it names. `docs/PRD.md` carries only measured
  figures; the original draft's projected numbers were not reproduced and must not return.
- **The simulation must call `balance.balance`**, the production function. A faster copy
  would make the simulated numbers describe different code.
- **`balance()` has no early exit.** FR-2 requires all 126 partitions be evaluated and
  the response reports `partitions_evaluated`.
- **Matchmaking locks go through `services/matchmaking.py:_lock_lobby`** with
  `FOR UPDATE SKIP LOCKED`. `lock_mode="for_update"|"none"` exist only for
  `benchmarks/concurrency.py`; routes must never pass them.
- **Every status change happens under a row lock or a guarded UPDATE** (`WHERE status = ...`).
  Queue/dequeue lock the player row; results use `UPDATE ... WHERE status = 'ACTIVE'`.
- **`match_players.created_at` must equal `matches.created_at`.** It is denormalized so
  history is one index scan (migration 002). Set it from the match's RETURNING value.
- **Add schema changes as a new numbered SQL file**; never edit an applied migration.
  `benchmarks/history.py` depends on 002 being exactly the history index.
- Errors are `AppError` subclasses in `errors.py`, rendered flat as
  `{"error": CODE, "message": ..., **extra}` to match PRD §18.
