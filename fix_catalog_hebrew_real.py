# -*- coding: utf-8 -*-
"""
תיקון אמיתי של עמודות ייצוא קטלוג לעברית
"""

with open('admin_station.py', 'r', encoding='utf-8') as f:
    content = f.read()

# הבעיה: הקוד הקודם לא עבד כי השמות באים מ-SQL
# צריך לשנות את השאילתה עצמה או לעשות rename אחרי הקריאה

# מציאת הפונקציה _export_catalog_csv
marker = """            try:
                import pandas as pd
                df = pd.DataFrame(rows)
                
                # Rename columns to Hebrew
                hebrew_columns = {"""

if marker in content:
    print("הקוד כבר קיים, מדלג...")
else:
    # הקוד עדיין לא קיים, נוסיף אותו
    old_code = """            try:
                import pandas as pd
                df = pd.DataFrame(rows)
                df.to_excel(fp, index=False, engine='openpyxl')"""
    
    new_code = """            try:
                import pandas as pd
                df = pd.DataFrame(rows)
                
                # Rename columns to Hebrew
                hebrew_columns = {
                    'product_id': 'מזהה מוצר',
                    'product_is_active': 'פעיל',
                    'product_name': 'שם מוצר',
                    'product_display_name': 'שם תצוגה',
                    'product_price_points': 'מחיר (נקודות)',
                    'product_stock_qty': 'מלאי',
                    'product_image_path': 'נתיב תמונה',
                    'category_name': 'קטגוריה',
                    'product_allowed_classes': 'כיתות מורשות',
                    'product_min_points_required': 'מינימום נקודות',
                    'product_max_per_student': 'מקסימום לתלמיד',
                    'product_max_per_class': 'מקסימום לכיתה',
                    'challenge_id': 'מזהה אתגר',
                    'challenge_is_active': 'אתגר פעיל',
                    'challenge_duration_minutes': 'משך (דקות)',
                    'challenge_capacity_per_slot': 'קיבולת למשבצת',
                    'challenge_start_time': 'שעת התחלה',
                    'challenge_end_time': 'שעת סיום',
                    'challenge_allow_auto_time': 'בחירת זמן אוטומטית',
                    'challenge_max_per_student': 'אתגר - מקס\' לתלמיד',
                    'challenge_max_per_class': 'אתגר - מקס\' לכיתה',
                }
                df = df.rename(columns=hebrew_columns)
                
                df.to_excel(fp, index=False, engine='openpyxl')"""
    
    content = content.replace(old_code, new_code)
    
    with open('admin_station.py', 'w', encoding='utf-8') as f:
        f.write(content)
    
    print("תיקון 4: עמודות קטלוג בעברית - הושלם!")
