-- PRD §11 schema, tightened with the constraints the service relies on.
--
-- Deviations from the PRD's sketch, and why:
--   * players.status adds IDLE (not queued) and IN_MATCH. AVAILABLE means "waiting in
--     the queue", so a newly created player defaults to IDLE rather than AVAILABLE.
--   * matches.status (ACTIVE/COMPLETED) defines what an "active match" is (FR-5).
--   * match_players.created_at is denormalized from matches.created_at so player
--     history can be served from one index (PRD §14). The index itself is migration 002,
--     kept separate so the history benchmark can measure the schema without it.

CREATE TABLE players (
    id         BIGSERIAL PRIMARY KEY,
    username   VARCHAR(50) UNIQUE NOT NULL,
    elo        INTEGER NOT NULL DEFAULT 1000 CHECK (elo >= 0),
    status     VARCHAR(20) NOT NULL DEFAULT 'IDLE'
               CHECK (status IN ('IDLE', 'AVAILABLE', 'IN_MATCH')),
    queued_at  TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT players_queued_at_iff_available
        CHECK ((status = 'AVAILABLE') = (queued_at IS NOT NULL))
);

-- The matchmaking lobby query: AVAILABLE players, oldest first (PRD §9).
CREATE INDEX idx_players_queue ON players (queued_at, id) WHERE status = 'AVAILABLE';

CREATE TABLE matches (
    id             BIGSERIAL PRIMARY KEY,
    status         VARCHAR(20) NOT NULL DEFAULT 'ACTIVE'
                   CHECK (status IN ('ACTIVE', 'COMPLETED')),
    team_a_elo     INTEGER NOT NULL,
    team_b_elo     INTEGER NOT NULL,
    elo_difference INTEGER NOT NULL,
    winner_team    VARCHAR(1) CHECK (winner_team IN ('A', 'B')),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at   TIMESTAMPTZ,
    CONSTRAINT matches_difference_consistent
        CHECK (elo_difference = abs(team_a_elo - team_b_elo)),
    CONSTRAINT matches_winner_iff_completed
        CHECK ((status = 'COMPLETED') = (winner_team IS NOT NULL)
           AND (status = 'COMPLETED') = (completed_at IS NOT NULL))
);

CREATE TABLE match_players (
    id           BIGSERIAL PRIMARY KEY,
    match_id     BIGINT NOT NULL REFERENCES matches (id),
    player_id    BIGINT NOT NULL REFERENCES players (id),
    team         VARCHAR(1) NOT NULL CHECK (team IN ('A', 'B')),
    elo_at_match INTEGER NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL,
    CONSTRAINT match_players_once_per_match UNIQUE (match_id, player_id)
);
