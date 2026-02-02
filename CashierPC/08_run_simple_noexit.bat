@echo off
setlocal

set "LOGDIR=%~dp0"
set "LOG=%LOGDIR%LOG_simple.txt"

echo ====================================== > "%LOG%"
echo [%DATE% %TIME%] Simple run with no-exit >> "%LOG%"
echo ====================================== >> "%LOG%"

echo Running cashier from Z:\ with venv...
echo Log: %LOG%
echo.

powershell -NoProfile -NoExit -ExecutionPolicy Bypass -Command ^
  "$Project = 'Z:\\'; ^
   $Entry = Join-Path $Project 'cashier_station.py'; ^
   if (-not (Test-Path -LiteralPath $Entry)) { ^
     $Project = 'Z:\\SchoolPoints'; ^
     $Entry = Join-Path $Project 'cashier_station.py'; ^
   }; ^
   if (-not (Test-Path -LiteralPath $Entry)) { ^
     $Project = '\\Yankl-pc\c\מיצד\SchoolPoints'; ^
     $Entry = Join-Path $Project 'cashier_station.py'; ^
   }; ^
   $Venv = Join-Path $env:LOCALAPPDATA 'SchoolPoints\venv'; ^
   $VenvPy = Join-Path $Venv 'Scripts\python.exe'; ^
   Write-Host ('Project: ' + $Project); ^
   Write-Host ('Entry:   ' + $Entry); ^
   Write-Host ('VenvPy:  ' + $VenvPy); ^
   Write-Host ''; ^
   if (-not (Test-Path -LiteralPath $VenvPy)) { ^
     Write-Host 'ERROR: venv missing. Run: 01_install_deps_from_network.bat' -ForegroundColor Red; ^
     Read-Host 'Press Enter'; ^
     exit 1; ^
   }; ^
   if (-not (Test-Path -LiteralPath $Entry)) { ^
     Write-Host 'ERROR: cashier_station.py not found' -ForegroundColor Red; ^
     Read-Host 'Press Enter'; ^
     exit 1; ^
   }; ^
   Write-Host 'Starting cashier...'; ^
   ^& $VenvPy $Entry"

endlocal
