@echo off
setlocal EnableDelayedExpansion

set "LOGFILE=%~dp0LOG_global.txt"

echo ====================================== > "%LOGFILE%"
echo Run with Global Python (no venv) >> "%LOGFILE%"
echo [%DATE% %TIME%] >> "%LOGFILE%"
echo ====================================== >> "%LOGFILE%"
echo. >> "%LOGFILE%"

REM Find cashier_station.py
set "PROJECT=Z:\"
set "ENTRY=%PROJECT%cashier_station.py"
if exist "%ENTRY%" goto :found

set "PROJECT=Z:\SchoolPoints"
set "ENTRY=%PROJECT%\cashier_station.py"
if exist "%ENTRY%" goto :found

set "PROJECT=\\Yankl-pc\c\מיצד\SchoolPoints"
set "ENTRY=%PROJECT%\cashier_station.py"
if exist "%ENTRY%" goto :found

echo ERROR: cashier_station.py not found >> "%LOGFILE%"
type "%LOGFILE%"
pause
exit /b 1

:found
echo Found: %ENTRY% >> "%LOGFILE%"
echo. >> "%LOGFILE%"

echo Using global Python... >> "%LOGFILE%"
python --version >> "%LOGFILE%" 2>&1

echo. >> "%LOGFILE%"
echo Starting cashier... >> "%LOGFILE%"
echo ====================================== >> "%LOGFILE%"

type "%LOGFILE%"
echo.
echo Running: python "%ENTRY%"
echo.

python "%ENTRY%" 2>&1 | tee -a "%LOGFILE%"

echo. >> "%LOGFILE%"
echo ====================================== >> "%LOGFILE%"
echo Cashier exited. >> "%LOGFILE%"

type "%LOGFILE%"
pause
endlocal
