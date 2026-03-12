# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Ghost Typer — macOS menu bar app."""

import os

block_cipher = None
project_root = os.path.dirname(os.path.abspath(SPEC))

a = Analysis(
    [os.path.join(project_root, 'run.py')],
    pathex=[project_root],
    binaries=[],
    datas=[
        # Include icon files
        (os.path.join(project_root, 'icons'), 'icons'),
    ],
    hiddenimports=[
        'rumps',
        'pynput',
        'pynput.keyboard',
        'pynput.keyboard._darwin',
        'pynput._util',
        'pynput._util.darwin',
        'anthropic',
        'dotenv',
        'bs4',
        'PIL',
        'cv2',
        'pytesseract',
        'AppKit',
        'Foundation',
        'Quartz',
        'objc',
        'src',
        'src.models',
        'src.typing_engine',
        'src.typing_planner',
        'src.ai_planner',
        'src.orchestrator',
        'src.menu_bar_app',
        'src.settings_ui',
        'src.clipboard_monitor',
        'src.hotkey_listener',
        'src.keystroke_simulator',
        'src.human_errors',
        'src.text_parser',
        'src.notification_service',
        'src.progress_overlay',
        'src.visual_verifier',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='GhostTyper',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # No terminal window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='GhostTyper',
)

app = BUNDLE(
    coll,
    name='Ghost Typer.app',
    icon=os.path.join(project_root, 'icons', 'GhostTyper.icns'),
    bundle_identifier='com.gavin.ghost-typer',
    info_plist={
        'CFBundleName': 'Ghost Typer',
        'CFBundleDisplayName': 'Ghost Typer',
        'CFBundleVersion': '1.0.0',
        'CFBundleShortVersionString': '1.0.0',
        'LSUIElement': True,  # Menu bar app, no dock icon
        'LSMultipleInstancesProhibited': True,
        'NSAppleEventsUsageDescription': 'Ghost Typer needs to send notifications.',
        'NSAccessibilityUsageDescription': 'Ghost Typer needs accessibility access to simulate keyboard input.',
    },
)
