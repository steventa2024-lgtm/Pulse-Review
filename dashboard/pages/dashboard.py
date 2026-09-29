from __future__ import annotations

from nicegui import ui

from ..components.layout import frame
from ..components.tables import reviews_table
from ..components.widgets import stat_card
from ..context import Ctx


def register(ctx: Ctx) -> None:
    @ui.page("/")
    def index():
        with frame(ctx, "dashboard"):
            with ui.row().classes("items-center justify-between w-full"):
                with ui.column().classes("gap-0"):
                    ui.label("Dashboard").classes("text-2xl font-semibold")
                    ui.label("AI-assisted pull-request reviews. Nothing is published until you say so.").classes("zp-muted")
                ui.button("New review", icon="add", on_click=lambda: ui.navigate.to("/review/new")).props("unelevated color=primary")

            cards = ui.row().classes("w-full gap-3 no-wrap overflow-x-auto")

            def draw_cards() -> None:
                s = ctx.services.db.stats()
                cards.clear()
                with cards:
                    stat_card("Total reviews", s["total"], "fact_check")
                    stat_card("Completed", s["completed"], "task_alt")
                    stat_card("Findings detected", s["findings"], "bug_report")
                    stat_card("Tests generated", s["tests"], "science")
                    stat_card("Published to GitHub", s["published"], "publish")

            draw_cards()
            ui.timer(5.0, draw_cards)

            with ui.element("div").classes("zp-card w-full"):
                ui.label("Recent pull-request reviews").classes("zp-card-title mb-2")
                if not ctx.services.db.list_reviews(1):
                    with ui.column().classes("items-center w-full py-8 gap-2"):
                        ui.icon("rate_review", size="42px").classes("zp-muted")
                        ui.label("No reviews yet").classes("text-lg")
                        ui.label("Connect GitHub in Settings, pick a model, then paste a pull-request URL.").classes("zp-muted")
                        with ui.row():
                            ui.button("Open settings", on_click=lambda: ui.navigate.to("/settings")).props("flat")
                            ui.button("Start a review", on_click=lambda: ui.navigate.to("/review/new")).props("unelevated color=primary")
                reviews_table(ctx, limit=25, pagination=8)
