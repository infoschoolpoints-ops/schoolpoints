# -*- mode: python ; coding: utf-8 -*-

import os

_manifest_path = os.path.abspath('dpi_per_monitor_v2.manifest')

datas = [
    ('_clean_install/school_points.db', '.'),
    ('_clean_install/config.json', '.'),
    ('_clean_install/bonus_settings.json', '.'),
    ('_clean_install/color_settings.json', '.'),
    ('_clean_install/db_path.txt', '.'),
    ('_clean_install/excel_path.txt', '.'),
    ('_clean_install/master_card.txt', '.'),
    # פונט ותמונות רקע (לא חובה לקופה, אבל נשמר עקב שיתוף תשתיות/קונפיג)
    ('Gan CLM Bold.otf', '.'),
    ('תמונות/רקע בהיר לאורך.png', 'תמונות'),
    ('תמונות/רקע כהה לאורך.png', 'תמונות'),
    ('תמונות/רקע בהיר לרוחב.png', 'תמונות'),
    ('תמונות/רקע כהה לרוחב.png', 'תמונות'),
]


def _add_data_dir_if_exists(src: str, dest: str) -> None:
    try:
        if src and os.path.exists(src):
            datas.append((src, dest))
    except Exception:
        pass


_exe_icon = None
try:
    _icon_path = os.path.abspath(os.path.join('icons', 'cashier.ico'))
    if os.path.exists(_icon_path):
        _exe_icon = _icon_path
except Exception:
    _exe_icon = None


# סאונדים נדרשים (שיתוף תשתיות)
_add_data_dir_if_exists('sounds', 'sounds')
_add_data_dir_if_exists('sounds/‏‏תיקיה חדשה/קצר וטוב', 'sounds/‏‏תיקיה חדשה/קצר וטוב')
_add_data_dir_if_exists('sounds/‏‏תיקיה חדשה/הראשונים לבונוס', 'sounds/‏‏תיקיה חדשה/הראשונים לבונוס')
_add_data_dir_if_exists('icons/cashier.ico', 'icons')

a = Analysis(
    ['run_cashier.pyw'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[
        'pyluach',
        'pyluach.dates',
        'pyluach.hebrewcal',
        'pyluach.parshios',
        'pyluach.utils',
        'pyluach.gematria',
        'bidi',
        'bidi.algorithm',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt5'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SchoolPoints_Cashier',
    icon=_exe_icon,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    manifest=_manifest_path,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='SchoolPoints_Cashier',
)
