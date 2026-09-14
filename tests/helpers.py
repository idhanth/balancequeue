from itertools import combinations

from sqlalchemy import Engine, text

# The lobby from the PRD §6 example response.
PRD_EXAMPLE_ELOS = [1540, 1520, 1510, 1490, 1475, 1460, 1420, 1410, 1395, 1380]


def queue_players(engine: Engine, elos: list[int]) -> list[int]:
    """Insert AVAILABLE players queued one millisecond apart, in list order. Returns ids in that order."""
    with engine.begin() as conn:
        ids = conn.execute(
            text(
                """
                INSERT INTO players (username, elo, status, queued_at)
                SELECT 'player-' || gen_random_uuid(), elo, 'AVAILABLE', now() + n * interval '1 millisecond'
                FROM unnest(CAST(:elos AS integer[])) WITH ORDINALITY AS t(elo, n)
                ORDER BY n
                RETURNING id
                """
            ),
            {"elos": elos},
        ).scalars()
        return sorted(ids)


def brute_force_min_difference(elos: list[int]) -> int:
    """Independent oracle: try all 252 five-player subsets, mirrors included."""
    total = sum(elos)
    return min(abs(2 * sum(elos[i] for i in team) - total) for team in combinations(range(len(elos)), 5))
