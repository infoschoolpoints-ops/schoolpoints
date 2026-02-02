@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================
echo בניית התוכנה - גרסה מהירה
echo ========================================
echo.

REM הגדרת דגל
echo [0/4] מגדיר ENABLE_PURCHASES=True...
python -c "open('build_flags.py','w',encoding='utf-8').write('ENABLE_PURCHASES = True\n')"

echo [0.5/4] יוצר אייקונים (icons/*.ico) אם חסר...
python generate_app_icons.py

REM דילוג על התקנת תלויות - נניח שכבר מותקנות
echo [1/4] דולג על התקנת תלויות (נניח שכבר מותקנות)...
echo אם יש שגיאות בהמשך, הרץ: pip install -r requirements.txt
echo.

echo [2/4] בונה עמדת ניהול...
pyinstaller SchoolPoints_Admin.spec --clean --noconfirm
if %errorlevel% neq 0 (
    echo ❌ שגיאה בבניית עמדת ניהול!
    pause
    exit /b 1
)
echo ✓ עמדת ניהול נבנתה

echo [3/4] בונה עמדה ציבורית...
pyinstaller SchoolPoints_Public.spec --clean --noconfirm
if %errorlevel% neq 0 (
    echo ❌ שגיאה בבניית עמדה ציבורית!
    pause
    exit /b 1
)
echo ✓ עמדה ציבורית נבנתה

echo [4/4] בונה עמדת קופה...
pyinstaller SchoolPoints_Cashier.spec --clean --noconfirm
if %errorlevel% neq 0 (
    echo ❌ שגיאה בבניית עמדת קופה!
    pause
    exit /b 1
)
echo ✓ עמדת קופה נבנתה

echo.
echo [5/5] יוצר version.json...
python generate_version_json.py

echo.
echo ========================================
echo ✓ הבנייה הסתיימה בהצלחה!
echo ========================================
echo.
echo קבצים נוצרו בתיקייה: dist\
echo.
pause
