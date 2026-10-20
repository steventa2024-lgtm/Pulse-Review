# Run only via build_mac.sh, on arm64 macOS.
import json
from pathlib import Path

import nicegui

root = Path(SPECPATH).parent
info = json.loads((root / "build/mac/build-info.json").read_text())
a = Analysis(
    [str(root / "main.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[(str(Path(nicegui.__file__).parent), "nicegui"),
           (str(root / "dashboard/assets"), "dashboard/assets"),
           (str(root / "build/mac/build-info.json"), ".")],
    hiddenimports=["webview.platforms.cocoa", "keyring.backends.macOS",
                   "uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto",
                   "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on"],
    hookspath=[], runtime_hooks=[],
    excludes=["PyQt5", "PyQt6", "PySide2", "PySide6", "webview.platforms.qt",
              "webview.platforms.gtk", "webview.platforms.winforms", "pytest", "playwright"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="PulseReview",
          debug=False, strip=False, upx=False, console=False,
          argv_emulation=False, target_arch="arm64", codesign_identity=None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="PulseReview")
app = BUNDLE(coll, name="PulseReview.app", icon=str(root / "build/mac/PulseReview.icns"),
             bundle_identifier="com.zeropulse.PulseReview", info_plist={
                 "CFBundleDisplayName": "PulseReview",
                 "CFBundleShortVersionString": info["version"],
                 "CFBundleVersion": info["version"],
                 "CFBundleGetInfoString": "PulseReview by ZeroPulse — macOS beta — " + info["source_commit"],
                 "NSHumanReadableCopyright": "Copyright © ZeroPulse",
                 "LSMinimumSystemVersion": "14.0",
                 "NSHighResolutionCapable": True,
                 "NSRequiresAquaSystemAppearance": False,
                 "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
             })
