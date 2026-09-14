-- PRD §14: serve GET /players/{id}/matches from a single index range scan.
--
-- The history query filters on player_id and orders by (created_at DESC, match_id DESC).
-- Without this index PostgreSQL scans every match_players row and sorts the player's
-- matches; with it, the first `limit` rows come straight off the index in order.
-- benchmarks/history.py measures the API with and without exactly this statement.

CREATE INDEX idx_player_history
    ON match_players (player_id, created_at DESC, match_id DESC);
