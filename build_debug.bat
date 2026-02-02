@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================
echo בניית התוכנה - מצב DEBUG
echo ========================================
echo.

echo מנקה קבצים ישנים...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
echo ✓ נוקה

echo יוצר אייקונים (icons/*.ico) אם חסר...
python generate_app_icons.py

echo.
echo [1/3] בונה עמדת ניהול עם פלט מפורט...
echo (אם זה תקוע - תראה בדיוק איפה)
echo ----------------------------------------
pyinstaller SchoolPoints_Admin.spec --clean --noconfirm --log-level INFO 2>&1 | findstr /V "DEBUG:"

if %errorlevel% neq 0 (
    echo.
    echo ❌ שגיאה! בודק לוגים...
    if exist build\SchoolPoints_Admin\warn-SchoolPoints_Admin.txt (
        echo.
        echo === אזהרות מ-PyInstaller ===
        type build\SchoolPoints_Admin\warn-SchoolPoints_Admin.txt
    )
    pause
    exit /b 1
)
echo ✓ עמדת ניהול הושלמה

echo.
echo [2/3] בונה עמדה ציבורית...
pyinstaller SchoolPoints_Public.spec --clean --noconfirm --log-level INFO 2>&1 | findstr /V "DEBUG:"
if %errorlevel% neq 0 (
    echo ❌ שגיאה בעמדה ציבורית!
    pause
    exit /b 1
)
echo ✓ עמדה ציבורית הושלמה

echo.
echo [3/3] בונה עמדת קופה...
pyinstaller SchoolPoints_Cashier.spec --clean --noconfirm --log-level INFO 2>&1 | findstr /V "DEBUG:"
if %errorlevel% neq 0 (
    echo ❌ שגיאה בעמדת קופה!
    pause
    exit /b 1
)
echo ✓ עמדת קופה הושלמה

echo.
echo ========================================
echo ✓ כל העמדות נבנו בהצלחה!
echo ========================================
echo.
echo קבצים ב: dist\SchoolPoints_Admin\
echo           dist\SchoolPoints_Public\
echo           dist\SchoolPoints_Cashier\
echo.
pause
