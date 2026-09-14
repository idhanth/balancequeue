from balancequeue.simulation import percentile, run


def test_percentile_is_nearest_rank():
    values = list(range(1, 101))
    assert percentile(values, 50) == 50
    assert percentile(values, 95) == 95
    assert percentile(values, 100) == 100
    assert percentile([7], 99) == 7


def test_simulation_is_reproducible_for_a_seed():
    first, second = run(games=500, seed=1), run(games=500, seed=1)
    assert first.random_assignment == second.random_assignment
    assert first.optimized_assignment == second.optimized_assignment


def test_optimized_assignment_meets_prd_target_over_50000_games():
    result = run(games=50_000, seed=42)
    assert result.games == 50_000
    # PRD §4: at least a 50% reduction in average team-strength disparity vs. random.
    assert result.mean_reduction >= 0.50
    assert result.optimized_assignment.p95 <= result.random_assignment.p95
    # PRD §17: matchmaking computation under 100 ms.
    assert result.balance_call_p99_us < 100_000
