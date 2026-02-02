"""
הפעלת עמדת קופה ללא חלון CMD
"""
import sys
import os

# חשוב: הגדרת DPI awareness חייבת לקרות לפני טעינת tkinter
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

# הפעלת עמדת קופה
import cashier_station
cashier_station.main()
