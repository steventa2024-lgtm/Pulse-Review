"""PulseReview core library (shared by the CLI and the dashboard)."""

__version__ = "0.1.1-beta"
APP_NAME = "PulseReview"

# The Mac beta is a separate source revision/channel from the Windows release.
import sys
if sys.platform == "darwin":
    __version__ = "0.1.3-macos-beta"
