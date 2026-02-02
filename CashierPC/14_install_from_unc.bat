@echo off
setlocal EnableDelayedExpansion

echo Installing from UNC path (no drive mapping needed)...
echo.

set "VENV=C:\SchoolPoints_venv"
set "PIP=%VENV%\Scripts\pip.exe"

if not exist "%VENV%" (
    echo ERROR: venv not found at %VENV%
    echo Please run 11_install_simple.bat first
    pause
    exit /b 1
)

set "WHEELS=\\Yankl-pc\c\מיצד\SchoolPoints\wheels"

if not exist "%WHEELS%" (
    echo ERROR: Wheels directory not found at:
    echo   %WHEELS%
    echo.
    echo Make sure the network share is accessible.
    pause
    exit /b 1
)

echo Found wheels at: %WHEELS%
echo.
echo Installing packages from local wheels...
echo This should be fast (no internet needed)
echo.

"%PIP%" install --no-index --find-links="%WHEELS%" Pillow pyserial pywin32 reportlab openpyxl python-barcode tkcalendar pyluach

if errorlevel 1 (
    echo.
    echo ERROR: Installation failed
    echo Check that all wheel files exist in: %WHEELS%
    pause
    exit /b 1
)

echo.
echo ======================================
echo Installation complete!
echo ======================================
echo.
echo You can now run cashier station with:
echo   \\Yankl-pc\c\מיצד\SchoolPoints\CashierPC\09_direct_python.bat
echo.
pause
endlocal
