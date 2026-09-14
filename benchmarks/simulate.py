"""PRD §8: random vs. optimized team assignment over simulated games.

    uv run python benchmarks/simulate.py                 # 50,000 games, seed 42
    uv run python benchmarks/simulate.py --elo-sd 150    # a tighter skill spread

Writes benchmarks/results/simulation.json. Needs no database.
"""

import argparse
import platform
import time

from _bench import write_result

from balancequeue.simulation import run


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--games", type=int, default=50_000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--elo-mean", type=float, default=1500)
    parser.add_argument("--elo-sd", type=float, default=300)
    parser.add_argument("--name", default="simulation", help="results file name (without .json)")
    args = parser.parse_args()

    started = time.perf_counter()
    result = run(games=args.games, seed=args.seed, elo_mean=args.elo_mean, elo_sd=args.elo_sd)
    elapsed = time.perf_counter() - started

    r, o = result.random_assignment, result.optimized_assignment
    print(f"games={result.games} seed={result.seed} elo={result.elo_distribution}")
    print(f"{'':>10} {'mean':>9} {'median':>9} {'p95':>7} {'max':>7}")
    print(f"{'random':>10} {r.mean:>9.1f} {r.median:>9.1f} {r.p95:>7} {r.max:>7}")
    print(f"{'optimized':>10} {o.mean:>9.1f} {o.median:>9.1f} {o.p95:>7} {o.max:>7}")
    print(f"mean disparity reduction:   {result.mean_reduction:.1%}")
    print(f"median disparity reduction: {result.median_reduction:.1%}")
    print(f"balance() per lobby: p50 {result.balance_call_p50_us:.1f} us, p99 {result.balance_call_p99_us:.1f} us")

    path = write_result(
        args.name,
        {
            "command": "uv run python benchmarks/simulate.py "
            + f"--games {args.games} --seed {args.seed} --elo-mean {args.elo_mean:g} --elo-sd {args.elo_sd:g}",
            "python": platform.python_version(),
            "elapsed_seconds": round(elapsed, 2),
            **result.to_dict(),
        },
    )
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
