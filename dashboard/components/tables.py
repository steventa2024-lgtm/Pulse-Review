from __future__ import annotations

from nicegui import ui

from ..context import Ctx
from .widgets import STATUS_STYLE, fmt_time

COLUMNS = [
    {"name": "repo", "label": "Repository", "field": "repo", "align": "left", "sortable": True},
    {"name": "pr", "label": "Pull request", "field": "pr", "align": "left", "sortable": True},
    {"name": "model", "label": "Model", "field": "model", "align": "left"},
    {"name": "findings", "label": "Findings", "field": "findings", "align": "center", "sortable": True},
    {"name": "status", "label": "Status", "field": "status_label", "align": "left", "sortable": True},
    {"name": "when", "label": "Last reviewed", "field": "when", "align": "left", "sortable": True},
    {"name": "actions", "label": "Actions", "field": "id", "align": "right"},
]


def build_rows(ctx: Ctx, limit: int = 200) -> list[dict]:
    rows = []
    for r in ctx.services.db.list_reviews(limit):
        cls, label = STATUS_STYLE.get(r["status"], ("zp-b-gray", r["status"]))
        title = r["pr_title"] or ""
        rows.append({
            "id": r["id"], "repo": r["repo"], "pr": f"#{r['pr_number']}" + (f"  {title[:70]}" if title else ""),
            "model": r["model"], "findings": r["findings_count"], "status": r["status"], "status_cls": cls,
            "status_label": label, "when": fmt_time(r["updated_at"]), "url": r["pr_url"],
        })
    return rows


def reviews_table(ctx: Ctx, *, limit: int = 200, pagination: int = 10, on_delete=None):
    """Reviews table with status pills and actions; refreshes itself every few seconds."""
    table = ui.table(columns=COLUMNS, rows=build_rows(ctx, limit), row_key="id", pagination=pagination).classes("w-full").props("flat dense")
    table.add_slot("body-cell-status", '''
        <q-td :props="props"><span :class="'zp-badge ' + props.row.status_cls">{{ props.row.status_label }}</span></q-td>''')
    table.add_slot("body-cell-actions", '''
        <q-td :props="props" class="q-gutter-x-xs">
          <q-btn flat dense round size="sm" icon="open_in_new" @click="() => $parent.$emit('open', props.row)"><q-tooltip>Open review</q-tooltip></q-btn>
          <q-btn flat dense round size="sm" icon="delete_outline" color="negative" @click="() => $parent.$emit('remove', props.row)"><q-tooltip>Delete review</q-tooltip></q-btn>
        </q-td>''')
    table.on("open", lambda e: ui.navigate.to(f"/review/{e.args['id']}"))

    def _confirm_delete(e) -> None:
        rid, label = e.args["id"], f"{e.args['repo']} {e.args['pr']}"
        with ui.dialog() as d, ui.card().classes("zp-card"):
            ui.label("Delete this review?").classes("text-lg")
            ui.label(label).classes("zp-muted")
            ui.label("The stored findings, generated test and history are removed locally. Nothing on GitHub changes.").classes("text-sm")
            with ui.row().classes("justify-end w-full"):
                ui.button("Cancel", on_click=d.close).props("flat")

                def _do() -> None:
                    ctx.services.db.delete_review(rid)
                    d.close()
                    refresh()
                    ui.notify("Review deleted", type="positive")
                    if on_delete:
                        on_delete()

                ui.button("Delete", color="negative", on_click=_do)
        d.open()

    table.on("remove", _confirm_delete)

    def refresh() -> None:
        table.rows = build_rows(ctx, limit)
        table.update()

    ui.timer(3.0, refresh)
    return table
