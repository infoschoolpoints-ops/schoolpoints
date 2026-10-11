# -*- mode: python ; coding: utf-8 -*-
#
# בנייה לגרסת התקנה קבועה (onedir) — תיקייה מותקנת עם EXE יחיד מאוחד
# (ניהול / ציבורית / קופה) ומסך בחירה בהפעלה (run_launcher.pyw).
#
#   pyinstaller SchoolPoints_Installer.spec --noconfirm
#

import os
import re

# מספר גרסה — נקרא מ-auto_updater.py כדי שיופיע בשם הקובץ
VERSION = '0.0.0'
try:
    with open('auto_updater.py', encoding='utf-8') as _vf:
        _vm = re.search(r'CURRENT_VERSION\s*=\s*["\']([^"\']+)', _vf.read())
        if _vm:
            VERSION = _vm.group(1)
except Exception:
    pass

datas = [
    ('_clean_install/school_points.db', '.'),
    ('_clean_install/config.json', '.'),
    ('_clean_install/bonus_settings.json', '.'),
    ('_clean_install/color_settings.json', '.'),
    ('_clean_install/db_path.txt', '.'),
    ('_clean_install/excel_path.txt', '.'),
    ('_clean_install/master_card.txt', '.'),
    ('guide_index.html', '.'),
    ('guide_admin.html', '.'),
    ('guide_teacher.html', '.'),
    ('guide_user.html', '.'),
    ('guide_user_embedded.html', '.'),
    ('הוראות התקנה ראשוניות.html', '.'),
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
    _icon_path = os.path.abspath(os.path.join('icons', 'installer.ico'))
    if os.path.exists(_icon_path):
        _exe_icon = _icon_path
except Exception:
    _exe_icon = None


_add_data_dir_if_exists('sounds', 'sounds')
_add_data_dir_if_exists('sounds/‏‏תיקיה חדשה/קצר וטוב', 'sounds/‏‏תיקיה חדשה/קצר וטוב')
_add_data_dir_if_exists('sounds/‏‏תיקיה חדשה/הראשונים לבונוס', 'sounds/‏‏תיקיה חדשה/הראשונים לבונוס')
_add_data_dir_if_exists('תמונות/להוראות', 'תמונות/להוראות')
_add_data_dir_if_exists('icons/admin.ico', 'icons')
_add_data_dir_if_exists('icons/public.ico', 'icons')
_add_data_dir_if_exists('icons/cashier.ico', 'icons')
_add_data_dir_if_exists('icons/installer.ico', 'icons')

a = Analysis(
    ['run_launcher.pyw'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[
        'admin_station',
        'public_station',
        'cashier_station',
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
    excludes=['PyQt5', 'tkinter.test', 'unittest', 'test', 'tests'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=f'SchoolPoints_v{VERSION}_Setup',
    icon=_exe_icon,
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
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=f'SchoolPoints_v{VERSION}_Setup',
)
