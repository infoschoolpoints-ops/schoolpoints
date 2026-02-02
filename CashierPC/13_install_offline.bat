@echo off
setlocal EnableDelayedExpansion

set "LOGFILE=%~dp0LOG_install_offline.txt"

echo ====================================== > "%LOGFILE%"
echo Installing from local wheels (offline) >> "%LOGFILE%"
echo [%DATE% %TIME%] >> "%LOGFILE%"
echo ====================================== >> "%LOGFILE%"
echo. >> "%LOGFILE%"

echo Installing from local wheels (offline mode)...
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
set "PYTHON=%VENV%\Scripts\python.exe"

REM Find wheels directory
set "WHEELS=Z:\wheels"
if not exist "%WHEELS%" (
    set "WHEELS=Z:\SchoolPoints\wheels"
)
if not exist "%WHEELS%" (
    set "WHEELS=\\Yankl-pc\c\מיצד\SchoolPoints\wheels"
)

if exist "%WHEELS%" (
    echo Found wheels directory: %WHEELS% >> "%LOGFILE%"
    echo Installing from local wheels... >> "%LOGFILE%"
    echo. >> "%LOGFILE%"
    
    "%PIP%" install --no-index --find-links="%WHEELS%" Pillow pyserial pywin32 reportlab openpyxl python-barcode tkcalendar pyluach >> "%LOGFILE%" 2>&1
    
    if errorlevel 1 (
        echo WARNING: Offline install failed, trying online with pip index... >> "%LOGFILE%"
        goto :online_install
    ) else (
        echo Offline install successful! >> "%LOGFILE%"
        goto :done
    )
) else (
    echo Wheels directory not found, using online install... >> "%LOGFILE%"
    goto :online_install
)

:online_install
echo. >> "%LOGFILE%"
echo Installing packages online (may be slow due to NetFree)... >> "%LOGFILE%"
echo. >> "%LOGFILE%"

echo Installing Pillow... >> "%LOGFILE%"
"%PYTHON%" -m pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org --trusted-host pypi.python.org Pillow >> "%LOGFILE%" 2>&1

echo Installing pyserial... >> "%LOGFILE%"
"%PYTHON%" -m pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org --trusted-host pypi.python.org pyserial >> "%LOGFILE%" 2>&1

echo Installing pywin32... >> "%LOGFILE%"
"%PYTHON%" -m pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org --trusted-host pypi.python.org pywin32 >> "%LOGFILE%" 2>&1

echo Installing reportlab... >> "%LOGFILE%"
"%PYTHON%" -m pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org --trusted-host pypi.python.org reportlab >> "%LOGFILE%" 2>&1

echo Installing openpyxl... >> "%LOGFILE%"
"%PYTHON%" -m pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org --trusted-host pypi.python.org openpyxl >> "%LOGFILE%" 2>&1

echo Installing python-barcode... >> "%LOGFILE%"
"%PYTHON%" -m pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org --trusted-host pypi.python.org python-barcode >> "%LOGFILE%" 2>&1

echo Installing tkcalendar... >> "%LOGFILE%"
"%PYTHON%" -m pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org --trusted-host pypi.python.org tkcalendar >> "%LOGFILE%" 2>&1

echo Installing pyluach... >> "%LOGFILE%"
"%PYTHON%" -m pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org --trusted-host pypi.python.org pyluach >> "%LOGFILE%" 2>&1

:done
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
