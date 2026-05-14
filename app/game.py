"""Game engine: turn loop, draw logic, win detection, and POV snapshots."""
from __future__ import annotations

import random
import uuid
from typing import Dict, List, Optional, Tuple

from . import actions
from .deck import build_deck, shuffle
from .models import (
    Card,
    CardType,
    Color,
    GameState,
    Organ,
    OrganStatus,
    Player,
    TreatmentKind,
)


def new_game(human_name: str = "You", bot_names: Optional[List[str]] = None) -> GameState:
    bot_names = bot_names or ["Bot 1", "Bot 2", "Bot 3"]
    players = [Player(id=0, name=human_name, is_bot=False)]
    for i, n in enumerate(bot_names, start=1):
        players.append(Player(id=i, name=n, is_bot=True))

    deck = build_deck()
    shuffle(deck)

    state = GameState(game_id=uuid.uuid4().hex[:10], players=players, deck=deck)

    # Deal 3 cards each.
    for p in state.players:
        drawn, state.deck, state.discard = _draw(state, 3)
        p.hand = drawn
    return state


def _draw(state: GameState, n: int) -> Tuple[List[Card], List[Card], List[Card]]:
    """Draw helper that reshuffles discard back into deck when empty."""
    drawn: List[Card] = []
    deck = state.deck
    discard = state.discard
    for _ in range(n):
        if not deck:
            if not discard:
                break
            deck = list(discard)
            discard = []
            random.shuffle(deck)
        drawn.append(deck.pop())
    return drawn, deck, discard


def end_turn_draw(state: GameState) -> List[str]:
    """Refill the current player's hand to 3 (unless they're flagged to skip)."""
    player_idx = state.current
    me = state.players[player_idx]
    events: List[str] = []
    if player_idx in state.skip_draw:
        state.skip_draw.remove(player_idx)
        events.append(f"{me.name} skipped their draw.")
    else:
        need = 3 - len(me.hand)
        if need > 0:
            drawn, state.deck, state.discard = _draw(state, need)
            me.hand.extend(drawn)
    return events


def advance_turn(state: GameState) -> None:
    state.current = (state.current + 1) % len(state.players)
    state.turn_number += 1


def check_winner(state: GameState) -> Optional[int]:
    for p in state.players:
        if p.has_won():
            state.winner = p.id
            return p.id
    return None


def play_card(
    state: GameState,
    player_idx: int,
    card_id: str,
    targets: Optional[Dict] = None,
) -> List[str]:
    """Execute a single card play for the active player, then refill + advance."""
    if state.winner is not None:
        raise ValueError("game over")
    if state.current != player_idx:
        raise ValueError("not this player's turn")
    events = actions.apply_play(state, player_idx, card_id, targets)
    if check_winner(state) is not None:
        return events
    events += end_turn_draw(state)
    advance_turn(state)
    return events


def discard_cards(state: GameState, player_idx: int, card_ids: List[str]) -> List[str]:
    if state.winner is not None:
        raise ValueError("game over")
    if state.current != player_idx:
        raise ValueError("not this player's turn")
    events = actions.apply_discard(state, player_idx, card_ids)
    events += end_turn_draw(state)
    advance_turn(state)
    return events


def pass_turn(state: GameState, player_idx: int) -> List[str]:
    """Used when a player has an empty hand (e.g. after Latex Glove) and
    therefore cannot play or discard. Just draws + advances."""
    if state.winner is not None:
        raise ValueError("game over")
    if state.current != player_idx:
        raise ValueError("not this player's turn")
    me = state.players[player_idx]
    if me.hand:
        raise ValueError("cannot pass while holding cards")
    events = [f"{me.name} has no cards to play."]
    events += end_turn_draw(state)
    advance_turn(state)
    return events


# ---------- client-POV serialization ----------

def public_snapshot(state: GameState, viewer_idx: int = 0) -> Dict:
    """Render state from the viewer's POV: hide other players' hand contents,
    show only counts."""
    out_players = []
    for i, p in enumerate(state.players):
        entry = {
            "id": p.id,
            "name": p.name,
            "is_bot": p.is_bot,
            "is_current": i == state.current,
            "body": [
                {
                    "card": p.body[j].card.model_dump(mode="json"),
                    "attached": [c.model_dump(mode="json") for c in p.body[j].attached],
                    "status": p.body[j].status.value,
                }
                for j in range(len(p.body))
            ],
            "hand_count": len(p.hand),
        }
        if i == viewer_idx:
            entry["hand"] = [c.model_dump(mode="json") for c in p.hand]
        out_players.append(entry)
    return {
        "game_id": state.game_id,
        "current": state.current,
        "turn_number": state.turn_number,
        "deck_count": len(state.deck),
        "discard_count": len(state.discard),
        "winner": state.winner,
        "players": out_players,
    }
