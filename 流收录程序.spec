# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['src\\launcher.py'],
    pathex=['src'],
    binaries=[('bundled\\ffmpeg\\ffmpeg.exe', 'ffmpeg'), ('bundled\\ffmpeg\\ffprobe.exe', 'ffmpeg')],
    datas=[('bundled\\ffmpeg\\LICENSE-FFmpeg.txt', 'ffmpeg')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name='流收录程序',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
