"""
סקריפט עזר להוספת שמירת מהירות טיקר בפונקציית save_settings
"""

# קריאת הקובץ
with open('admin_station.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# מציאת השורה של panel_style (המופע הראשון בלבד)
insert_line = None
for i, line in enumerate(lines):
    if "cfg['panel_style'] = panel_style_map.get(selected_panel_label, 'solid')" in line and i > 8100 and i < 8150:
        insert_line = i + 1
        break

if insert_line is None:
    print("לא נמצא המיקום המתאים")
    exit(1)

# הטקסט להוספה
save_code = """
            # מהירות טיקר חדשות
            selected_ticker_speed_label = ticker_speed_var.get()
            cfg['news_ticker_speed'] = ticker_speed_map.get(selected_ticker_speed_label, 'slow')
"""

# הוספת הקוד אחרי panel_style
lines.insert(insert_line, save_code)

# שמירת הקובץ
with open('admin_station.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)

print(f"קוד השמירה נוסף בהצלחה בשורה {insert_line}")
