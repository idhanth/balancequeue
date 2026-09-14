"""Database-level correctness checks shared by the tests and the concurrency benchmark.

Each check returns a list of violations (empty means the invariant holds), so a
benchmark can report counts instead of stopping at the first failure.
"""

from dataclasses import dataclass, field

from sqlalchemy import Connection, text


@dataclass
class AssignmentReport:
    duplicate_assignments: list[tuple[int, int]] = field(default_factory=list)  # (player_id, active matches)
    malformed_matches: list[int] = field(default_factory=list)  # not exactly 5 on A and 5 on B
    inconsistent_totals: list[int] = field(default_factory=list)  # stored totals != roster sums
    status_mismatches: list[int] = field(default_factory=list)  # IN_MATCH <-> active roster disagree
    active_matches: int = 0
    assigned_players: int = 0

    @property
    def ok(self) -> bool:
        return not (
            self.duplicate_assignments or self.malformed_matches or self.inconsistent_totals or self.status_mismatches
        )


def check_assignments(conn: Connection) -> AssignmentReport:
    report = AssignmentReport()

    report.duplicate_assignments = [
        (row.player_id, row.n)
        for row in conn.execute(
            text(
                """
                SELECT mp.player_id, count(*) AS n
                FROM match_players mp JOIN matches m ON m.id = mp.match_id
                WHERE m.status = 'ACTIVE'
                GROUP BY mp.player_id HAVING count(*) > 1
                """
            )
        )
    ]

    report.malformed_matches = [
        row.id
        for row in conn.execute(
            text(
                """
                SELECT m.id
                FROM matches m LEFT JOIN match_players mp ON mp.match_id = m.id
                GROUP BY m.id
                HAVING count(*) FILTER (WHERE mp.team = 'A') <> 5
                    OR count(*) FILTER (WHERE mp.team = 'B') <> 5
                """
            )
        )
    ]

    report.inconsistent_totals = [
        row.id
        for row in conn.execute(
            text(
                """
                SELECT m.id
                FROM matches m JOIN match_players mp ON mp.match_id = m.id
                GROUP BY m.id, m.team_a_elo, m.team_b_elo, m.elo_difference
                HAVING m.team_a_elo <> coalesce(sum(mp.elo_at_match) FILTER (WHERE mp.team = 'A'), 0)
                    OR m.team_b_elo <> coalesce(sum(mp.elo_at_match) FILTER (WHERE mp.team = 'B'), 0)
                    OR m.elo_difference <> abs(m.team_a_elo - m.team_b_elo)
                """
            )
        )
    ]

    report.status_mismatches = [
        row.player_id
        for row in conn.execute(
            text(
                """
                WITH active AS (
                    SELECT DISTINCT mp.player_id
                    FROM match_players mp JOIN matches m ON m.id = mp.match_id
                    WHERE m.status = 'ACTIVE'
                )
                SELECT coalesce(p.id, a.player_id) AS player_id
                FROM (SELECT id FROM players WHERE status = 'IN_MATCH') p
                FULL JOIN active a ON a.player_id = p.id
                WHERE p.id IS NULL OR a.player_id IS NULL
                """
            )
        )
    ]

    report.active_matches = conn.execute(text("SELECT count(*) FROM matches WHERE status = 'ACTIVE'")).scalar_one()
    report.assigned_players = conn.execute(
        text("SELECT count(*) FROM match_players mp JOIN matches m ON m.id = mp.match_id WHERE m.status = 'ACTIVE'")
    ).scalar_one()
    return report
