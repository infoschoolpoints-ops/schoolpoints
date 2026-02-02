@echo off
setlocal

set "LOG=%~dp0LOG.txt"
echo.>>"%LOG%"
echo ======================================>>"%LOG%"
echo [%DATE% %TIME%] 01_install_deps_from_network>>"%LOG%"
echo ======================================>>"%LOG%"

REM ================================
REM SchoolPoints - Cashier PC Setup
REM IMPORTANT: Uses PowerShell to support Unicode UNC paths (Hebrew folders)
REM ================================

powershell -NoProfile -ExecutionPolicy Bypass -Command "& {
  $Project = 'Z:\\'
  if (-not (Test-Path -LiteralPath (Join-Path $Project 'requirements.txt'))) {
    $Project = 'Z:\\SchoolPoints'
  }
  if (-not (Test-Path -LiteralPath (Join-Path $Project 'requirements.txt'))) {
    $Project = '\\Yankl-pc\c\מיצד\SchoolPoints'
  }
  $Venv = 'C:\SchoolPoints_venv'
  Write-Host '======================================'
  Write-Host 'SchoolPoints - Install deps from network'
  Write-Host ('Project: ' + $Project)
  Write-Host ('Venv:    ' + $Venv)
  Write-Host '======================================'
  Write-Host ''

  & python --version
  if ($LASTEXITCODE -ne 0) {
    Write-Host 'ERROR: Python not found in PATH.'
    Write-Host 'Install Python and check "Add python.exe to PATH".'
    exit 1
  }

  $Req = Join-Path $Project 'requirements.txt'
  if (-not (Test-Path -LiteralPath $Req)) {
    Write-Host 'ERROR: requirements.txt not found:'
    Write-Host $Req
    exit 1
  }

  $VenvPy = Join-Path $Venv 'Scripts\python.exe'
  if (-not (Test-Path -LiteralPath $VenvPy)) {
    Write-Host 'Creating venv...'
    & python -m venv $Venv
    if ($LASTEXITCODE -ne 0) { exit 1 }
  }

  Write-Host 'Upgrading pip...'
  & $VenvPy -m pip install --upgrade pip
  if ($LASTEXITCODE -ne 0) { exit 1 }

  Write-Host 'Installing requirements...'
  & $VenvPy -m pip install -r $Req
  if ($LASTEXITCODE -ne 0) { exit 1 }

  Write-Host 'Installing critical deps (display+print)...'
  & $VenvPy -m pip install pyserial pywin32
  if ($LASTEXITCODE -ne 0) { exit 1 }

  Write-Host ''
  Write-Host 'DONE.'
  Write-Host 'Next:'
  Write-Host ' - Run cashier:  02_run_cashier_from_network.bat'
  Write-Host ' - Test display: 03_test_display_from_network.bat'
  Write-Host ' - Test printer: 04_test_printer_from_cashier_settings.bat'
}" >> "%LOG%" 2>&1

if errorlevel 1 (
  echo.
  echo ERROR: משהו נכשל. פותח לוג: %LOG%
  notepad "%LOG%"
)

echo.
pause
endlocal
