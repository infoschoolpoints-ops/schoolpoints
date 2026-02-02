@echo off
setlocal EnableDelayedExpansion

set "LOGFILE=%~dp0LOG_direct.txt"

echo ====================================== > "%LOGFILE%"
echo Direct Python Run >> "%LOGFILE%"
echo [%DATE% %TIME%] >> "%LOGFILE%"
echo ====================================== >> "%LOGFILE%"
echo. >> "%LOGFILE%"

echo Checking paths... >> "%LOGFILE%"

REM Try Z:\ first
set "PROJECT=Z:\"
set "ENTRY=%PROJECT%cashier_station.py"
if exist "%ENTRY%" (
    echo Found: %ENTRY% >> "%LOGFILE%"
    goto :found
)

REM Try Z:\SchoolPoints
set "PROJECT=Z:\SchoolPoints"
set "ENTRY=%PROJECT%\cashier_station.py"
if exist "%ENTRY%" (
    echo Found: %ENTRY% >> "%LOGFILE%"
    goto :found
)

REM Try UNC
set "PROJECT=\\Yankl-pc\c\מיצד\SchoolPoints"
set "ENTRY=%PROJECT%\cashier_station.py"
if exist "%ENTRY%" (
    echo Found: %ENTRY% >> "%LOGFILE%"
    goto :found
)

echo ERROR: cashier_station.py not found in any location >> "%LOGFILE%"
echo Tried: >> "%LOGFILE%"
echo   Z:\cashier_station.py >> "%LOGFILE%"
echo   Z:\SchoolPoints\cashier_station.py >> "%LOGFILE%"
echo   \\Yankl-pc\c\מיצד\SchoolPoints\cashier_station.py >> "%LOGFILE%"
type "%LOGFILE%"
pause
exit /b 1

:found
set "VENV=C:\SchoolPoints_venv"
set "PYTHON=%VENV%\Scripts\python.exe"

echo Venv: %VENV% >> "%LOGFILE%"
echo Python: %PYTHON% >> "%LOGFILE%"
echo. >> "%LOGFILE%"

if not exist "%PYTHON%" (
    echo ERROR: Python venv not found at: >> "%LOGFILE%"
    echo   %PYTHON% >> "%LOGFILE%"
    echo. >> "%LOGFILE%"
    echo Run first: 01_install_deps_from_network.bat >> "%LOGFILE%"
    type "%LOGFILE%"
    pause
    exit /b 1
)

echo Starting cashier... >> "%LOGFILE%"
echo. >> "%LOGFILE%"
echo ====================================== >> "%LOGFILE%"

type "%LOGFILE%"
echo.
echo Running: "%PYTHON%" "%ENTRY%"
echo.

"%PYTHON%" "%ENTRY%" 2>&1

echo.
echo ====================================== >> "%LOGFILE%"
echo Cashier exited at [%DATE% %TIME%] >> "%LOGFILE%"
echo. >> "%LOGFILE%"

echo.
echo Cashier exited. Check window above for any errors.
echo.
pause
endlocal
