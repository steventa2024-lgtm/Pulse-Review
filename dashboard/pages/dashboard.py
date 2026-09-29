from __future__ import annotations

from nicegui import ui

from ..components.kit import btn, card, empty_state, page_header
from ..components.layout import frame
from ..components.tables import reviews_table
from ..components.widgets import stat_card
from ..context import Ctx


def register(ctx: Ctx) -> None:
    @ui.page("/")
    def index():
        with frame(ctx, "dashboard"):
            actions = page_header("Dashboard", "AI-assisted pull-request reviews. Nothing is published until you confirm it.")
            with actions:
                btn("New review", "add", lambda: ui.navigate.to("/review/new"), kind="primary")

            cards = ui.row().classes("w-full gap-4 no-wrap overflow-x-auto")

            def draw_cards() -> None:
                s = ctx.services.db.stats()
                cards.clear()
                with cards:
                    stat_card("Reviews", s["total"], "fact_check")
                    stat_card("Completed", s["completed"], "task_alt")
                    stat_card("Findings", s["findings"], "bug_report")
                    stat_card("Tests generated", s["tests"], "science")
                    stat_card("Published", s["published"], "publish")

            draw_cards()
            ui.timer(5.0, draw_cards)

            with card("Recent reviews"):
                if not ctx.services.db.list_reviews(1):
                    with empty_state("rate_review", "No reviews yet",
                                     "Sign in to GitHub and choose a model in Settings, then paste a pull-request link."):
                        with ui.row().classes("gap-2 mt-3"):
                            btn("Open settings", "tune", lambda: ui.navigate.to("/settings"), kind="secondary")
                            btn("Start a review", "add", lambda: ui.navigate.to("/review/new"), kind="primary")
                else:
                    reviews_table(ctx, limit=25, pagination=8)
