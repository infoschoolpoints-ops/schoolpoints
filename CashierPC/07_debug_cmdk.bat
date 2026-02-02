@echo off
setlocal

REM Forces window to stay open even if something crashes immediately

echo Opening persistent debug window...
echo.

cmd /k call "%~dp006_run_cashier_with_transcript.bat"

endlocal
