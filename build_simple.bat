@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================
echo בניית התוכנה - גרסה פשוטה
echo ========================================
echo.

echo [0/4] מגדיר ENABLE_PURCHASES=True...
python -c "open('build_flags.py','w',encoding='utf-8').write('ENABLE_PURCHASES = True\n')"

echo [1/4] מתקין תלויות...
echo (זה עשוי לקחת כמה דקות - אנא המתן)
pip install -r requirements.txt --quiet

echo [1.5/4] יוצר אייקונים (icons/*.ico) אם חסר...
python generate_app_icons.py

echo [2/4] בונה עמדת ניהול...
pyinstaller SchoolPoints_Admin.spec --clean --noconfirm

echo [3/4] בונה עמדה ציבורית...
pyinstaller SchoolPoints_Public.spec --clean --noconfirm

echo [4/4] בונה עמדת קופה...
pyinstaller SchoolPoints_Cashier.spec --clean --noconfirm

echo.
echo ✓ הבנייה הסתיימה!
echo.
pause
