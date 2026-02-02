@echo off
setlocal

echo Installing python-escpos for logo printing...
echo.

set "VENV=C:\SchoolPoints_venv"
set "PIP=%VENV%\Scripts\pip.exe"

if not exist "%PIP%" (
    echo ERROR: venv not found at %VENV%
    echo Please run 11_install_simple.bat first
    pause
    exit /b 1
)

echo Installing python-escpos...
"%PIP%" install --trusted-host pypi.org --trusted-host files.pythonhosted.org --trusted-host pypi.python.org python-escpos

echo.
echo Installation complete!
echo.
pause
endlocal
