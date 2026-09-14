from helpers import PRD_EXAMPLE_ELOS, brute_force_min_difference, queue_players
from sqlalchemy import text


def create_player(client, username: str, elo: int = 1000) -> dict:
    response = client.post("/players", json={"username": username, "elo": elo})
    assert response.status_code == 201, response.text
    return response.json()


def team_ids(body: dict, team: str) -> set[int]:
    return {member["player_id"] for member in body[team]}


def scalar(engine, sql: str, **params):
    with engine.connect() as conn:
        return conn.execute(text(sql), params).scalar_one()


# --- players -------------------------------------------------------------------------


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_create_and_get_player(client):
    created = create_player(client, "ada", 1640)
    assert created["elo"] == 1640
    assert created["status"] == "IDLE"
    assert created["queued_at"] is None
    assert client.get(f"/players/{created['player_id']}").json() == created


def test_new_player_elo_defaults_to_1000(client):
    response = client.post("/players", json={"username": "newcomer"})
    assert response.json()["elo"] == 1000


def test_duplicate_username_is_a_conflict(client):
    create_player(client, "ada")
    response = client.post("/players", json={"username": "ada"})
    assert response.status_code == 409
    assert response.json()["error"] == "USERNAME_TAKEN"


def test_unknown_player_is_not_found(client):
    response = client.get("/players/999")
    assert response.status_code == 404
    assert response.json()["error"] == "PLAYER_NOT_FOUND"


def test_validation_errors_use_the_error_envelope(client):
    response = client.post("/players", json={"username": ""})
    assert response.status_code == 422
    assert response.json()["error"] == "VALIDATION_ERROR"


# --- queue ---------------------------------------------------------------------------


def test_enqueue_then_dequeue(client):
    player = create_player(client, "ada")
    queued = client.post("/queue", json={"player_id": player["player_id"]})
    assert queued.status_code == 201
    assert queued.json()["status"] == "AVAILABLE"
    assert queued.json()["queued_at"] is not None

    removed = client.delete(f"/queue/{player['player_id']}")
    assert removed.status_code == 200
    assert removed.json()["status"] == "IDLE"
    assert removed.json()["queued_at"] is None


def test_enqueue_twice_is_a_conflict(client):
    player = create_player(client, "ada")
    client.post("/queue", json={"player_id": player["player_id"]})
    response = client.post("/queue", json={"player_id": player["player_id"]})
    assert response.status_code == 409
    assert response.json()["error"] == "PLAYER_ALREADY_QUEUED"


def test_enqueue_unknown_player_is_not_found(client):
    response = client.post("/queue", json={"player_id": 424242})
    assert response.status_code == 404


def test_dequeue_player_not_in_queue_is_a_conflict(client):
    player = create_player(client, "ada")
    response = client.delete(f"/queue/{player['player_id']}")
    assert response.status_code == 409
    assert response.json()["error"] == "PLAYER_NOT_QUEUED"


# --- matchmaking ---------------------------------------------------------------------


def test_fewer_than_ten_players_is_a_conflict(client, engine):
    queue_players(engine, [1500] * 8)
    response = client.post("/matches")
    assert response.status_code == 409
    assert response.json()["error"] == "INSUFFICIENT_PLAYERS"
    assert response.json()["available_players"] == 8
    assert scalar(engine, "SELECT count(*) FROM matches") == 0
    assert scalar(engine, "SELECT count(*) FROM players WHERE status = 'AVAILABLE'") == 8


def test_create_match_balances_and_assigns_all_ten(client, engine):
    ids = queue_players(engine, PRD_EXAMPLE_ELOS)
    response = client.post("/matches")
    assert response.status_code == 201, response.text
    body = response.json()

    assert len(body["team_a"]) == len(body["team_b"]) == 5
    assert team_ids(body, "team_a") | team_ids(body, "team_b") == set(ids)
    assert body["team_a_elo"] == sum(m["elo"] for m in body["team_a"])
    assert body["team_b_elo"] == sum(m["elo"] for m in body["team_b"])
    assert body["elo_difference"] == brute_force_min_difference(PRD_EXAMPLE_ELOS)
    assert body["partitions_evaluated"] == 126
    assert body["status"] == "ACTIVE"

    for player_id in ids:
        player = client.get(f"/players/{player_id}").json()
        assert player["status"] == "IN_MATCH"
        assert player["queued_at"] is None

    fetched = client.get(f"/matches/{body['match_id']}").json()
    assert team_ids(fetched, "team_a") == team_ids(body, "team_a")
    assert (fetched["team_a_elo"], fetched["team_b_elo"], fetched["elo_difference"]) == (
        body["team_a_elo"],
        body["team_b_elo"],
        body["elo_difference"],
    )


def test_longest_waiting_players_are_matched_first(client, engine):
    ids = queue_players(engine, [1500] * 12)
    body = client.post("/matches").json()
    assert team_ids(body, "team_a") | team_ids(body, "team_b") == set(ids[:10])
    assert scalar(engine, "SELECT count(*) FROM players WHERE status = 'AVAILABLE'") == 2


def test_rating_at_match_time_is_preserved(client, engine):
    ids = queue_players(engine, PRD_EXAMPLE_ELOS)
    body = client.post("/matches").json()
    with engine.begin() as conn:
        conn.execute(text("UPDATE players SET elo = elo + 500"))

    fetched = client.get(f"/matches/{body['match_id']}").json()
    assert sorted(m["elo"] for m in fetched["team_a"] + fetched["team_b"]) == sorted(PRD_EXAMPLE_ELOS)
    history = client.get(f"/players/{ids[0]}/matches").json()
    assert history["matches"][0]["elo_at_match"] == PRD_EXAMPLE_ELOS[0]


def test_player_in_a_match_cannot_queue_or_dequeue(client, engine):
    ids = queue_players(engine, [1500] * 10)
    client.post("/matches")
    assert client.post("/queue", json={"player_id": ids[0]}).json()["error"] == "PLAYER_IN_MATCH"
    assert client.delete(f"/queue/{ids[0]}").json()["error"] == "PLAYER_IN_MATCH"


def test_unknown_match_is_not_found(client):
    assert client.get("/matches/77").status_code == 404


def test_recording_a_result_completes_the_match_and_frees_players(client, engine):
    ids = queue_players(engine, [1500] * 10)
    match_id = client.post("/matches").json()["match_id"]

    response = client.post(f"/matches/{match_id}/result", json={"winner_team": "A"})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "COMPLETED"
    assert response.json()["winner_team"] == "A"
    assert response.json()["completed_at"] is not None
    assert scalar(engine, "SELECT count(*) FROM players WHERE status = 'IDLE'") == len(ids)

    again = client.post(f"/matches/{match_id}/result", json={"winner_team": "B"})
    assert again.status_code == 409
    assert again.json()["error"] == "MATCH_NOT_ACTIVE"
    assert client.post("/matches/999/result", json={"winner_team": "A"}).status_code == 404
    assert client.post(f"/matches/{match_id}/result", json={"winner_team": "C"}).status_code == 422


# --- player history ------------------------------------------------------------------


def test_history_is_newest_first_and_paginates(client, engine):
    ids = queue_players(engine, [1200, 1300, 1400, 1500, 1600, 1700, 1800, 1900, 2000, 2100])
    player_id = ids[0]
    match_ids, winners = [], ["A", "B", "A"]
    for round_number, winner in enumerate(winners):
        if round_number:
            for pid in ids:
                assert client.post("/queue", json={"player_id": pid}).status_code == 201
        body = client.post("/matches").json()
        match_ids.append(body["match_id"])
        client.post(f"/matches/{body['match_id']}/result", json={"winner_team": winner})

    history = client.get(f"/players/{player_id}/matches").json()
    assert history["player_id"] == player_id
    assert [m["match_id"] for m in history["matches"]] == match_ids[::-1]
    for entry, winner in zip(history["matches"], winners[::-1]):
        assert entry["winner"] == (entry["team"] == winner)

    page_one = client.get(f"/players/{player_id}/matches", params={"limit": 2, "offset": 0}).json()["matches"]
    page_two = client.get(f"/players/{player_id}/matches", params={"limit": 2, "offset": 2}).json()["matches"]
    past_end = client.get(f"/players/{player_id}/matches", params={"limit": 2, "offset": 4}).json()["matches"]
    assert [m["match_id"] for m in page_one + page_two] == match_ids[::-1]
    assert past_end == []


def test_history_of_an_active_match_has_no_winner_yet(client, engine):
    ids = queue_players(engine, [1500] * 10)
    client.post("/matches")
    [entry] = client.get(f"/players/{ids[3]}/matches").json()["matches"]
    assert entry["winner"] is None


def test_history_for_unknown_player_is_not_found(client):
    assert client.get("/players/31337/matches").status_code == 404


def test_history_limit_is_bounded(client, engine):
    [player_id, *_] = queue_players(engine, [1500])
    assert client.get(f"/players/{player_id}/matches", params={"limit": 0}).status_code == 422
    assert client.get(f"/players/{player_id}/matches", params={"limit": 101}).status_code == 422
