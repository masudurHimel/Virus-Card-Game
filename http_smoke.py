"""HTTP-level smoke test: drive a full game through the live API.

Uses the bot's choose_action against a *client-side mirror* of the game state
(reconstructed from public_snapshot). The mirror is loose — we don't need a
perfect copy, just enough info to pick legal targets via /api/legal.
"""
from __future__ import annotations

import json
import random
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8765"
HUMAN = 0


def http(method: str, path: str, body=None):
    data = None
    if body is not None:
        data = json.dumps(body).encode()
    req = urllib.request.Request(BASE + path, data=data, method=method)
    if body is not None:
        req.add_header("content-type", "application/json")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def play_full_game(label: int) -> dict:
    res = http("POST", "/api/new-game")
    snap = res["snapshot"]
    gid = snap["game_id"]

    events_count = 0
    turn_cap = 600
    step_log = []
    while snap["winner"] is None and snap["turn_number"] < turn_cap:
        cur = snap["current"]
        if cur != HUMAN:
            r = http("POST", f"/api/auto-step/{gid}")
            snap = r["snapshot"]
            step_log.append(r.get("step"))
            events_count += len(r.get("step", {}).get("events", []))
            continue

        # Human: pick a card. Try to play if legal, else discard one.
        human = snap["players"][HUMAN]
        hand = human["hand"]
        if not hand:
            # Auto-step the human pass
            r = http("POST", f"/api/auto-step/{gid}")
            snap = r["snapshot"]
            step_log.append(r.get("step"))
            continue
        # Try each card for a legal target
        played = False
        order = list(hand)
        random.shuffle(order)
        for card in order:
            legal = http("GET", f"/api/legal/{gid}/{card['id']}")
            targets = legal["targets"]
            if not targets:
                continue
            tgt = random.choice(targets)
            r = http("POST", f"/api/play/{gid}", {"card_id": card["id"], "targets": tgt})
            snap = r["snapshot"]
            step_log.append(r.get("step"))
            played = True
            break
        if not played:
            # Discard the first card
            ids = [hand[0]["id"]]
            r = http("POST", f"/api/discard/{gid}", {"card_ids": ids})
            snap = r["snapshot"]
            step_log.append(r.get("step"))

    return {
        "label": label,
        "turns": snap["turn_number"],
        "winner": snap["winner"],
        "winner_name": snap["players"][snap["winner"]]["name"] if snap["winner"] is not None else None,
        "events_count": events_count,
        "steps": len(step_log),
    }


def main():
    games = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    t0 = time.time()
    rows = []
    for i in range(games):
        try:
            r = play_full_game(i)
            rows.append(r)
            print(f"[game {i}] winner={r['winner_name']} turns={r['turns']} steps={r['steps']}")
        except Exception as e:
            print(f"[game {i}] ERROR: {e}")
            sys.exit(1)
    dt = time.time() - t0
    print(f"\ntotal: {games} games in {dt:.1f}s -> avg {dt/games:.2f}s/game")


if __name__ == "__main__":
    main()
