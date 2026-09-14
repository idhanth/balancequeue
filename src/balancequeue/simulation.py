"""Random vs. optimized team assignment (PRD §8).

For each simulated game: draw 10 players, split them once at random, split them with
the production `balance` function, and record both team-strength disparities.

The Elo distribution is an explicit input because the result depends on it: disparity
is reported in Elo points, and the reduction percentage depends on the shape of the
distribution (normal vs. uniform) though not on its scale.
"""

import math
import random
import statistics
import time
from dataclasses import asdict, dataclass

from balancequeue.balance import LOBBY_SIZE, LobbyPlayer, balance, random_split


@dataclass(frozen=True)
class DisparityStats:
    mean: float
    median: float
    p95: int
    max: int

    @classmethod
    def of(cls, values: list[int]) -> "DisparityStats":
        ordered = sorted(values)
        return cls(
            mean=statistics.fmean(ordered),
            median=statistics.median(ordered),
            p95=percentile(ordered, 95),
            max=ordered[-1],
        )


@dataclass(frozen=True)
class SimulationResult:
    games: int
    seed: int
    elo_distribution: str
    random_assignment: DisparityStats
    optimized_assignment: DisparityStats
    mean_reduction: float  # (random - optimized) / random, on mean disparity
    median_reduction: float
    balance_call_p50_us: float
    balance_call_p99_us: float
    balance_call_max_us: float

    def to_dict(self) -> dict:
        return asdict(self)


def percentile(sorted_values: list, pct: float):
    """Nearest-rank percentile of an already-sorted list."""
    if not sorted_values:
        raise ValueError("percentile of an empty list")
    rank = max(1, math.ceil(pct / 100 * len(sorted_values)))
    return sorted_values[rank - 1]


def normal_lobby(rng: random.Random, mean: float, sd: float) -> list[LobbyPlayer]:
    return [LobbyPlayer(player_id=i, elo=max(0, round(rng.gauss(mean, sd)))) for i in range(1, LOBBY_SIZE + 1)]


def run(games: int = 50_000, seed: int = 42, elo_mean: float = 1500, elo_sd: float = 300) -> SimulationResult:
    rng = random.Random(seed)
    random_disparities: list[int] = []
    optimized_disparities: list[int] = []
    call_ns: list[int] = []

    for _ in range(games):
        lobby = normal_lobby(rng, elo_mean, elo_sd)
        random_disparities.append(random_split(lobby, rng).elo_difference)

        started = time.perf_counter_ns()
        optimized = balance(lobby)
        call_ns.append(time.perf_counter_ns() - started)
        optimized_disparities.append(optimized.elo_difference)

    random_stats = DisparityStats.of(random_disparities)
    optimized_stats = DisparityStats.of(optimized_disparities)
    call_ns.sort()
    return SimulationResult(
        games=games,
        seed=seed,
        elo_distribution=f"normal(mean={elo_mean:g}, sd={elo_sd:g}), rounded, floored at 0",
        random_assignment=random_stats,
        optimized_assignment=optimized_stats,
        mean_reduction=_reduction(random_stats.mean, optimized_stats.mean),
        median_reduction=_reduction(random_stats.median, optimized_stats.median),
        balance_call_p50_us=percentile(call_ns, 50) / 1000,
        balance_call_p99_us=percentile(call_ns, 99) / 1000,
        balance_call_max_us=call_ns[-1] / 1000,
    )


def _reduction(baseline: float, optimized: float) -> float:
    return (baseline - optimized) / baseline if baseline else 0.0
