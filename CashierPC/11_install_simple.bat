@echo off
setlocal EnableDelayedExpansion

set "LOGFILE=%~dp0LOG_install.txt"

echo ====================================== > "%LOGFILE%"
echo Installing Python venv and dependencies >> "%LOGFILE%"
echo [%DATE% %TIME%] >> "%LOGFILE%"
echo ====================================== >> "%LOGFILE%"
echo. >> "%LOGFILE%"

echo Installing Python venv and dependencies...
echo Log: %LOGFILE%
echo.

REM Find requirements.txt
set "PROJECT=Z:\"
set "REQS=%PROJECT%requirements.txt"
if exist "%REQS%" goto :found_reqs

set "PROJECT=Z:\SchoolPoints"
set "REQS=%PROJECT%\requirements.txt"
if exist "%REQS%" goto :found_reqs

set "PROJECT=\\Yankl-pc\c\מיצד\SchoolPoints"
set "REQS=%PROJECT%\requirements.txt"
if exist "%REQS%" goto :found_reqs

echo ERROR: requirements.txt not found >> "%LOGFILE%"
echo Tried: >> "%LOGFILE%"
echo   Z:\requirements.txt >> "%LOGFILE%"
echo   Z:\SchoolPoints\requirements.txt >> "%LOGFILE%"
echo   \\Yankl-pc\c\מיצד\SchoolPoints\requirements.txt >> "%LOGFILE%"
type "%LOGFILE%"
pause
exit /b 1

:found_reqs
echo Found requirements.txt: %REQS% >> "%LOGFILE%"
echo. >> "%LOGFILE%"

set "VENV=C:\SchoolPoints_venv"
echo Venv location: %VENV% >> "%LOGFILE%"
echo. >> "%LOGFILE%"

echo Checking Python... >> "%LOGFILE%"
python --version >> "%LOGFILE%" 2>&1
if errorlevel 1 (
    echo ERROR: Python not found in PATH >> "%LOGFILE%"
    echo Please install Python 3.12 first >> "%LOGFILE%"
    type "%LOGFILE%"
    pause
    exit /b 1
)

echo. >> "%LOGFILE%"
echo Creating venv at: %VENV% >> "%LOGFILE%"
echo This may take a few minutes... >> "%LOGFILE%"
echo. >> "%LOGFILE%"

if exist "%VENV%" (
    echo Venv already exists, removing old one... >> "%LOGFILE%"
    rmdir /s /q "%VENV%" >> "%LOGFILE%" 2>&1
)

python -m venv "%VENV%" >> "%LOGFILE%" 2>&1
if errorlevel 1 (
    echo ERROR: Failed to create venv >> "%LOGFILE%"
    type "%LOGFILE%"
    pause
    exit /b 1
)

echo Venv created successfully >> "%LOGFILE%"
echo. >> "%LOGFILE%"

set "PYTHON=%VENV%\Scripts\python.exe"
set "PIP=%VENV%\Scripts\pip.exe"

echo Upgrading pip... >> "%LOGFILE%"
"%PYTHON%" -m pip install --upgrade pip >> "%LOGFILE%" 2>&1

echo. >> "%LOGFILE%"
echo Installing dependencies from: >> "%LOGFILE%"
echo   %REQS% >> "%LOGFILE%"
echo. >> "%LOGFILE%"

"%PIP%" install -r "%REQS%" >> "%LOGFILE%" 2>&1
if errorlevel 1 (
    echo. >> "%LOGFILE%"
    echo WARNING: Some packages may have failed to install >> "%LOGFILE%"
    echo Check log for details >> "%LOGFILE%"
) else (
    echo. >> "%LOGFILE%"
    echo All dependencies installed successfully! >> "%LOGFILE%"
)

echo. >> "%LOGFILE%"
echo ====================================== >> "%LOGFILE%"
echo Installation complete >> "%LOGFILE%"
echo Venv location: %VENV% >> "%LOGFILE%"
echo ====================================== >> "%LOGFILE%"

type "%LOGFILE%"
echo.
echo Installation complete!
echo You can now run: 09_direct_python.bat
echo.
pause
endlocal
