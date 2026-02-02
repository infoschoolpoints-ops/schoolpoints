# -*- coding: utf-8 -*-
"""
תיקון שמות עמודות בייצוא קטלוג לעברית
"""

with open('admin_station.py', 'r', encoding='utf-8') as f:
    content = f.read()

# מציאת הפונקציה _export_catalog_csv והוספת מיפוי עברית
old_code = """            try:
                import pandas as pd
                df = pd.DataFrame(rows)
                df.to_excel(fp, index=False, engine='openpyxl')"""

new_code = """            try:
                import pandas as pd
                df = pd.DataFrame(rows)
                
                # Rename columns to Hebrew
                hebrew_columns = {
                    'id': 'מזהה',
                    'name': 'שם פנימי',
                    'points': 'נקודות',
                    'product_type': 'סוג',
                    'category_id': 'מזהה קטגוריה',
                    'is_active': 'פעיל',
                    'category_name': 'קטגוריה',
                    'scheduled_service_id': 'מזהה שירות',
                    'duration_minutes': 'משך (דקות)',
                    'capacity_per_slot': 'קיבולת למשבצת',
                    'start_time': 'שעת התחלה',
                    'end_time': 'שעת סיום',
                    'allow_auto_time': 'בחירת זמן אוטומטית',
                    'max_per_student': 'מקסימום לתלמיד',
                    'max_per_class': 'מקסימום לכיתה',
                    'queue_priority_mode': 'מצב עדיפות',
                    'queue_priority_custom': 'עדיפות מותאמת',
                    'challenge_id': 'מזהה אתגר',
                    'display_name': 'שם תצוגה',
                    'image_path': 'נתיב תמונה',
                    'stock_qty': 'מלאי',
                    'min_stock': 'מלאי מינימלי'
                }
                df = df.rename(columns=hebrew_columns)
                
                df.to_excel(fp, index=False, engine='openpyxl')"""

content = content.replace(old_code, new_code)

with open('admin_station.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Fix: Catalog export columns now in Hebrew")
