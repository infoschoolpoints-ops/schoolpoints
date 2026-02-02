@echo off
setlocal

set "LOG=%~dp0LOG.txt"

echo.>>"%LOG%"
echo ======================================>>"%LOG%"
echo [%DATE% %TIME%] 05_diagnose_keep_window_open>>"%LOG%"
echo ======================================>>"%LOG%"

echo.
echo This window will STAY OPEN.
echo If cashier crashes immediately, the error will be in:
echo   %LOG%
echo.
echo Running: 02_run_cashier_from_network.bat
echo.

call "%~dp002_run_cashier_from_network.bat"

echo.
echo Done. Press any key.
pause
endlocal
