# Benchmarks

Every number on this page was produced by a script in `benchmarks/`. The raw output,
including query plans and per-trial data, is in `benchmarks/results/*.json`. To change
a number here, re-run the command and copy the new result. Never edit a figure by hand.

**Environment** (recorded by the scripts, 2026-09-14 UTC): Apple M5 (10 cores),
macOS 26.5.1, Python 3.12.13, PostgreSQL 16.15 with default memory settings
(`shared_buffers` 128MB, `work_mem` 4MB, 2 parallel workers per gather). The client,
API and database all ran on the same laptop. The runs were made before the first
commit, so `git_commit` is null in the JSON files. The measured code (`src/` and
`benchmarks/`) was not changed between these runs and the initial commit. Later runs
record the commit hash.

The original PRD draft contained projected figures written before any code existed.
They were not reproduced and have been removed from `docs/PRD.md`. The measured values
on this page replace them.

---

## 1. Team balance vs. random assignment (PRD §8)

```
uv run python benchmarks/simulate.py --games 50000 --seed 42 --elo-mean 1500 --elo-sd 300
```

Each game draws 10 players with Elo ~ Normal(1500, 300), rounded. The baseline is one
uniformly random 5v5 split. The optimized split comes from `balancequeue.balance.balance`,
the same function the API calls. Disparity is `abs(team_a_elo - team_b_elo)`.

| Assignment | Mean   | Median | p95   | Max   |
|------------|-------:|-------:|------:|------:|
| Random     | 755.4  | 635.0  | 1857  | 4243  |
| Optimized  | 10.8   | 7.0    | 33    | 598   |

- **Mean disparity reduction: 98.6%** (median: 98.9%). The PRD target is at least 50%.
- `balance()` time per lobby: p50 10.4 µs, p99 16.4 µs. The PRD target is under 100 ms.
- The optimized maximum of 598 comes from lobbies with extreme outliers, where no
  5v5 split can be close.

### Conditions behind the 98.6% figure

The percentage is only meaningful with these conditions attached:

| Condition | Value |
|---|---|
| Games | 50,000, fixed seed 42 (re-running reproduces identical disparities) |
| Lobby | 10 players drawn independently for each game, not sampled from a live queue |
| Ratings | Normal(mean 1500, sd 300), rounded to integers, floored at 0 |
| Baseline | One uniformly random 5v5 split per game (random team assignment) |
| Optimized | `balance()`, the production function: all 126 partitions, minimum \|A − B\| |
| Metric | (mean random disparity − mean optimized disparity) / mean random disparity |

**Why the reduction is so large.** A random split is one draw from the 126 possible
matchups, while the balancer takes the best of all 126. With ten independently drawn
ratings, the best matchup is usually within a few Elo points (median 7.0). So almost all
of a random split's disparity can be removed.

**Not measured:** other rating distributions, lobbies pre-filtered by skill (as a real
queue might produce), and stronger baselines such as a snake draft. Each would change
the percentage. Cite 98.6% only with the conditions above.

`tests/test_simulation.py` repeats the 50,000-game run and asserts that the reduction
is at least 50%, the PRD target.

Worked example: for the PRD's sample lobby (1540, 1520, 1510, 1490, 1475, 1460, 1420,
1410, 1395, 1380), the balancer returns 7300 vs. 7300, a difference of 0. The brute-force
oracle in `tests/test_balance.py` confirms that 0 is the true minimum.

---

## 2. Concurrent matchmaking (PRD §9-10)

```
uv run python benchmarks/concurrency.py --trials 20 --seed 42
```

Each trial queues 1,000 players, which is enough for every request. It then starts 100
matchmaking transactions at the same instant: 100 threads wait on a barrier, and each
already holds its own database connection. Afterwards `balancequeue.invariants` audits
the database. The run is repeated for three locking strategies, 20 trials each, for
2,000 transactions per strategy.

| Strategy               | Matches created | Players double-assigned | Excess assignments | Median trial wall time | Median request p95 |
|------------------------|----------------:|------------------------:|-------------------:|-----------------------:|-------------------:|
| `FOR UPDATE SKIP LOCKED` (shipped) | 2000 / 2000 | **0** | 0      | 131 ms | 119 ms |
| `FOR UPDATE`           | 2000 / 2000     | 0                       | 0                  | 153 ms                 | 129 ms             |
| no lock (control)      | 2000 / 2000     | 200 (in 20 of 20 trials) | 19,800            | 180 ms                 | 165 ms             |

- **The shipped strategy produced 0 duplicate assignments across 2,000 simultaneous
  transactions.** No trial had a malformed match (anything other than 5v5) or a player
  whose status disagreed with the rosters.
- **Why the no-lock control is kept:** it shows that the test really does race. Without locks, all 100 requests in
  a trial read the same 10 players and created 100 matches from them: 10 players
  double-assigned and 990 excess assignments per trial.
- With plenty of players, plain `FOR UPDATE` is also correct. On this machine,
  `SKIP LOCKED`'s advantage is modest: 131 ms vs. 153 ms median wall time for the
  batch, because requests take the next free players instead of waiting.

`tests/test_concurrency.py` runs the same checks in CI form:

- 100 simultaneous service-level transactions.
- 100 concurrent HTTP `POST /matches` calls against a live uvicorn server.
- A scarcity case with 250 players for 100 requests.

Caveat from the scarcity case: under `SKIP LOCKED`, a request can get
`INSUFFICIENT_PLAYERS` while other in-flight transactions briefly hold the remaining
rows. The test therefore asserts that no player is lost or duplicated, not an exact
number of matches.

---

## 3. Player-history latency before and after indexing (PRD §13-14)

```
uv run python benchmarks/history.py --players 50000 --matches 500000 --requests 500 --warmup 50 --seed 42
```

**Dataset** (seeded deterministically in SQL):

- 50,000 players and 500,000 completed matches.
- **5,000,000 `match_players` rows**, about 100 matches per player.
- `match_players` takes up 643 MB including its primary-key and unique indexes.

**Method:**

- One uvicorn worker serves `GET /players/{id}/matches?limit=20`.
- A single keep-alive client sends 500 sequential requests for random players, after 50
  warm-up requests.
- The first phase uses migration 001 only. The second applies migration
  `002_player_history_index.sql` (`(player_id, created_at DESC, match_id DESC)`), runs
  `VACUUM ANALYZE` and restarts the server.

| Schema              | p50      | p95      | p99      | Mean     | Max       |
|---------------------|---------:|---------:|---------:|---------:|----------:|
| Without history index | 63.48 ms | 70.08 ms | 82.69 ms | 64.42 ms | 110.89 ms |
| With history index    | 1.22 ms  | 1.44 ms  | 1.67 ms  | 1.25 ms  | 2.10 ms   |

- **p95: 70.08 ms → 1.44 ms, a 97.9% reduction.** The PRD's target is a p95 under 50 ms.
  Without the index, the endpoint misses it at this dataset size.
- `EXPLAIN (ANALYZE, BUFFERS)` of the endpoint's exact query:
  - Without the index, a parallel sequential scan discards 1,666,633 rows per worker
    (about 5M in total) and reads 42k buffers. Execution time: 66.063 ms.
  - With it, an index scan on `idx_player_history` reads the 20 newest rows in order
    and touches 112 buffers. Execution time: 0.131 ms.
- The no-index latency depends on table size. This page does not measure how it
  scales. Pass `--matches` to test a different size.

---

## Statements these results support

- Reduced mean team Elo disparity **98.6%** vs. random assignment across **50,000**
  simulated games (Normal(1500, 300) ratings), by exhaustively evaluating all **126**
  unique 5v5 partitions, with a p99 balancing time of **16 µs**.
- **0 duplicate player assignments** across **2,000** matchmaking transactions
  (20 × **100** simultaneous) using PostgreSQL `FOR UPDATE SKIP LOCKED`. The same
  harness without row locks double-assigned players in 20 of 20 trials.
- Cut player-history p95 latency from **70.08 ms to 1.44 ms (−97.9%)** on
  **5M** `match_players` rows with a composite `(player_id, created_at DESC, match_id DESC)`
  index, verified with `EXPLAIN ANALYZE`.
