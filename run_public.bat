@echo off
REM הפעלת עמדה ציבורית ללא חלון CMD
cd /d "%~dp0"
start "" pythonw.exe public_station.py
exit
