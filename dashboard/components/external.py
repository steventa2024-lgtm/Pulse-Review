"""Open external links in the user's default browser, never inside the app window."""
from __future__ import annotations

import webbrowser
from urllib.parse import urlparse

from fastapi.responses import Response
from nicegui import app


def _safe(url: str) -> bool:
    p = urlparse(url or "")
    return p.scheme in ("http", "https") and bool(p.netloc)


def open_external(url: str) -> None:
    if _safe(url):
        webbrowser.open(url, new=2)


@app.get("/__open")
def _open_route(url: str = "") -> Response:
    open_external(url)
    return Response(status_code=204)


# Intercepts clicks on external <a> links (e.g. links inside Markdown) and opens them in the system browser.
INTERCEPT_JS = """<script>
document.addEventListener('click', function (e) {
  const a = e.target.closest && e.target.closest('a[href]');
  if (!a) return;
  const u = new URL(a.href, location.href);
  if (u.origin === location.origin || !/^https?:$/.test(u.protocol)) return;
  e.preventDefault();
  fetch('/__open?url=' + encodeURIComponent(u.href));
}, true);
</script>"""
