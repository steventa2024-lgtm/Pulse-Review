import sqlite3

import pytest

from core.db import Database
from core.schemas import Issue, ReviewMetadata, ReviewResult, TestFile


def _result():
    return ReviewResult(summary="s", overall_risk="high", issues=[
        Issue(id="F1", file="a.py", line=3, title="t'; DROP TABLE reviews;--", explanation="e", severity="high")],
        test_file=TestFile(filename="tests/test_a.py", language="python", framework="pytest", content="x"),
        metadata=ReviewMetadata(provider="openrouter", model="m", head_sha="abc"))


def test_review_history_survives_restart(tmp_path):
    p = tmp_path / "reviews.db"
    db = Database(p)
    rid = db.create_review(repo="o/r", pr_number=1, pr_url="u", provider="openrouter", model="m")
    db.save_result(rid, _result(), pr_json="{}")
    db.update_review(rid, status="completed")
    db2 = Database(p)  # "restart"
    rows = db2.list_reviews()
    assert rows[0]["id"] == rid and rows[0]["status"] == "completed" and rows[0]["findings_count"] == 1
    res = db2.get_result(rid)
    assert res.issues[0].title.startswith("t'; DROP") and res.metadata.head_sha == "abc"
    assert db2.stats() == {"total": 1, "completed": 1, "findings": 1, "tests": 1, "published": 0}


def test_migrations_versioned_and_idempotent(tmp_path):
    db = Database(tmp_path / "d.db")
    v = db.schema_version()
    assert v >= 1
    Database(tmp_path / "d.db")
    assert db.schema_version() == v


def test_parameterized_sql_and_column_whitelist(tmp_path):
    db = Database(tmp_path / "d.db")
    rid = db.create_review(repo="o/r'; --", pr_number=1, pr_url="u", provider="p", model="m")
    assert db.get_review(rid)["repo"] == "o/r'; --"
    with pytest.raises(ValueError):
        db.update_review(rid, status="x", **{"model = 'evil', id": "1"})


def test_delete_cascades_and_clear(tmp_path):
    db = Database(tmp_path / "d.db")
    rid = db.create_review(repo="o/r", pr_number=1, pr_url="u", provider="p", model="m")
    db.save_result(rid, _result())
    db.save_execution(rid, status="passed", passed=1, failed=0, duration=1.0, output="ok", runner="docker")
    db.delete_review(rid)
    assert db.get_review(rid) is None
    conn = sqlite3.connect(tmp_path / "d.db")
    for t in ("findings", "test_artifacts", "execution_results"):
        assert conn.execute(f"select count(*) from {t}").fetchone()[0] == 0
    rid2 = db.create_review(repo="o/r", pr_number=2, pr_url="u", provider="p", model="m")
    db.add_watched_repo("o/r")
    db.clear_pr_content()
    assert db.get_review(rid2) is None and db.list_watched_repos()  # watches survive


def test_recover_interrupted(tmp_path):
    db = Database(tmp_path / "d.db")
    rid = db.create_review(repo="o/r", pr_number=1, pr_url="u", provider="p", model="m", status="analyzing")
    assert db.recover_interrupted() == 1
    assert db.get_review(rid)["status"] == "failed"


def test_preferences_and_transaction_rollback(tmp_path):
    db = Database(tmp_path / "d.db")
    db.set_pref("k", {"a": 1})
    assert db.get_pref("k") == {"a": 1} and db.get_pref("none", 5) == 5
    with pytest.raises(RuntimeError):
        with db.tx() as c:
            c.execute("INSERT INTO preferences VALUES ('x','1')")
            raise RuntimeError
    assert db.get_pref("x") is None
