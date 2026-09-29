"""GitHub access: PR URL validation, paginated PR retrieval, publishing, and watch polling."""
from __future__ import annotations

import io
import logging
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

import httpx
from github import Auth, Github
from github.GithubException import BadCredentialsException, GithubException, RateLimitExceededException

from .schemas import FileChange, PRData, PRRef

log = logging.getLogger(__name__)

_OWNER = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
_REPO = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
ALLOWED_HOSTS = {"github.com", "www.github.com"}


class InvalidPRUrl(ValueError):
    pass


class GitHubError(Exception):
    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind  # auth | permission | not_found | rate_limit | network | validation | unknown
        self.message = message


def parse_pr_url(url: str) -> PRRef:
    """Strictly validate a GitHub PR URL. Raises InvalidPRUrl with a user-presentable reason."""
    if not isinstance(url, str) or not url.strip():
        raise InvalidPRUrl("Enter a pull-request URL such as https://github.com/OWNER/REPO/pull/123")
    raw = url.strip()
    if any(c in raw for c in "\r\n\t \x00"):
        raise InvalidPRUrl("The URL contains whitespace or control characters.")
    parsed = urlparse(raw)
    if parsed.scheme != "https":
        raise InvalidPRUrl("Only https:// GitHub URLs are supported.")
    if parsed.username or parsed.password or parsed.port:
        raise InvalidPRUrl("The URL must not contain credentials or a custom port.")
    if (parsed.hostname or "").lower() not in ALLOWED_HOSTS:
        raise InvalidPRUrl("Only github.com pull-request URLs are supported.")
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 4 or parts[2] != "pull":
        raise InvalidPRUrl("Expected the form https://github.com/OWNER/REPO/pull/NUMBER")
    owner, repo, _, num = parts[:4]
    if len(parts) > 4 and parts[4] not in ("files", "commits", "checks", "conversation"):
        raise InvalidPRUrl("Unexpected extra path after the pull-request number.")
    if not _OWNER.match(owner):
        raise InvalidPRUrl(f"Invalid repository owner '{owner[:40]}'.")
    if not _REPO.match(repo) or repo in (".", "..") or repo.endswith(".git"):
        raise InvalidPRUrl(f"Invalid repository name '{repo[:60]}'.")
    if not num.isdigit() or not (1 <= int(num) <= 10_000_000):
        raise InvalidPRUrl("The pull-request number must be a positive integer.")
    return PRRef(owner=owner, repo=repo, number=int(num))


def parse_repo_name(name: str) -> tuple[str, str]:
    m = re.fullmatch(r"\s*([A-Za-z0-9-]{1,39})/([A-Za-z0-9._-]{1,100})\s*", name or "")
    if not m or m.group(2) in (".", ".."):
        raise InvalidPRUrl("Enter a repository as OWNER/REPO.")
    return m.group(1), m.group(2)


def _map_exc(exc: Exception) -> GitHubError:
    if isinstance(exc, GitHubError):
        return exc
    if isinstance(exc, RateLimitExceededException):
        return GitHubError("rate_limit", "GitHub API rate limit exceeded. Wait for the limit to reset and retry.")
    if isinstance(exc, BadCredentialsException):
        return GitHubError("auth", "GitHub rejected the token (invalid, expired or revoked).")
    if isinstance(exc, GithubException):
        status = exc.status
        msg = ""
        if isinstance(exc.data, dict):
            msg = str(exc.data.get("message", ""))
        if status == 401:
            return GitHubError("auth", "GitHub rejected the token (invalid, expired or revoked).")
        if status == 403:
            if "rate limit" in msg.lower():
                return GitHubError("rate_limit", "GitHub API rate limit exceeded.")
            return GitHubError("permission", f"GitHub denied access: {msg or 'the token lacks the required permission'}.")
        if status == 404:
            return GitHubError("not_found", "Not found. The repository/PR does not exist, or your token cannot access it "
                                            "(GitHub reports inaccessible private repositories as 404).")
        if status == 422:
            return GitHubError("validation", f"GitHub rejected the request: {msg or exc.data}")
        return GitHubError("unknown", f"GitHub error {status}: {msg}")
    if isinstance(exc, (httpx.HTTPError, OSError)):
        return GitHubError("network", f"Could not reach GitHub: {exc}")
    return GitHubError("unknown", f"Unexpected GitHub error: {exc}")


@dataclass
class ConnectionInfo:
    login: str
    name: str | None
    html_url: str
    rate_remaining: int | None = None
    rate_limit: int | None = None
    avatar_url: str = ""
    scopes: str = ""


@dataclass
class RepoAccess:
    full_name: str
    private: bool
    can_read: bool
    can_push: bool
    default_branch: str = ""


@dataclass
class OpenPR:
    number: int
    title: str
    author: str
    url: str
    head_sha: str
    updated_at: str
    draft: bool = False


@dataclass
class PollResult:
    not_modified: bool
    prs: list[OpenPR]
    etag: str | None


class GitHubClient:
    """Thin, testable wrapper. Pass ``gh`` (a PyGithub-like object) in tests."""

    def __init__(self, token: str | None, api_base_url: str = "https://api.github.com", *,
                 gh: Any | None = None, http: httpx.Client | None = None, timeout: float = 30.0) -> None:
        self._token = token
        self.api_base_url = api_base_url.rstrip("/")
        if gh is not None:
            self.gh = gh
        else:
            auth = Auth.Token(token) if token else None
            self.gh = Github(auth=auth, base_url=self.api_base_url, per_page=100, timeout=int(timeout))
        self._http = http or httpx.Client(timeout=timeout, follow_redirects=False)

    @property
    def authenticated(self) -> bool:
        return bool(self._token)

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
             "User-Agent": "ZeroPulse-PR-Review-Agent"}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        if extra:
            h.update(extra)
        return h

    # -- connection -------------------------------------------------------------------
    def test_connection(self) -> ConnectionInfo:
        if not self._token:
            raise GitHubError("auth", "No GitHub token configured.")
        try:
            user = self.gh.get_user()
            login = user.login  # forces the request
            rate = None
            try:
                rate = self.gh.get_rate_limit().core
            except Exception:  # noqa: BLE001 - rate info is optional
                rate = None
            scopes = getattr(self.gh, "oauth_scopes", None)
            return ConnectionInfo(login=login, name=getattr(user, "name", None), html_url=getattr(user, "html_url", ""),
                                  rate_remaining=getattr(rate, "remaining", None), rate_limit=getattr(rate, "limit", None),
                                  avatar_url=getattr(user, "avatar_url", "") or "",
                                  scopes=", ".join(scopes) if isinstance(scopes, list) else "")
        except Exception as exc:  # noqa: BLE001
            raise _map_exc(exc) from exc

    def validate_repo_access(self, owner: str, repo: str) -> RepoAccess:
        try:
            r = self.gh.get_repo(f"{owner}/{repo}")
            perms = getattr(r, "permissions", None)
            return RepoAccess(full_name=r.full_name, private=bool(r.private), can_read=True,
                              can_push=bool(getattr(perms, "push", False)) if perms else False,
                              default_branch=getattr(r, "default_branch", "") or "")
        except Exception as exc:  # noqa: BLE001
            raise _map_exc(exc) from exc

    def list_accessible_repos(self, limit: int = 100) -> list[str]:
        if not self._token:
            return []
        try:
            out: list[str] = []
            for r in self.gh.get_user().get_repos(sort="pushed"):
                out.append(r.full_name)
                if len(out) >= limit:
                    break
            return out
        except Exception as exc:  # noqa: BLE001
            raise _map_exc(exc) from exc

    def list_repos_detailed(self, limit: int = 300) -> list[dict[str, Any]]:
        """Repositories the signed-in account can access (owned, collaborator, organisation), most recently pushed first."""
        if not self._token:
            return []
        try:
            out: list[dict[str, Any]] = []
            for r in self.gh.get_user().get_repos(sort="pushed"):
                out.append({"full_name": r.full_name, "private": bool(r.private),
                            "pushed_at": r.pushed_at.isoformat() if getattr(r, "pushed_at", None) else ""})
                if len(out) >= limit:
                    break
            return out
        except Exception as exc:  # noqa: BLE001
            raise _map_exc(exc) from exc

    def list_pull_requests(self, full_name: str, state: str = "open", limit: int = 100) -> list[OpenPR]:
        try:
            out: list[OpenPR] = []
            for p in self.gh.get_repo(full_name).get_pulls(state=state, sort="updated", direction="desc"):
                out.append(OpenPR(number=p.number, title=p.title or "", author=p.user.login if p.user else "",
                                  url=p.html_url, head_sha=p.head.sha, updated_at=p.updated_at.isoformat() if p.updated_at else "",
                                  draft=bool(getattr(p, "draft", False))))
                if len(out) >= limit:
                    break
            return out
        except Exception as exc:  # noqa: BLE001
            raise _map_exc(exc) from exc

    # -- PR retrieval -----------------------------------------------------------------
    def fetch_pr(self, ref: PRRef) -> PRData:
        try:
            repo = self.gh.get_repo(ref.full_name)
            pr = repo.get_pull(ref.number)
            data = PRData(
                ref=ref, title=pr.title or "", body=pr.body or "", author=(pr.user.login if pr.user else ""),
                state=pr.state, draft=bool(getattr(pr, "draft", False)),
                base_ref=pr.base.ref, head_ref=pr.head.ref, base_sha=pr.base.sha, head_sha=pr.head.sha,
                private=bool(repo.private), default_branch=getattr(repo, "default_branch", "") or "",
                repo_language=getattr(repo, "language", None), html_url=pr.html_url or ref.url,
                changed_files_reported=int(getattr(pr, "changed_files", 0) or 0),
            )
            # get_files() is a lazily paginated list; iterating consumes every page (100 per page).
            for f in pr.get_files():
                data.files.append(self._to_file_change(f))
        except Exception as exc:  # noqa: BLE001
            raise _map_exc(exc) from exc
        if len(data.files) < data.changed_files_reported:
            data.limitations.append(
                f"GitHub returned {len(data.files)} of {data.changed_files_reported} changed files "
                "(the API caps file listings); the remaining files were NOT reviewed.")
        unavailable = [f.filename for f in data.files if f.patch_state == "unavailable"]
        if unavailable:
            data.limitations.append(
                f"{len(unavailable)} file(s) had no patch data (binary, too large, or removed content) and were not "
                "analysed: " + ", ".join(unavailable[:10]) + ("…" if len(unavailable) > 10 else ""))
        return data

    @staticmethod
    def _to_file_change(f: Any) -> FileChange:
        patch = getattr(f, "patch", None)
        status = getattr(f, "status", "modified") or "modified"
        adds, dels = int(getattr(f, "additions", 0) or 0), int(getattr(f, "deletions", 0) or 0)
        changes = int(getattr(f, "changes", adds + dels) or 0)
        binary = False
        state = "full"
        note = None
        if not patch:
            if status == "renamed" and changes == 0:
                state, note = "full", "Renamed without content changes."
            elif changes == 0 and status in ("added", "modified", "changed"):
                binary, state, note = True, "unavailable", "Binary or empty file — no textual diff."
            else:
                state, note = "unavailable", "GitHub did not provide a patch (file too large or diff suppressed)."
        return FileChange(filename=f.filename, status=status, additions=adds, deletions=dels, changes=changes,
                          patch=patch, previous_filename=getattr(f, "previous_filename", None), binary=binary,
                          patch_state=state, patch_note=note)

    def get_head_sha(self, ref: PRRef) -> str:
        try:
            return self.gh.get_repo(ref.full_name).get_pull(ref.number).head.sha
        except Exception as exc:  # noqa: BLE001
            raise _map_exc(exc) from exc

    def get_file_content(self, ref: PRRef, path: str, sha: str, max_bytes: int = 200_000) -> str | None:
        """Text of ``path`` at commit ``sha`` (None if missing/binary/too big)."""
        try:
            c = self.gh.get_repo(ref.full_name).get_contents(path, ref=sha)
            if isinstance(c, list) or getattr(c, "size", 0) > max_bytes:
                return None
            return c.decoded_content.decode("utf-8")
        except UnicodeDecodeError:
            return None
        except GithubException as exc:
            if exc.status == 404:
                return None
            raise _map_exc(exc) from exc
        except Exception as exc:  # noqa: BLE001
            raise _map_exc(exc) from exc

    def get_repo_tree(self, ref: PRRef, sha: str) -> tuple[list[str], bool]:
        """(file paths, truncated) at ``sha``. Truncated when GitHub cut the recursive tree."""
        try:
            t = self.gh.get_repo(ref.full_name).get_git_tree(sha, recursive=True)
            paths = [e.path for e in t.tree if getattr(e, "type", "blob") == "blob"]
            return paths, bool(getattr(t, "raw_data", {}).get("truncated", False))
        except Exception as exc:  # noqa: BLE001
            raise _map_exc(exc) from exc

    def download_archive(self, ref: PRRef, sha: str, max_bytes: int = 60_000_000) -> bytes:
        """Download the repository zip at ``sha`` (the host never executes it)."""
        url = f"{self.api_base_url}/repos/{ref.full_name}/zipball/{sha}"
        try:
            with self._http.stream("GET", url, headers=self._headers(), follow_redirects=True) as r:
                if r.status_code >= 400:
                    raise GitHubError("not_found" if r.status_code == 404 else "unknown",
                                      f"Archive download failed (HTTP {r.status_code}).")
                buf = io.BytesIO()
                for chunk in r.iter_bytes():
                    buf.write(chunk)
                    if buf.tell() > max_bytes:
                        raise GitHubError("validation", "Repository archive exceeds the size limit for sandbox testing.")
                return buf.getvalue()
        except httpx.HTTPError as exc:
            raise _map_exc(exc) from exc

    # -- publishing -------------------------------------------------------------------
    def create_review(self, ref: PRRef, head_sha: str, body: str, comments: list[dict[str, Any]]) -> tuple[int, str]:
        """POST a regular COMMENT review (never APPROVE/REQUEST_CHANGES)."""
        try:
            repo = self.gh.get_repo(ref.full_name)
            pr = repo.get_pull(ref.number)
            commit = repo.get_commit(head_sha)
            kwargs: dict[str, Any] = {"commit": commit, "body": body, "event": "COMMENT"}
            if comments:
                kwargs["comments"] = comments
            review = pr.create_review(**kwargs)
            return int(review.id), getattr(review, "html_url", "") or f"{ref.url}#pullrequestreview-{review.id}"
        except Exception as exc:  # noqa: BLE001
            raise _map_exc(exc) from exc

    # -- polling ----------------------------------------------------------------------
    def list_open_prs(self, repo_full_name: str, etag: str | None = None, max_pages: int = 3) -> PollResult:
        """Open PRs, newest activity first, using a conditional request on page 1."""
        prs: list[OpenPR] = []
        new_etag = etag
        url: str | None = f"{self.api_base_url}/repos/{repo_full_name}/pulls"
        params: dict[str, Any] | None = {"state": "open", "sort": "updated", "direction": "desc", "per_page": 100}
        for page in range(max_pages):
            headers = self._headers({"If-None-Match": etag} if (page == 0 and etag) else None)
            try:
                r = self._http.get(url, params=params, headers=headers)
            except httpx.HTTPError as exc:
                raise _map_exc(exc) from exc
            if r.status_code == 304:
                return PollResult(True, [], etag)
            if r.status_code == 403 and "rate limit" in r.text.lower():
                raise GitHubError("rate_limit", "GitHub API rate limit exceeded.")
            if r.status_code in (401,):
                raise GitHubError("auth", "GitHub rejected the token.")
            if r.status_code == 404:
                raise GitHubError("not_found", "Repository not found or not accessible with this token.")
            if r.status_code >= 400:
                raise GitHubError("unknown", f"GitHub returned HTTP {r.status_code}.")
            if page == 0:
                new_etag = r.headers.get("etag") or new_etag
            for p in r.json():
                prs.append(OpenPR(number=p["number"], title=p.get("title", ""), author=(p.get("user") or {}).get("login", ""),
                                  url=p.get("html_url", ""), head_sha=(p.get("head") or {}).get("sha", ""),
                                  updated_at=p.get("updated_at", ""), draft=bool(p.get("draft"))))
            nxt = r.links.get("next", {}).get("url") if hasattr(r, "links") else None
            if not nxt:
                break
            url, params = nxt, None
        return PollResult(False, prs, new_etag)


def safe_extract_zip(data: bytes, dest: Path, *, max_files: int = 20000, max_total: int = 300_000_000) -> Path:
    """Extract a GitHub zipball into ``dest`` defending against zip-slip, symlinks and zip bombs.

    Returns the repository root inside ``dest`` (GitHub wraps content in one top-level folder).
    """
    dest = dest.resolve()
    total = 0
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        infos = zf.infolist()
        if len(infos) > max_files:
            raise GitHubError("validation", "Archive contains too many files.")
        for info in infos:
            name = info.filename
            p = PurePosixPath(name)
            if p.is_absolute() or ".." in p.parts or "\\" in name or re.match(r"^[A-Za-z]:", name):
                raise GitHubError("validation", f"Unsafe path in archive: {name!r}")
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                continue  # skip symlinks
            total += info.file_size
            if total > max_total:
                raise GitHubError("validation", "Archive expands beyond the allowed size.")
            target = (dest / name).resolve()
            if dest != target and dest not in target.parents:
                raise GitHubError("validation", f"Unsafe path in archive: {name!r}")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                out.write(src.read())
    roots = [p for p in dest.iterdir() if p.is_dir()]
    return roots[0] if len(roots) == 1 else dest
