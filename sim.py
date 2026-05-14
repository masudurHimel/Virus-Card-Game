"""Headless end-to-end simulator.

Plays N full games using the real engine + bot AI for ALL seats (the "human"
seat is also driven by the bot). Surfaces every engine error, illegal state,
or non-termination, with detailed traces.

Usage:
    python3 sim.py                # 200 games
    python3 sim.py --games 500    # 500 games
    python3 sim.py --verbose      # print event log of every game
"""
from __future__ import annotations

import argparse
import sys
import traceback
from collections import Counter

# Make `app` package importable when run from repo root.
sys.path.insert(0, ".")

from app import bot, game
from app.models import Color, GameState, OrganStatus

MAX_TURNS = 800  # safety cap; well above the longest sane game


def play_one_game(seed_idx: int, verbose: bool = False) -> dict:
    """Drive one full game; bots act for every seat."""
    state = game.new_game()
    events_log: list[str] = []
    error: str | None = None
    turn_cap = MAX_TURNS
    last_progress_turn = 0
    last_progress_signature = ""

    def signature(s: GameState) -> str:
        return "|".join(
            f"{p.name}:" + ",".join(
                f"{o.card.color.value}{o.status.value[0]}{len(o.attached)}"
                for o in p.body
            ) + f"/h{len(p.hand)}"
            for p in s.players
        ) + f"/d{len(s.deck)},x{len(s.discard)}"

    try:
        while state.winner is None and state.turn_number < turn_cap:
            idx = state.current
            kind, payload = bot.choose_action(state, idx)

            if kind == "play":
                ev = game.play_card(state, idx, payload["card_id"], payload.get("targets") or {})
            elif kind == "discard":
                ev = game.discard_cards(state, idx, payload["card_ids"])
            else:
                ev = game.pass_turn(state, idx)
            events_log.extend(ev)

            # Stuck detector: if state signature hasn't changed in 60 turns, flag.
            sig = signature(state)
            if sig != last_progress_signature:
                last_progress_signature = sig
                last_progress_turn = state.turn_number
            elif state.turn_number - last_progress_turn > 60:
                error = f"no progress for 60 turns at turn {state.turn_number}"
                break

            # Validate global invariants every turn.
            inv_err = check_invariants(state)
            if inv_err:
                error = f"invariant violation: {inv_err}"
                break

    except Exception as e:
        error = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"

    result = {
        "seed": seed_idx,
        "turns": state.turn_number,
        "winner": state.winner,
        "winner_name": state.players[state.winner].name if state.winner is not None else None,
        "error": error,
        "events": events_log if verbose else None,
        "final_hands": [len(p.hand) for p in state.players],
        "final_bodies": [
            [(o.card.color.value, o.status.value) for o in p.body] for p in state.players
        ],
    }
    return result


def check_invariants(state: GameState) -> str | None:
    # 1. No player ever holds duplicate fixed-color organs.
    for p in state.players:
        fixed = [o.card.color for o in p.body if o.card.color != Color.MULTI]
        if len(fixed) != len(set(fixed)):
            return f"{p.name} has duplicate-color organs: {fixed}"
        multi = sum(1 for o in p.body if o.card.color == Color.MULTI)
        if multi > 1:
            return f"{p.name} has {multi} multicolor organs"

    # 2. Hand size never exceeds 3.
    for p in state.players:
        if len(p.hand) > 3:
            return f"{p.name} hand size {len(p.hand)} > 3"

    # 3. No organ has impossible attached counts.
    for p in state.players:
        for o in p.body:
            viruses = sum(1 for c in o.attached if c.type.value == "virus")
            meds = sum(1 for c in o.attached if c.type.value == "medicine")
            if viruses > 1:
                return f"{p.name}'s {o.card.color.value} organ has {viruses} viruses"
            if meds > 2:
                return f"{p.name}'s {o.card.color.value} organ has {meds} medicines"
            # An organ cannot simultaneously hold a virus and a medicine.
            if viruses >= 1 and meds >= 1:
                return f"{p.name}'s {o.card.color.value} organ holds both virus and medicine"

    # 4. Status enum must match attached layout.
    for p in state.players:
        for o in p.body:
            expected = o.status  # uses property
            if expected == OrganStatus.IMMUNIZED:
                meds = sum(1 for c in o.attached if c.type.value == "medicine")
                if meds < 2:
                    return f"{p.name}: organ marked IMMUNIZED with {meds} medicines"
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=200)
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--stop-on-error", action="store_true")
    args = ap.parse_args()

    errors = []
    win_counts = Counter()
    turn_dist = []
    no_winner = 0

    for i in range(args.games):
        r = play_one_game(i, verbose=args.verbose)
        if r["error"]:
            errors.append(r)
            print(f"[game {i}] ERROR after {r['turns']} turns: {r['error']}", file=sys.stderr)
            if args.verbose:
                for ev in (r["events"] or [])[-40:]:
                    print("   ", ev, file=sys.stderr)
            if args.stop_on_error:
                break
        elif r["winner"] is None:
            no_winner += 1
            print(f"[game {i}] no winner after {r['turns']} turns "
                  f"(hands={r['final_hands']}, bodies={r['final_bodies']})", file=sys.stderr)
        else:
            win_counts[r["winner_name"]] += 1
        turn_dist.append(r["turns"])

    print()
    print(f"games played       : {len(turn_dist)}")
    print(f"errors             : {len(errors)}")
    print(f"games without winner: {no_winner}")
    print(f"avg turns          : {sum(turn_dist) / max(1, len(turn_dist)):.1f}")
    print(f"max turns          : {max(turn_dist, default=0)}")
    print(f"min turns          : {min(turn_dist, default=0)}")
    print(f"win counts         : {dict(win_counts)}")

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
