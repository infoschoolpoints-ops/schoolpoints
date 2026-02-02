@echo off
setlocal

set "LOG=%~dp0LOG.txt"
echo.>>"%LOG%"
echo ======================================>>"%LOG%"
echo [%DATE% %TIME%] 02_run_cashier_from_network>>"%LOG%"
echo ======================================>>"%LOG%"

powershell -NoProfile -ExecutionPolicy Bypass -Command "& {
  $Project = 'Z:\\'
  $Entry = Join-Path $Project 'cashier_station.py'
  if (-not (Test-Path -LiteralPath $Entry)) {
    $Project = 'Z:\\SchoolPoints'
    $Entry = Join-Path $Project 'cashier_station.py'
  }
  if (-not (Test-Path -LiteralPath $Entry)) {
    $Project = '\\Yankl-pc\c\מיצד\SchoolPoints'
    $Entry = Join-Path $Project 'cashier_station.py'
  }
  $Venv = 'C:\SchoolPoints_venv'
  $VenvPy = Join-Path $Venv 'Scripts\python.exe'
  if (-not (Test-Path -LiteralPath $VenvPy)) {
    Write-Host 'ERROR: venv missing. Run first: 01_install_deps_from_network.bat'
    exit 1
  }
  if (-not (Test-Path -LiteralPath $Entry)) {
    Write-Host 'ERROR: cashier_station.py not found:'
    Write-Host $Entry
    exit 1
  }
  Write-Host ('Running: ' + $Entry)
  & $VenvPy $Entry
}" >> "%LOG%" 2>&1

if errorlevel 1 (
  echo.
  echo ERROR: עמדת הקופה נסגרה בגלל שגיאה. פותח לוג: %LOG%
  notepad "%LOG%"
)

echo.
pause
endlocal
