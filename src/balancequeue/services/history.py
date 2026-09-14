"""Match lookups and player history (PRD §12-14)."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from balancequeue.errors import MatchNotFound, PlayerNotFound
from balancequeue.models import Match, MatchPlayer, Player


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    match_id: int
    team: str
    elo_at_match: int
    winner: bool | None  # None while the match is still ACTIVE
    played_at: datetime


def history_query(player_id: int, *, limit: int, offset: int) -> Select:
    """The exact statement behind GET /players/{id}/matches; benchmarks EXPLAIN this."""
    return (
        select(
            MatchPlayer.match_id,
            MatchPlayer.team,
            MatchPlayer.elo_at_match,
            MatchPlayer.created_at,
            Match.winner_team,
        )
        .join(Match, Match.id == MatchPlayer.match_id)
        .where(MatchPlayer.player_id == player_id)
        .order_by(MatchPlayer.created_at.desc(), MatchPlayer.match_id.desc())
        .limit(limit)
        .offset(offset)
    )


def player_history(session: Session, player_id: int, *, limit: int, offset: int) -> list[HistoryEntry]:
    if session.execute(select(Player.id).where(Player.id == player_id)).first() is None:
        raise PlayerNotFound(player_id)
    rows = session.execute(history_query(player_id, limit=limit, offset=offset))
    return [
        HistoryEntry(
            match_id=row.match_id,
            team=row.team,
            elo_at_match=row.elo_at_match,
            winner=None if row.winner_team is None else row.winner_team == row.team,
            played_at=row.created_at,
        )
        for row in rows
    ]


@dataclass(frozen=True, slots=True)
class MatchDetail:
    match: Match
    roster: list[MatchPlayer]


def get_match(session: Session, match_id: int) -> MatchDetail:
    match = session.get(Match, match_id, populate_existing=True)
    if match is None:
        raise MatchNotFound(match_id)
    roster = list(
        session.execute(
            select(MatchPlayer)
            .where(MatchPlayer.match_id == match_id)
            .order_by(MatchPlayer.elo_at_match.desc(), MatchPlayer.player_id)
        ).scalars()
    )
    return MatchDetail(match=match, roster=roster)
