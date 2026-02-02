@echo off
setlocal

set "LOGDIR=%~dp0"
set "LOG=%LOGDIR%LOG_transcript.txt"

echo.
echo This window will stay open.
echo Transcript will be written to:
echo   %LOG%
echo.

powershell -NoProfile -NoExit -ExecutionPolicy Bypass -Command "& {
  $Log = '%LOG%'
  try {
    try { Remove-Item -LiteralPath $Log -Force -ErrorAction SilentlyContinue } catch {}
    Start-Transcript -LiteralPath $Log -Append | Out-Null
  } catch {
    # Fallback: if transcript fails, continue and rely on manual output
    try {
      ('[TRANSCRIPT FAILED] ' + $_.Exception.Message) | Out-File -LiteralPath $Log -Encoding UTF8 -Append
    } catch {}
  }

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

  $Venv = Join-Path $env:LOCALAPPDATA 'SchoolPoints\venv'
  $VenvPy = Join-Path $Venv 'Scripts\python.exe'

  Write-Host ('Project: ' + $Project)
  Write-Host ('Entry:   ' + $Entry)
  Write-Host ('VenvPy:  ' + $VenvPy)

  if (-not (Test-Path -LiteralPath $VenvPy)) {
    Write-Host 'ERROR: venv missing. Run: 01_install_deps_from_network.bat'
    Stop-Transcript | Out-Null
    exit 1
  }
  if (-not (Test-Path -LiteralPath $Entry)) {
    Write-Host 'ERROR: cashier_station.py not found.'
    Stop-Transcript | Out-Null
    exit 1
  }

  try {
    & $VenvPy $Entry
  } catch {
    try {
      ('[ERROR] ' + $_.Exception.ToString()) | Out-File -LiteralPath $Log -Encoding UTF8 -Append
    } catch {}
    throw
  } finally {
    try { Stop-Transcript | Out-Null } catch {}
  }
}"

echo.
echo If it crashed, open:
echo   %LOG%
echo.
pause
endlocal
