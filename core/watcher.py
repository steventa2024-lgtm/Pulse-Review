"""Polling-based repository watching (no webhook server required)."""
from __future__ import annotations

from dataclasses import dataclass

from .db import Database
from .github_client import GitHubClient, parse_repo_name


@dataclass
class RefreshResult:
    repo: str
    not_modified: bool
    new: int = 0
    updated: int = 0
    total_open: int = 0


class WatchService:
    def __init__(self, github: GitHubClient, db: Database) -> None:
        self.github, self.db = github, db

    def add_repo(self, name: str) -> str:
        owner, repo = parse_repo_name(name)
        access = self.github.validate_repo_access(owner, repo)  # raises GitHubError if inaccessible
        self.db.add_watched_repo(access.full_name)
        return access.full_name

    def refresh(self, repo: str) -> RefreshResult:
        row = next((r for r in self.db.list_watched_repos() if r["repo"] == repo), None)
        etag = row["etag"] if row else None
        poll = self.github.list_open_prs(repo, etag)
        if poll.not_modified:
            self.db.set_repo_poll(repo, None)
            return RefreshResult(repo, True, total_open=len(self.db.list_watched_prs(repo)))
        new = updated = 0
        seen: set[int] = set()
        for pr in poll.prs:
            seen.add(pr.number)
            prev = self.db.get_watched_pr(repo, pr.number)
            if prev is None:
                indicator, new = "new", new + 1
            elif prev["head_sha"] != pr.head_sha:
                indicator, updated = "updated", updated + 1
            else:
                indicator = prev["indicator"]
            self.db.upsert_watched_pr(repo, pr.number, title=pr.title, author=pr.author, url=pr.url,
                                      head_sha=pr.head_sha, indicator=indicator)
        if len(poll.prs) < 100:  # complete listing → PRs that vanished are closed/merged
            self.db.close_missing_prs(repo, seen)
        self.db.set_repo_poll(repo, poll.etag)
        return RefreshResult(repo, False, new, updated, len(poll.prs))

    def refresh_all(self) -> list[RefreshResult]:
        return [self.refresh(r["repo"]) for r in self.db.list_watched_repos()]

    def needs_analysis(self, repo: str) -> list[dict]:
        """Open, non-draft PRs whose current head SHA has never been reviewed (never re-processes unchanged PRs)."""
        out = []
        for pr in self.db.list_watched_prs(repo):
            if pr["reviewed_sha"] == pr["head_sha"] or pr["head_sha"] in self.db.reviewed_shas(repo, pr["pr_number"]):
                continue
            out.append(pr)
        return out
