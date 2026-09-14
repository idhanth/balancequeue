import random
from itertools import combinations

import pytest
from helpers import PRD_EXAMPLE_ELOS, brute_force_min_difference

from balancequeue.balance import PARTITIONS, UNIQUE_PARTITIONS, LobbyPlayer, balance, random_split, team_elo

EVERYONE = frozenset(range(10))


def lobby(elos: list[int]) -> list[LobbyPlayer]:
    return [LobbyPlayer(player_id=i + 1, elo=elo) for i, elo in enumerate(elos)]


def ids(team) -> set[int]:
    return {player.player_id for player in team}


def test_team_elo_sums_ratings():
    assert team_elo(lobby([1200, 1350, 1600])) == 4150
    assert team_elo([]) == 0


def test_exactly_126_distinct_five_player_partitions():
    assert len(PARTITIONS) == UNIQUE_PARTITIONS == 126
    assert len({frozenset(team) for team in PARTITIONS}) == 126
    assert all(len(set(team)) == 5 and set(team) <= EVERYONE for team in PARTITIONS)


def test_no_partition_is_the_mirror_of_another():
    teams = {frozenset(team) for team in PARTITIONS}
    assert all(EVERYONE - team not in teams for team in teams)


def test_partitions_plus_mirrors_cover_all_252_subsets():
    teams = {frozenset(team) for team in PARTITIONS}
    covered = teams | {EVERYONE - team for team in teams}
    assert covered == {frozenset(subset) for subset in combinations(range(10), 5)}


def test_prd_example_lobby_reaches_the_true_minimum():
    # The PRD's example response shows a difference of 10, but this lobby splits evenly:
    # 1540 + 1510 + 1475 + 1395 + 1380 = 7300 = 14600 / 2.
    split = balance(lobby(PRD_EXAMPLE_ELOS))
    assert split.elo_difference == brute_force_min_difference(PRD_EXAMPLE_ELOS) == 0
    assert split.team_a_elo == split.team_b_elo == 7300


def test_matches_brute_force_on_2000_random_lobbies():
    rng = random.Random(7)
    for _ in range(2000):
        elos = [rng.randint(600, 2600) for _ in range(10)]
        assert balance(lobby(elos)).elo_difference == brute_force_min_difference(elos)


def test_split_is_a_complete_5v5_of_the_lobby():
    players = lobby([1000, 1100, 1200, 1300, 1400, 1500, 1600, 1700, 1800, 1900])
    split = balance(players)
    assert len(split.team_a) == len(split.team_b) == 5
    assert ids(split.team_a).isdisjoint(ids(split.team_b))
    assert ids(split.team_a) | ids(split.team_b) == ids(players)
    assert split.team_a_elo + split.team_b_elo == team_elo(players)
    assert split.elo_difference == abs(split.team_a_elo - split.team_b_elo)
    assert split.partitions_evaluated == 126


def test_result_does_not_depend_on_input_order():
    players = lobby([1540, 1320, 1777, 990, 1405, 1650, 1210, 1888, 1333, 1499])
    expected = ids(balance(players).team_a)
    rng = random.Random(11)
    for _ in range(50):
        shuffled = players[:]
        rng.shuffle(shuffled)
        assert ids(balance(shuffled).team_a) == expected


def test_ties_resolve_to_the_first_partition():
    split = balance(lobby([1500] * 10))
    assert split.elo_difference == 0
    assert ids(split.team_a) == {1, 2, 3, 4, 5}


def test_odd_total_cannot_reach_zero():
    elos = list(range(1, 11))  # total 55
    assert balance(lobby(elos)).elo_difference == 1


@pytest.mark.parametrize("size", [0, 9, 11])
def test_rejects_lobbies_that_are_not_ten_players(size):
    with pytest.raises(ValueError, match="exactly 10"):
        balance(lobby([1500] * size))


def test_rejects_duplicate_players():
    players = lobby([1500] * 9) + [LobbyPlayer(player_id=1, elo=1500)]
    with pytest.raises(ValueError, match="duplicate"):
        balance(players)


def test_random_split_is_a_valid_seeded_5v5():
    players = lobby([1000 + 50 * i for i in range(10)])
    first = random_split(players, random.Random(3))
    again = random_split(players, random.Random(3))
    assert ids(first.team_a) == ids(again.team_a)
    assert len(first.team_a) == len(first.team_b) == 5
    assert ids(first.team_a) | ids(first.team_b) == ids(players)
