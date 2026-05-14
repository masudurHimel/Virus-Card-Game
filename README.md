# Virus! Card Game

A browser-playable implementation of the Virus! card game. One human plays against three bots; the first player to assemble four healthy organs wins.

## Gameplay

Each player builds a body of four different-colored organs (red, green, blue, yellow) and attacks opponents with viruses. Hand size is three cards; on your turn you either play one card or discard any number, then refill to three.

**Deck — 68 cards:**
- 21 **Organs** (5 per color + 1 multicolor wild)
- 17 **Viruses** (4 per color + 1 multicolor)
- 20 **Medicines** (4 per color + 4 multicolor)
- 10 **Treatments** (2 each of 5 kinds: Transplant, Organ Thief, Contagion, Latex Glove, Medical Error)

Organ states cycle through *healthy → infected → vaccinated → immunized* (or destroyed) depending on viruses and medicines applied. Immunized organs are locked in and count toward your win.

## Tech stack

- **Backend:** FastAPI + Pydantic (Python 3.11+)
- **Frontend:** vanilla JS, CSS, inline SVG card art
- **State:** in-memory game registry (single process; restarts wipe games)

## Project layout

```
app/
  models.py     # Card, Organ, Player, GameState dataclasses
  deck.py       # 68-card deck builder, shuffle, draw
  actions.py    # Pure functions for every card effect + legal-target enumeration
  game.py       # Turn loop, win check, public snapshot, event log
  bot.py        # Hard heuristic AI
  main.py       # FastAPI routes
templates/
  index.html
static/
  css/ js/ svg/
```

## Run

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
./run.sh
```

Open <http://127.0.0.1:8002>.

`run.sh` launches `uvicorn app.main:app --reload` on port 8002.

## API

| Method | Path | Purpose |
|---|---|---|
| `GET`  | `/` | Game UI |
| `POST` | `/api/new-game` | Start a new game, returns `game_id` |
| `GET`  | `/api/state/{game_id}` | Current public snapshot |
| `GET`  | `/api/legal/{game_id}/{card_id}` | Legal targets for a card in hand |
| `POST` | `/api/play/{game_id}` | Play a card: `{card_id, targets}` |
| `POST` | `/api/discard/{game_id}` | Discard cards: `{card_ids}` |
| `POST` | `/api/auto-step/{game_id}` | Advance one bot turn (frontend polls between human turns) |

## Tests / harness scripts

- `sim.py` — headless game simulation
- `http_smoke.py` — exercises the HTTP API
- `browser_test.py`, `snap_dealt.py`, `snap_playing.py` — Playwright-based UI checks and screenshots
