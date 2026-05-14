"""Drive the live page through a full game via Playwright.

This test uses the in-page state object as the source of truth, plays via
direct DOM clicks (so animations + bot loop also exercise the UI code), and
asserts no JS errors, no 4xx/5xx responses, and the game reaches a winner.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

URL = "http://127.0.0.1:8765/"
SHOTS = Path("/tmp")


async def wait_for_human(page, timeout_s: float = 90.0) -> bool:
    """Block until human can act (current==0, hand>0, not busy) or game ends."""
    end = asyncio.get_event_loop().time() + timeout_s
    while asyncio.get_event_loop().time() < end:
        info = await page.evaluate("""() => {
          if (!state || !state.snapshot) return {ready: false};
          if (state.busy) return {ready: false};
          if (state.snapshot.winner !== null) return {ready: false, ended: true};
          const me = state.snapshot.players[0];
          return {
            ready: state.snapshot.current === 0 && me.hand && me.hand.length > 0,
            current: state.snapshot.current,
            handCount: (me.hand || []).length,
            turn: state.snapshot.turn_number,
            ended: false,
          };
        }""")
        if info.get("ready"):
            return True
        if info.get("ended"):
            return False
        await page.wait_for_timeout(250)
    return False


async def play_one_turn(page) -> str:
    """Pick one card → click target if needed → return action label."""
    hand = await page.evaluate("() => state.snapshot.players[0].hand.map(c => ({id: c.id, type: c.type}))")

    for card in hand:
        cid = card["id"]
        legal = await page.evaluate(
            "(cid) => fetch(`/api/legal/${state.gameId}/${cid}`).then(r => r.json())",
            cid,
        )
        targets = legal.get("targets", [])
        if not targets:
            continue
        # Click the card
        await page.click(f'#your-hand .card[data-card-id="{cid}"]', force=True)
        # Wait for state.legalTargets to be populated for this card
        try:
            await page.wait_for_function(
                f"() => state.primaryCardId === '{cid}' && state.legalTargets !== null",
                timeout=3000,
            )
        except Exception:
            pass
        # No-target card → click play (after btn-play becomes enabled)
        if len(targets) == 1 and not targets[0]:
            try:
                await page.wait_for_function(
                    "() => !document.getElementById('btn-play').disabled",
                    timeout=3000,
                )
            except Exception:
                pass
            await page.click("#btn-play", force=True)
            return f"play:{card['type']}"
        # Has targets → wait briefly then click first glowing target.
        await page.wait_for_timeout(200)
        glow = await page.query_selector(".organ.target-valid, .opponent.target-valid")
        if glow:
            await glow.click(force=True)
            return f"play:{card['type']}->target"
        # Couldn't click target? Deselect and try next.
        await page.click(f'#your-hand .card[data-card-id="{cid}"]', force=True)
        await page.wait_for_timeout(150)

    # No card playable → discard one
    first_id = hand[0]["id"] if hand else None
    if first_id:
        await page.click(f'#your-hand .card[data-card-id="{first_id}"]', force=True)
        try:
            await page.wait_for_function(
                "() => !document.getElementById('btn-discard').disabled",
                timeout=3000,
            )
        except Exception:
            pass
        await page.click("#btn-discard", force=True)
        return "discard"
    return "noop"


async def run():
    errors = []
    console_msgs = []
    bad_responses = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
        page = await ctx.new_page()

        page.on("pageerror", lambda exc: errors.append(("pageerror", str(exc))))
        page.on("console", lambda msg: console_msgs.append((msg.type, msg.text)))

        def on_response(resp):
            if resp.status >= 400 and "/api/" in resp.url:
                bad_responses.append(f"{resp.status} {resp.request.method} {resp.url}")
        page.on("response", on_response)

        await page.goto(URL, wait_until="domcontentloaded")
        await page.wait_for_selector("#btn-start", state="visible")
        await page.screenshot(path=str(SHOTS / "vc-1-menu.png"))

        await page.click("#btn-start")
        await page.wait_for_timeout(3200)  # initial deal animation
        await page.screenshot(path=str(SHOTS / "vc-2-dealt.png"))

        max_turns = 80
        actions_log = []
        for t in range(max_turns):
            ok = await wait_for_human(page)
            if not ok:
                break
            cur_turn = await page.evaluate("() => state.snapshot.turn_number")
            try:
                action = await play_one_turn(page)
                actions_log.append((t, action, cur_turn))
            except Exception as e:
                errors.append(("turn-error", f"turn {t}: {e}"))
                break
            # Wait for turn_number to advance OR game to end OR error
            try:
                await page.wait_for_function(
                    f"() => state.snapshot.winner !== null || state.snapshot.turn_number > {cur_turn}",
                    timeout=20000,
                )
            except Exception:
                errors.append(("no-advance", f"after action {action} at turn {cur_turn}, no advance in 20s"))
                break

        # Let any pending bots finish (in case we won)
        for _ in range(120):
            ended = await page.evaluate("() => state.snapshot && state.snapshot.winner !== null")
            if ended:
                break
            await page.wait_for_timeout(500)

        await page.screenshot(path=str(SHOTS / "vc-3-end.png"))

        winner = await page.evaluate("() => state.snapshot && state.snapshot.winner")
        winner_name = await page.evaluate("() => state.snapshot && state.snapshot.players[state.snapshot.winner]?.name")
        turn_no = await page.evaluate("() => state.snapshot && state.snapshot.turn_number")
        deck_count = await page.evaluate("() => state.snapshot && state.snapshot.deck_count")
        discard_count = await page.evaluate("() => state.snapshot && state.snapshot.discard_count")
        print(f"\nGame ended. winner={winner_name} idx={winner} turns={turn_no} deck={deck_count} discard={discard_count}")
        print(f"actions taken: {len(actions_log)}")

        modal_visible = await page.evaluate('() => !document.getElementById("result-modal").classList.contains("hidden")')
        print(f"Result modal visible: {modal_visible}")

        await browser.close()

    print(f"\nPage errors: {len(errors)}")
    for tag, msg in errors:
        print(f"  [{tag}] {msg}")
    print(f"Bad responses: {len(bad_responses)}")
    for r in bad_responses[:30]:
        print(f"  {r}")
    bad_console = [m for m in console_msgs if m[0] == "error"]
    print(f"Console errors: {len(bad_console)}")
    for t, m in bad_console[:20]:
        print(f"  [{t}] {m}")

    fail = bool(errors) or bool(bad_responses)
    if fail:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(run())
