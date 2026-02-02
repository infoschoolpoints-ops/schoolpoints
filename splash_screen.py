"""
Splash Screen מודול - מסך טעינה יפה לפני הפעלת התוכנה
"""
import tkinter as tk
from tkinter import ttk
import threading
import time

class SplashScreen:
    def __init__(self, title="מערכת ניהול נקודות", subtitle="אנא המתן, התוכנה עולה..."):
        self.root = tk.Tk()
        self.root.title("טוען...")
        
        # מסך מלא או מרכזי
        width = 500
        height = 300
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = (screen_width - width) // 2
        y = (screen_height - height) // 2
        
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.overrideredirect(True)  # ללא מסגרת חלון
        self.root.configure(bg='#2c3e50')
        
        # הוספת צל (אפקט עומק)
        self.root.attributes('-topmost', True)
        
        # Frame מרכזי
        main_frame = tk.Frame(self.root, bg='#2c3e50')
        main_frame.pack(expand=True, fill='both', padx=20, pady=20)
        
        # אייקון גדול (אימוג'י)
        icon_label = tk.Label(
            main_frame,
            text="🎓",
            font=('Arial', 72),
            bg='#2c3e50',
            fg='#ffffff'
        )
        icon_label.pack(pady=(20, 10))
        
        # כותרת
        title_label = tk.Label(
            main_frame,
            text=title,
            font=('Arial', 24, 'bold'),
            bg='#2c3e50',
            fg='#ffffff'
        )
        title_label.pack(pady=10)
        
        # תת כותרת
        self.subtitle_label = tk.Label(
            main_frame,
            text=subtitle,
            font=('Arial', 14),
            bg='#2c3e50',
            fg='#ecf0f1'
        )
        self.subtitle_label.pack(pady=10)
        
        # Progress bar מעוצב
        style = ttk.Style()
        style.theme_use('clam')
        style.configure(
            "Custom.Horizontal.TProgressbar",
            troughcolor='#34495e',
            background='#3498db',
            bordercolor='#2c3e50',
            lightcolor='#3498db',
            darkcolor='#2980b9'
        )
        
        self.progress = ttk.Progressbar(
            main_frame,
            style="Custom.Horizontal.TProgressbar",
            orient='horizontal',
            length=400,
            mode='indeterminate'
        )
        self.progress.pack(pady=20)
        self.progress.start(10)  # אנימציה
        
        # טקסט סטטוס
        self.status_label = tk.Label(
            main_frame,
            text="מאתחל מערכת...",
            font=('Arial', 10),
            bg='#2c3e50',
            fg='#95a5a6'
        )
        self.status_label.pack(pady=5)
        
        # הוספת אנימציה לנקודות
        self.dots = 0
        self.animate_dots()
        
        self.root.update()
    
    def animate_dots(self):
        """אנימציה של נקודות מתנועעות"""
        dots_text = "." * (self.dots % 4)
        self.subtitle_label.config(text=f"אנא המתן, התוכנה עולה{dots_text}")
        self.dots += 1
        if hasattr(self, 'root') and self.root.winfo_exists():
            self.root.after(500, self.animate_dots)
    
    def update_status(self, message):
        """עדכון הודעת הסטטוס"""
        if hasattr(self, 'status_label') and self.status_label.winfo_exists():
            self.status_label.config(text=message)
            self.root.update()
    
    def close(self):
        """סגירת מסך הטעינה"""
        try:
            self.progress.stop()
            self.root.destroy()
        except:
            pass


def show_splash_and_run(main_function, title="מערכת ניהול נקודות", init_time=2):
    """
    הצגת splash screen והפעלת הפונקציה הראשית
    
    Args:
        main_function: הפונקציה הראשית להפעיל (לדוגמה: lambda: AdminStation())
        title: כותרת ה-splash screen
        init_time: זמן מינימלי להצגת ה-splash (שניות - במילישניות למעשה)
    """
    splash = SplashScreen(title=title)
    
    # פונקציה שתרוץ אחרי ה-delay
    def close_and_run():
        try:
            splash.close()
        except:
            pass
        # רץ את התוכנה הראשית
        main_function()
    
    # תזמון סגירת splash והרצת התוכנה (ללא threading!)
    splash.root.after(int(init_time * 1000), close_and_run)
    
    # הצגת splash
    try:
        splash.root.mainloop()
    except:
        # אם יש בעיה, רץ את התוכנה בלי splash
        main_function()


if __name__ == "__main__":
    # דוגמה לשימוש
    def demo_app():
        root = tk.Tk()
        root.title("התוכנה הראשית")
        root.geometry("600x400")
        tk.Label(root, text="התוכנה נטענה בהצלחה!", font=('Arial', 20)).pack(pady=50)
        root.mainloop()
    
    show_splash_and_run(demo_app, "מערכת ניהול נקודות - דמו")
