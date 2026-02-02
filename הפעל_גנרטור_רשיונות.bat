@echo off
chcp 65001 > nul
REM Run SchoolPoints license key generator (GUI)

cd /d "%~dp0"

REM Force Python to use UTF-8 for I/O
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

REM Try to run with 'pyw' (preferred on Windows)
start "" pyw -X utf8 "יצירת רשיון.pyw"
if %errorlevel% neq 0 (
    echo -----
    echo 'pyw' not found, trying 'pythonw'...
    start "" pythonw -X utf8 "יצירת רשיון.pyw"
)

REM No pause needed - GUI runs independently
