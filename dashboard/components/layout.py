"""Application frame: top bar, sidebar navigation, page container."""
from __future__ import annotations

from contextlib import contextmanager

from nicegui import app, ui

from ..context import Ctx

NAV = [
    ("dashboard", "Dashboard", "space_dashboard", "/"),
    ("new", "New Review", "add_circle_outline", "/review/new"),
    ("history", "Review History", "history", "/history"),
    ("watch", "Watched Repositories", "visibility", "/watch"),
    ("testlab", "Test Lab", "science", "/testlab"),
    ("settings", "Settings", "settings", "/settings"),
]


def _chip(ctx: Ctx, text_key: str, ok_key: str | None = None, icon: str | None = None):
    with ui.element("span").classes("zp-chip") as chip:
        dot = ui.element("span").classes("zp-dot")
        if icon:
            ui.icon(icon, size="14px")
        lbl = ui.label().bind_text_from(ctx.status, text_key)
        if ok_key:
            dot.bind_visibility_from(ctx.status, ok_key, backward=lambda v: v is not None)
            ui.timer(1.0, lambda: dot.classes(replace="zp-dot " + {True: "ok", False: "bad"}.get(ctx.status.get(ok_key), "")))
        else:
            dot.set_visibility(False)
        chip.bind_visibility_from(ctx.status, text_key, backward=lambda v: bool(v))
    return chip


@contextmanager
def frame(ctx: Ctx, active: str):
    ui.dark_mode(True)
    ui.colors(primary="#388bfd", secondary="#8b949e", accent="#a371f7", positive="#3fb950", negative="#f85149",
              warning="#d29922", info="#388bfd")
    ui.add_head_html('<link rel="stylesheet" href="/assets/style.css"><meta name="color-scheme" content="dark">')
    ctx.refresh_static()

    with ui.header(elevated=False).classes("items-center justify-between px-4 py-2 gap-4"):
        with ui.row().classes("items-center gap-3 no-wrap"):
            ui.image("/assets/icon.png").classes("w-8 h-8")
            ui.html('<span class="zp-brand">Zero<b>Pulse</b> PR Review Agent</span>').classes("text-base")
        with ui.row().classes("items-center gap-2 wrap"):
            _chip(ctx, "github_text", "github_ok", "hub")
            _chip(ctx, "provider_text", None, "memory")
            _chip(ctx, "model_text", None, "psychology")
            _chip(ctx, "ollama_text", "ollama_ok")
            _chip(ctx, "docker_text", "docker_ok")
        with ui.row().classes("items-center gap-1 no-wrap"):
            ui.button(icon="settings", on_click=lambda: ui.navigate.to("/settings")).props("flat round dense").tooltip("Settings")
            ui.button(icon="power_settings_new", on_click=lambda: _quit_dialog()).props("flat round dense color=negative").tooltip("Quit ZeroPulse")

    with ui.left_drawer(value=True, fixed=True).props("width=232 breakpoint=900").classes("p-3"):
        ui.label("WORKSPACE").classes("zp-card-title px-3 pb-2 pt-1")
        for key, label, icon, href in NAV:
            with ui.element("div").classes("zp-nav-item" + (" active" if key == active else "")).on("click", lambda h=href: ui.navigate.to(h)):
                ui.icon(icon, size="20px")
                ui.label(label)
        ui.space()
        ui.label("Local-first • publishing is always manual").classes("zp-muted text-xs px-3 pt-6")

    with ui.column().classes("w-full max-w-[1400px] mx-auto p-4 gap-4"):
        yield


def _quit_dialog() -> None:
    with ui.dialog() as d, ui.card().classes("zp-card"):
        ui.label("Quit ZeroPulse?").classes("text-lg")
        ui.label("Running reviews will be interrupted. Stored history is kept.").classes("zp-muted")
        with ui.row().classes("justify-end w-full"):
            ui.button("Cancel", on_click=d.close).props("flat")
            ui.button("Quit", color="negative", on_click=lambda: app.shutdown())
    d.open()
