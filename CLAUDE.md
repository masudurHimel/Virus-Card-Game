# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Run / dev

- `./run.sh` — boots uvicorn with `--reload` on `127.0.0.1:8002` using the vendored `./venv`. The script execs the venv's uvicorn directly, so you do **not** need to activate the venv first.
- Dependencies are installed inside `./venv` (see `requirements.txt`). When adding deps, install with `./venv/bin/pip install …` so `run.sh` picks them up.
- The app serves `/` (HTML), `/static/*`, and `/api/*` JSON. Open `http://127.0.0.1:8002/` after starting.

## Smoke tests

- `http_smoke.py` drives full games through the live HTTP API by replaying the bot's `choose_action` for the "human" seat. It expects the server on **port 8765** (hardcoded `BASE`) — either edit `BASE` or run uvicorn on 8765 before invoking. Usage: `./venv/bin/python http_smoke.py [N_GAMES]` (default 3).
- `sim.py` runs games entirely in-process against the game engine (no HTTP). Use this for fast bot-tuning iteration.
- `snap_dealt.py` / `snap_playing.py` capture Playwright screenshots of the rendered UI in specific game states (Playwright is **not** in `requirements.txt` — install separately if you need them).
- There is no unit-test suite; the smoke scripts are the regression net. If you change rule logic in `app/actions.py` or `app/bot.py`, re-run `sim.py` (and ideally `http_smoke.py`) before committing.

## Architecture

This is a single-process FastAPI app implementing the Spanish card game **Virus!** as human-vs-3-bots. All state lives in memory; restarting the server wipes games.

### Layering (`app/`)

The engine is split into pure layers, each importable without the one above:

1. `models.py` — Pydantic models: `Card`, `Organ`, `Player`, `GameState`, plus enums (`Color`, `CardType`, `TreatmentKind`, `OrganStatus`). `Organ.status` is **derived** from attached cards (2 medicines → IMMUNIZED, etc.), and `Player.has_won()` encodes the 4-distinct-healthy-colors rule including MULTI wildcards.
2. `deck.py` — Builds the canonical 68-card deck (21 organs / 17 viruses / 20 medicines / 10 treatments) and reshuffle-on-empty draw helper.
3. `actions.py` — **The rule book.** Every card effect is a pure function that mutates `GameState` and returns event strings; raises `ValueError` on illegal plays. Two exports drive everything else:
   - `apply_play(state, idx, card_id, targets)` — execute one card. `targets` is a dict like `{"player": int, "organ_id": str | None}`; transplant/contagion use compound shapes.
   - `legal_play_targets(state, idx, card)` — enumerate every legal `targets` dict for a card. Used by the bot **and** by the `/api/legal` endpoint to drive the UI's target picker. Returns `[{}]` for no-target cards; `[]` if unplayable.
4. `game.py` — Turn loop: `play_card` / `discard_cards` / `pass_turn` each call into `actions`, then `check_winner`, then `end_turn_draw` (refill to 3), then `advance_turn`. Also owns `public_snapshot(state, viewer_idx)`, which hides other players' hand **contents** (only `hand_count` is exposed); this is the only shape the frontend ever sees.
5. `bot.py` — `choose_action(state, idx)` returns `("play"|"discard"|"pass", payload)`. Pure heuristic AI, no search.
6. `main.py` — FastAPI surface. Holds the global `GAMES: Dict[str, GameState]` registry and the `HUMAN_IDX = 0` convention. Notable endpoint: `POST /api/auto-step/{game_id}` — runs **one** automatic step (a bot move, or an auto-pass when the human has an empty hand). The frontend polls this between human turns so each bot move is a discrete animation frame; do not collapse it into a "run until human" loop without updating the client.

### Frontend (`static/` + `templates/index.html`)

- `static/js/app.js` — orchestrates the click-flow and the auto-step polling loop.
- `static/js/render.js` — pure `snapshot → DOM`. Re-render on every API response.
- The client never holds authoritative state; it re-renders from the latest `snapshot` returned by `/api/{new-game,play,discard,auto-step,state}`.

### Invariants worth knowing before editing

- **`actions.py` is the only place that mutates organs/hands.** `game.py` orchestrates but never reaches into `Player.body` or `Player.hand` itself. Keep it that way.
- **The Pydantic models are the wire format.** `public_snapshot` calls `model_dump(mode="json")` on cards/organs; the JS expects exactly those keys.
- **Templates use the modern Starlette signature** `templates.TemplateResponse(request, "index.html")`. The legacy `(name, {"request": request})` form crashes deep in Jinja's cache on this Starlette version — don't switch back.
- **`Organ.status` is computed, not stored** — never try to set it; mutate `Organ.attached` instead and let the property recompute.

## Port / URL drift

`run.sh` uses 8002, `http_smoke.py` hardcodes 8765, `tasks.md` mentions 8000. `run.sh` is the source of truth for local dev; align the others when you touch them.
