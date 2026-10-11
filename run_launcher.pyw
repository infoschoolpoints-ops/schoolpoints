"""
משגר מאוחד (EXE יחיד) לבחירת עמדה: ניהול / ציבורית / קופה.

ניתן להפעיל גם ישירות עם ארגומנט שורת פקודה:
    SchoolPoints.exe --admin    -> עמדת ניהול
    SchoolPoints.exe --public   -> עמדה ציבורית
    SchoolPoints.exe --cashier  -> עמדת קופה
ללא ארגומנט מוצג מסך בחירה.
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

# תיקיית עבודה: ליד קובץ ה-EXE (frozen) או ליד הסקריפט
try:
    if bool(getattr(sys, 'frozen', False)):
        base_dir = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(base_dir)
except Exception:
    base_dir = os.path.dirname(os.path.abspath(__file__))


def _resource_dir():
    """תיקיית המשאבים המובנים (ב-onefile זו תיקיית _MEIPASS הזמנית)."""
    return getattr(sys, '_MEIPASS', base_dir)


def _run_station(station: str):
    """הפעלת מודול העמדה הנבחר."""
    if station == 'admin':
        import admin_station
        admin_station.main()
    elif station == 'public':
        import public_station
        public_station.main()
    elif station == 'cashier':
        import cashier_station
        cashier_station.main()


def _station_from_args():
    args = [a.lower().lstrip('-/') for a in sys.argv[1:]]
    for a in args:
        if a in ('admin', 'ניהול'):
            return 'admin'
        if a in ('public', 'ציבורית'):
            return 'public'
        if a in ('cashier', 'קופה'):
            return 'cashier'
    return None


def _choose_station_gui():
    """מסך בחירת עמדה. מחזיר 'admin' / 'public' / 'cashier' או None אם בוטל."""
    import tkinter as tk

    selection = {'value': None}
    root = tk.Tk()
    root.title("מערכת ניקוד בית ספרית - בחירת עמדה")
    root.configure(bg='#f0f0f0')

    # אייקון
    try:
        for ico in ('admin.ico',):
            p = os.path.join(_resource_dir(), 'icons', ico)
            if os.path.exists(p):
                root.iconbitmap(p)
                break
    except Exception:
        pass

    def pick(value):
        selection['value'] = value
        try:
            root.destroy()
        except Exception:
            pass

    container = tk.Frame(root, bg='#f0f0f0', padx=30, pady=24)
    container.pack(fill=tk.BOTH, expand=True)

    tk.Label(
        container,
        text="בחר/י עמדה להפעלה",
        font=('Segoe UI', 16, 'bold'),
        bg='#f0f0f0',
        fg='#222222',
    ).pack(pady=(0, 20))

    buttons = [
        ("עמדת ניהול", '#2563eb', 'admin'),
        ("עמדה ציבורית", '#059669', 'public'),
        ("עמדת קופה", '#d97706', 'cashier'),
    ]
    for text, color, value in buttons:
        b = tk.Button(
            container,
            text=text,
            font=('Segoe UI', 13, 'bold'),
            bg=color,
            fg='white',
            activebackground=color,
            activeforeground='white',
            relief=tk.FLAT,
            cursor='hand2',
            width=22,
            height=2,
            command=lambda v=value: pick(v),
        )
        b.pack(pady=6)

    tk.Button(
        container,
        text="יציאה",
        font=('Segoe UI', 10),
        bg='#e5e7eb',
        fg='#374151',
        relief=tk.FLAT,
        cursor='hand2',
        command=root.destroy,
    ).pack(pady=(16, 0))

    # מרכוז החלון
    try:
        root.update_idletasks()
        w = max(360, root.winfo_reqwidth())
        h = max(320, root.winfo_reqheight())
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        x = max(0, (sw // 2) - (w // 2))
        y = max(0, (sh // 2) - (h // 2))
        root.geometry(f'{w}x{h}+{x}+{y}')
        root.resizable(False, False)
    except Exception:
        pass

    root.mainloop()
    return selection['value']


def main():
    station = _station_from_args()
    if station is None:
        station = _choose_station_gui()
    if station:
        _run_station(station)


if __name__ == '__main__':
    main()
