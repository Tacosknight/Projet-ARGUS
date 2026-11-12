# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import os
from PyInstaller.utils.hooks import collect_all, copy_metadata

root = Path(SPECPATH).resolve().parent
app = root / "facture-checker"

datas = [
    (str(app / "web" / "templates"), "web/templates"),
    (str(app / "web" / "static"), "web/static"),
    (os.environ.get("ARGUS_BUILD_MODELS_DIR", str(root / "models")), "models"),
]
binaries = []
hiddenimports = ["web.app", "uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto", "uvicorn.protocols.websockets.auto"]
for package in ("paddle", "paddleocr", "paddlex", "cv2", "pypdfium2", "skimage"):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

# PaddleX checks installed distribution metadata at runtime, including extras
# that PyInstaller may otherwise not associate with an importable module.
for distribution in ("imagesize", "opencv-contrib-python", "pyclipper", "pypdfium2", "python-bidi", "shapely"):
    datas += copy_metadata(distribution)

a = Analysis(
    [str(app / "launcher.py")],
    pathex=[str(app)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib.tests", "numpy.tests", "pandas.tests"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ARGUS",
    icon=str(app / "web" / "static" / "argus.ico"),
    console=False,
    disable_windowed_traceback=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="ARGUS")
