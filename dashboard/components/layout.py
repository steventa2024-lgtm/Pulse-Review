"""Application frame: top bar, sidebar navigation, page container."""
from __future__ import annotations

from contextlib import contextmanager

from nicegui import app, ui

from core import __version__

from ..context import Ctx
from .kit import btn, icon_btn

NAV = [
    ("dashboard", "Dashboard", "space_dashboard", "/"),
    ("new", "New review", "add_circle_outline", "/review/new"),
    ("history", "Review history", "history", "/history"),
    ("watch", "Watched repositories", "visibility", "/watch"),
    ("testlab", "Test lab", "science", "/testlab"),
]


def _status_chip(ctx: Ctx, text_key: str, ok_key: str, icon: str, href: str, tip_key: str | None = None):
    with ui.element("div").classes("zp-chip clickable").on("click", lambda: ui.navigate.to(href)) as chip:
        dot = ui.element("span").classes("zp-dot")
        ui.icon(icon, size="15px").classes("zp-muted")
        ui.label().bind_text_from(ctx.status, text_key)

        def sync() -> None:
            state = ctx.status.get(ok_key)
            dot.classes(replace="zp-dot " + {True: "ok", False: "bad"}.get(state, "busy"))

        sync()
        ui.timer(1.0, sync)
        if tip_key:
            with ui.tooltip().classes("max-w-[360px]"):
                ui.label().bind_text_from(ctx.status, tip_key)
    return chip


@contextmanager
def frame(ctx: Ctx, active: str):
    ui.dark_mode(True)
    ui.colors(primary="#4c8dff", secondary="#7d8795", accent="#a48cf0", positive="#3fb950", negative="#f06a63",
              warning="#d9a13b", info="#4c8dff", dark="#11151c", dark_page="#0b0e13")
    ui.add_head_html('<link rel="stylesheet" href="/assets/style.css"><meta name="color-scheme" content="dark">')
    ctx.refresh_static()

    with ui.header(elevated=False).classes("items-center justify-between px-4 gap-4 no-wrap"):
        with ui.row().classes("items-center gap-3 no-wrap"):
            ui.image("/assets/icon.png").classes("w-7 h-7")
            ui.html('<span class="zp-brand">Zero<b>Pulse</b> <span style="font-weight:500;color:var(--zp-text-2)">PR Review</span></span>')
        with ui.row().classes("items-center gap-2 no-wrap"):
            _status_chip(ctx, "github_text", "github_ok", "hub", "/settings?tab=github")
            _status_chip(ctx, "model_chip", "model_ok", "auto_awesome", "/settings?tab=ai")
            _status_chip(ctx, "docker_text", "docker_ok", "inventory_2", "/settings?tab=app", "docker_reason")
            ui.element("div").classes("w-2")
            icon_btn("settings", lambda: ui.navigate.to("/settings"), "Settings")
            icon_btn("power_settings_new", _quit_dialog, "Quit ZeroPulse")

    with ui.left_drawer(value=True, fixed=True).props("width=232 breakpoint=900").classes("p-0 column no-wrap"):
        with ui.column().classes("w-full gap-0 px-3 pt-4 flex-1"):
            btn("New review", "add", lambda: ui.navigate.to("/review/new"), kind="primary").classes("w-full mb-3")
            ui.label("Workspace").classes("zp-eyebrow zp-nav-group")
            for key, label, icon, href in NAV:
                with ui.element("div").classes("zp-nav-item" + (" active" if key == active else "")).on("click", lambda h=href: ui.navigate.to(h)):
                    ui.icon(icon, size="19px")
                    ui.label(label)
            ui.label("Configure").classes("zp-eyebrow zp-nav-group")
            with ui.element("div").classes("zp-nav-item" + (" active" if active == "settings" else "")).on("click", lambda: ui.navigate.to("/settings")):
                ui.icon("tune", size="19px")
                ui.label("Settings")
        with ui.column().classes("zp-sidefoot w-full gap-0"):
            ui.label("Publishing is always manual").classes("zp-xs zp-muted")
            ui.label(f"v{__version__} · runs locally").classes("zp-xs zp-muted")

    with ui.column().classes("zp-page w-full"):
        yield


def _quit_dialog() -> None:
    with ui.dialog() as d, ui.card().classes("zp-card w-[420px]"):
        ui.label("Quit ZeroPulse?").classes("zp-h2")
        ui.label("Running reviews will be interrupted. Your review history is kept.").classes("zp-sub")
        with ui.row().classes("justify-end w-full gap-2 mt-2"):
            btn("Cancel", on_click=d.close, kind="ghost")
            btn("Quit", on_click=lambda: app.shutdown(), kind="danger-solid")
    d.open()
