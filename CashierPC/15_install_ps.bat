@echo off
echo Installing packages via PowerShell (handles Hebrew paths)...
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command "& { $venv = 'C:\SchoolPoints_venv'; $pip = Join-Path $venv 'Scripts\pip.exe'; if (-not (Test-Path $pip)) { Write-Host 'ERROR: venv not found'; Read-Host 'Press Enter'; exit 1 }; $wheels = '\\Yankl-pc\c\מיצד\SchoolPoints\wheels'; if (-not (Test-Path $wheels)) { Write-Host ('ERROR: Wheels not found at: ' + $wheels); Read-Host 'Press Enter'; exit 1 }; Write-Host 'Installing from local wheels...'; Write-Host ''; & $pip install --no-index --find-links=$wheels Pillow pyserial pywin32 reportlab openpyxl python-barcode tkcalendar pyluach; if ($LASTEXITCODE -eq 0) { Write-Host ''; Write-Host '======================================'; Write-Host 'Installation complete!'; Write-Host '======================================'; Write-Host '' } else { Write-Host ''; Write-Host 'ERROR: Installation failed'; Write-Host '' }; Read-Host 'Press Enter to close' }"
