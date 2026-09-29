import io
import json
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from core.github_client import (GitHubClient, GitHubError, InvalidPRUrl, parse_pr_url, parse_repo_name,
                                safe_extract_zip)
from core.schemas import PRRef
from tests.fixtures.pr_fixture import FAKE_TOKEN, make_gh


# ---------------------------------------------------------------- URL parsing
@pytest.mark.parametrize("url,expected", [
    ("https://github.com/OWNER/REPO/pull/123", ("OWNER", "REPO", 123)),
    ("  https://github.com/o-w/re.po_x/pull/9/files  ", ("o-w", "re.po_x", 9)),
    ("https://www.github.com/a/b/pull/5/commits", ("a", "b", 5)),
    ("https://github.com/a/b/pull/5?diff=split#discussion", ("a", "b", 5)),
])
def test_parse_valid_urls(url, expected):
    r = parse_pr_url(url)
    assert (r.owner, r.repo, r.number) == expected


@pytest.mark.parametrize("url", [
    "", "   ", "not a url", "http://github.com/a/b/pull/1", "https://gitlab.com/a/b/pull/1",
    "https://github.com.evil.com/a/b/pull/1", "https://evil.com/github.com/a/b/pull/1",
    "https://user:pw@github.com/a/b/pull/1", "https://github.com:444/a/b/pull/1",
    "https://github.com/a/b/issues/1", "https://github.com/a/b/pull/abc", "https://github.com/a/b/pull/0",
    "https://github.com/a/b/pull/-3", "https://github.com/a/pull/1", "https://github.com/-bad-/b/pull/1",
    "https://github.com/a/../pull/1", "https://github.com/a/b.git/pull/1", "https://github.com/a/b/pull/1/../../x",
    "https://github.com/a/b/pull/1\nX-Injected: 1", "https://github.com/a/b/pull/99999999999", None, 123,
])
def test_parse_invalid_urls_rejected(url):
    with pytest.raises(InvalidPRUrl):
        parse_pr_url(url)


def test_parse_repo_name():
    assert parse_repo_name(" a/b ") == ("a", "b")
    with pytest.raises(InvalidPRUrl):
        parse_repo_name("a/../b")


# ---------------------------------------------------------------- PR fetch via fake gh
def test_fetch_pr_full_metadata_and_patch_states():
    gh, pull = make_gh()
    pr = GitHubClient(FAKE_TOKEN, gh=gh).fetch_pr(PRRef(owner="acme", repo="shop", number=7))
    assert pr.title and pr.base_sha == "b" * 40 and pr.head_sha == "h" * 40 and pr.author == "dev1"
    states = {f.filename: f for f in pr.files}
    assert states["app/orders.py"].patch_state == "full"
    assert states["assets/logo.png"].binary and states["assets/logo.png"].patch_state == "unavailable"
    assert states["data/huge.json"].patch_state == "unavailable" and not states["data/huge.json"].binary
    assert pr.partial
    assert any("no patch data" in l for l in pr.limitations)


def test_fetch_pr_reports_missing_files_beyond_api_cap():
    gh, pull = make_gh()
    pull.changed_files = 3200  # GitHub only lists 3000
    pr = GitHubClient(FAKE_TOKEN, gh=gh).fetch_pr(PRRef(owner="acme", repo="shop", number=7))
    assert any("NOT reviewed" in l for l in pr.limitations)


def test_renamed_file_without_patch_is_not_flagged_unavailable():
    from tests.fixtures.pr_fixture import make_file
    gh, _ = make_gh(files=[make_file("new.py", None, status="renamed", additions=0, deletions=0, previous_filename="old.py")])
    pr = GitHubClient(FAKE_TOKEN, gh=gh).fetch_pr(PRRef(owner="acme", repo="shop", number=7))
    assert pr.files[0].patch_state == "full" and pr.files[0].previous_filename == "old.py"


# ---------------------------------------------------------------- real PyGithub pagination against a local server
class _Handler(BaseHTTPRequestHandler):
    total_files = 5  # served 2 per page → 3 pages
    per_page = 2

    def log_message(self, *a):  # silence
        pass

    def _send(self, obj, headers=None):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        base = f"http://127.0.0.1:{self.server.server_port}"
        if u.path == "/repos/o/r":
            return self._send({"full_name": "o/r", "private": False, "default_branch": "main", "language": "Python", "id": 1,
                               "url": base + "/repos/o/r"})
        if u.path == "/repos/o/r/pulls/1":
            return self._send({"number": 1, "title": "T", "body": "B", "state": "open", "draft": False, "user": {"login": "u"},
                               "base": {"ref": "main", "sha": "b" * 40, "label": "x"}, "head": {"ref": "f", "sha": "h" * 40, "label": "y"},
                               "changed_files": self.total_files, "html_url": "https://github.com/o/r/pull/1",
                               "url": base + "/repos/o/r/pulls/1"})
        if u.path == "/repos/o/r/pulls/1/files":
            page = int(parse_qs(u.query).get("page", ["1"])[0])
            allf = [{"filename": f"f{i}.py", "status": "modified", "additions": 1, "deletions": 0, "changes": 1,
                     "patch": f"@@ -1 +1,2 @@\n a\n+b{i}", "sha": "s"} for i in range(self.total_files)]
            chunk = allf[(page - 1) * self.per_page: page * self.per_page]
            headers = {}
            if page * self.per_page < self.total_files:
                headers["Link"] = f'<{base}/repos/o/r/pulls/1/files?page={page + 1}>; rel="next"'
            self.server.hits.append(page)
            return self._send(chunk, headers)
        self.send_response(404)
        self.end_headers()


@pytest.fixture
def local_github():
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    srv.hits = []
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv
    srv.shutdown()


def test_real_pygithub_pagination_fetches_every_page(local_github):
    client = GitHubClient("tok", f"http://127.0.0.1:{local_github.server_port}")
    pr = client.fetch_pr(PRRef(owner="o", repo="r", number=1))
    assert [f.filename for f in pr.files] == [f"f{i}.py" for i in range(5)]
    assert local_github.hits == [1, 2, 3]
    assert not pr.limitations


# ---------------------------------------------------------------- polling with conditional requests
def _http(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_list_open_prs_paginates_and_uses_etag():
    seen = []

    def handler(req: httpx.Request):
        seen.append((str(req.url), req.headers.get("if-none-match")))
        if "page=2" in str(req.url):
            return httpx.Response(200, json=[{"number": 2, "title": "b", "user": {"login": "u"}, "html_url": "h2", "head": {"sha": "s2"}}])
        return httpx.Response(200, json=[{"number": 1, "title": "a", "user": {"login": "u"}, "html_url": "h1", "head": {"sha": "s1"}}],
                              headers={"ETag": 'W/"abc"', "Link": '<https://api.github.com/repos/o/r/pulls?page=2>; rel="next"'})

    c = GitHubClient("t", gh=object(), http=_http(handler))
    res = c.list_open_prs("o/r")
    assert [p.number for p in res.prs] == [1, 2] and res.etag == 'W/"abc"' and not res.not_modified

    def handler304(req):
        assert req.headers["if-none-match"] == 'W/"abc"'
        return httpx.Response(304)

    res2 = GitHubClient("t", gh=object(), http=_http(handler304)).list_open_prs("o/r", 'W/"abc"')
    assert res2.not_modified and res2.prs == []


@pytest.mark.parametrize("status,text,kind", [(404, "", "not_found"), (401, "", "auth"), (403, "API rate limit exceeded", "rate_limit")])
def test_list_open_prs_errors(status, text, kind):
    c = GitHubClient("t", gh=object(), http=_http(lambda r: httpx.Response(status, text=text)))
    with pytest.raises(GitHubError) as e:
        c.list_open_prs("o/r")
    assert e.value.kind == kind


def test_github_error_mapping_for_bad_token():
    from github.GithubException import BadCredentialsException

    class Boom:
        def get_user(self):
            raise BadCredentialsException(401, {"message": "Bad credentials"}, {})

    with pytest.raises(GitHubError) as e:
        GitHubClient("t", gh=Boom()).test_connection()
    assert e.value.kind == "auth"
    with pytest.raises(GitHubError):
        GitHubClient(None, gh=Boom()).test_connection()


def test_connection_info():
    gh, _ = make_gh()
    info = GitHubClient("t", gh=gh).test_connection()
    assert info.login == "tester" and info.rate_remaining == 4999
    acc = GitHubClient("t", gh=gh).validate_repo_access("acme", "shop")
    assert acc.can_push and not acc.private


# ---------------------------------------------------------------- archive safety
def _zip(entries: dict[str, bytes], symlink: str | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for k, v in entries.items():
            z.writestr(k, v)
        if symlink:
            zi = zipfile.ZipInfo(symlink)
            zi.external_attr = (0o120777 << 16)
            z.writestr(zi, "/etc/passwd")
    return buf.getvalue()


def test_safe_extract_zip(tmp_path):
    root = safe_extract_zip(_zip({"repo-abc/a.py": b"x=1", "repo-abc/sub/b.py": b"y"}, symlink="repo-abc/link"), tmp_path)
    assert (root / "a.py").read_text() == "x=1" and not (root / "link").exists()


@pytest.mark.parametrize("name", ["../evil.py", "/abs.py", "a/../../evil.py", "C:/x.py"])
def test_safe_extract_zip_blocks_zip_slip(tmp_path, name):
    with pytest.raises(GitHubError):
        safe_extract_zip(_zip({name: b"x"}), tmp_path)


def test_repo_and_pr_listing_for_pickers():
    from datetime import datetime, timezone
    from types import SimpleNamespace as NS
    gh, pull = make_gh()
    repo = gh.repo
    repo.pushed_at = datetime(2026, 9, 1, tzinfo=timezone.utc)
    pr_obj = NS(number=7, title="Fix", user=NS(login="dev1"), html_url="https://github.com/acme/shop/pull/7",
                head=NS(sha="h" * 40), updated_at=datetime(2026, 9, 2, tzinfo=timezone.utc), draft=False)
    repo.get_pulls = lambda state, sort, direction: [pr_obj]
    c = GitHubClient("t", gh=gh)
    assert c.list_repos_detailed() == [{"full_name": "acme/shop", "private": False, "pushed_at": "2026-09-01T00:00:00+00:00"}]
    prs = c.list_pull_requests("acme/shop")
    assert prs[0].number == 7 and prs[0].author == "dev1" and prs[0].url.endswith("/pull/7")
    assert GitHubClient(None, gh=gh).list_repos_detailed() == []
