# -*- coding: utf-8 -*-
"""
תיקון ייצוא אתגרים - האתגרים נמצאים ב-scheduled_services ולא ב-activities
"""

with open('admin_station.py', 'r', encoding='utf-8') as f:
    content = f.read()

# החלפת הפונקציה export_activity_cards_excel לקרוא מ-scheduled_services
old_function = """    def export_activity_cards_excel(self):
        if not self.ensure_can_modify():
            return
        if not (self.current_teacher and int(self.current_teacher.get('is_admin', 0) or 0) == 1):
            messagebox.showwarning("אין הרשאה", "גישה רק למנהלים")
            return
        try:
            rows = self.db.get_all_activities() or []
        except Exception:
            rows = []
        if not rows:
            messagebox.showwarning('אין נתונים', 'אין אתגרים במערכת. נא להוסיף אתגרים דרך "ניהול אתגרים"')
            return"""

new_function = """    def export_activity_cards_excel(self):
        if not self.ensure_can_modify():
            return
        if not (self.current_teacher and int(self.current_teacher.get('is_admin', 0) or 0) == 1):
            messagebox.showwarning("אין הרשאה", "גישה רק למנהלים")
            return
        try:
            # אתגרים נמצאים ב-scheduled_services (לא ב-activities)
            rows = self.db.get_all_scheduled_services() or []
        except Exception as e:
            print(f"שגיאה בקריאת אתגרים: {e}")
            rows = []
        if not rows:
            messagebox.showwarning('אין נתונים', 'אין אתגרים במערכת. נא להוסיף אתגרים דרך "ניהול קניות"')
            return"""

content = content.replace(old_function, new_function)

# עדכון גם את הלולאה שיוצרת את הנתונים
old_loop = """            data = []
            for r in rows:
                if int(r.get('is_active', 1) or 0) != 1:
                    continue
                data.append({
                    'שם אתגר': str(r.get('name') or ''),
                    'נקודות': int(r.get('points', 0) or 0),
                    'קוד הדפסה': str(r.get('print_code') or ''),
                })"""

new_loop = """            data = []
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
                })"""

content = content.replace(old_loop, new_loop)

# עדכון גם את יצירת ה-DataFrame
content = content.replace(
    "df = pd.DataFrame(data, columns=['שם אתגר', 'נקודות', 'קוד הדפסה'])",
    "df = pd.DataFrame(data, columns=['שם אתגר', 'נקודות', 'משך (דקות)', 'קיבולת'])"
)

with open('admin_station.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("תיקון 2: ייצוא אתגרים - הושלם!")
