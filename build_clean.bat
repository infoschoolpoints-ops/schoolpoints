@echo off
chcp 65001 >nul

REM עבור לתיקיית הסקריפט (היכן שה-batch file נמצא)
cd /d "%~dp0"

echo [0/3] מתקין תלויות (requirements.txt)...
set "PIP_LOG=%CD%\pip_install.log"
echo Log pip: "%PIP_LOG%"
python -V
python -m pip -V

echo [pre] מגדיר ENABLE_PURCHASES=False (build נקי ללא קניות)...
python -c "import os; p='build_flags.py'; open(p,'w',encoding='utf-8').write('ENABLE_PURCHASES = False\n')"
if %errorlevel% neq 0 (
    echo ❌ שגיאה בהגדרת build_flags.py!
    pause
    exit /b 1
)

python -m pip install -U pip setuptools wheel --disable-pip-version-check --log "%PIP_LOG%"
python -m pip install -r requirements.txt -v --timeout 30 --retries 2 --progress-bar off --disable-pip-version-check --only-binary=:all: --log "%PIP_LOG%"
if %errorlevel% neq 0 (
    echo ❌ שגיאה בהתקנת תלויות!
    pause
    exit /b 1
)
echo ✓ תלויות הותקנו בהצלחה

echo [pre] יוצר אייקונים (icons/*.ico) אם חסר...
python generate_app_icons.py

echo ========================================
echo בניית התוכנה עם קבצים נקיים
echo ========================================
echo.
echo תיקיית עבודה: %CD%
echo.

echo [1/3] בונה עמדת ניהול...
pyinstaller SchoolPoints_Admin.spec --clean
if %errorlevel% neq 0 (
    echo ❌ שגיאה בבניית עמדת ניהול!
    pause
    exit /b 1
)
echo ✓ עמדת ניהול נבנתה בהצלחה
echo.

echo [2/3] בונה עמדה ציבורית...
pyinstaller SchoolPoints_Public.spec --clean
if %errorlevel% neq 0 (
    echo ❌ שגיאה בבניית עמדה ציבורית!
    pause
    exit /b 1
)
echo ✓ עמדה ציבורית נבנתה בהצלחה
echo.

echo [3/3] סיכום...
echo ✓ שתי העמדות נבנו בהצלחה עם קבצים נקיים!
echo.
echo מיקומים:
echo   - עמדת ניהול: dist\SchoolPoints_Admin\
echo   - עמדה ציבורית: dist\SchoolPoints_Public\
echo.

echo יוצר version.json לעדכון...
python generate_version_json.py
if %errorlevel% neq 0 (
    echo ❌ שגיאה ביצירת version.json!
    pause
    exit /b 1
)
echo ✓ version.json נוצר בהצלחה (Output\version.json)
echo.

echo כעת ניתן לבנות את קובץ ההתקנה עם Inno Setup:
echo   SchoolPoints_Installer.iss
echo.
pause
