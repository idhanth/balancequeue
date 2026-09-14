"""ORM mappings. The schema itself is owned by the SQL files in migrations/."""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class PlayerStatus(StrEnum):
    IDLE = "IDLE"
    AVAILABLE = "AVAILABLE"  # waiting in the matchmaking queue
    IN_MATCH = "IN_MATCH"


class MatchStatus(StrEnum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"


class Player(Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    elo: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), server_default=PlayerStatus.IDLE)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    status: Mapped[str] = mapped_column(String(20), server_default=MatchStatus.ACTIVE)
    team_a_elo: Mapped[int] = mapped_column(Integer)
    team_b_elo: Mapped[int] = mapped_column(Integer)
    elo_difference: Mapped[int] = mapped_column(Integer)
    winner_team: Mapped[str | None] = mapped_column(String(1))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MatchPlayer(Base):
    __tablename__ = "match_players"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    match_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("matches.id"))
    player_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("players.id"))
    team: Mapped[str] = mapped_column(String(1))
    elo_at_match: Mapped[int] = mapped_column(Integer)
    # Copy of matches.created_at, so history is one index scan (see migration 002).
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
