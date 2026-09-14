"""Domain errors. The API renders them as {"error": CODE, "message": ..., **extra} (PRD §18)."""

from typing import Any


class AppError(Exception):
    status_code = 400
    code = "BAD_REQUEST"

    def __init__(self, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.message = message
        self.extra = extra


class PlayerNotFound(AppError):
    status_code = 404
    code = "PLAYER_NOT_FOUND"

    def __init__(self, player_id: int) -> None:
        super().__init__(f"player {player_id} does not exist", player_id=player_id)


class MatchNotFound(AppError):
    status_code = 404
    code = "MATCH_NOT_FOUND"

    def __init__(self, match_id: int) -> None:
        super().__init__(f"match {match_id} does not exist", match_id=match_id)


class UsernameTaken(AppError):
    status_code = 409
    code = "USERNAME_TAKEN"

    def __init__(self, username: str) -> None:
        super().__init__(f"username {username!r} is already taken")


class InsufficientPlayers(AppError):
    status_code = 409
    code = "INSUFFICIENT_PLAYERS"

    def __init__(self, available: int) -> None:
        super().__init__("a 5v5 match needs 10 available players", available_players=available)


class PlayerAlreadyQueued(AppError):
    status_code = 409
    code = "PLAYER_ALREADY_QUEUED"

    def __init__(self, player_id: int) -> None:
        super().__init__(f"player {player_id} is already in the queue", player_id=player_id)


class PlayerInMatch(AppError):
    status_code = 409
    code = "PLAYER_IN_MATCH"

    def __init__(self, player_id: int) -> None:
        super().__init__(f"player {player_id} is in an active match", player_id=player_id)


class PlayerNotQueued(AppError):
    status_code = 409
    code = "PLAYER_NOT_QUEUED"

    def __init__(self, player_id: int) -> None:
        super().__init__(f"player {player_id} is not in the queue", player_id=player_id)


class MatchNotActive(AppError):
    status_code = 409
    code = "MATCH_NOT_ACTIVE"

    def __init__(self, match_id: int) -> None:
        super().__init__(f"match {match_id} already has a result", match_id=match_id)
