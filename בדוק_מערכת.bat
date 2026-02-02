@echo off
chcp 65001 > nul
echo ╔════════════════════════════════════════════════════════════╗
echo ║              בדיקת מערכת - מערכת ניקוד                    ║
echo ╚════════════════════════════════════════════════════════════╝
echo.

echo [1/5] בודק Python...
python --version 2>nul
if %errorlevel% neq 0 (
    echo ❌ Python לא מותקן
    echo התקן מ: https://www.python.org/downloads/
    goto :error
) else (
    echo ✅ Python מותקן
)
echo.

echo [2/5] בודק חבילות Python...
python -c "import pandas" 2>nul
if %errorlevel% neq 0 (
    echo ❌ pandas לא מותקן
    goto :error
) else (
    echo ✅ pandas מותקן
)

python -c "import openpyxl" 2>nul
if %errorlevel% neq 0 (
    echo ❌ openpyxl לא מותקן
    goto :error
) else (
    echo ✅ openpyxl מותקן
)

python -c "import PIL" 2>nul
if %errorlevel% neq 0 (
    echo ❌ Pillow לא מותקן
    goto :error
) else (
    echo ✅ Pillow מותקן
)

python -c "import tkinter" 2>nul
if %errorlevel% neq 0 (
    echo ❌ tkinter לא זמין
    goto :error
) else (
    echo ✅ tkinter זמין
)
echo.

echo [3/5] בודק קבצים עיקריים...
if not exist "admin_station.py" (
    echo ❌ admin_station.py חסר
    goto :error
) else (
    echo ✅ admin_station.py קיים
)

if not exist "public_station.py" (
    echo ❌ public_station.py חסר
    goto :error
) else (
    echo ✅ public_station.py קיים
)

if not exist "database.py" (
    echo ❌ database.py חסר
    goto :error
) else (
    echo ✅ database.py קיים
)

if not exist "school_points.db" (
    echo ⚠️ school_points.db לא קיים (ייווצר אוטומטית)
) else (
    echo ✅ school_points.db קיים
)
echo.

echo [4/5] בודק קבצי הפעלה...
if not exist "run_admin.pyw" (
    echo ⚠️ run_admin.pyw חסר
) else (
    echo ✅ run_admin.pyw קיים
)

if not exist "run_public.pyw" (
    echo ⚠️ run_public.pyw חסר
) else (
    echo ✅ run_public.pyw קיים
)
echo.

echo [5/5] גרסאות חבילות:
python -c "import pandas; print('   pandas:', pandas.__version__)"
python -c "import openpyxl; print('   openpyxl:', openpyxl.__version__)"
python -c "import PIL; print('   Pillow:', PIL.__version__)"
echo.

echo ╔════════════════════════════════════════════════════════════╗
echo ║               ✅ המערכת תקינה ומוכנה לשימוש!               ║
echo ╚════════════════════════════════════════════════════════════╝
echo.
echo כדי להריץ:
echo   • עמדת ניהול: run_admin.pyw
echo   • עמדה ציבורית: run_public.pyw
echo.
goto :end

:error
echo.
echo ╔════════════════════════════════════════════════════════════╗
echo ║                  ❌ נמצאו בעיות במערכת                     ║
echo ╚════════════════════════════════════════════════════════════╝
echo.
echo הרץ: התקן_חבילות.bat
echo או ראה: מדריך_העברה_למחשב_חדש.txt
echo.

:end
pause
