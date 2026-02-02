"""
תיקון גודל חלון ניהול קופה
"""

with open('admin_station.py', 'r', encoding='utf-8') as f:
    content = f.read()

# הגדלת חלון ניהול קופה
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

print("תיקון 2 הושלם - הגדלת חלון ניהול קופה")
