"""Mount, copy, verify, and launch the installer contents using scratch app data."""
import plistlib
from pathlib import Path
import subprocess
import sys
import tempfile

from smoke_mac import main as smoke


def main(dmg: Path) -> None:
    result = subprocess.check_output(["hdiutil", "attach", "-readonly", "-nobrowse", "-plist", str(dmg)])
    mount = next(e["mount-point"] for e in plistlib.loads(result)["system-entities"] if "mount-point" in e)
    try:
        with tempfile.TemporaryDirectory(prefix="pulsereview-install-") as scratch:
            app = Path(scratch) / "PulseReview.app"
            subprocess.run(["ditto", str(Path(mount) / "PulseReview.app"), str(app)], check=True)
            subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)
            smoke(app)
    finally:
        subprocess.run(["hdiutil", "detach", mount], check=True)


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
