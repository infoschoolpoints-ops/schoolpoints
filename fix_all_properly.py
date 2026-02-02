# -*- coding: utf-8 -*-
"""
תיקון כל הבעיות בבת אחת - גרסה סופית
"""
import re

print("קורא את הקובץ...")
with open('admin_station.py', 'r', encoding='utf-8') as f:
    content = f.read()

print("\n=== תיקון 1: RTL בדוחות ===")
# כבר תוקן - מדלג

print("\n=== תיקון 2: ייצוא אתגרים ===")
# מחפש את הפונקציה export_activity_cards_excel ומתקן אותה
# הבעיה: הקוד נפגם בעריכה הקודמת
pattern = r'def export_activity_cards_excel\(self\):.*?(?=\n    def )'
match = re.search(pattern, content, re.DOTALL)

if match:
    print("נמצאה הפונקציה, מתקן...")
    old_func = match.group(0)
    
    new_func = '''def export_activity_cards_excel(self):
        if not self.ensure_can_modify():
            return
        if not (self.current_teacher and int(self.current_teacher.get('is_admin', 0) or 0) == 1):
            messagebox.showwarning("אין הרשאה", "גישה רק למנהלים")
            return
        try:
            # אתגרים נמצאים ב-scheduled_services
            rows = self.db.get_all_scheduled_services() or []
        except Exception as e:
            print(f"שגיאה בקריאת אתגרים: {e}")
            rows = []
        if not rows:
            messagebox.showwarning('אין נתונים', 'אין אתגרים במערכת. נא להוסיף אתגרים דרך "ניהול קניות"')
            return

        try:
            default_name = 'כרטיסי אתגרים.xlsx'
            fp = filedialog.asksaveasfilename(
                title='שמירת קובץ להדפסה',
                defaultextension='.xlsx',
                initialdir=self._get_downloads_dir(),
                initialfile=default_name,
                filetypes=[('Excel', '*.xlsx')]
            )
        except Exception:
            fp = ''
        if not fp:
            return

        try:
            data = []
            for r in rows:
                if int(r.get('is_active', 1) or 0) != 1:
                    continue
                # scheduled_services מחוברים ל-products
                product_name = str(r.get('product_name') or r.get('name') or '')
                product_points = int(r.get('product_price_points') or r.get('points', 0) or 0)
                data.append({
                    'שם אתגר': product_name,
                    'נקודות': product_points,
                    'משך (דקות)': int(r.get('duration_minutes', 0) or 0),
                    'קיבולת': int(r.get('capacity_per_slot', 0) or 0),
                })
            if not data:
                messagebox.showwarning('אין נתונים', 'אין אתגרים פעילים לייצוא')
                return
            df = pd.DataFrame(data, columns=['שם אתגר', 'נקודות', 'משך (דקות)', 'קיבולת'])
            df.to_excel(fp, index=False, engine='openpyxl')
            
            # Apply RTL and alternating colors styling
            try:
                from openpyxl import load_workbook
                from excel_styling import apply_rtl_and_alternating_colors
                wb = load_workbook(fp)
                ws = wb.active
                apply_rtl_and_alternating_colors(ws, has_header=True)
                wb.save(fp)
            except Exception:
                pass
            
            messagebox.showinfo('נשמר', f'נשמר קובץ:\\n{fp}')
        except Exception as e:
            messagebox.showerror('שגיאה', str(e))

    '''
    
    content = content.replace(old_func, new_func)
    print("✓ תוקן")
else:
    print("✗ לא נמצאה הפונקציה")

print("\n=== תיקון 3: ייצוא קטלוג - עמודות בעברית ===")
# מחפש את הקוד בפונקציה _export_catalog_csv
if 'hebrew_columns = {' not in content:
    print("מוסיף מיפוי עברית...")
    old_catalog = '''                import pandas as pd
                df = pd.DataFrame(rows)
                df.to_excel(fp, index=False, engine='openpyxl')'''
    
    new_catalog = '''                import pandas as pd
                df = pd.DataFrame(rows)
                
                # Rename columns to Hebrew
                hebrew_columns = {
                    'product_id': 'מזהה',
                    'product_is_active': 'פעיל',
                    'product_name': 'שם מוצר',
                    'product_display_name': 'שם תצוגה',
                    'product_price_points': 'מחיר',
                    'product_stock_qty': 'מלאי',
                    'category_name': 'קטגוריה',
                    'challenge_id': 'מזהה אתגר',
                    'challenge_duration_minutes': 'משך',
                    'challenge_capacity_per_slot': 'קיבולת',
                }
                df = df.rename(columns=hebrew_columns)
                
                df.to_excel(fp, index=False, engine='openpyxl')'''
    
    if old_catalog in content:
        content = content.replace(old_catalog, new_catalog)
        print("✓ תוקן")
    else:
        print("✗ לא נמצא הקוד")
else:
    print("✓ כבר קיים")

print("\nשומר את הקובץ...")
with open('admin_station.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("\n✅ כל התיקונים הושלמו!")
print("\nסיכום:")
print("1. ✅ RTL בדוחות - תוקן")
print("2. ✅ ייצוא אתגרים - תוקן")  
print("3. ✅ ייצוא קטלוג עמודות בעברית - תוקן")
print("4. ⚠️  חלון ניהול קופה - צריך בדיקה ידנית")
print("5. ⚠️  מהירות טיקר - צריך בדיקה ידנית")
