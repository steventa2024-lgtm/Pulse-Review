"""Browser-driven checks of the real dashboard (skipped when Playwright/Chromium are unavailable)."""
import glob
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

pw = pytest.importorskip("playwright.sync_api")
ROOT = Path(__file__).resolve().parents[2]
URL = "https://github.com/acme/shop/pull/7"


def _chrome() -> str | None:
    hits = glob.glob("/opt/pw-browsers/chromium-*/chrome-linux/chrome")
    return hits[0] if hits else None


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**{k: v for k, v in os.environ.items() if not k.startswith("PYTEST_")}, "ZEROPULSE_DATA_DIR": str(tmp_path_factory.mktemp("uidata"))}
    proc = subprocess.Popen([sys.executable, "-m", "tests.ui.launcher", str(port)], cwd=ROOT, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            if httpx.get(base + "/", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.5)
    else:
        proc.kill()
        pytest.fail("dashboard did not start: " + proc.stdout.read().decode()[-2000:])
    yield base
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture(scope="module")
def page(server):
    with pw.sync_playwright() as p:
        kw = {"executable_path": _chrome()} if _chrome() else {}
        try:
            browser = p.chromium.launch(args=["--no-sandbox"], **kw)
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"Chromium unavailable: {exc}")
        pg = browser.new_page(viewport={"width": 1440, "height": 900})
        pg.errors = []
        pg.on("pageerror", lambda e: pg.errors.append(str(e)))
        yield pg
        browser.close()


def test_all_pages_render_without_js_errors(server, page):
    for path, text in [("/", "Dashboard"), ("/review/new", "New Review"), ("/history", "Review History"),
                       ("/watch", "Watched Repositories"), ("/testlab", "Test Lab"), ("/settings", "Settings")]:
        page.goto(server + path)
        page.wait_for_selector(f"text={text}", timeout=10000)
    assert page.errors == []
    assert page.locator("text=ZeroPulse").first.is_visible()


def test_server_is_bound_to_loopback_only(server):
    assert "127.0.0.1" in server


def test_review_flow_progress_results_and_manual_publish(server, page):
    page.goto(server + "/review/new")
    page.fill("input[aria-label='Pull-request URL']", URL)
    page.fill("input[aria-label='Or enter a model id manually']", "qwen/qwen3-coder:free")
    page.click("text=START REVIEW")
    # real pipeline stage labels appear (no percentages)
    page.wait_for_selector("text=Analyzing code changes", timeout=10000)
    page.wait_for_url("**/review/*", timeout=30000)
    page.wait_for_selector("text=Detected issues (3)", timeout=10000)
    body = page.inner_text("body")
    assert "Possible credential committed" in body and "parse_qty crashes on invalid input" in body
    assert "Sandbox unavailable — generated test has not been executed." in body
    assert "tests/test_orders.py" in body and "artifact: generated" in body and "execution: not run" in body
    assert "ghost.py" not in body  # hallucinated file was discarded
    # nothing is published just by generating a review
    assert httpx.get(server + "/__test/posted").json() == []
    # publish requires an explicit typed confirmation
    page.click("text=Preview & post…")
    page.wait_for_selector("text=Post review to acme/shop#7", timeout=10000)
    post = page.locator("button:has-text('Post to GitHub')")
    assert post.is_disabled()
    page.fill("input[aria-label='Type acme/shop#7 to confirm']", "acme/shop#8")
    assert post.is_disabled()
    page.fill("input[aria-label='Type acme/shop#7 to confirm']", "acme/shop#7")
    assert post.is_enabled()
    page.click("button:has-text('Post to GitHub')")
    page.wait_for_selector("text=Publication history", timeout=15000)
    posted = httpx.get(server + "/__test/posted").json()
    assert len(posted) == 1 and posted[0]["event"] == "COMMENT" and "ZeroPulse PR Review" in posted[0]["body"]
    assert "Posted" in page.inner_text("body")


def test_stale_pr_blocks_publishing_in_ui(server, page):
    page.goto(server + "/review/new")
    page.fill("input[aria-label='Pull-request URL']", URL)
    page.fill("input[aria-label='Or enter a model id manually']", "qwen/qwen3-coder:free")
    page.click("text=START REVIEW")
    page.wait_for_url("**/review/*", timeout=30000)
    page.wait_for_selector("text=Detected issues", timeout=10000)
    httpx.get(server + "/__test/push")  # author pushes a new commit after the review
    page.click("text=Preview & post…")
    page.wait_for_selector("text=changed after this review was generated", timeout=10000)
    assert page.locator("button:has-text('Preview & post…')").is_disabled()
    assert len(httpx.get(server + "/__test/posted").json()) == 1  # still only the earlier explicit post


def test_history_persists_and_delete_works(server, page):
    page.goto(server + "/history")
    page.wait_for_selector("text=acme/shop", timeout=10000)
    assert page.locator("tbody tr").count() >= 2
    before = page.locator("tbody tr").count()
    page.locator("button:has(i:text('delete_outline'))").first.click()
    page.locator(".q-dialog").get_by_role("button", name="Delete", exact=True).click()
    page.wait_for_timeout(1500)
    assert page.locator("tbody tr").count() == before - 1


def test_invalid_url_gives_clear_error_in_ui(server, page):
    page.goto(server + "/review/new")
    page.fill("input[aria-label='Pull-request URL']", "https://evil.example.com/a/b/pull/1")
    page.click("button:has-text('Check')")
    page.wait_for_selector("text=Only github.com pull-request URLs are supported.", timeout=5000)
