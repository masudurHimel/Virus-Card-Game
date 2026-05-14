"""Take a screenshot after a few moves so we see organs in the player's body."""
import asyncio
from playwright.async_api import async_playwright

URL = "http://127.0.0.1:8765/"


async def play_one_turn(page):
    hand = await page.evaluate("() => state.snapshot.players[0].hand.map(c => ({id: c.id, type: c.type}))")
    for card in hand:
        cid = card["id"]
        legal = await page.evaluate(
            "(cid) => fetch(`/api/legal/${state.gameId}/${cid}`).then(r => r.json())", cid)
        targets = legal.get("targets", [])
        if not targets:
            continue
        await page.click(f'#your-hand .card[data-card-id="{cid}"]', force=True)
        try:
            await page.wait_for_function(
                f"() => state.primaryCardId === '{cid}' && state.legalTargets !== null",
                timeout=3000,
            )
        except Exception:
            pass
        if len(targets) == 1 and not targets[0]:
            try:
                await page.wait_for_function(
                    "() => !document.getElementById('btn-play').disabled", timeout=3000)
            except Exception:
                pass
            await page.click("#btn-play", force=True)
            return
        await page.wait_for_timeout(200)
        glow = await page.query_selector(".organ.target-valid, .opponent.target-valid")
        if glow:
            await glow.click(force=True)
            return
        await page.click(f'#your-hand .card[data-card-id="{cid}"]', force=True)
        await page.wait_for_timeout(150)
    first_id = hand[0]["id"] if hand else None
    if first_id:
        await page.click(f'#your-hand .card[data-card-id="{first_id}"]', force=True)
        try:
            await page.wait_for_function(
                "() => !document.getElementById('btn-discard').disabled", timeout=3000)
        except Exception:
            pass
        await page.click("#btn-discard", force=True)


async def wait_for_human(page, timeout_s=60.0):
    end = asyncio.get_event_loop().time() + timeout_s
    while asyncio.get_event_loop().time() < end:
        info = await page.evaluate("""() => {
          if (!state || !state.snapshot) return {ready: false};
          if (state.busy) return {ready: false};
          if (state.snapshot.winner !== null) return {ready: false, ended: true};
          const me = state.snapshot.players[0];
          return { ready: state.snapshot.current === 0 && me.hand && me.hand.length > 0, ended: false };
        }""")
        if info.get("ready"): return True
        if info.get("ended"): return False
        await page.wait_for_timeout(250)
    return False


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
        page = await ctx.new_page()
        await page.goto(URL, wait_until="domcontentloaded")
        await page.wait_for_selector("#btn-start", state="visible")
        await page.click("#btn-start")
        await page.wait_for_timeout(3300)

        # Play several turns to build organs
        for _ in range(8):
            ok = await wait_for_human(page)
            if not ok:
                break
            cur_turn = await page.evaluate("() => state.snapshot.turn_number")
            await play_one_turn(page)
            try:
                await page.wait_for_function(
                    f"() => state.snapshot.winner !== null || state.snapshot.turn_number > {cur_turn}",
                    timeout=20000)
            except Exception:
                break
            await page.wait_for_timeout(300)

        # Wait until human's turn again
        await wait_for_human(page)
        await page.screenshot(path="/tmp/playing-1440x900.png")
        await page.screenshot(path="/tmp/playing-clip.png", clip={"x": 0, "y": 600, "width": 1440, "height": 300})
        print("wrote /tmp/playing-1440x900.png")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
