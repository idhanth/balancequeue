# Product Requirements Document

> **Figures in this document are measured results.** Every benchmark number below comes from
> a reproducible script in `benchmarks/`; the conditions, methodology and raw data are in
> [benchmarks.md](benchmarks.md). Figures projected in the original draft were not reproduced
> and have been removed. Targets (such as "at least 50%" and "p95 < 50 ms") are unchanged.

## 1. Product Name

**BalanceQueue**

A backend service that takes a group of 10 players, evaluates every possible 5v5 split using player Elo ratings, and produces the most competitively balanced matchup while safely supporting concurrent requests and fast player-history retrieval.

---

## 2. Problem Statement

Competitive games often suffer from uneven teams when players have different skill levels.

A simple random shuffle can create games where one team is significantly stronger than the other, leading to:

* one-sided matches,
* worse player experience,
* lower replay rates,
* complaints about unfair matchmaking,
* difficulty evaluating matchmaking quality.

The service also needs to handle multiple matchmaking requests happening simultaneously without accidentally assigning the same player to multiple games.

Finally, player statistics and matchmaking history must remain fast to retrieve as the dataset grows.

---

## 3. Product Goal

Build a matchmaking backend that:

1. Creates the fairest possible 5v5 teams from a pool of 10 players.
2. Prevents a player from being assigned to multiple matches during concurrent requests.
3. Stores match and player history in PostgreSQL.
4. Exposes APIs for matchmaking and player-history retrieval.
5. Maintains low API latency as historical data grows.
6. Provides measurable improvements over random team assignment.

---

## 4. Success Metrics

### Team Balance

Primary metric:

**Team-strength disparity**

Defined as:

```text
disparity = abs(teamA_total_elo - teamB_total_elo)
```

Target:

* Reduce average team-strength disparity by at least **50% versus random assignment**.

Measured ([benchmarks.md](benchmarks.md) §1):

* **98.6% reduction in mean disparity across 50,000 simulated games** (10 players per game with Elo drawn from Normal(1500, 300); baseline is one uniformly random 5v5 split).

---

### Matchmaking Correctness

Target:

```text
0 duplicate player assignments
```

when multiple matchmaking requests execute concurrently.

Concurrency benchmark:

* 100 simultaneous requests.
* No player should appear in more than one active match.

Measured ([benchmarks.md](benchmarks.md) §2):

* **0 duplicate assignments** across 20 trials × 100 simultaneous transactions (2,000 total).
* The same harness with row locking removed double-assigned players in 20 of 20 trials,
  which shows the test genuinely produces races.

---

### Player History Performance

Primary metric:

```text
p95 response latency
```

Target:

```text
< 50 ms
```

Measured ([benchmarks.md](benchmarks.md) §3), 5,000,000 `match_players` rows:

```text
Without history index: p95 70.08 ms
With history index:    p95 1.44 ms
```

Improvement:

```text
97.9%
```

---

## 5. Target Users

### Players

Players want:

* fair teams,
* quick matchmaking,
* accurate game histories,
* reliable skill ratings.

### Game Administrators

Administrators want:

* consistent team-balancing behavior,
* player and match history,
* performance visibility,
* reliable matchmaking under load.

### Developers

Developers need:

* predictable APIs,
* concurrency-safe player assignment,
* efficient database access,
* clear matchmaking logic.

---

# 6. Core User Flow

## Matchmaking Flow

A client sends a matchmaking request.

```text
POST /matches
```

The backend:

```text
1. Finds 10 available players
2. Locks those player records
3. Calculates possible 5v5 partitions
4. Evaluates Elo difference for each partition
5. Selects the most balanced partition
6. Creates the match
7. Assigns players to Team A or Team B
8. Marks players as unavailable
9. Commits transaction
10. Returns match details
```

Example response (real output for this lobby, abridged). The ten ratings total 14,600, and
1540 + 1510 + 1475 + 1395 + 1380 = 7300, so the lobby splits evenly and the balancer
returns a difference of 0. The original draft's example showed a non-optimal 10-point split.

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

---

# 7. Team-Balancing Algorithm

Given exactly 10 players, the system must split them into two teams of five.

The number of ways to choose five players is:

```text
C(10,5) = 252
```

However, selecting Team A automatically determines Team B.

For example:

```text
Team A = {1,2,3,4,5}
Team B = {6,7,8,9,10}
```

is the same matchup as:

```text
Team A = {6,7,8,9,10}
Team B = {1,2,3,4,5}
```

Therefore only:

```text
252 / 2 = 126
```

unique partitions need to be evaluated.

---

## Algorithm

For every unique 5v5 split:

```text
team_a_elo = sum(player.elo for player in team_a)

team_b_elo = sum(player.elo for player in team_b)

difference = abs(team_a_elo - team_b_elo)
```

Track the partition with the smallest difference.

Pseudo-code:

```python
best_difference = infinity
best_match = None

for team_a in unique_5_player_combinations(players):

    team_b = players - team_a

    team_a_elo = sum_elo(team_a)
    team_b_elo = sum_elo(team_b)

    difference = abs(team_a_elo - team_b_elo)

    if difference < best_difference:
        best_difference = difference
        best_match = (team_a, team_b)
```

Because only 126 combinations are evaluated, exhaustive search is practical and guarantees the best Elo-balanced partition for a 10-player lobby.

---

# 8. Simulation / Validation

A simulation framework should compare:

```text
Random Team Assignment
vs.
Optimized Elo Assignment
```

For each simulated game:

1. Generate or sample 10 players.
2. Create one random 5v5 assignment.
3. Calculate random-team Elo disparity.
4. Run optimized matchmaking.
5. Calculate optimized Elo disparity.
6. Record both values.

Run:

```text
50,000 simulated games
```

Calculate:

```text
average_random_disparity
average_optimized_disparity
```

Improvement:

```text
reduction =
(random_disparity - optimized_disparity)
/
random_disparity
```

Measured benchmark (Normal(1500, 300) ratings, seed 42; conditions in [benchmarks.md](benchmarks.md) §1):

```text
98.6% lower mean team-strength disparity (755.4 → 10.8 Elo)
```

---

# 9. Concurrent Matchmaking

## Problem

Two matchmaking requests may execute at the same time.

Without concurrency controls:

```text
Request A reads Player 42 as available.

Request B reads Player 42 as available.

Request A assigns Player 42.

Request B also assigns Player 42.
```

Player 42 is now assigned to two games.

This is a race condition.

---

## Solution

Use PostgreSQL row-level locking:

```sql
SELECT id, elo
FROM players
WHERE status = 'AVAILABLE'
ORDER BY queued_at
LIMIT 10
FOR UPDATE SKIP LOCKED;
```

### Why `FOR UPDATE`

Locks the selected rows until the transaction finishes.

Other transactions cannot modify or acquire the same rows.

### Why `SKIP LOCKED`

Instead of waiting for locked players, another matchmaking request skips them and looks for other available players.

Example:

```text
Request A locks Players 1–10.

Request B starts concurrently.

Players 1–10 are already locked.

SKIP LOCKED causes Request B to select Players 11–20.
```

---

## Transaction Flow

```text
BEGIN

SELECT 10 available players
FOR UPDATE SKIP LOCKED

↓

Verify 10 players exist

↓

Run balancing algorithm

↓

INSERT match

↓

INSERT team assignments

↓

UPDATE player states

↓

COMMIT
```

If an operation fails:

```text
ROLLBACK
```

The players become available again.

---

# 10. Concurrency Testing

Create a stress test that launches:

```text
100 concurrent matchmaking requests
```

Verify:

```text
each player_id appears in at most one active match
```

Example assertion:

```python
assert len(player_ids) == len(set(player_ids))
```

Target:

```text
0 duplicate assignments
```

---

# 11. Database Schema

## Players

```sql
CREATE TABLE players (
    id BIGSERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    elo INTEGER NOT NULL DEFAULT 1000,
    status VARCHAR(20) NOT NULL DEFAULT 'AVAILABLE',
    queued_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);
```

---

## Matches

```sql
CREATE TABLE matches (
    id BIGSERIAL PRIMARY KEY,
    team_a_elo INTEGER NOT NULL,
    team_b_elo INTEGER NOT NULL,
    elo_difference INTEGER NOT NULL,
    winner_team VARCHAR(1),
    created_at TIMESTAMP DEFAULT NOW()
);
```

---

## Match Players

```sql
CREATE TABLE match_players (
    id BIGSERIAL PRIMARY KEY,
    match_id BIGINT REFERENCES matches(id),
    player_id BIGINT REFERENCES players(id),
    team VARCHAR(1) NOT NULL,
    elo_at_match INTEGER NOT NULL
);
```

---

# 12. Player History API

Endpoint:

```text
GET /players/{player_id}/matches
```

Example:

```text
GET /players/128/matches?limit=20&offset=0
```

Response:

```json
{
  "player_id": 128,
  "matches": [
    {
      "match_id": 9021,
      "team": "A",
      "elo_at_match": 1514,
      "winner": true,
      "played_at": "2026-09-13T19:20:11Z"
    }
  ]
}
```

---

# 13. Player History Performance Problem

As `match_players` grows, querying:

```sql
SELECT ...
FROM match_players
JOIN matches
ON matches.id = match_players.match_id
WHERE player_id = ?
ORDER BY matches.created_at DESC;
```

may require scanning a large number of database rows.

Measured without the history index (5,000,000 `match_players` rows):

```text
p95 = 70.08 ms
```

---

# 14. Database Optimization

Add a composite index covering the player-history access pattern.

Example:

```sql
CREATE INDEX idx_match_players_player_match
ON match_players(player_id, match_id);
```

Depending on the final schema, an additional index may be used for chronological lookup:

```sql
CREATE INDEX idx_matches_created
ON matches(created_at DESC);
```

Potential denormalized design:

```sql
CREATE INDEX idx_player_history
ON match_players(player_id, created_at DESC);
```

if `created_at` is stored directly in the association table.

Implemented as migration 002: `match_players(player_id, created_at DESC, match_id DESC)`.

Measured after index optimization:

```text
p95 latency:

70.08 ms → 1.44 ms
```

Improvement:

```text
97.9%
```

---

# 15. API Requirements

## Add Player to Queue

```text
POST /queue
```

Request:

```json
{
  "player_id": 128
}
```

---

## Remove Player From Queue

```text
DELETE /queue/{player_id}
```

---

## Create Match

```text
POST /matches
```

Response includes:

```text
match_id
team_a
team_b
team Elo totals
Elo difference
```

---

## Get Match

```text
GET /matches/{match_id}
```

---

## Get Player

```text
GET /players/{player_id}
```

---

## Get Player History

```text
GET /players/{player_id}/matches
```

Supports:

```text
limit
offset
```

or cursor-based pagination.

---

# 16. Functional Requirements

### FR-1

The system must select exactly 10 available players before creating a 5v5 match.

### FR-2

The system must evaluate all 126 unique 5v5 Elo partitions.

### FR-3

The system must select the partition with the smallest absolute Elo difference.

### FR-4

The system must create the match and player assignments atomically.

### FR-5

A player must not be assigned to multiple active matches.

### FR-6

Concurrent matchmaking requests must use database-level row locking.

### FR-7

Player history must support pagination.

### FR-8

Matchmaking must store the player's Elo at the time of the match.

### FR-9

The system must store the resulting team-level Elo totals and disparity.

---

# 17. Non-Functional Requirements

### Performance

Matchmaking computation:

```text
< 100 ms
```

under normal application load.

Player-history API:

```text
p95 < 50 ms
```

---

### Reliability

No partially created matches.

All matchmaking operations must execute inside a database transaction.

---

### Consistency

Player assignments must remain strongly consistent.

Database state is the source of truth.

---

### Scalability

The application should support:

```text
100+ concurrent matchmaking requests
```

without duplicate player assignment.

---

# 18. Error Cases

### Fewer Than 10 Players

Return:

```http
409 Conflict
```

Example:

```json
{
  "error": "INSUFFICIENT_PLAYERS",
  "available_players": 8
}
```

---

### Player Already Queued

Return:

```http
409 Conflict
```

---

### Invalid Player

Return:

```http
404 Not Found
```

---

### Database Failure

Rollback the transaction.

No players should remain partially assigned.

---

# 19. Testing Strategy

## Unit Tests

Test:

* Elo summation
* combination generation
* team partition uniqueness
* minimum-disparity selection
* player-history serialization
* validation logic

---

## Algorithm Tests

Known input:

```text
10 fixed Elo ratings
```

Verify that the algorithm returns the mathematically minimum difference.

---

## Simulation Tests

Run:

```text
50,000 games
```

Compare optimized balancing against random balancing.

Track:

```text
mean disparity
median disparity
p95 disparity
percentage improvement
```

---

## Concurrency Tests

Run:

```text
100 simultaneous requests
```

Verify:

```text
no duplicate player assignments
no corrupted matches
no partially committed matches
```

---

## Performance Tests

Seed the database with a large number of historical records.

Benchmark:

```text
GET /players/:id/matches
```

Measure:

```text
p50
p95
p99
```

Compare query performance before and after index creation.

---

# 20. Technical Architecture

```text
Client
   |
   v
REST API
   |
   v
Matchmaking Service
   |
   +-------- Team Balancing Engine
   |
   +-------- Match Service
   |
   +-------- Player History Service
   |
   v
PostgreSQL
```

Suggested implementation:

```text
Backend: Python + FastAPI
Database: PostgreSQL
ORM: SQLAlchemy
Testing: pytest
Load testing: Locust or custom asyncio tests
Deployment: Docker
```

Equivalent Node.js/Express or Java/Spring implementations would also work.

---

# 21. MVP Scope

The first release includes:

* player creation,
* matchmaking queue,
* Elo-based balancing,
* exhaustive 126-partition search,
* match creation,
* concurrency-safe assignment,
* player match history,
* PostgreSQL persistence,
* benchmark tests,
* simulation tests.

The MVP does not require:

* authentication,
* payments,
* chat,
* ranked seasons,
* frontend game client,
* advanced anti-cheat,
* ML-based matchmaking.

---

# 22. Future Improvements

Possible V2 features:

### Role-aware matchmaking

Support positions such as:

```text
Tank
Support
DPS
```

while preserving team balance.

### Multi-variable balancing

Optimize using:

```text
Elo
win rate
experience
role
recent performance
latency
```

### Queue-Wait Tradeoff

Allow balance constraints to gradually loosen as players wait longer.

Example:

```text
0–30 sec:
maximum difference 50 Elo

30–60 sec:
maximum difference 100 Elo

60+ sec:
maximum difference 200 Elo
```

### Elo Updates

Update ratings automatically after each game.

### Matchmaking Analytics

Dashboard showing:

```text
average Elo disparity
queue duration
match creation rate
player-history latency
concurrent request volume
```

---

# 23. Resume-Level Engineering Outcomes

Bullets supported by the measured results in [benchmarks.md](benchmarks.md):

* **Reduced mean team Elo disparity 98.6% versus random assignment across 50,000 simulated 5v5 games by exhaustively evaluating all 126 unique team partitions (p99 balancing time 16 µs per lobby).**
* **Achieved 0 duplicate player assignments across 2,000 matchmaking transactions (20 trials × 100 simultaneous) using PostgreSQL `FOR UPDATE SKIP LOCKED` and atomic match creation; the identical harness without row locks double-assigned players in 20 of 20 trials.**
* **Cut player-history API p95 latency 97.9%, from 70.08 ms to 1.44 ms, on 5M match-history rows by replacing a parallel sequential scan with a composite `(player_id, created_at DESC, match_id DESC)` index, verified with `EXPLAIN ANALYZE`.**

The important requirement is that each figure must come from an actual reproducible benchmark or test in the repository.
