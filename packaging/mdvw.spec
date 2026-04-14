# PyInstaller spec for mdvw (Windows onedir build, UPX off for Defender-friendliness)
# Build with:  pyinstaller packaging/mdvw.spec  (from repo root)
from pathlib import Path

# SPECPATH is the directory containing this spec (…/packaging), so the
# repo root is its parent.
ROOT = Path(SPECPATH).resolve().parent
SRC = ROOT / "src" / "mdvw"
assert (SRC / "__main__.py").exists(), f"Expected src/mdvw/__main__.py; got ROOT={ROOT}"

block_cipher = None

a = Analysis(
    [str(SRC / "__main__.py")],
    pathex=[str(SRC.parent)],
    binaries=[],
    datas=[(str(SRC / "assets"), "mdvw/assets")],
    hiddenimports=[
        "webview.platforms.edgechromium",
        "clr_loader",
        "pythonnet",
        "pystray._win32",
        "PIL.Image",
        "PIL.ImageDraw",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "test", "unittest"],
    noarchive=False,
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="mdvw",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX causes Defender false-positives
    console=False,
    disable_windowed_traceback=False,
    icon=str(SRC / "assets" / "icon.ico") if (SRC / "assets" / "icon.ico").exists() else None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="mdvw",
)
