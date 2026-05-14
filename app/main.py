from __future__ import annotations

import copy
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from pydantic import BaseModel

from . import bot, game
from .actions import legal_play_targets
from .models import Card, GameState

app = FastAPI(title="Virus! Card Game")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# In-memory game registry. Single-process; restarting the server wipes games.
GAMES: Dict[str, GameState] = {}

HUMAN_IDX = 0


# ---------- request bodies ----------

class PlayBody(BaseModel):
    card_id: str
    targets: Optional[Dict] = None


class DiscardBody(BaseModel):
    card_ids: List[str]


# ---------- helpers ----------

def _get(game_id: str) -> GameState:
    s = GAMES.get(game_id)
    if s is None:
        raise HTTPException(404, "game not found")
    return s


def _serialize_card(card: Card) -> dict:
    return card.model_dump(mode="json")


def _snapshot_response(state: GameState, step: Optional[dict] = None) -> dict:
    out = {
        "snapshot": game.public_snapshot(state, HUMAN_IDX),
    }
    if step is not None:
        out["step"] = step
    return out


def _execute_human_play(state: GameState, card_id: str, targets: dict) -> dict:
    me = state.players[HUMAN_IDX]
    card = next((c for c in me.hand if c.id == card_id), None)
    if card is None:
        raise ValueError("card not in hand")
    card_snapshot = _serialize_card(card)
    events = game.play_card(state, HUMAN_IDX, card_id, targets)
    return {
        "actor": HUMAN_IDX,
        "actor_name": me.name,
        "action": "play",
        "card": card_snapshot,
        "targets": targets,
        "events": events,
    }


def _execute_human_discard(state: GameState, card_ids: List[str]) -> dict:
    me = state.players[HUMAN_IDX]
    cards_snapshot = []
    for cid in card_ids:
        card = next((c for c in me.hand if c.id == cid), None)
        if card is None:
            raise ValueError("card not in hand")
        cards_snapshot.append(_serialize_card(card))
    events = game.discard_cards(state, HUMAN_IDX, card_ids)
    return {
        "actor": HUMAN_IDX,
        "actor_name": me.name,
        "action": "discard",
        "cards": cards_snapshot,
        "events": events,
    }


def _execute_auto_step(state: GameState) -> dict:
    """Run exactly one automatic step: bot move, or human auto-pass on empty hand.
    Returns the step descriptor. Raises ValueError if no auto step is appropriate."""
    if state.winner is not None:
        raise ValueError("game over")
    idx = state.current
    p = state.players[idx]

    # Auto-pass for human with empty hand (e.g. after Latex Glove).
    if idx == HUMAN_IDX:
        if p.hand:
            raise ValueError("human has cards — manual action required")
        events = game.pass_turn(state, idx)
        return {
            "actor": idx,
            "actor_name": p.name,
            "action": "pass",
            "events": events,
        }

    # Bot turn.
    kind, payload = bot.choose_action(state, idx)
    if kind == "play":
        card = next(c for c in p.hand if c.id == payload["card_id"])
        card_snapshot = _serialize_card(card)
        targets = payload.get("targets") or {}
        events = game.play_card(state, idx, payload["card_id"], targets)
        return {
            "actor": idx,
            "actor_name": p.name,
            "action": "play",
            "card": card_snapshot,
            "targets": targets,
            "events": events,
        }
    if kind == "discard":
        cards_snapshot = []
        for cid in payload["card_ids"]:
            card = next((c for c in p.hand if c.id == cid), None)
            if card is not None:
                cards_snapshot.append(_serialize_card(card))
        events = game.discard_cards(state, idx, payload["card_ids"])
        return {
            "actor": idx,
            "actor_name": p.name,
            "action": "discard",
            "cards": cards_snapshot,
            "events": events,
        }
    # pass
    events = game.pass_turn(state, idx)
    return {
        "actor": idx,
        "actor_name": p.name,
        "action": "pass",
        "events": events,
    }


# ---------- routes ----------

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.post("/api/new-game")
def new_game_route():
    state = game.new_game()
    GAMES[state.game_id] = state
    return {
        "snapshot": game.public_snapshot(state, HUMAN_IDX),
        "events": [f"New game started — you vs {len(state.players) - 1} bots."],
    }


@app.get("/api/state/{game_id}")
def state_route(game_id: str):
    s = _get(game_id)
    return {"snapshot": game.public_snapshot(s, HUMAN_IDX)}


@app.get("/api/legal/{game_id}/{card_id}")
def legal_targets_route(game_id: str, card_id: str):
    s = _get(game_id)
    if s.current != HUMAN_IDX:
        return {"targets": []}
    human = s.players[HUMAN_IDX]
    card = next((c for c in human.hand if c.id == card_id), None)
    if card is None:
        raise HTTPException(404, "card not in hand")
    return {"targets": legal_play_targets(s, HUMAN_IDX, card), "card_type": card.type.value}


@app.post("/api/play/{game_id}")
def play_route(game_id: str, body: PlayBody):
    s = _get(game_id)
    if s.current != HUMAN_IDX:
        raise HTTPException(400, "not your turn")
    try:
        step = _execute_human_play(s, body.card_id, body.targets or {})
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _snapshot_response(s, step)


@app.post("/api/discard/{game_id}")
def discard_route(game_id: str, body: DiscardBody):
    s = _get(game_id)
    if s.current != HUMAN_IDX:
        raise HTTPException(400, "not your turn")
    try:
        step = _execute_human_discard(s, body.card_ids)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _snapshot_response(s, step)


@app.post("/api/auto-step/{game_id}")
def auto_step_route(game_id: str):
    """Execute one automatic step (a bot's turn, or human auto-pass on empty hand).
    Frontend polls this between human turns to pace each bot's thinking time."""
    s = _get(game_id)
    try:
        step = _execute_auto_step(s)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _snapshot_response(s, step)
