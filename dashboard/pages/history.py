from __future__ import annotations

from nicegui import ui

from ..components.layout import frame
from ..components.tables import reviews_table
from ..context import Ctx


def register(ctx: Ctx) -> None:
    @ui.page("/history")
    def history():
        with frame(ctx, "history"):
            with ui.row().classes("items-center justify-between w-full"):
                ui.label("Review History").classes("text-2xl font-semibold")
                ui.button("Clear stored PR content", icon="delete_sweep", color="negative", on_click=lambda: confirm_clear()).props("flat")
            with ui.element("div").classes("zp-card w-full"):
                search = ui.input(placeholder="Filter by repository, PR, model or status…").props("outlined dense clearable").classes("w-full max-w-md mb-3")
                table = reviews_table(ctx, limit=1000, pagination=15)
                search.bind_value(table, "filter")
            ui.label(f"Stored in {ctx.services.db.path}").classes("zp-muted text-xs zp-mono")

            def confirm_clear() -> None:
                with ui.dialog() as d, ui.card().classes("zp-card"):
                    ui.label("Clear all stored PR content?").classes("text-lg")
                    ui.label("Deletes every review, finding, generated test, execution result and publication record from this computer. "
                             "Settings and watched repositories are kept. Nothing on GitHub is touched.").classes("text-sm w-96")
                    with ui.row().classes("justify-end w-full"):
                        ui.button("Cancel", on_click=d.close).props("flat")

                        def _do() -> None:
                            ctx.services.db.clear_pr_content()
                            d.close()
                            ui.notify("Stored PR content cleared", type="positive")
                            ui.navigate.reload()

                        ui.button("Delete everything", color="negative", on_click=_do)
                d.open()
