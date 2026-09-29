"""Reusable UI pieces. AI/repository text is only ever rendered as escaped text or inside code blocks."""
from __future__ import annotations

import hashlib
import html
from datetime import datetime

from nicegui import ui

from core.diff_parser import FileDiff

STATUS_STYLE = {
    "pending": ("zp-b-gray", "Pending"), "fetching": ("zp-b-low", "Fetching"), "analyzing": ("zp-b-low", "Analyzing"),
    "generating_tests": ("zp-b-low", "Generating tests"), "testing": ("zp-b-low", "Testing"),
    "completed": ("zp-b-ok", "Completed"), "posted": ("zp-b-purple", "Posted"), "failed": ("zp-b-critical", "Failed"),
    "cancelled": ("zp-b-gray", "Cancelled"), "stale": ("zp-b-medium", "Stale"),
}
ACTIVE_STATUSES = {"pending", "fetching", "analyzing", "generating_tests", "testing"}


def status_badge(status: str):
    cls, label = STATUS_STYLE.get(status, ("zp-b-gray", status))
    with ui.element("span").classes(f"zp-badge {cls}"):
        if status in ACTIVE_STATUSES:
            ui.element("span").classes("zp-dot busy mr-1")
        ui.label(label).classes("inline")


def severity_badge(sev: str):
    return ui.label(sev.upper()).classes(f"zp-badge zp-b-{sev}")


def risk_badge(risk: str):
    return ui.label(f"{risk.upper()} RISK").classes(f"zp-badge zp-b-{risk}")


def pill(text: str, tone: str = "gray"):
    return ui.label(text).classes(f"zp-badge zp-b-{tone}")


def stat_card(title: str, value, icon: str, tone: str = "") -> None:
    with ui.element("div").classes("zp-stat-card"):
        with ui.row().classes("items-center justify-between w-full no-wrap"):
            ui.label(title).classes("zp-eyebrow")
            ui.icon(icon, size="18px").classes("zp-muted")
        ui.label(str(value)).classes("zp-stat")


def fmt_time(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso).astimezone()
        return dt.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return iso


def github_diff_url(pr_url: str, path: str, line: int | None, side: str = "RIGHT") -> str:
    anchor = "#diff-" + hashlib.sha256(path.encode()).hexdigest()
    if line:
        anchor += ("R" if side == "RIGHT" else "L") + str(line)
    return f"{pr_url}/files{anchor}"


def diff_html(fd: FileDiff, line: int | None, side: str = "RIGHT", context: int = 5) -> str:
    """Escaped, line-numbered diff excerpt around ``line`` (or the first hunk when no line)."""
    rows: list[str] = []
    hunks = fd.hunks
    if line is not None:
        chosen = [h for h in hunks if any((l.new_no == line and side == "RIGHT") or (l.old_no == line and side == "LEFT" and l.kind == "del") for l in h.lines)]
        hunks = chosen or hunks[:1]
    else:
        hunks = hunks[:1]
    for h in hunks:
        lines = h.lines
        idx = next((i for i, l in enumerate(lines) if line is not None and ((side == "RIGHT" and l.new_no == line) or (side == "LEFT" and l.kind == "del" and l.old_no == line))), None)
        lo, hi = (0, len(lines)) if idx is None else (max(0, idx - context), min(len(lines), idx + context + 1))
        rows.append(f'<tr class="gap"><td class="no"></td><td class="no"></td><td>{html.escape("@@ -%d,%d +%d,%d @@%s" % (h.old_start, h.old_len, h.new_start, h.new_len, h.header))}</td></tr>')
        for i in range(lo, hi):
            l = lines[i]
            cls = {"add": "add", "del": "del", "ctx": ""}[l.kind]
            if idx == i:
                cls += " hit"
            sign = {"add": "+", "del": "-", "ctx": " "}[l.kind]
            rows.append(f'<tr class="{cls}"><td class="no">{l.old_no or ""}</td><td class="no">{l.new_no or ""}</td>'
                        f'<td>{sign}{html.escape(l.text)}</td></tr>')
    return '<div class="zp-diff"><table>' + "".join(rows) + "</table></div>"


def copy_button(text: str, label: str = "Copy", icon: str = "content_copy"):
    def _copy() -> None:
        ui.clipboard.write(text)
        ui.notify("Copied to clipboard", type="positive", timeout=1500)

    return ui.button(label, icon=icon, on_click=_copy, color=None).props("flat no-caps").classes("zp-btn-ghost zp-btn-sm")


def download_button(text: str, filename: str, label: str = "Download", icon: str = "download", media: str = "text/plain"):
    return ui.button(label, icon=icon, on_click=lambda: ui.download.content(text.encode("utf-8"), filename, media), color=None).props("flat no-caps").classes("zp-btn-ghost zp-btn-sm")


def skeleton(lines: int = 3, height: str = "18px") -> None:
    for i in range(lines):
        ui.element("div").classes("zp-skel w-full mb-2").style(f"height:{height}; width:{92 - i * 9}%")
