# Virus! Card Game — Build Tasks

Reference: full plan at `~/.claude/plans/i-want-to-create-scalable-lemur.md`.

Tasks are executed in order. Each one is committed (in source-control terms) before the next begins.

| # | Task | Status |
|---|---|---|
| 1 | Set up project structure & install dependencies | done |
| 2 | Build `app/models.py` and `app/deck.py` (Card, Organ, Player, GameState + 68-card deck builder) | done |
| 3 | Implement `app/actions.py` — pure functions for every card effect (organ, virus, medicine, 5 treatments) + legal-target enumeration | done |
| 4 | Implement `app/game.py` — turn loop, win check, client-POV state snapshot, event log | done |
| 5 | Implement `app/bot.py` — "Hard" heuristic AI (self-preservation, build-to-win, attack-leader, resource-value, discard fallback) | done |
| 6 | Build `app/main.py` FastAPI routes (`/`, `/api/new-game`, `/api/state`, `/api/play`, `/api/discard`) + in-memory game registry + auto-advance bot turns | done |
| 7 | Build `templates/index.html` + `static/css/styles.css` + SVG icons (card visuals, 4-player layout, log panel) | done |
| 8 | Wire `static/js/render.js` + `static/js/app.js` (state→DOM, click handlers, multicolor picker, animation sequencing) | done |
| 9 | End-to-end browser test + tune bot weights for challenge | done |

## How to run

```bash
source venv/bin/activate
./run.sh        # or: uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000.
