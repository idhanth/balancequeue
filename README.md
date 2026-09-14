# BalanceQueue

BalanceQueue is a matchmaking backend for 5v5 games. It takes the 10 longest-waiting
players and evaluates all 126 unique 5v5 splits of their Elo ratings. It then creates
the most balanced match inside one PostgreSQL transaction. Concurrent requests can
never assign the same player twice.

Python 3.12 · FastAPI · SQLAlchemy 2 · PostgreSQL 16 · pytest. The specification is in
[docs/PRD.md](docs/PRD.md).

## Results

All figures come from reproducible scripts. The commands, method and raw JSON are in
[docs/benchmarks.md](docs/benchmarks.md).

| What | Result |
|------|--------|
| Mean team Elo disparity vs. random assignment, 50,000 simulated games (Normal(1500, 300) ratings; [conditions](docs/benchmarks.md#conditions-behind-the-986-figure)) | **−98.6%** (755.4 → 10.8) |
| Duplicate player assignments, 20 trials × 100 simultaneous transactions | **0** (without locks: 20 of 20 trials had duplicates) |
| `GET /players/{id}/matches` p95, 5M history rows, before → after index | **70.08 ms → 1.44 ms** (−97.9%) |
| Balancer time per lobby (p99) | **16.4 µs** |

## Quick start

**Option A: Docker.** `docker compose up --build` starts PostgreSQL 16 and the API on
http://127.0.0.1:8010 (interactive docs at `/docs`). Migrations run on startup. The
compose credentials are for local development only.

**Option B: local, no Docker.** Requires [uv](https://docs.astral.sh/uv/) and the
PostgreSQL 16 server binaries (`initdb`, `pg_ctl`, `psql`). `scripts/env.sh` looks
for them in `$BQ_PG_BIN`, then on `PATH`, then in any micromamba env. One way to get
them without admin rights is `micromamba create -n balancequeue -c conda-forge postgresql=16`.

```bash
git clone <repo-url> balancequeue && cd balancequeue
source scripts/env.sh                       # export BQ_PGPORT=5440 first if 5434 is taken
./scripts/services.sh start                 # initdb + PostgreSQL on 127.0.0.1:5434, creates dev and test DBs
uv sync
uv run python -m balancequeue.migrate       # apply migrations to the dev database
uv run pytest                               # 43 tests (the suite migrates its own test database)
uv run balancequeue                         # API on http://127.0.0.1:8010
./scripts/services.sh stop                  # when done
```

### Example

Queue ten players rated 1540, 1520, 1510, 1490, 1475, 1460, 1420, 1410, 1395 and 1380,
then call `POST /matches`. This is the real response, abridged:

```json
{
  "match_id": 1,
  "status": "ACTIVE",
  "team_a": [
    {"player_id": 1, "elo": 1540},
    {"player_id": 3, "elo": 1510},
    {"player_id": 5, "elo": 1475},
    {"player_id": 9, "elo": 1395},
    {"player_id": 10, "elo": 1380}
  ],
  "team_b": [
    {"player_id": 2, "elo": 1520},
    {"player_id": 4, "elo": 1490},
    {"player_id": 6, "elo": 1460},
    {"player_id": 7, "elo": 1420},
    {"player_id": 8, "elo": 1410}
  ],
  "team_a_elo": 7300,
  "team_b_elo": 7300,
  "elo_difference": 0,
  "partitions_evaluated": 126
}
```

The ratings total 14,600, and this split is exactly 7300 vs. 7300.

## API

| Method & path | Purpose | Errors |
|---|---|---|
| `POST /players` `{"username", "elo"?}` | Create a player (Elo defaults to 1000) | 409 `USERNAME_TAKEN` |
| `GET /players/{id}` | Get a player | 404 |
| `POST /queue` `{"player_id"}` | Join the matchmaking queue | 404, 409 `PLAYER_ALREADY_QUEUED` / `PLAYER_IN_MATCH` |
| `DELETE /queue/{id}` | Leave the queue | 404, 409 `PLAYER_NOT_QUEUED` / `PLAYER_IN_MATCH` |
| `POST /matches` | Match the 10 longest-waiting players | 409 `INSUFFICIENT_PLAYERS` with `available_players` |
| `GET /matches/{id}` | Get teams, totals, difference and result | 404 |
| `POST /matches/{id}/result` `{"winner_team": "A"\|"B"}` | Record the winner and return players to IDLE | 404, 409 `MATCH_NOT_ACTIVE` |
| `GET /players/{id}/matches?limit=20&offset=0` | Player history, newest first | 404 |

Errors use the PRD's flat format: `{"error": "INSUFFICIENT_PLAYERS", "message": "...", "available_players": 8}`.

## How it works

**Balancing** ([balance.py](src/balancequeue/balance.py)). Of the C(10,5) = 252
five-player subsets, each split appears twice, once from each team's side. Pinning player 0
to Team A leaves C(9,4) = 126 unique splits. All 126 are scored as `|2·A − total|`,
with no early exit. Ties go to the first split in order, so results are deterministic.
The same function serves the API and the simulation.

**Matchmaking transaction** ([services/matchmaking.py](src/balancequeue/services/matchmaking.py)):

```
BEGIN
  SELECT id, elo FROM players WHERE status = 'AVAILABLE'
    ORDER BY queued_at, id LIMIT 10 FOR UPDATE SKIP LOCKED
  balance -> INSERT matches -> INSERT 10 match_players -> UPDATE players SET status = 'IN_MATCH'
COMMIT            -- any failure rolls back and releases the row locks
```

**Player history.** `match_players.created_at` is copied from the match row. This lets
history come straight from one index, `(player_id, created_at DESC, match_id DESC)`,
with no scan and no sort ([migration 002](src/balancequeue/migrations/002_player_history_index.sql)).

**Correctness checks.** [invariants.py](src/balancequeue/invariants.py) audits:

- every player is in at most one active match
- every match is exactly 5v5
- stored team totals match the rosters
- player statuses agree with the rosters

The tests and the concurrency benchmark share these checks.

## Deviations from the PRD

- **Player states:** `IDLE`, `AVAILABLE` (queued) and `IN_MATCH`. New players start
  `IDLE`; the PRD's default of `AVAILABLE` would put every new player straight into the queue.
- **Matches have a status (`ACTIVE`/`COMPLETED`)** and a `POST /matches/{id}/result`
  endpoint. FR-5 needs a definition of "active match", and history needs a winner.
- **`match_players.created_at` is denormalized** so history can use one index (the
  PRD §14 "potential denormalized design").
- **The schema is stricter:** check constraints for statuses, a 5v5-consistent
  difference, winner if and only if completed, and `queued_at` if and only if
  `AVAILABLE`. Timestamps are `TIMESTAMPTZ`.
- **The corrected example split is 7300 vs. 7300.** The original PRD draft's example
  showed a 10-point difference for a lobby that splits evenly. `docs/PRD.md` now shows
  the real output, and `tests/test_balance.py` pins the minimum of 0.
- **Pagination is `limit`/`offset` only**, with no cursor. Elo updates after a match are
  left to V2, as the PRD's scope allows.

## Layout

```
src/balancequeue/     balance.py · services/ · api.py · migrations/*.sql · invariants.py · simulation.py
benchmarks/           simulate.py · concurrency.py · history.py · results/*.json
tests/                balance · simulation · api · transactions · concurrency
scripts/              env.sh · services.sh (local Postgres without Docker)
```
