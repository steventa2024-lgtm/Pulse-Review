"""Auto-analysis of watched PRs: analysis only, never publishes, never re-processes unchanged PRs."""
from core.db import Database
from dashboard.context import Ctx


class FakeJobs:
    def __init__(self):
        self.started = []

    def active(self):
        return []

    def start(self, url, options, provider, model):
        self.started.append(url)


class FakeWatcher:
    def __init__(self, db):
        self.db = db

    def needs_analysis(self, repo):
        return [p for p in self.db.list_watched_prs(repo) if p["reviewed_sha"] != p["head_sha"]]


class FakeSvc:
    def __init__(self, db):
        self.db = db
        self.published = 0
        from core.config import AppConfig
        self.cfg = AppConfig()

    def watcher(self):
        return FakeWatcher(self.db)

    def review_options(self):
        return object()

    def publisher(self):  # must never be used by auto-analysis
        self.published += 1
        raise AssertionError("auto-analysis must not publish")


def test_auto_analyze_starts_one_review_for_new_or_updated_pr_and_never_publishes(tmp_path):
    db = Database(tmp_path / "w.db")
    db.add_watched_repo("acme/shop")
    db.upsert_watched_pr("acme/shop", 5, title="a", author="u", url="https://github.com/acme/shop/pull/5", head_sha="s1", indicator="new")
    db.upsert_watched_pr("acme/shop", 6, title="b", author="u", url="https://github.com/acme/shop/pull/6", head_sha="s2", indicator="none")
    svc, jobs = FakeSvc(db), FakeJobs()
    Ctx(services=svc, jobs=jobs)._auto_analyze()
    assert jobs.started == ["https://github.com/acme/shop/pull/5"]  # only the new/updated one, one at a time
    assert svc.published == 0
