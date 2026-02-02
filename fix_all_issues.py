"""
תיקון כל הבעיות שהמשתמש דיווח
"""
import re

with open('admin_station.py', 'r', encoding='utf-8') as f:
    content = f.read()

print("מתחיל תיקונים...")

# 1. תיקון פריסת טבלאות - הבעיה היא שהטבלה עצמה לא מוגדרת RTL
# צריך להוסיף style configuration ל-Treeview
old_preview = """            columns = list(df.columns)
            tree = ttk.Treeview(tree_frame, columns=columns, show='headings', height=25)
            
            for col in columns:
                tree.heading(col, text=str(col), anchor='e')
                tree.column(col, width=120, anchor='e')"""

new_preview = """            columns = list(df.columns)
            
            # Configure RTL style for preview table
            preview_style = ttk.Style()
            preview_style.configure("Preview.Treeview", 
                                   background="#ffffff",
                                   foreground="#000000",
                                   fieldbackground="#ffffff",
                                   font=('Arial', 10))
            preview_style.configure("Preview.Treeview.Heading",
                                   font=('Arial', 10, 'bold'),
                                   background="#4472C4",
                                   foreground="#ffffff",
                                   anchor='e')
            preview_style.layout("Preview.Treeview", [('Preview.Treeview.treearea', {'sticky': 'nswe'})])
            
            tree = ttk.Treeview(tree_frame, columns=columns, show='headings', height=25, style="Preview.Treeview")
            
            # Reverse column order for RTL display
            reversed_cols = list(reversed(columns))
            tree['columns'] = reversed_cols
            
            for col in reversed_cols:
                tree.heading(col, text=str(col), anchor='e')
                tree.column(col, width=120, anchor='e')"""

content = content.replace(old_preview, new_preview)
print("✓ תיקון 1: פריסת טבלאות RTL")

# 2. תיקון ברירת מחדל של טיקר - צריך לשנות מ-slow ל-normal
content = content.replace(
    "cfg['news_ticker_speed'] = ticker_speed_map.get(selected_ticker_speed_label, 'slow')",
    "cfg['news_ticker_speed'] = ticker_speed_map.get(selected_ticker_speed_label, 'normal')"
)
print("✓ תיקון 2: ברירת מחדל טיקר ל-'רגיל'")

# 3. בדיקה שהגודל של חלון קופה השתנה
if 'dialog.geometry("1200x750")' in content:
    print("✓ תיקון 3: גודל חלון קופה כבר תוקן")
else:
    print("✗ שגיאה: גודל חלון קופה לא השתנה - מתקן עכשיו")
    content = content.replace(
        'dialog.geometry("1000x650")',
        'dialog.geometry("1200x750")'
    )
    content = content.replace(
        'dialog.minsize(950, 600)',
        'dialog.minsize(1150, 700)'
    )

with open('admin_station.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("\nכל התיקונים הושלמו!")
print("עכשיו אבדוק את ייצוא הקטלוג...")
