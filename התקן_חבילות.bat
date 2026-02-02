@echo off
chcp 65001 > nul
echo ╔════════════════════════════════════════════════════════════╗
echo ║         התקנת חבילות Python - מערכת ניקוד                ║
echo ╚════════════════════════════════════════════════════════════╝
echo.
echo מתחיל התקנת חבילות...
echo.

echo [1/4] בודק Python...
python --version
if %errorlevel% neq 0 (
    echo.
    echo ❌ שגיאה: Python לא מותקן!
    echo אנא התקן Python מ: https://www.python.org/downloads/
    pause
    exit /b 1
)
echo ✅ Python מותקן
echo.

echo [2/4] משדרג pip...
python -m pip install --upgrade pip
echo.

echo [3/4] מתקין חבילות נדרשות...
python -m pip install pandas>=2.0.0
python -m pip install openpyxl>=3.1.0
python -m pip install Pillow>=10.0.0
echo.

echo [4/4] בודק התקנה...
python -c "import pandas; print('✅ pandas:', pandas.__version__)"
python -c "import openpyxl; print('✅ openpyxl:', openpyxl.__version__)"
python -c "import PIL; print('✅ Pillow:', PIL.__version__)"
python -c "import tkinter; print('✅ tkinter: מותקן')"
echo.

echo ╔════════════════════════════════════════════════════════════╗
echo ║                  ✅ ההתקנה הושלמה בהצלחה!                  ║
echo ╚════════════════════════════════════════════════════════════╝
echo.
echo עכשיו אפשר להריץ את המערכת!
echo.
pause
