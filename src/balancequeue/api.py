"""REST API (PRD §15). Handlers translate HTTP <-> services and nothing else.

    uv run uvicorn balancequeue.api:create_app --factory --port 8010
"""

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, FastAPI, Path, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from balancequeue.balance import TEAM_SIZE
from balancequeue.db import make_engine, make_sessionmaker
from balancequeue.errors import AppError
from balancequeue.models import MatchStatus, Player
from balancequeue.schemas import (
    PG_BIGINT_MAX,
    HistoryEntryOut,
    MatchCreated,
    MatchOut,
    MatchResult,
    PlayerCreate,
    PlayerHistoryOut,
    PlayerOut,
    QueueRequest,
    TeamMember,
)
from balancequeue.services import history, matchmaking, players


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.sessionmaker() as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]
PlayerId = Annotated[int, Path(gt=0, le=PG_BIGINT_MAX)]
MatchId = Annotated[int, Path(gt=0, le=PG_BIGINT_MAX)]


def create_app(session_factory: sessionmaker[Session] | None = None) -> FastAPI:
    app = FastAPI(title="BalanceQueue", version="0.1.0")
    app.state.sessionmaker = session_factory or make_sessionmaker(make_engine())

    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.code, "message": exc.message, **exc.extra},
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={
                "error": "VALIDATION_ERROR",
                "message": "request validation failed",
                "details": jsonable_encoder(exc.errors()),
            },
        )

    @app.get("/health")
    def health(session: SessionDep) -> dict[str, str]:
        session.execute(text("SELECT 1"))
        return {"status": "ok"}

    @app.post("/players", status_code=status.HTTP_201_CREATED)
    def create_player(body: PlayerCreate, session: SessionDep) -> PlayerOut:
        return _player_out(players.create_player(session, body.username, body.elo))

    @app.get("/players/{player_id}")
    def get_player(player_id: PlayerId, session: SessionDep) -> PlayerOut:
        return _player_out(players.get_player(session, player_id))

    @app.get("/players/{player_id}/matches")
    def get_player_history(
        player_id: PlayerId,
        session: SessionDep,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
    ) -> PlayerHistoryOut:
        entries = history.player_history(session, player_id, limit=limit, offset=offset)
        return PlayerHistoryOut(
            player_id=player_id,
            limit=limit,
            offset=offset,
            matches=[
                HistoryEntryOut(
                    match_id=e.match_id,
                    team=e.team,
                    elo_at_match=e.elo_at_match,
                    winner=e.winner,
                    played_at=e.played_at,
                )
                for e in entries
            ],
        )

    @app.post("/queue", status_code=status.HTTP_201_CREATED)
    def enqueue(body: QueueRequest, session: SessionDep) -> PlayerOut:
        return _player_out(players.enqueue(session, body.player_id))

    @app.delete("/queue/{player_id}")
    def dequeue(player_id: PlayerId, session: SessionDep) -> PlayerOut:
        return _player_out(players.dequeue(session, player_id))

    @app.post("/matches", status_code=status.HTTP_201_CREATED)
    def create_match(session: SessionDep) -> MatchCreated:
        created = matchmaking.create_match(session)
        split = created.split
        return MatchCreated(
            match_id=created.match_id,
            status=MatchStatus.ACTIVE,
            team_a=[TeamMember(player_id=p.player_id, elo=p.elo) for p in _by_elo(split.team_a)],
            team_b=[TeamMember(player_id=p.player_id, elo=p.elo) for p in _by_elo(split.team_b)],
            team_a_elo=split.team_a_elo,
            team_b_elo=split.team_b_elo,
            elo_difference=split.elo_difference,
            winner_team=None,
            created_at=created.created_at,
            completed_at=None,
            partitions_evaluated=split.partitions_evaluated,
        )

    @app.get("/matches/{match_id}")
    def get_match(match_id: MatchId, session: SessionDep) -> MatchOut:
        return _match_out(history.get_match(session, match_id))

    @app.post("/matches/{match_id}/result")
    def record_result(match_id: MatchId, body: MatchResult, session: SessionDep) -> MatchOut:
        matchmaking.record_result(session, match_id, body.winner_team)
        return _match_out(history.get_match(session, match_id))

    return app


def _player_out(player: Player) -> PlayerOut:
    return PlayerOut(
        player_id=player.id,
        username=player.username,
        elo=player.elo,
        status=player.status,
        queued_at=player.queued_at,
        created_at=player.created_at,
    )


def _by_elo(team):
    return sorted(team, key=lambda p: (-p.elo, p.player_id))


def _match_out(detail: history.MatchDetail) -> MatchOut:
    match = detail.match
    members = {
        team: [TeamMember(player_id=mp.player_id, elo=mp.elo_at_match) for mp in detail.roster if mp.team == team]
        for team in ("A", "B")
    }
    assert len(members["A"]) == len(members["B"]) == TEAM_SIZE, f"match {match.id} roster is not 5v5"
    return MatchOut(
        match_id=match.id,
        status=match.status,
        team_a=members["A"],
        team_b=members["B"],
        team_a_elo=match.team_a_elo,
        team_b_elo=match.team_b_elo,
        elo_difference=match.elo_difference,
        winner_team=match.winner_team,
        created_at=match.created_at,
        completed_at=match.completed_at,
    )
