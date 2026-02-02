
@echo off
chcp 65001 >nul

REM עבור לתיקיית הסקריפט (היכן שה-batch file נמצא)
cd /d "%~dp0"

echo ========================================
echo בניית התוכנה (FULL) - כולל קניות/קופה
echo ========================================
echo.

echo [0/4] מגדיר ENABLE_PURCHASES=True...
set "BUILD_FLAGS_FILE=%~dp0build_flags.py"
attrib -R "%BUILD_FLAGS_FILE%" >nul 2>&1
python -c "import os; p=os.environ.get('BUILD_FLAGS_FILE','build_flags.py'); open(p,'w',encoding='utf-8').write('ENABLE_PURCHASES = True\n')"
if %errorlevel% neq 0 (
    echo ❌ שגיאה בהגדרת build_flags.py!
    pause
    exit /b 1
)

echo [1/4] מתקין תלויות (requirements.txt)...
set "PIP_LOG=%TEMP%\SchoolPoints_pip_install_%RANDOM%.log"
echo Log pip: "%PIP_LOG%"
python -V
python -m pip -V
echo.

echo דולג על עדכון pip (כבר מעודכן)...
echo.
echo מתקין חבילות מ-requirements.txt...
echo תראה התקדמות מלאה למטה:
echo ----------------------------------------

set "REQ_FILE=%~dp0requirements.txt"
set "WHEELS_DIR=%~dp0wheels"
if exist "%WHEELS_DIR%" goto offline_pip
goto online_pip

:offline_pip
echo נמצא wheels מקומי: "%WHEELS_DIR%"
echo מתקין OFFLINE מה-wheels - ללא אינטרנט...
echo.
echo בודק אילו חבילות כבר מותקנות...
python -c "import sys; pkgs=['pandas','openpyxl','Pillow','pyluach','python-bidi','pyserial']; missing=[]; import importlib.metadata as m; [missing.append(p) for p in pkgs if not any([True for _ in [0] if (lambda: (m.version(p),True) if True else False)() or (lambda: (m.version(p.replace('-','_')),True) if True else False)() ])]; print('Already installed:', len(pkgs)-len(missing), '/', len(pkgs)); print('Need to install:', ', '.join(missing) if missing else '(none)'); sys.exit(0 if not missing else 1)"
if %errorlevel% equ 0 (
    echo ✓ כל התלויות כבר מותקנות, מדלג על pip install
    goto after_pip
)

echo.
echo מתקין חבילות חסרות...
python -m pip install --no-index --find-links="%WHEELS_DIR%" --only-binary=:all: -r "%REQ_FILE%" --no-input --disable-pip-version-check
if %errorlevel% neq 0 (
    echo.
    echo ❌ התקנת תלויות OFFLINE נכשלה.
    echo כנראה שחסרות חבילות בתיקיית wheels.
    echo יש להשלים את קבצי ה-wheel לתיקיית:
    echo   "%WHEELS_DIR%"
    echo.
    pause
    exit /b 1
)
goto after_pip

:online_pip
echo לא נמצא wheels מקומי, מתקין ONLINE...
python -m pip install -r "%REQ_FILE%" --timeout 90 --retries 3 --no-input --disable-pip-version-check --progress-bar on -vv
if %errorlevel% neq 0 (
    echo.
    echo ❌ שגיאה בהתקנת תלויות!
    echo.
    pause
    exit /b 1
)

:after_pip

echo ✓ תלויות הותקנו בהצלחה

echo [1.4/4] בודק PyInstaller...
python -m pip show pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo PyInstaller לא מותקן, מתקין עכשיו...
    python -m pip install pyinstaller --no-input --disable-pip-version-check
    if %errorlevel% neq 0 (
        echo ❌ שגיאה בהתקנת PyInstaller!
        pause
        exit /b 1
    )
    echo ✓ PyInstaller הותקן בהצלחה
) else (
    echo ✓ PyInstaller כבר מותקן
)

echo [1.5/4] יוצר אייקונים (icons\*.ico) אם חסר...
python generate_app_icons.py
if %errorlevel% neq 0 (
    echo ❌ שגיאה ביצירת אייקונים!
    pause
    exit /b 1
)

echo [2/4] בונה עמדת ניהול...
echo מציג התקדמות - אם תקוע יותר מ-10 דקות, עצור עם Ctrl+C
echo.
set "PYI_ADMIN_LOG=%TEMP%\SchoolPoints_pyinstaller_admin.log"
echo PyInstaller log: "%PYI_ADMIN_LOG%"
type nul > "%PYI_ADMIN_LOG%" 2>nul
start "PyInstaller Admin Log" powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Content -Path '%PYI_ADMIN_LOG%' -Wait"
pyinstaller SchoolPoints_Admin.spec --clean --noconfirm --log-level INFO > "%PYI_ADMIN_LOG%" 2>&1
if %errorlevel% neq 0 (
    echo ❌ שגיאה בבניית עמדת ניהול!
    pause
    exit /b 1
)
echo ✓ עמדת ניהול נבנתה בהצלחה

echo [3/4] בונה עמדה ציבורית...
set "PYI_PUBLIC_LOG=%TEMP%\SchoolPoints_pyinstaller_public.log"
echo PyInstaller log: "%PYI_PUBLIC_LOG%"
type nul > "%PYI_PUBLIC_LOG%" 2>nul
start "PyInstaller Public Log" powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Content -Path '%PYI_PUBLIC_LOG%' -Wait"
pyinstaller SchoolPoints_Public.spec --clean --noconfirm --log-level INFO > "%PYI_PUBLIC_LOG%" 2>&1
if %errorlevel% neq 0 (
    echo ❌ שגיאה בבניית עמדה ציבורית!
    pause
    exit /b 1
)
echo ✓ עמדה ציבורית נבנתה בהצלחה

echo [3.5/4] בונה עמדת קופה...
set "PYI_CASHIER_LOG=%TEMP%\SchoolPoints_pyinstaller_cashier.log"
echo PyInstaller log: "%PYI_CASHIER_LOG%"
type nul > "%PYI_CASHIER_LOG%" 2>nul
start "PyInstaller Cashier Log" powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Content -Path '%PYI_CASHIER_LOG%' -Wait"
pyinstaller SchoolPoints_Cashier.spec --clean --noconfirm --log-level INFO > "%PYI_CASHIER_LOG%" 2>&1
if %errorlevel% neq 0 (
    echo ❌ שגיאה בבניית עמדת קופה!
    pause
    exit /b 1
)
echo ✓ עמדת קופה נבנתה בהצלחה

echo [4/4] יוצר version.json לעדכון...
python generate_version_json.py
if %errorlevel% neq 0 (
    echo ❌ שגיאה ביצירת version.json!
    pause
    exit /b 1
)

echo [5/5] בונה מתקין - Inno Setup...
set "INNO_ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%INNO_ISCC%" set "INNO_ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist "%INNO_ISCC%" goto inno_not_found

"%INNO_ISCC%" "SchoolPoints_Installer.iss"
if %errorlevel% neq 0 goto inno_failed
goto inno_success

:inno_not_found
echo ❌ לא נמצא ISCC.exe. יש להתקין Inno Setup 6 או לעדכן את הנתיב בבאט.
echo ניסיתי:
echo   %ProgramFiles(x86)%\Inno Setup 6\ISCC.exe
echo   %ProgramFiles%\Inno Setup 6\ISCC.exe
pause
exit /b 1

:inno_failed
echo ❌ שגיאה בבניית מתקין Inno Setup!
echo בדוק לוג: "%INNO_LOG%"
pause
exit /b 1

:inno_success

echo.
echo ========================================
echo ✓✓✓ הבנייה הושלמה בהצלחה! ✓✓✓
echo ========================================
echo.
echo קבצים נוצרו ב:
echo   - dist\SchoolPoints_Admin\SchoolPoints_Admin.exe
echo   - dist\SchoolPoints_Public\SchoolPoints_Public.exe
echo   - dist\SchoolPoints_Cashier\SchoolPoints_Cashier.exe
echo.
echo לחץ על מקש כלשהו לסיום...
pause >nul
