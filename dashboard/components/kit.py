"""Small UI kit so every page uses the same controls, spacing and typography."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Callable

from nicegui import ui


def btn(label: str = "", icon: str | None = None, on_click: Callable | None = None, *, kind: str = "secondary",
        size: str = "md", tooltip: str | None = None) -> ui.button:
    """kind: primary | secondary | ghost | danger | danger-solid; size: sm | md | lg."""
    b = ui.button(label, icon=icon, on_click=on_click, color="primary" if kind == "primary" else "negative" if kind == "danger-solid" else None)
    if kind == "primary":
        b.props("unelevated no-caps color=primary")
    elif kind == "danger-solid":
        b.props("unelevated no-caps color=negative")
    elif kind == "secondary":
        b.props("unelevated no-caps").classes("zp-btn-2")
    elif kind == "danger":
        b.props("flat no-caps").classes("zp-btn-danger")
    else:
        b.props("flat no-caps").classes("zp-btn-ghost")
    if size == "sm":
        b.classes("zp-btn-sm")
    elif size == "lg":
        b.classes("zp-btn-lg")
    if tooltip:
        b.tooltip(tooltip)
    return b


def icon_btn(icon: str, on_click: Callable | None = None, tooltip: str | None = None, color: str | None = None) -> ui.button:
    b = ui.button(icon=icon, on_click=on_click, color=None).props("flat round dense" + (f" color={color}" if color else "")).classes("zp-icon-btn")
    if tooltip:
        b.tooltip(tooltip)
    return b


def page_header(title: str, subtitle: str | None = None):
    """Returns the right-hand actions container."""
    with ui.row().classes("w-full items-end justify-between no-wrap gap-4"):
        with ui.column().classes("gap-1"):
            ui.label(title).classes("zp-h1")
            if subtitle:
                ui.label(subtitle).classes("zp-sub")
        actions = ui.row().classes("items-center gap-2 no-wrap")
    return actions


@contextmanager
def card(title: str | None = None, subtitle: str | None = None, *, classes: str = "", tight: bool = False, actions: Callable | None = None):
    with ui.element("div").classes(f"zp-card w-full {'tight' if tight else ''} {classes}") as c:
        if title or actions:
            with ui.element("div").classes("zp-card-head"):
                with ui.column().classes("gap-0"):
                    if title:
                        ui.label(title).classes("zp-h2")
                    if subtitle:
                        ui.label(subtitle).classes("zp-sub zp-small")
                if actions:
                    with ui.row().classes("items-center gap-2"):
                        actions()
        with ui.column().classes("w-full gap-3"):
            yield c


@contextmanager
def setting(label: str, description: str | None = None):
    """Two-column settings row: label/description left, controls right."""
    with ui.element("div").classes("zp-setting"):
        with ui.column().classes("gap-0"):
            ui.label(label).classes("zp-setting-label")
            if description:
                ui.label(description).classes("zp-setting-desc")
        with ui.column().classes("gap-3 w-full min-w-0"):
            yield


@contextmanager
def field(label: str, hint: str | None = None, classes: str = "w-full"):
    with ui.column().classes(f"gap-0 {classes}"):
        ui.label(label).classes("zp-label")
        yield
        if hint:
            ui.label(hint).classes("zp-hint")


def text_input(placeholder: str = "", value: str = "", *, password: bool = False, classes: str = "w-full") -> ui.input:
    return ui.input(placeholder=placeholder, value=value, password=password,
                    password_toggle_button=password).props("outlined dense hide-bottom-space").classes(classes)


def select(options, value=None, *, classes: str = "w-full", with_input: bool = False, new_values: bool = False) -> ui.select:
    s = ui.select(options, value=value, with_input=with_input, new_value_mode="add-unique" if new_values else None)
    return s.props("outlined dense options-dense hide-bottom-space behavior=menu popup-content-class=zp-select-menu").classes(classes)


def segmented(options: dict, value, on_change: Callable | None = None) -> ui.toggle:
    # own colour class: Quasar's layered bg-primary !important cannot be overridden from an unlayered stylesheet
    t = ui.toggle(options, value=value, on_change=on_change).props("no-caps unelevated toggle-color=zpseg toggle-text-color=zpsegtext")
    return t


def callout(text: str, tone: str = "info", icon: str | None = None):
    icons = {"info": "info", "warn": "warning_amber", "err": "error_outline", "ok": "check_circle"}
    colors = {"info": "text-blue-300", "warn": "zp-warn", "err": "zp-err", "ok": "zp-ok"}
    with ui.row().classes(f"zp-callout {tone} items-start no-wrap gap-3") as r:
        ui.icon(icon or icons[tone], size="18px").classes(colors[tone])
        lbl = ui.label(text).classes("zp-text-2")
    r.label = lbl  # type: ignore[attr-defined]
    return r


def empty_state(icon: str, title: str, text: str = ""):
    with ui.element("div").classes("zp-empty") as e:
        ui.icon(icon, size="36px")
        ui.label(title).classes("zp-h3")
        if text:
            ui.label(text).classes("zp-sub zp-small")
    return e


def fmt_ctx(n: int | None) -> str:
    if not n:
        return ""
    if n >= 1_000_000:
        return f"{n / 1_000_000:g}M ctx"
    return f"{round(n / 1000):g}K ctx"
