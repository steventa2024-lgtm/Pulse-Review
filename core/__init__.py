"""PulseReview core library (shared by the CLI and the dashboard)."""

__version__ = "0.1.1-beta"
APP_NAME = "PulseReview"

# The Mac beta is a separate source revision/channel from the Windows release.
import sys
if sys.platform == "darwin":
    __version__ = "0.1.3-macos-beta"
    if getattr(sys, "frozen", False):
        import json
        from pathlib import Path
        _info = json.loads((Path(sys._MEIPASS) / "build-info.json").read_text())
        __version__ = f"{_info['version']}-macos-beta+{_info['source_commit'][:8]}"
