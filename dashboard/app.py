"""NiceGUI application assembly."""
from __future__ import annotations

import logging

from nicegui import app, ui

from core import paths
from core.services import AppServices

from .context import Ctx
from .jobs import JobManager
from .pages import code_reviewer, dashboard, history, new_review, review_detail, settings, test_lab, watched

log = logging.getLogger(__name__)


def build_app(services: AppServices | None = None) -> Ctx:
    services = services or AppServices()
    ctx = Ctx(services=services, jobs=JobManager(services))
    app.add_static_files("/assets", str(paths.assets_dir()))
    for module in (dashboard, history, new_review, review_detail, code_reviewer, watched, test_lab, settings):
        module.register(ctx)
    app.on_startup(lambda: __import__("nicegui.background_tasks", fromlist=["create"]).create(ctx.background_loop()))
    return ctx


def run_app(*, native: bool, port: int, show: bool = True, services: AppServices | None = None) -> None:
    build_app(services)
    ui.run(
        host="127.0.0.1",  # never exposed to the LAN
        port=port,
        title="PulseReview",
        favicon=str(paths.assets_dir() / "icon.png"),
        dark=True,
        native=native,
        window_size=(1440, 900) if native else None,
        reload=False,
        show=show and not native,
        show_welcome_message=False,
        storage_secret=None,
    )
