"""Team-balancing engine (PRD §7).

Ten players split into two teams of five. There are C(10,5) = 252 five-player subsets,
but every split appears twice (a team and its complement describe the same game), so
there are 252 / 2 = 126 unique matchups. We enumerate exactly those 126 by pinning the
first player to Team A and choosing Team A's other four members from the remaining
nine: C(9,4) = 126. Pinning one player is what removes the mirror duplicates.

This module is pure: no database, no clock. The matchmaking service and the simulation
both call the same `balance` function, so the simulated numbers describe the code that
actually runs in production.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import combinations

TEAM_SIZE = 5
LOBBY_SIZE = 2 * TEAM_SIZE
UNIQUE_PARTITIONS = 126


@dataclass(frozen=True, slots=True)
class LobbyPlayer:
    player_id: int
    elo: int


@dataclass(frozen=True, slots=True)
class Split:
    team_a: tuple[LobbyPlayer, ...]
    team_b: tuple[LobbyPlayer, ...]
    partitions_evaluated: int

    @property
    def team_a_elo(self) -> int:
        return team_elo(self.team_a)

    @property
    def team_b_elo(self) -> int:
        return team_elo(self.team_b)

    @property
    def elo_difference(self) -> int:
        return abs(self.team_a_elo - self.team_b_elo)


def team_elo(team: Sequence[LobbyPlayer]) -> int:
    return sum(player.elo for player in team)


def unique_partitions() -> tuple[tuple[int, ...], ...]:
    """Team A index sets for the 126 unique 5v5 splits of indices 0-9, lexicographic."""
    return tuple((0, *rest) for rest in combinations(range(1, LOBBY_SIZE), TEAM_SIZE - 1))


PARTITIONS = unique_partitions()
if len(PARTITIONS) != UNIQUE_PARTITIONS:  # pragma: no cover - guards the constant above
    raise RuntimeError(f"expected {UNIQUE_PARTITIONS} partitions, got {len(PARTITIONS)}")


def balance(players: Sequence[LobbyPlayer]) -> Split:
    """Return the 5v5 split with the smallest absolute team Elo difference.

    All 126 partitions are scored with no early exit, so the result is the true minimum.
    Players are ordered by id first, so a lobby yields the same split whatever order the
    database returned it in; ties go to the first partition in lexicographic order.
    """
    lobby = _canonical(players)
    elos = [player.elo for player in lobby]
    total = sum(elos)

    best_index = 0
    best_difference = None
    for index, (i0, i1, i2, i3, i4) in enumerate(PARTITIONS):
        team_a_elo = elos[i0] + elos[i1] + elos[i2] + elos[i3] + elos[i4]
        # Team B is everyone else, so |A - B| = |A - (total - A)| = |2A - total|.
        difference = abs(2 * team_a_elo - total)
        if best_difference is None or difference < best_difference:
            best_difference = difference
            best_index = index

    return _split(lobby, PARTITIONS[best_index], partitions_evaluated=len(PARTITIONS))


def random_split(players: Sequence[LobbyPlayer], rng: random.Random) -> Split:
    """The baseline the PRD compares against: one uniformly random 5v5 assignment."""
    lobby = _canonical(players)
    team_a = tuple(sorted(rng.sample(range(LOBBY_SIZE), TEAM_SIZE)))
    return _split(lobby, team_a, partitions_evaluated=1)


def _canonical(players: Sequence[LobbyPlayer]) -> list[LobbyPlayer]:
    if len(players) != LOBBY_SIZE:
        raise ValueError(f"a 5v5 lobby needs exactly {LOBBY_SIZE} players, got {len(players)}")
    if len({player.player_id for player in players}) != LOBBY_SIZE:
        raise ValueError("lobby contains duplicate player ids")
    return sorted(players, key=lambda player: player.player_id)


def _split(lobby: list[LobbyPlayer], team_a: tuple[int, ...], *, partitions_evaluated: int) -> Split:
    on_team_a = set(team_a)
    return Split(
        team_a=tuple(lobby[i] for i in range(LOBBY_SIZE) if i in on_team_a),
        team_b=tuple(lobby[i] for i in range(LOBBY_SIZE) if i not in on_team_a),
        partitions_evaluated=partitions_evaluated,
    )
