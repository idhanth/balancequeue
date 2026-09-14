from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from balancequeue.errors import PlayerAlreadyQueued, PlayerInMatch, PlayerNotFound, PlayerNotQueued, UsernameTaken
from balancequeue.models import Player, PlayerStatus


def create_player(session: Session, username: str, elo: int) -> Player:
    player = Player(username=username, elo=elo)
    session.add(player)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise UsernameTaken(username) from exc
    session.refresh(player)
    return player


def get_player(session: Session, player_id: int) -> Player:
    player = session.get(Player, player_id)
    if player is None:
        raise PlayerNotFound(player_id)
    return player


def enqueue(session: Session, player_id: int) -> Player:
    """POST /queue. Locks the player row so a concurrent dequeue or match sees a clean state."""
    try:
        player = _lock_player(session, player_id)
        if player.status == PlayerStatus.AVAILABLE:
            raise PlayerAlreadyQueued(player_id)
        if player.status == PlayerStatus.IN_MATCH:
            raise PlayerInMatch(player_id)
        player.status = PlayerStatus.AVAILABLE
        player.queued_at = func.clock_timestamp()
        session.commit()
    except BaseException:
        session.rollback()
        raise
    session.refresh(player)
    return player


def dequeue(session: Session, player_id: int) -> Player:
    """DELETE /queue/{id}. Blocks behind an in-flight matchmaking lock, then rechecks status."""
    try:
        player = _lock_player(session, player_id)
        if player.status == PlayerStatus.IN_MATCH:
            raise PlayerInMatch(player_id)
        if player.status != PlayerStatus.AVAILABLE:
            raise PlayerNotQueued(player_id)
        player.status = PlayerStatus.IDLE
        player.queued_at = None
        session.commit()
    except BaseException:
        session.rollback()
        raise
    session.refresh(player)
    return player


def _lock_player(session: Session, player_id: int) -> Player:
    player = session.execute(
        select(Player).where(Player.id == player_id).with_for_update().execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if player is None:
        raise PlayerNotFound(player_id)
    return player
