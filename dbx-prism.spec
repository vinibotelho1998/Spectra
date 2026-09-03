from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules

block_cipher = None

hiddenimports = (
    collect_submodules("clr_loader")
    + collect_submodules("pythonnet")
    + [
        "pyaudiowpatch",
        "pystray._win32",
        "PIL._tkinter_finder",
    ]
)

binaries = collect_dynamic_libs("clr_loader")

a = Analysis(
    ["run.py"],
    pathex=[],
    binaries=binaries,
    datas=[
        ("ui", "ui"),
        ("assets", "assets"),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "test", "unittest"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="DBXPrism",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/prism.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="DBXPrism",
)
