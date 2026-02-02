# -*- coding: utf-8 -*-
"""
העתקת צלילים שמחים מ-Windows לתיקיית sounds
"""
import os
import shutil

# צלילים שמחים ומתאימים מ-Windows
HAPPY_SOUNDS = [
    'tada.wav',
    'chimes.wav',
    'ding.wav',
    'notify.wav',
    'Windows Notify Calendar.wav',
    'Windows Notify Email.wav',
    'Windows Notify Messaging.wav',
    'Windows Proximity Connection.wav',
    'Windows Unlock.wav',
    'Windows Pop-up Blocked.wav',
    'Windows Battery Critical.wav',
    'Windows Battery Low.wav',
    'Windows Critical Stop.wav',
    'Windows Exclamation.wav',
    'Windows Hardware Fail.wav',
    'Windows Hardware Insert.wav',
    'Windows Hardware Remove.wav',
]

source_dir = r'C:\Windows\media'
target_dir = r'c:\מיצד\SchoolPoints\sounds'

# יצירת תיקיית יעד
os.makedirs(target_dir, exist_ok=True)

copied = []
not_found = []

for sound_file in HAPPY_SOUNDS:
    source_path = os.path.join(source_dir, sound_file)
    target_path = os.path.join(target_dir, sound_file)
    
    if os.path.exists(source_path):
        try:
            shutil.copy2(source_path, target_path)
            copied.append(sound_file)
            print(f"✓ הועתק: {sound_file}")
        except Exception as e:
            print(f"✗ שגיאה בהעתקת {sound_file}: {e}")
    else:
        not_found.append(sound_file)

print(f"\n--- סיכום ---")
print(f"הועתקו: {len(copied)} קבצים")
print(f"לא נמצאו: {len(not_found)} קבצים")

if not_found:
    print("\nקבצים שלא נמצאו:")
    for f in not_found:
        print(f"  - {f}")
