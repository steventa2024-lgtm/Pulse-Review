"""GitHub sign-in with the OAuth 2.0 Device Authorization flow (no client secret, no local web server).

Works with the Client ID of a GitHub OAuth App or a GitHub App that has "Enable Device Flow" switched on.
GitHub App tokens expire and come with a refresh token; OAuth App tokens do not expire. Both are handled.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

import httpx

from .config import ConfigManager

log = logging.getLogger(__name__)
GRANT_DEVICE = "urn:ietf:params:oauth:grant-type:device_code"


class OAuthError(Exception):
    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind  # not_configured | device_flow_disabled | expired | denied | network | unknown
        self.message = message


@dataclass
class DeviceCode:
    device_code: str
    user_code: str
    verification_uri: str
    expires_at: float
    interval: int


@dataclass
class OAuthToken:
    access_token: str
    scopes: str
    refresh_token: str | None = None
    expires_at: float | None = None


def scopes_for(include_private: bool) -> str:
    # OAuth App scopes are coarse: "repo" is needed for private repositories; "public_repo" covers public ones.
    return "repo read:user" if include_private else "public_repo read:user"


class DeviceFlow:
    def __init__(self, client_id: str, web_base_url: str = "https://github.com", *, http: httpx.Client | None = None,
                 sleep=time.sleep) -> None:
        if not client_id:
            raise OAuthError("not_configured", "No GitHub OAuth Client ID is configured. See Settings → GitHub → Sign-in setup.")
        self.client_id = client_id
        self.base = web_base_url.rstrip("/")
        self.http = http or httpx.Client(timeout=20)
        self.sleep = sleep

    def _post(self, path: str, data: dict) -> dict:
        try:
            r = self.http.post(self.base + path, data=data, headers={"Accept": "application/json"})
        except httpx.HTTPError as exc:
            raise OAuthError("network", f"Could not reach GitHub: {exc}") from exc
        if r.status_code == 404:
            raise OAuthError("not_configured", "GitHub did not recognise the OAuth Client ID.")
        try:
            body = r.json()
        except ValueError as exc:
            raise OAuthError("unknown", f"Unexpected response from GitHub (HTTP {r.status_code}).") from exc
        return body

    def start(self, scopes: str) -> DeviceCode:
        body = self._post("/login/device/code", {"client_id": self.client_id, "scope": scopes})
        err = body.get("error")
        if err == "device_flow_disabled":
            raise OAuthError("device_flow_disabled", "Device flow is not enabled for this OAuth app. Tick “Enable Device Flow” in its GitHub settings.")
        if err == "unauthorized_client" or err == "incorrect_client_credentials":
            raise OAuthError("not_configured", "GitHub rejected the OAuth Client ID.")
        if err or "device_code" not in body:
            raise OAuthError("unknown", body.get("error_description") or f"GitHub error: {err or 'no device code returned'}")
        return DeviceCode(device_code=body["device_code"], user_code=body["user_code"],
                          verification_uri=body.get("verification_uri", self.base + "/login/device"),
                          expires_at=time.time() + int(body.get("expires_in", 900)), interval=int(body.get("interval", 5)))

    def poll_once(self, code: DeviceCode) -> OAuthToken | str:
        """Returns a token, or 'pending' / 'slow_down'. Raises OAuthError on terminal failures."""
        body = self._post("/login/oauth/access_token",
                          {"client_id": self.client_id, "device_code": code.device_code, "grant_type": GRANT_DEVICE})
        if "access_token" in body:
            return _token(body)
        err = body.get("error", "unknown")
        if err in ("authorization_pending", "slow_down"):
            if err == "slow_down":
                code.interval = int(body.get("interval", code.interval + 5))
            return "pending" if err == "authorization_pending" else "slow_down"
        if err == "expired_token":
            raise OAuthError("expired", "The sign-in code expired. Start again.")
        if err == "access_denied":
            raise OAuthError("denied", "Sign-in was cancelled on GitHub.")
        if err == "device_flow_disabled":
            raise OAuthError("device_flow_disabled", "Device flow is not enabled for this OAuth app.")
        raise OAuthError("unknown", body.get("error_description") or f"GitHub error: {err}")

    def wait(self, code: DeviceCode, cancel: threading.Event | None = None) -> OAuthToken:
        while time.time() < code.expires_at:
            if cancel is not None and cancel.is_set():
                raise OAuthError("denied", "Sign-in cancelled.")
            self.sleep(code.interval)
            res = self.poll_once(code)
            if isinstance(res, OAuthToken):
                return res
        raise OAuthError("expired", "The sign-in code expired. Start again.")

    def refresh(self, refresh_token: str) -> OAuthToken:
        body = self._post("/login/oauth/access_token",
                          {"client_id": self.client_id, "grant_type": "refresh_token", "refresh_token": refresh_token})
        if "access_token" not in body:
            raise OAuthError("expired", "Your GitHub session expired. Sign in again.")
        return _token(body)


def _token(body: dict) -> OAuthToken:
    exp = body.get("expires_in")
    return OAuthToken(access_token=body["access_token"], scopes=body.get("scope", ""),
                      refresh_token=body.get("refresh_token"), expires_at=time.time() + int(exp) if exp else None)


def save_token(mgr: ConfigManager, tok: OAuthToken) -> None:
    mgr.set_github_oauth(tok.access_token, scopes=tok.scopes, refresh_token=tok.refresh_token, expires_at=tok.expires_at)


def ensure_fresh_token(mgr: ConfigManager, http: httpx.Client | None = None) -> None:
    """Refresh an expiring OAuth token shortly before it expires. No-op for PATs and non-expiring tokens."""
    gh = mgr.config.github
    if gh.auth_method != "oauth" or not gh.token_expires_at or gh.token_expires_at - time.time() > 300:
        return
    rt = mgr.get_github_refresh_token()
    if not rt:
        return
    try:
        save_token(mgr, DeviceFlow(mgr.effective_oauth_client_id(), gh.web_base_url, http=http).refresh(rt))
        log.info("GitHub token refreshed")
    except OAuthError as exc:
        log.warning("GitHub token refresh failed: %s", exc.message)
