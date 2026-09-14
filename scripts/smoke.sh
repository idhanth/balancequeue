#!/usr/bin/env bash
# End-to-end smoke test against a running API with an empty queue (e.g. a fresh
# `docker compose up`). Queues the PRD example lobby, which must split 7300 vs 7300,
# records a result and reads it back through player history.
#
#   scripts/smoke.sh [base-url]        # default http://127.0.0.1:8010
set -euo pipefail

BASE="${1:-http://127.0.0.1:8010}"
JSON='content-type: application/json'

for _ in $(seq 1 60); do
  curl -fsS "$BASE/health" >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS "$BASE/health" >/dev/null

run="smoke-$(date +%s)-$$"
ids=()
for elo in 1540 1520 1510 1490 1475 1460 1420 1410 1395 1380; do
  id=$(curl -fsS -X POST "$BASE/players" -H "$JSON" -d "{\"username\":\"$run-$elo\",\"elo\":$elo}" \
    | python3 -c 'import json, sys; print(json.load(sys.stdin)["player_id"])')
  curl -fsS -X POST "$BASE/queue" -H "$JSON" -d "{\"player_id\":$id}" >/dev/null
  ids+=("$id")
done

match=$(curl -fsS -X POST "$BASE/matches")
match_id=$(python3 - "$match" "${ids[@]}" <<'PY'
import json, sys
match = json.loads(sys.argv[1])
queued = {int(i) for i in sys.argv[2:]}
matched = {m["player_id"] for team in ("team_a", "team_b") for m in match[team]}
assert matched == queued, f"matched {matched}, queued {queued}"
assert (match["team_a_elo"], match["team_b_elo"], match["elo_difference"]) == (7300, 7300, 0), match
assert match["partitions_evaluated"] == 126, match
print(match["match_id"])
PY
)
echo "match $match_id: 7300 vs 7300, difference 0, 126 partitions evaluated"

status=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/matches")
[ "$status" = "409" ] || { echo "expected 409 INSUFFICIENT_PLAYERS, got $status" >&2; exit 1; }
echo "second match with an empty queue: 409 INSUFFICIENT_PLAYERS"

curl -fsS -X POST "$BASE/matches/$match_id/result" -H "$JSON" -d '{"winner_team":"A"}' >/dev/null
history=$(curl -fsS "$BASE/players/${ids[0]}/matches")
python3 - "$history" <<'PY'
import json, sys
[entry] = json.loads(sys.argv[1])["matches"]
assert entry["winner"] == (entry["team"] == "A"), entry
match_id, team, winner = entry["match_id"], entry["team"], entry["winner"]
print(f"history: match {match_id}, team {team}, winner={winner}")
PY
echo "smoke test passed"
