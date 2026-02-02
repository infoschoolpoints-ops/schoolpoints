"""
הפעלת עמדת ניהול ללא חלון CMD
"""
import sys
import os

# חשוב: הגדרת DPI awareness חייבת לקרות לפני טעינת tkinter (שמוטען דרך admin_station)
try:
    import ctypes
    if sys.platform == 'win32':
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass
except Exception:
    pass

# שינוי תיקיית עבודה
base_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(base_dir)

# הפעלת עמדת ניהול
import admin_station
admin_station.main()
