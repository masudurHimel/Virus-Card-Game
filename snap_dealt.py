"""Take a screenshot of the dealt-state at multiple viewport sizes."""
import asyncio
from playwright.async_api import async_playwright

URL = "http://127.0.0.1:8765/"


async def snap(p, w, h, path):
    browser = await p.chromium.launch(headless=True)
    ctx = await browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=2)
    page = await ctx.new_page()
    await page.goto(URL, wait_until="domcontentloaded")
    await page.wait_for_selector("#btn-start", state="visible")
    await page.click("#btn-start")
    await page.wait_for_timeout(3200)
    await page.screenshot(path=path)
    await browser.close()
    print(f"wrote {path}")


async def main():
    async with async_playwright() as p:
        await snap(p, 1440, 900, "/tmp/dealt-1440x900.png")
        await snap(p, 1280, 800, "/tmp/dealt-1280x800.png")
        await snap(p, 1920, 1080, "/tmp/dealt-1920x1080.png")
        await snap(p, 1366, 768, "/tmp/dealt-1366x768.png")


if __name__ == "__main__":
    asyncio.run(main())
