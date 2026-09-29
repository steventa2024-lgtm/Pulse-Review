from __future__ import annotations

from nicegui import ui

from ..components.kit import btn, card, page_header, text_input
from ..components.layout import frame
from ..components.tables import reviews_table
from ..context import Ctx


def register(ctx: Ctx) -> None:
    @ui.page("/history")
    def history():
        with frame(ctx, "history"):
            actions = page_header("Review history", "Every review is stored on this PC.")
            with actions:
                btn("Clear all", "delete_sweep", lambda: confirm_clear(), kind="danger")
            with card():
                search = text_input("Filter by repository, pull request, model or status…", classes="w-full max-w-md")
                table = reviews_table(ctx, limit=1000, pagination=15)
                search.bind_value(table, "filter")
            ui.label(f"Stored in {ctx.services.db.path}").classes("zp-mono zp-muted zp-xs")

            def confirm_clear() -> None:
                with ui.dialog() as d, ui.card().classes("zp-card w-[440px]"):
                    ui.label("Clear all stored review data?").classes("zp-h2")
                    ui.label("Deletes every review, finding, generated test and publication record from this PC. "
                             "Settings and watched repositories are kept. Nothing on GitHub changes.").classes("zp-sub")
                    with ui.row().classes("justify-end w-full gap-2 mt-2"):
                        btn("Cancel", on_click=d.close, kind="ghost")

                        def _do() -> None:
                            ctx.services.db.clear_pr_content()
                            d.close()
                            ui.notify("Review data cleared", type="positive")
                            ui.navigate.reload()

                        btn("Delete everything", on_click=_do, kind="danger-solid")
                d.open()
