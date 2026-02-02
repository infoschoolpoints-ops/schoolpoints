@echo off
REM הפעלת עמדת ניהול ללא חלון CMD
cd /d "%~dp0"
start "" pythonw.exe admin_station.py
exit
