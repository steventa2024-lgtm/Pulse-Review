"""Capture real screenshots of the running app (see demo_app.py) into website/public/screenshots/.

    python website/scripts/capture_screenshots.py http://127.0.0.1:8790
Needs: playwright (+ a Chromium), Pillow.
"""
import sys
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8790"
OUT = Path(__file__).resolve().parents[1] / "public" / "screenshots"
CHROME = sys.argv[2] if len(sys.argv) > 2 else None
W, H = 1440, 900


def pick(page, index, text):
    page.locator(".q-select").nth(index).click()
    page.locator(".q-menu .q-item", has_text=text).first.click()


def save(page, name, full=False):
    png = OUT / f"{name}.png"
    page.screenshot(path=str(png), full_page=full)
    img = Image.open(png).convert("RGB")
    img.save(OUT / f"{name}.webp", "WEBP", quality=88, method=6)
    png.unlink()
    print(name, img.size)


with sync_playwright() as p:
    OUT.mkdir(parents=True, exist_ok=True)
    browser = p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"]) if CHROME else p.chromium.launch()
    page = browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=2)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    # two real reviews through the actual pipeline, so history/results/test lab contain genuine output
    for _ in range(2):
        page.goto(BASE + "/review/new")
        page.wait_for_timeout(1500)
        pick(page, 0, "shop-service")
        page.wait_for_timeout(900)
        pick(page, 1, "#7")
        page.wait_for_selector("text=Add discount cap and qty parser", timeout=10000)
        page.get_by_role("button", name="Start review").click()
        page.wait_for_url("**/review/*", timeout=30000)
    review_url = page.url
    page.wait_for_timeout(1500)
    save(page, "review-results")

    page.goto(BASE + "/review/new")
    page.wait_for_timeout(1500)
    pick(page, 0, "shop-service")
    page.wait_for_timeout(900)
    pick(page, 1, "#7")
    page.wait_for_selector("text=Add discount cap and qty parser", timeout=10000)
    page.wait_for_timeout(600)
    save(page, "new-review")

    page.goto(BASE + "/code")
    page.wait_for_timeout(1500)
    pick(page, 0, "shop-service")
    page.wait_for_selector(".q-tree__node-header", timeout=10000)
    page.get_by_role("button", name="Run code review").click()
    page.wait_for_url("**/code/*", timeout=30000)
    page.wait_for_timeout(1800)
    save(page, "code-reviewer")

    for name, path in [("dashboard", "/"), ("review-history", "/history"), ("watched-repositories", "/watch"),
                       ("test-lab", "/testlab"), ("settings", "/settings?tab=ai")]:
        page.goto(BASE + path)
        page.wait_for_timeout(2500)
        if name == "watched-repositories":
            page.get_by_placeholder("owner/repo  (e.g. octocat/hello-world)").fill("demo-user/shop-service")
            page.get_by_role("button", name="Watch").click()
            page.wait_for_timeout(8000)  # let the notifications fade before capturing
        save(page, name)
    print("errors:", errors)
    browser.close()
