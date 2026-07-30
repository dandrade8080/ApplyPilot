# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for ApplyPilot desktop executable.

Builds a single .exe that launches the web dashboard + setup wizard.
No auto-apply dependencies (browser-use, langchain) included — keeps the
.exe around 200 MB instead of 1.5 GB.

Usage:
    pyinstaller applypilot.spec          # one-file build
    pyinstaller --onedir applypilot.spec  # folder build (faster startup)
"""

import sys
from pathlib import Path

a = Analysis(
    ['src/applypilot/gui.py'],
    pathex=[str(Path(__file__).parent)],
    binaries=[],
    datas=[
        ('src/applypilot/web/templates', 'applypilot/web/templates'),
        ('src/applypilot/config', 'applypilot/config'),
    ],
    hiddenimports=[
        'applypilot.config',
        'applypilot.database',
        'applypilot.llm',
        'applypilot.pipeline',
        'applypilot.web',
        'applypilot.web.routes',
        'applypilot.discovery',
        'applypilot.discovery.jobspy',
        'applypilot.scoring',
        'applypilot.scoring.scorer',
        'applypilot.scoring.tailor',
        'applypilot.scoring.cover_letter',
        'applypilot.scoring.pdf',
        'applypilot.scoring.validator',
        'applypilot.enrichment',
        'applypilot.enrichment.detail',
        'applypilot.wizard',
        'applypilot.wizard.init',
        'applypilot.alerts',
        'applypilot.knowledge',
        'applypilot.view',
        'yaml',
        'dotenv',
        'bs4',
        'pandas',
        'flask',
        'jinja2',
        'typer',
        'rich',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'browser_use',
        'langchain',
        'langchain_openai',
        'playwright',
        'playwright.sync_api',
        'applypilot.apply',
        'applypilot.apply.engine',
        'applypilot.apply.apply_agent',
        'applypilot.apply.ai_apply',
        'applypilot.apply.launcher',
        'applypilot.apply.chrome',
        'applypilot.apply.form_detector',
        'applypilot.apply.field_matcher',
        'applypilot.apply.question_answering',
        'applypilot.discovery.smartextract',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='ApplyPilot',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
