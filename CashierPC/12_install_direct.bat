@echo off
setlocal EnableDelayedExpansion

set "LOGFILE=%~dp0LOG_install_direct.txt"

echo ====================================== > "%LOGFILE%"
echo Installing Python packages directly >> "%LOGFILE%"
echo [%DATE% %TIME%] >> "%LOGFILE%"
echo ====================================== >> "%LOGFILE%"
echo. >> "%LOGFILE%"

echo Installing Python packages directly...
echo Log: %LOGFILE%
echo.

set "VENV=C:\SchoolPoints_venv"
echo Venv location: %VENV% >> "%LOGFILE%"
echo. >> "%LOGFILE%"

if not exist "%VENV%" (
    echo ERROR: venv not found. Run 11_install_simple.bat first >> "%LOGFILE%"
    type "%LOGFILE%"
    pause
    exit /b 1
)

set "PIP=%VENV%\Scripts\pip.exe"

echo Installing packages with --trusted-host to bypass SSL... >> "%LOGFILE%"
echo This may take several minutes... >> "%LOGFILE%"
echo. >> "%LOGFILE%"

echo [1/7] Installing Pillow... >> "%LOGFILE%"
"%PIP%" install --trusted-host pypi.org --trusted-host files.pythonhosted.org Pillow >> "%LOGFILE%" 2>&1

echo [2/7] Installing pyserial... >> "%LOGFILE%"
"%PIP%" install --trusted-host pypi.org --trusted-host files.pythonhosted.org pyserial >> "%LOGFILE%" 2>&1

echo [3/7] Installing pywin32... >> "%LOGFILE%"
"%PIP%" install --trusted-host pypi.org --trusted-host files.pythonhosted.org pywin32 >> "%LOGFILE%" 2>&1

echo [4/7] Installing reportlab... >> "%LOGFILE%"
"%PIP%" install --trusted-host pypi.org --trusted-host files.pythonhosted.org reportlab >> "%LOGFILE%" 2>&1

echo [5/7] Installing openpyxl... >> "%LOGFILE%"
"%PIP%" install --trusted-host pypi.org --trusted-host files.pythonhosted.org openpyxl >> "%LOGFILE%" 2>&1

echo [6/7] Installing python-barcode... >> "%LOGFILE%"
"%PIP%" install --trusted-host pypi.org --trusted-host files.pythonhosted.org python-barcode >> "%LOGFILE%" 2>&1

echo [7/7] Installing tkcalendar... >> "%LOGFILE%"
"%PIP%" install --trusted-host pypi.org --trusted-host files.pythonhosted.org tkcalendar >> "%LOGFILE%" 2>&1

echo. >> "%LOGFILE%"
echo ====================================== >> "%LOGFILE%"
echo Installation complete! >> "%LOGFILE%"
echo ====================================== >> "%LOGFILE%"

type "%LOGFILE%"
echo.
echo Installation complete!
echo You can now run: 09_direct_python.bat
echo.
pause
endlocal
