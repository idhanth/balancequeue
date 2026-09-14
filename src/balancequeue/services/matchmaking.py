"""The matchmaking transaction (PRD §6, §9).

    BEGIN
      SELECT 10 AVAILABLE players ... FOR UPDATE SKIP LOCKED
      balance them (all 126 partitions)
      INSERT match, INSERT 10 match_players, UPDATE players -> IN_MATCH
    COMMIT

`FOR UPDATE` holds the ten rows until commit, so no other transaction can assign them.
`SKIP LOCKED` makes a concurrent request take the *next* ten players instead of queueing
behind the first request's locks. Any exception rolls the whole thing back, which
releases the locks and leaves the players AVAILABLE.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import func, insert, select, update
from sqlalchemy.orm import Session

from balancequeue.balance import LOBBY_SIZE, LobbyPlayer, Split, balance
from balancequeue.errors import InsufficientPlayers, MatchNotActive, MatchNotFound
from balancequeue.models import Match, MatchPlayer, MatchStatus, Player, PlayerStatus

# "skip_locked" is the only mode the API uses. The other two exist so
# benchmarks/concurrency.py can demonstrate what the PRD's locking strategy prevents:
# "none" double-assigns players, "for_update" is safe but makes concurrent requests
# block on each other and then fail with INSUFFICIENT_PLAYERS.
LockMode = Literal["skip_locked", "for_update", "none"]


@dataclass(frozen=True, slots=True)
class CreatedMatch:
    match_id: int
    created_at: datetime
    split: Split


def create_match(session: Session, *, lock_mode: LockMode = "skip_locked") -> CreatedMatch:
    try:
        lobby = _lock_lobby(session, lock_mode)
        if len(lobby) < LOBBY_SIZE:
            raise InsufficientPlayers(available=len(lobby))

        split = balance(lobby)

        match_id, created_at = session.execute(
            insert(Match)
            .values(
                status=MatchStatus.ACTIVE,
                team_a_elo=split.team_a_elo,
                team_b_elo=split.team_b_elo,
                elo_difference=split.elo_difference,
            )
            .returning(Match.id, Match.created_at)
        ).one()

        session.execute(
            insert(MatchPlayer),
            [
                {
                    "match_id": match_id,
                    "player_id": player.player_id,
                    "team": team,
                    "elo_at_match": player.elo,  # FR-8: rating as it was when the match formed
                    "created_at": created_at,
                }
                for team, members in (("A", split.team_a), ("B", split.team_b))
                for player in members
            ],
        )

        _assign_players(session, [player.player_id for player in lobby])
        session.commit()
    except BaseException:
        session.rollback()
        raise

    return CreatedMatch(match_id=match_id, created_at=created_at, split=split)


def _lock_lobby(session: Session, lock_mode: LockMode) -> list[LobbyPlayer]:
    stmt = (
        select(Player.id, Player.elo)
        .where(Player.status == PlayerStatus.AVAILABLE)
        .order_by(Player.queued_at, Player.id)
        .limit(LOBBY_SIZE)
    )
    if lock_mode == "skip_locked":
        stmt = stmt.with_for_update(skip_locked=True)
    elif lock_mode == "for_update":
        stmt = stmt.with_for_update()
    return [LobbyPlayer(player_id=row.id, elo=row.elo) for row in session.execute(stmt)]


def _assign_players(session: Session, player_ids: list[int]) -> None:
    session.execute(
        update(Player)
        .where(Player.id.in_(player_ids))
        .values(status=PlayerStatus.IN_MATCH, queued_at=None)
        .execution_options(synchronize_session=False)
    )


def record_result(session: Session, match_id: int, winner_team: str) -> None:
    """Complete an ACTIVE match and release its players back to IDLE."""
    try:
        completed = session.execute(
            update(Match)
            .where(Match.id == match_id, Match.status == MatchStatus.ACTIVE)
            .values(status=MatchStatus.COMPLETED, winner_team=winner_team, completed_at=func.now())
            .returning(Match.id)
        ).first()
        if completed is None:
            exists = session.execute(select(Match.id).where(Match.id == match_id)).first()
            raise MatchNotActive(match_id) if exists else MatchNotFound(match_id)

        session.execute(
            update(Player)
            .where(
                Player.id.in_(select(MatchPlayer.player_id).where(MatchPlayer.match_id == match_id)),
                Player.status == PlayerStatus.IN_MATCH,
            )
            .values(status=PlayerStatus.IDLE)
            .execution_options(synchronize_session=False)
        )
        session.commit()
    except BaseException:
        session.rollback()
        raise
