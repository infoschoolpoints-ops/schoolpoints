"""
סקריפט לתיקון 6 הבעיות שהמשתמש דיווח
"""

# קריאת הקובץ
with open('admin_station.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. תיקון הודעת שגיאה בייצוא אתגרים - שינוי הודעה ברורה יותר
content = content.replace(
    "messagebox.showwarning('אין נתונים', 'אין אתגרים לייצוא')",
    "messagebox.showwarning('אין נתונים', 'אין אתגרים במערכת. נא להוסיף אתגרים דרך \"ניהול אתגרים\"')"
)

# שמירת הקובץ
with open('admin_station.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("תיקון 1 הושלם - הודעת שגיאה משופרת לייצוא אתגרים")
