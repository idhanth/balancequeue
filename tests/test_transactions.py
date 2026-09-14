"""PRD §18 'Database Failure': a failed matchmaking transaction leaves no trace."""

import pytest
from helpers import queue_players
from sqlalchemy import text, update
from sqlalchemy.exc import IntegrityError

from balancequeue.models import Player
from balancequeue.services import matchmaking


def test_database_failure_after_inserts_rolls_back_everything(db, engine, monkeypatch):
    ids = queue_players(engine, [1400, 1450, 1500, 1550, 1600, 1650, 1700, 1750, 1800, 1850])

    def violate_status_check(session, player_ids):
        # Runs after the match and all ten match_players rows are inserted, so this
        # proves the earlier statements are rolled back too, not merely never issued.
        session.execute(
            update(Player)
            .where(Player.id.in_(player_ids))
            .values(status="BOGUS")
            .execution_options(synchronize_session=False)
        )

    monkeypatch.setattr(matchmaking, "_assign_players", violate_status_check)
    with db() as session, pytest.raises(IntegrityError):
        matchmaking.create_match(session)

    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM matches")).scalar_one() == 0
        assert conn.execute(text("SELECT count(*) FROM match_players")).scalar_one() == 0
        statuses = conn.execute(text("SELECT DISTINCT status FROM players")).scalars().all()
        assert statuses == ["AVAILABLE"]

    # The rollback released the row locks, so the same ten players match immediately.
    monkeypatch.undo()
    with db() as session:
        created = matchmaking.create_match(session)
    matched = {p.player_id for p in created.split.team_a + created.split.team_b}
    assert matched == set(ids)
