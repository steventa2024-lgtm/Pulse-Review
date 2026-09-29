"""Run the REAL ZeroPulse dashboard with sample data, for capturing website screenshots.

Only GitHub and the model are replaced by offline fakes (sample repositories and a scripted model reply);
every page, component and style is the actual application code.  Usage (from the repo root):

    ZEROPULSE_DATA_DIR=<scratch dir> python website/scripts/demo_app.py 8790
"""
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("GITHUB_TOKEN", "demo-token")
os.environ.setdefault("OPENROUTER_API_KEY", "demo-key")

import io  # noqa: E402
import zipfile  # noqa: E402

from core.github_client import GitHubClient  # noqa: E402
from core.providers.base import ModelInfo  # noqa: E402
from core.sandbox.runner import SandboxResult, SandboxRunner  # noqa: E402
from core.services import AppServices  # noqa: E402
from tests.fixtures.pr_fixture import GOOD_REVIEW, GOOD_TEST, ORDERS_SRC, FakeProvider, make_gh  # noqa: E402

LOGIN = "demo-user"
gh, pull = make_gh()
gh.repo.full_name = "demo-user/shop-service"
gh.repo.pushed_at = datetime(2026, 9, 28, tzinfo=timezone.utc)
pull.html_url = "https://github.com/demo-user/shop-service/pull/7"
gh.get_user = lambda: NS(login=LOGIN, name="Demo User", html_url=f"https://github.com/{LOGIN}", avatar_url="",
                          get_repos=lambda sort=None: [gh.repo])
gh.repo.get_pulls = lambda state="open", sort="updated", direction="desc": [NS(
    number=7, title=pull.title, user=pull.user, html_url=pull.html_url, head=pull.head,
    updated_at=datetime(2026, 9, 28, tzinfo=timezone.utc), draft=False)]
gh.repo.get_branch = lambda b: NS(commit=NS(sha="4f2c9a1" + "0" * 33))
gh.repo.get_branches = lambda: [NS(name="main"), NS(name="feature/discount")]

SUMMARY = {"summary": "The change adds a discount cap and a quantity parser. Input validation is missing in both, and a "
                      "hard-coded token was committed in app/auth.py.", "overall_risk": "high", "issues": []}
MODELS = [ModelInfo(id="qwen/qwen3-coder-next:free", context_length=262144, is_free=True, recommended=True),
          ModelInfo(id="cohere/north-mini-code:free", context_length=256000, is_free=True, recommended=True),
          ModelInfo(id="nvidia/nemotron-3.5-lightning:free", context_length=1000000, is_free=True, recommended=True)]


class DemoSandbox(SandboxRunner):
    name = "docker"

    def available(self):
        return True, ""

    def run(self, req, cancel=None):
        return SandboxResult("failed", 1, 1, 2.4, "1 failed, 1 passed in 2.40s", "docker")


def _archive(self, ref, sha, max_bytes=0):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("shop-service-4f2c9a1/app/orders.py", ORDERS_SRC)
        z.writestr("shop-service-4f2c9a1/app/auth.py", 'API_TOKEN = "ghp_' + "Q7x9" * 9 + '"\ndef login(u, p):\n    return True\n')
        z.writestr("shop-service-4f2c9a1/README.md", "# Shop service\n")
    return buf.getvalue()


FakeProvider.review_models = lambda self, force=False: MODELS
FakeProvider.list_models = lambda self: [ModelInfo(id="qwen3-coder:30b", is_free=True), ModelInfo(id="qwen2.5-coder:7b", is_free=True)]
AppServices.github = lambda self: GitHubClient("t", gh=gh)
AppServices.provider = lambda self, provider=None, model=None: FakeProvider(
    [GOOD_REVIEW, SUMMARY, GOOD_TEST], model=model or "qwen/qwen3-coder-next:free")
AppServices.sandbox = lambda self: DemoSandbox()
GitHubClient.download_archive = _archive


def _open_prs(self, repo, etag=None, max_pages=3):
    from core.github_client import OpenPR, PollResult
    return PollResult(False, [
        OpenPR(7, pull.title, "dev1", pull.html_url, pull.head.sha, "2026-09-28T10:00:00Z"),
        OpenPR(9, "Add CSV export for orders", "dev2", "https://github.com/demo-user/shop-service/pull/9", "a" * 40, "2026-09-28T12:00:00Z"),
    ], 'W/"demo"')


GitHubClient.list_open_prs = _open_prs

# Show the same storage location the Windows app shows (only the displayed path; the sqlite file lives in the cwd).
import core.paths as _paths  # noqa: E402

_paths.db_path = lambda: Path(r"C:\Users\demo\AppData\Roaming\ZeroPulse\PRReviewAgent\reviews.db") \
    if sys.platform != "win32" else _paths.data_dir() / "reviews.db"

if __name__ == "__main__":
    from dashboard.app import run_app
    run_app(native=False, port=int(sys.argv[1]) if len(sys.argv) > 1 else 8790, show=False)
