@echo off
REM Copy this file to C:\TEMP on the cashier PC and run it from there

setlocal EnableDelayedExpansion

echo Installing Python packages from network wheels...
echo.

set "VENV=C:\SchoolPoints_venv"
set "PIP=%VENV%\Scripts\pip.exe"

if not exist "%VENV%" (
    echo ERROR: venv not found at %VENV%
    echo.
    echo First, create the venv by running:
    echo   python -m venv C:\SchoolPoints_venv
    echo.
    pause
    exit /b 1
)

echo Installing from network location...
echo This should be fast (no internet download)
echo.

"%PIP%" install --no-index --find-links="\\Yankl-pc\c\מיצד\SchoolPoints\wheels" Pillow pyserial pywin32 reportlab openpyxl python-barcode tkcalendar

if errorlevel 1 (
    echo.
    echo ERROR: Installation failed
    echo.
    echo Make sure the network path is accessible:
    echo   \\Yankl-pc\c\מיצד\SchoolPoints\wheels
    echo.
    pause
    exit /b 1
)

echo.
echo ======================================
echo Installation complete!
echo ======================================
echo.
pause
endlocal
