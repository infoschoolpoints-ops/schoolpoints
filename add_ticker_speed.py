"""
סקריפט עזר להוספת הגדרת מהירות טיקר לקובץ admin_station.py
"""

# קריאת הקובץ
with open('admin_station.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# מציאת השורה הראשונה של update_background_rows (המופע הראשון בלבד)
insert_line = None
for i, line in enumerate(lines):
    if 'def update_background_rows(*args):' in line and i > 7900 and i < 8000:
        insert_line = i
        break

if insert_line is None:
    print("לא נמצא המיקום המתאים")
    exit(1)

# הטקסט להוספה
ticker_code = """
        # מהירות טיקר חדשות
        ticker_speed_map = {
            "איטי": "slow",
            "רגיל": "normal",
            "מהיר": "fast",
        }
        current_ticker_speed = config.get('news_ticker_speed', 'slow')
        reverse_ticker_speed_map = {v: k for k, v in ticker_speed_map.items()}
        ticker_speed_var = tk.StringVar(value=reverse_ticker_speed_map.get(current_ticker_speed, "איטי"))
        
        ticker_frame = tk.Frame(content_frame, bg='#ecf0f1')
        ticker_frame.pack(fill=tk.X, pady=(0, 5))
        
        tk.Label(
            ticker_frame,
            text=fix_rtl_text("מהירות טיקר חדשות:"),
            font=('Arial', 10),
            bg='#ecf0f1',
            anchor='e',
            width=LABEL_WIDTH
        ).pack(side=tk.RIGHT, padx=5)
        
        ticker_speed_choices = list(ticker_speed_map.keys())
        ticker_speed_menu = tk.OptionMenu(ticker_frame, ticker_speed_var, *ticker_speed_choices)
        ticker_speed_menu.config(font=('Arial', 10), width=20)
        ticker_speed_menu.pack(side=tk.RIGHT, padx=5)

"""

# הוספת הקוד לפני update_background_rows
lines.insert(insert_line, ticker_code)

# שמירת הקובץ
with open('admin_station.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)

print(f"הקוד נוסף בהצלחה בשורה {insert_line}")
