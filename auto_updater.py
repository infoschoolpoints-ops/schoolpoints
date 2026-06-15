"""
Auto-updater module for SchoolPoints
Checks for new versions on GitHub Releases and downloads/installs updates
"""
import os
import sys
import json
import urllib.request
import urllib.error
import subprocess
import tempfile
import shutil
from typing import Optional, Tuple

CURRENT_VERSION = "1.6.5"
GITHUB_REPO = "infoschoolpoints-ops/schoolpoints"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


def compare_versions(v1: str, v2: str) -> int:
    """Compare two version strings (e.g., '1.6.5' vs '1.7.0').
    Returns: -1 if v1 < v2, 0 if equal, 1 if v1 > v2
    """
    try:
        parts1 = [int(x) for x in v1.split('.')]
        parts2 = [int(x) for x in v2.split('.')]
        
        # Pad to same length
        max_len = max(len(parts1), len(parts2))
        parts1 += [0] * (max_len - len(parts1))
        parts2 += [0] * (max_len - len(parts2))
        
        for p1, p2 in zip(parts1, parts2):
            if p1 < p2:
                return -1
            elif p1 > p2:
                return 1
        return 0
    except Exception:
        return 0


def check_for_updates(timeout: int = 10) -> Optional[dict]:
    """Check GitHub Releases for a newer version.
    Returns dict with 'version', 'download_url', 'release_notes' if update available, else None.
    """
    try:
        req = urllib.request.Request(
            GITHUB_API_URL,
            headers={'Accept': 'application/vnd.github.v3+json'}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        
        latest_version = str(data.get('tag_name') or '').lstrip('v').strip()
        if not latest_version:
            return None
        
        if compare_versions(CURRENT_VERSION, latest_version) >= 0:
            return None
        
        # Find the appropriate asset (EXE file)
        assets = data.get('assets', [])
        download_url = None
        
        # Determine which EXE we are (admin/public/cashier) based on sys.argv[0]
        exe_name = os.path.basename(sys.argv[0]).lower()
        if 'admin' in exe_name:
            target_name = 'SchoolPoints_Admin.exe'
        elif 'public' in exe_name:
            target_name = 'SchoolPoints_Public.exe'
        elif 'cashier' in exe_name or 'קופה' in exe_name:
            target_name = 'SchoolPoints_Cashier.exe'
        else:
            target_name = None
        
        for asset in assets:
            asset_name = str(asset.get('name') or '')
            if target_name and asset_name == target_name:
                download_url = asset.get('browser_download_url')
                break
        
        if not download_url:
            return None
        
        return {
            'version': latest_version,
            'download_url': download_url,
            'release_notes': str(data.get('body') or '').strip()
        }
    
    except Exception as e:
        print(f"[AUTO-UPDATE] Check failed: {e}")
        return None


def download_update(download_url: str, dest_path: str, timeout: int = 300) -> bool:
    """Download the update file to dest_path.
    Returns True if successful.
    """
    try:
        print(f"[AUTO-UPDATE] Downloading from {download_url}...")
        req = urllib.request.Request(download_url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            with open(dest_path, 'wb') as f:
                shutil.copyfileobj(resp, f)
        print(f"[AUTO-UPDATE] Downloaded to {dest_path}")
        return True
    except Exception as e:
        print(f"[AUTO-UPDATE] Download failed: {e}")
        return False


def install_update(new_exe_path: str) -> bool:
    """Install the update by replacing the current EXE.
    Uses a batch script to wait for the current process to exit, then replaces the EXE.
    Returns True if the update script was launched successfully.
    """
    try:
        current_exe = os.path.abspath(sys.argv[0])
        
        # Create a batch script to perform the update
        update_script = os.path.join(tempfile.gettempdir(), 'schoolpoints_update.bat')
        
        with open(update_script, 'w', encoding='utf-8') as f:
            f.write('@echo off\n')
            f.write('echo Waiting for SchoolPoints to close...\n')
            f.write(f'timeout /t 2 /nobreak >nul\n')
            f.write(f'echo Installing update...\n')
            f.write(f'move /y "{new_exe_path}" "{current_exe}"\n')
            f.write(f'if errorlevel 1 (\n')
            f.write(f'    echo Update failed!\n')
            f.write(f'    pause\n')
            f.write(f'    exit /b 1\n')
            f.write(f')\n')
            f.write(f'echo Update installed successfully!\n')
            f.write(f'echo Restarting SchoolPoints...\n')
            f.write(f'start "" "{current_exe}"\n')
            f.write(f'del "%~f0"\n')  # Delete the update script itself
        
        # Launch the update script and exit
        subprocess.Popen(
            ['cmd', '/c', update_script],
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
        )
        
        print(f"[AUTO-UPDATE] Update script launched. Exiting...")
        return True
    
    except Exception as e:
        print(f"[AUTO-UPDATE] Install failed: {e}")
        return False


def check_and_prompt_update(parent_window=None, auto_install: bool = False) -> bool:
    """Check for updates and optionally prompt the user.
    If auto_install=True, downloads and installs without prompting.
    Returns True if an update was initiated.
    """
    update_info = check_for_updates()
    if not update_info:
        return False
    
    version = update_info['version']
    download_url = update_info['download_url']
    notes = update_info['release_notes']
    
    if auto_install:
        print(f"[AUTO-UPDATE] New version {version} available. Auto-installing...")
    else:
        try:
            import tkinter as tk
            from tkinter import messagebox
            
            msg = f"גירסה חדשה זמינה: {version}\n\n"
            if notes:
                msg += f"שינויים:\n{notes[:500]}\n\n"
            msg += "האם להוריד ולהתקין עכשיו?"
            
            result = messagebox.askyesno(
                "עדכון זמין",
                msg,
                parent=parent_window
            )
            
            if not result:
                return False
        except Exception:
            # No GUI available or error — skip
            return False
    
    # Download to temp file
    temp_exe = os.path.join(tempfile.gettempdir(), f'schoolpoints_update_{version}.exe')
    
    if not download_update(download_url, temp_exe):
        try:
            from tkinter import messagebox
            messagebox.showerror("שגיאה", "הורדת העדכון נכשלה.", parent=parent_window)
        except Exception:
            pass
        return False
    
    # Install
    if install_update(temp_exe):
        try:
            from tkinter import messagebox
            messagebox.showinfo(
                "עדכון מותקן",
                "העדכון הותקן בהצלחה. התוכנה תיסגר ותיפתח מחדש.",
                parent=parent_window
            )
        except Exception:
            pass
        
        # Exit the current process (update script will restart)
        sys.exit(0)
    else:
        try:
            from tkinter import messagebox
            messagebox.showerror("שגיאה", "התקנת העדכון נכשלה.", parent=parent_window)
        except Exception:
            pass
        return False


if __name__ == '__main__':
    # Test the updater
    print(f"Current version: {CURRENT_VERSION}")
    update_info = check_for_updates()
    if update_info:
        print(f"Update available: {update_info['version']}")
        print(f"Download URL: {update_info['download_url']}")
        print(f"Release notes: {update_info['release_notes'][:200]}...")
    else:
        print("No updates available.")
