"""Shared application context for dashboard pages."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from nicegui import run

from core.github_client import GitHubError
from core.providers import ProviderError
from core.services import AppServices

from .jobs import JobManager

log = logging.getLogger(__name__)


@dataclass
class Ctx:
    services: AppServices
    jobs: JobManager
    # bindable status shown in the top bar
    status: dict[str, object] = field(default_factory=lambda: {
        "github_text": "GitHub: checking…", "github_ok": None, "provider_text": "", "model_text": "",
        "ollama_text": "", "ollama_ok": None, "docker_text": "Sandbox", "docker_ok": None, "docker_reason": "Checking Docker…",
        "model_chip": "", "model_ok": None})
    _last_watch: float = 0.0

    def refresh_static(self) -> None:
        cfg = self.services.cfg
        self.status["provider_text"] = "OpenRouter (free)" if cfg.provider == "openrouter" else "Local Ollama"
        self.status["model_text"] = cfg.active_model
        short = cfg.active_model.split("/")[-1]
        self.status["model_chip"] = ("OpenRouter · " if cfg.provider == "openrouter" else "Ollama · ") + short

    def check_github(self) -> None:
        if not self.services.config_mgr.get_github_token():
            self.status.update(github_text="GitHub · not connected", github_ok=False)
            return
        try:
            info = self.services.github().test_connection()
            self.status.update(github_text=f"GitHub · {info.login}", github_ok=True)
        except GitHubError as exc:
            self.status.update(github_text=f"GitHub · {exc.kind.replace('_', ' ')}", github_ok=False)

    def check_local_services(self) -> None:
        ok, reason = self.services.sandbox().available()
        self.status.update(docker_text="Sandbox · ready" if ok else "Sandbox · off", docker_ok=ok,
                           docker_reason="Docker (Linux containers) is ready for isolated test runs." if ok else reason)
        if self.services.cfg.provider == "ollama":
            try:
                h = self.services.provider().health_check()
                self.status.update(model_ok=h.ok)
            except ProviderError:
                self.status.update(model_ok=False)
        else:
            self.status.update(model_ok=bool(self.services.config_mgr.get_openrouter_key()))

    async def refresh_all(self) -> None:
        self.refresh_static()
        await run.io_bound(self.check_github)
        await run.io_bound(self.check_local_services)

    async def background_loop(self) -> None:
        """Status refresh + optional watch polling. Never publishes anything."""
        await asyncio.sleep(1)
        while True:
            try:
                await self.refresh_all()
                await self._maybe_poll_watch()
            except Exception:  # noqa: BLE001
                log.exception("background loop error")
            await asyncio.sleep(30)

    async def _maybe_poll_watch(self) -> None:
        minutes = self.services.cfg.app.watch_poll_minutes
        if minutes <= 0 or time.time() - self._last_watch < minutes * 60:
            return
        self._last_watch = time.time()
        if not self.services.db.list_watched_repos():
            return
        results = await run.io_bound(self.services.watcher().refresh_all)
        if self.services.cfg.app.auto_analyze_watched:
            await run.io_bound(self._auto_analyze)
        log.info("Watch poll finished: %s", [(r.repo, r.new, r.updated) for r in results])

    def _auto_analyze(self) -> None:
        w = self.services.watcher()
        for repo in self.services.db.list_watched_repos():
            for pr in w.needs_analysis(repo["repo"]):
                if pr["indicator"] in ("new", "updated") and not self.jobs.active():
                    self.jobs.start(pr["url"], self.services.review_options(), None, None)  # analysis only, never posts
                    return
