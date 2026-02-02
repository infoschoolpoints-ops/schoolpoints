# -*- coding: utf-8 -*-
"""
הוספת עמודת צלילים לעורך הצבעים
שינוי כותרת ל"צלילים וצבעים"
"""

with open('color_editor.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. שינוי כותרת החלון
content = content.replace(
    'self.root.title("הגדרות מטבעות וצבעים - מערכת ניקוד")',
    'self.root.title("🎵 הגדרות צלילים, צבעים ומטבעות - מערכת ניקוד")'
)

content = content.replace(
    'text="⚙️ עורך מטבעות וצבעים - טווחי נקודות"',
    'text="🎵 עורך צלילים, צבעים ומטבעות"'
)

content = content.replace(
    'text="קבע צבעים שונים לטווחי נקודות, ומטבעות/יהלומים מבוססי נקודות בעמדה הציבורית"',
    'text="קבע צלילים וצבעים לטווחי נקודות, ומטבעות/יהלומים בעמדה הציבורית"'
)

# 2. שינוי שם הטאב הראשון
content = content.replace(
    'notebook.add(ranges_tab, text="צבעים")',
    'notebook.add(ranges_tab, text="צלילים וצבעים")'
)

# 3. הוספת עמודת צליל בכותרות
old_headers = """        tk.Label(headers, text="צבע", font=('Arial', 10, 'bold'), bg='#ecf0f1', width=10).pack(side=tk.RIGHT, padx=5)
        tk.Label(headers, text="שם", font=('Arial', 10, 'bold'), bg='#ecf0f1', width=10).pack(side=tk.RIGHT, padx=5)
        tk.Label(headers, text="מקסימום", font=('Arial', 10, 'bold'), bg='#ecf0f1', width=10).pack(side=tk.RIGHT, padx=5)
        tk.Label(headers, text="מינימום", font=('Arial', 10, 'bold'), bg='#ecf0f1', width=10).pack(side=tk.RIGHT, padx=5)"""

new_headers = """        tk.Label(headers, text="צליל", font=('Arial', 10, 'bold'), bg='#ecf0f1', width=12).pack(side=tk.RIGHT, padx=5)
        tk.Label(headers, text="צבע", font=('Arial', 10, 'bold'), bg='#ecf0f1', width=10).pack(side=tk.RIGHT, padx=5)
        tk.Label(headers, text="שם", font=('Arial', 10, 'bold'), bg='#ecf0f1', width=10).pack(side=tk.RIGHT, padx=5)
        tk.Label(headers, text="מקסימום", font=('Arial', 10, 'bold'), bg='#ecf0f1', width=10).pack(side=tk.RIGHT, padx=5)
        tk.Label(headers, text="מינימום", font=('Arial', 10, 'bold'), bg='#ecf0f1', width=10).pack(side=tk.RIGHT, padx=5)"""

content = content.replace(old_headers, new_headers)

# 4. הגדלת גודל החלון כדי להכיל את העמודה החדשה
content = content.replace(
    'self.root.geometry("520x500")',
    'self.root.geometry("720x550")'
)

with open('color_editor.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("שינוי כותרת וכותרות עמודות הושלם!")
print("עכשיו צריך להוסיף את הלוגיקה לבחירת קבצי שמע בכל שורה...")
