from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

PG_BIGINT_MAX = 2**63 - 1

Team = Literal["A", "B"]


class PlayerCreate(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    elo: int = Field(default=1000, ge=0, le=10_000)


class PlayerOut(BaseModel):
    player_id: int
    username: str
    elo: int
    status: str
    queued_at: datetime | None
    created_at: datetime


class QueueRequest(BaseModel):
    player_id: int = Field(gt=0, le=PG_BIGINT_MAX)


class TeamMember(BaseModel):
    player_id: int
    elo: int


class MatchOut(BaseModel):
    match_id: int
    status: str
    team_a: list[TeamMember]
    team_b: list[TeamMember]
    team_a_elo: int
    team_b_elo: int
    elo_difference: int
    winner_team: Team | None
    created_at: datetime
    completed_at: datetime | None


class MatchCreated(MatchOut):
    partitions_evaluated: int


class MatchResult(BaseModel):
    winner_team: Team


class HistoryEntryOut(BaseModel):
    match_id: int
    team: Team
    elo_at_match: int
    winner: bool | None
    played_at: datetime


class PlayerHistoryOut(BaseModel):
    player_id: int
    limit: int
    offset: int
    matches: list[HistoryEntryOut]
