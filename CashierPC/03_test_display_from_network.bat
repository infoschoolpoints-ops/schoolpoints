@echo off
setlocal

set "LOG=%~dp0LOG.txt"
echo.>>"%LOG%"
echo ======================================>>"%LOG%"
echo [%DATE% %TIME%] 03_test_display_from_network>>"%LOG%"
echo ======================================>>"%LOG%"

powershell -NoProfile -ExecutionPolicy Bypass -Command "& {
  $Project = 'Z:\\'
  $Bat = Join-Path $Project 'test_display.bat'
  if (-not (Test-Path -LiteralPath $Bat)) {
    $Project = 'Z:\\SchoolPoints'
    $Bat = Join-Path $Project 'test_display.bat'
  }
  if (-not (Test-Path -LiteralPath $Bat)) {
    $Project = '\\Yankl-pc\c\מיצד\SchoolPoints'
    $Bat = Join-Path $Project 'test_display.bat'
  }
  if (-not (Test-Path -LiteralPath $Bat)) {
    Write-Host 'ERROR: not found:'
    Write-Host $Bat
    exit 1
  }
  Write-Host ('Running: ' + $Bat)
  cmd /c ""$Bat""
}" >> "%LOG%" 2>&1

if errorlevel 1 (
  echo.
  echo ERROR: בדיקת המסך נכשלה. פותח לוג: %LOG%
  notepad "%LOG%"
)

echo.
pause
endlocal
