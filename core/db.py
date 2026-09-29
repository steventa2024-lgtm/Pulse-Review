"""SQLite persistence (stdlib sqlite3, parameterised SQL, versioned migrations)."""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from . import paths
from .schemas import ReviewResult, ReviewStatus, utcnow_iso

MIGRATIONS: list[str] = [
    # v1 -------------------------------------------------------------------------------
    """
    CREATE TABLE reviews (
        id TEXT PRIMARY KEY,
        repo TEXT NOT NULL,
        pr_number INTEGER NOT NULL,
        pr_url TEXT NOT NULL,
        pr_title TEXT NOT NULL DEFAULT '',
        author TEXT NOT NULL DEFAULT '',
        head_sha TEXT NOT NULL DEFAULT '',
        base_sha TEXT NOT NULL DEFAULT '',
        provider TEXT NOT NULL DEFAULT '',
        model TEXT NOT NULL DEFAULT '',
        depth TEXT NOT NULL DEFAULT 'standard',
        status TEXT NOT NULL DEFAULT 'pending',
        stage_detail TEXT NOT NULL DEFAULT '',
        overall_risk TEXT NOT NULL DEFAULT 'low',
        summary TEXT NOT NULL DEFAULT '',
        findings_count INTEGER NOT NULL DEFAULT 0,
        private_repo INTEGER NOT NULL DEFAULT 0,
        error TEXT,
        result_json TEXT,
        pr_json TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX idx_reviews_repo_pr ON reviews(repo, pr_number);
    CREATE TABLE findings (
        id TEXT NOT NULL,
        review_id TEXT NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
        severity TEXT NOT NULL, category TEXT NOT NULL,
        file TEXT NOT NULL, line INTEGER, side TEXT NOT NULL DEFAULT 'RIGHT',
        title TEXT NOT NULL, explanation TEXT NOT NULL,
        evidence TEXT NOT NULL DEFAULT '', suggested_fix TEXT NOT NULL DEFAULT '',
        suggested_code TEXT, verification_status TEXT NOT NULL,
        source TEXT NOT NULL DEFAULT 'ai',
        PRIMARY KEY (review_id, id)
    );
    CREATE TABLE test_artifacts (
        id TEXT PRIMARY KEY,
        review_id TEXT NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
        filename TEXT NOT NULL, language TEXT NOT NULL, framework TEXT NOT NULL,
        content TEXT NOT NULL, purpose TEXT NOT NULL DEFAULT '',
        needs_verification INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    );
    CREATE TABLE execution_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        review_id TEXT NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
        artifact_id TEXT,
        status TEXT NOT NULL, passed INTEGER, failed INTEGER,
        duration_seconds REAL, output TEXT, runner TEXT,
        created_at TEXT NOT NULL
    );
    CREATE TABLE watched_repos (
        repo TEXT PRIMARY KEY,
        etag TEXT,
        last_checked TEXT,
        added_at TEXT NOT NULL
    );
    CREATE TABLE watched_prs (
        repo TEXT NOT NULL REFERENCES watched_repos(repo) ON DELETE CASCADE,
        pr_number INTEGER NOT NULL,
        title TEXT NOT NULL DEFAULT '',
        author TEXT NOT NULL DEFAULT '',
        url TEXT NOT NULL DEFAULT '',
        head_sha TEXT NOT NULL,
        reviewed_sha TEXT,
        indicator TEXT NOT NULL DEFAULT 'none',
        state TEXT NOT NULL DEFAULT 'open',
        first_seen TEXT NOT NULL,
        last_seen TEXT NOT NULL,
        PRIMARY KEY (repo, pr_number)
    );
    CREATE TABLE publications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        review_id TEXT NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
        repo TEXT NOT NULL, pr_number INTEGER NOT NULL,
        head_sha TEXT NOT NULL,
        mode TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        github_review_id INTEGER,
        url TEXT,
        inline_comments INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    );
    CREATE INDEX idx_pub_hash ON publications(repo, pr_number, content_hash);
    CREATE TABLE preferences (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    """,
]


class Database:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = str(path or paths.db_path())
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._mem_conn: sqlite3.Connection | None = None
        self.migrate()

    # -- connections ------------------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        if self.path == ":memory:":
            if self._mem_conn is None:
                self._mem_conn = sqlite3.connect(":memory:", check_same_thread=False)
                self._mem_conn.row_factory = sqlite3.Row
                self._mem_conn.execute("PRAGMA foreign_keys = ON")
            return self._mem_conn
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        return conn

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN")
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
            finally:
                if self.path != ":memory:":
                    conn.close()

    def _q(self, sql: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
        with self._lock:
            conn = self._connect()
            try:
                return conn.execute(sql, params).fetchall()
            finally:
                if self.path != ":memory:":
                    conn.close()

    # -- migrations -------------------------------------------------------------------
    def schema_version(self) -> int:
        return int(self._q("PRAGMA user_version")[0][0])

    def migrate(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                current = int(conn.execute("PRAGMA user_version").fetchone()[0])
                for idx in range(current, len(MIGRATIONS)):
                    conn.executescript("BEGIN;\n" + MIGRATIONS[idx] + f"\nPRAGMA user_version = {idx + 1};\nCOMMIT;")
            finally:
                if self.path != ":memory:":
                    conn.close()

    # -- reviews ----------------------------------------------------------------------
    def create_review(self, *, repo: str, pr_number: int, pr_url: str, provider: str, model: str,
                      depth: str = "standard", status: ReviewStatus = "pending") -> str:
        rid = uuid.uuid4().hex[:12]
        now = utcnow_iso()
        with self.tx() as c:
            c.execute(
                "INSERT INTO reviews (id, repo, pr_number, pr_url, provider, model, depth, status, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (rid, repo, pr_number, pr_url, provider, model, depth, status, now, now),
            )
        return rid

    _REVIEW_COLS = {
        "pr_title", "author", "head_sha", "base_sha", "provider", "model", "depth", "status",
        "stage_detail", "overall_risk", "summary", "findings_count", "private_repo", "error",
    }

    def update_review(self, rid: str, **fields: Any) -> None:
        bad = set(fields) - self._REVIEW_COLS
        if bad:
            raise ValueError(f"unknown review columns: {sorted(bad)}")
        if not fields:
            return
        sets = ", ".join(f"{k} = ?" for k in fields)
        with self.tx() as c:
            c.execute(f"UPDATE reviews SET {sets}, updated_at = ? WHERE id = ?",  # column names whitelisted above
                      (*fields.values(), utcnow_iso(), rid))

    def save_result(self, rid: str, result: ReviewResult, pr_json: str | None = None) -> None:
        """Persist the full result plus normalised finding/test rows in one transaction."""
        now = utcnow_iso()
        with self.tx() as c:
            c.execute(
                "UPDATE reviews SET result_json=?, pr_json=COALESCE(?, pr_json), summary=?, overall_risk=?, "
                "findings_count=?, head_sha=?, base_sha=?, provider=?, model=?, updated_at=? WHERE id=?",
                (result.model_dump_json(), pr_json, result.summary, result.overall_risk, len(result.issues),
                 result.metadata.head_sha, result.metadata.base_sha, result.metadata.provider,
                 result.metadata.model, now, rid),
            )
            c.execute("DELETE FROM findings WHERE review_id = ?", (rid,))
            for i in result.issues:
                c.execute(
                    "INSERT INTO findings (id, review_id, severity, category, file, line, side, title, explanation, "
                    "evidence, suggested_fix, suggested_code, verification_status, source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (i.id, rid, i.severity, i.category, i.file, i.line, i.side, i.title, i.explanation,
                     i.evidence, i.suggested_fix, i.suggested_code, i.verification_status, i.source),
                )
            c.execute("DELETE FROM test_artifacts WHERE review_id = ?", (rid,))
            t = result.test_file
            if t:
                c.execute(
                    "INSERT INTO test_artifacts (id, review_id, filename, language, framework, content, purpose, "
                    "needs_verification, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (f"{rid}-t", rid, t.filename, t.language, t.framework, t.content, t.purpose,
                     int(t.needs_verification), now),
                )

    def get_review(self, rid: str) -> dict[str, Any] | None:
        rows = self._q("SELECT * FROM reviews WHERE id = ?", (rid,))
        return dict(rows[0]) if rows else None

    def get_result(self, rid: str) -> ReviewResult | None:
        row = self.get_review(rid)
        if not row or not row.get("result_json"):
            return None
        return ReviewResult.model_validate_json(row["result_json"])

    def get_pr_json(self, rid: str) -> str | None:
        row = self.get_review(rid)
        return row.get("pr_json") if row else None

    def list_reviews(self, limit: int = 200) -> list[dict[str, Any]]:
        rows = self._q(
            "SELECT id, repo, pr_number, pr_url, pr_title, model, provider, findings_count, status, overall_risk, "
            "head_sha, updated_at, created_at FROM reviews ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    def delete_review(self, rid: str) -> None:
        with self.tx() as c:
            c.execute("DELETE FROM reviews WHERE id = ?", (rid,))

    def clear_pr_content(self) -> None:
        """Remove stored PR content (diffs, results, findings, artifacts) but keep settings and watches."""
        with self.tx() as c:
            for t in ("execution_results", "test_artifacts", "findings", "publications", "reviews"):
                c.execute(f"DELETE FROM {t}")  # fixed table names, no user input

    def stats(self) -> dict[str, int]:
        one = lambda sql: int(self._q(sql)[0][0] or 0)  # noqa: E731
        return {
            "total": one("SELECT COUNT(*) FROM reviews"),
            "completed": one("SELECT COUNT(*) FROM reviews WHERE status IN ('completed','posted','stale')"),
            "findings": one("SELECT COUNT(*) FROM findings"),
            "tests": one("SELECT COUNT(*) FROM test_artifacts"),
            "published": one("SELECT COUNT(DISTINCT review_id) FROM publications"),
        }

    def mark_stale(self, rid: str) -> None:
        self.update_review(rid, status="stale")

    def latest_review_for(self, repo: str, pr_number: int) -> dict[str, Any] | None:
        rows = self._q("SELECT * FROM reviews WHERE repo=? AND pr_number=? ORDER BY created_at DESC, rowid DESC LIMIT 1",
                       (repo, pr_number))
        return dict(rows[0]) if rows else None

    def reviewed_shas(self, repo: str, pr_number: int) -> set[str]:
        rows = self._q("SELECT head_sha FROM reviews WHERE repo=? AND pr_number=? AND status IN "
                       "('completed','posted','stale')", (repo, pr_number))
        return {r[0] for r in rows}

    def recover_interrupted(self) -> int:
        """Reviews left mid-flight by a crash/exit are marked failed on next start."""
        with self.tx() as c:
            cur = c.execute(
                "UPDATE reviews SET status='failed', error='Application closed before the review finished', "
                "updated_at=? WHERE status IN ('pending','fetching','analyzing','generating_tests','testing')",
                (utcnow_iso(),))
            return cur.rowcount

    # -- execution results ------------------------------------------------------------
    def save_execution(self, rid: str, *, status: str, passed: int | None, failed: int | None,
                       duration: float | None, output: str | None, runner: str) -> None:
        with self.tx() as c:
            c.execute(
                "INSERT INTO execution_results (review_id, artifact_id, status, passed, failed, duration_seconds, output, "
                "runner, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (rid, f"{rid}-t", status, passed, failed, duration, output, runner, utcnow_iso()))

    def list_executions(self, rid: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self._q("SELECT * FROM execution_results WHERE review_id=? ORDER BY id DESC", (rid,))]

    def list_test_artifacts(self) -> list[dict[str, Any]]:
        rows = self._q(
            "SELECT a.*, r.repo, r.pr_number, r.head_sha FROM test_artifacts a JOIN reviews r ON r.id=a.review_id "
            "ORDER BY a.created_at DESC")
        return [dict(r) for r in rows]

    # -- publications -----------------------------------------------------------------
    def record_publication(self, *, review_id: str, repo: str, pr_number: int, head_sha: str, mode: str,
                           content_hash: str, github_review_id: int | None, url: str | None,
                           inline_comments: int) -> None:
        with self.tx() as c:
            c.execute(
                "INSERT INTO publications (review_id, repo, pr_number, head_sha, mode, content_hash, github_review_id, "
                "url, inline_comments, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (review_id, repo, pr_number, head_sha, mode, content_hash, github_review_id, url, inline_comments,
                 utcnow_iso()))
            c.execute("UPDATE reviews SET status='posted', updated_at=? WHERE id=?", (utcnow_iso(), review_id))

    def find_publication(self, repo: str, pr_number: int, content_hash: str) -> dict[str, Any] | None:
        rows = self._q("SELECT * FROM publications WHERE repo=? AND pr_number=? AND content_hash=? LIMIT 1",
                       (repo, pr_number, content_hash))
        return dict(rows[0]) if rows else None

    def list_publications(self, review_id: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self._q("SELECT * FROM publications WHERE review_id=? ORDER BY id DESC", (review_id,))]

    # -- watched repositories ---------------------------------------------------------
    def add_watched_repo(self, repo: str) -> None:
        with self.tx() as c:
            c.execute("INSERT OR IGNORE INTO watched_repos (repo, added_at) VALUES (?,?)", (repo, utcnow_iso()))

    def remove_watched_repo(self, repo: str) -> None:
        with self.tx() as c:
            c.execute("DELETE FROM watched_repos WHERE repo = ?", (repo,))

    def list_watched_repos(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self._q("SELECT * FROM watched_repos ORDER BY repo")]

    def set_repo_poll(self, repo: str, etag: str | None) -> None:
        with self.tx() as c:
            c.execute("UPDATE watched_repos SET etag = COALESCE(?, etag), last_checked = ? WHERE repo = ?",
                      (etag, utcnow_iso(), repo))

    def get_watched_pr(self, repo: str, number: int) -> dict[str, Any] | None:
        rows = self._q("SELECT * FROM watched_prs WHERE repo=? AND pr_number=?", (repo, number))
        return dict(rows[0]) if rows else None

    def upsert_watched_pr(self, repo: str, number: int, *, title: str, author: str, url: str, head_sha: str,
                          indicator: str) -> None:
        now = utcnow_iso()
        with self.tx() as c:
            c.execute(
                "INSERT INTO watched_prs (repo, pr_number, title, author, url, head_sha, indicator, state, first_seen, last_seen) "
                "VALUES (?,?,?,?,?,?,?,'open',?,?) ON CONFLICT(repo, pr_number) DO UPDATE SET title=excluded.title, "
                "author=excluded.author, url=excluded.url, head_sha=excluded.head_sha, indicator=excluded.indicator, "
                "state='open', last_seen=excluded.last_seen",
                (repo, number, title, author, url, head_sha, indicator, now, now))

    def touch_watched_pr(self, repo: str, number: int) -> None:
        with self.tx() as c:
            c.execute("UPDATE watched_prs SET last_seen=?, state='open' WHERE repo=? AND pr_number=?",
                      (utcnow_iso(), repo, number))

    def close_missing_prs(self, repo: str, open_numbers: set[int]) -> None:
        with self.tx() as c:
            for row in c.execute("SELECT pr_number FROM watched_prs WHERE repo=? AND state='open'", (repo,)).fetchall():
                if row[0] not in open_numbers:
                    c.execute("UPDATE watched_prs SET state='closed' WHERE repo=? AND pr_number=?", (repo, row[0]))

    def list_watched_prs(self, repo: str, state: str = "open") -> list[dict[str, Any]]:
        return [dict(r) for r in self._q(
            "SELECT * FROM watched_prs WHERE repo=? AND state=? ORDER BY pr_number DESC", (repo, state))]

    def mark_pr_reviewed(self, repo: str, number: int, sha: str) -> None:
        with self.tx() as c:
            c.execute("UPDATE watched_prs SET reviewed_sha=?, indicator='none' WHERE repo=? AND pr_number=?",
                      (sha, repo, number))

    # -- preferences ------------------------------------------------------------------
    def set_pref(self, key: str, value: Any) -> None:
        with self.tx() as c:
            c.execute("INSERT INTO preferences (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                      (key, json.dumps(value)))

    def get_pref(self, key: str, default: Any = None) -> Any:
        rows = self._q("SELECT value FROM preferences WHERE key=?", (key,))
        return json.loads(rows[0][0]) if rows else default
