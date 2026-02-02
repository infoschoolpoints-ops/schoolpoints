# -*- coding: utf-8 -*-
"""
הוספת הגדרת השמעת צלילים בחלון הגדרות מערכת
"""

with open('admin_station.py', 'r', encoding='utf-8') as f:
    content = f.read()

# מציאת המיקום להוספה - אחרי הגדרת show_student_photo
# נוסיף את ההגדרה לפני license_frame

insert_marker = """        license_frame = tk.Frame(content_frame, bg='#ecf0f1')
        license_frame.pack(fill=tk.X, pady=(5, 5))"""

new_code = """        # הגדרת השמעת צלילים בעמדה הציבורית
        sounds_enabled_value = config.get('sounds_enabled', '1')
        sounds_enabled_var = tk.BooleanVar(value=sounds_enabled_value == '1')
        
        sounds_frame = tk.Frame(content_frame, bg='#ecf0f1')
        sounds_frame.pack(fill=tk.X, pady=(0, 5))
        
        tk.Label(
            sounds_frame,
            text=fix_rtl_text("השמעת צלילים בעמדה הציבורית:"),
            font=('Arial', 10),
            bg='#ecf0f1',
            anchor='e',
            width=LABEL_WIDTH
        ).pack(side=tk.RIGHT, padx=5)
        
        from toggle_switch import ToggleSwitch
        ToggleSwitch(
            sounds_frame,
            variable=sounds_enabled_var
        ).pack(side=tk.RIGHT, padx=5)
        
        # הגדרת עוצמת שמע (0-100)
        volume_value = int(config.get('sound_volume', 80))
        volume_var = tk.IntVar(value=volume_value)
        
        volume_frame = tk.Frame(content_frame, bg='#ecf0f1')
        volume_frame.pack(fill=tk.X, pady=(0, 5))
        
        tk.Label(
            volume_frame,
            text=fix_rtl_text("עוצמת צלילים (0-100):"),
            font=('Arial', 10),
            bg='#ecf0f1',
            anchor='e',
            width=LABEL_WIDTH
        ).pack(side=tk.RIGHT, padx=5)
        
        volume_scale = tk.Scale(
            volume_frame,
            from_=0,
            to=100,
            orient=tk.HORIZONTAL,
            variable=volume_var,
            length=200,
            bg='#ecf0f1'
        )
        volume_scale.pack(side=tk.RIGHT, padx=5)

        license_frame = tk.Frame(content_frame, bg='#ecf0f1')
        license_frame.pack(fill=tk.X, pady=(5, 5))"""

content = content.replace(insert_marker, new_code)

# עכשיו נוסיף את השמירה של ההגדרות בפונקציית save_settings
# מחפשים את הפונקציה save_settings בתוך open_system_settings

save_marker = """            config['campaign_name'] = campaign_var.get().strip()
            
            # שמירת הגדרת מדפסת ברירת מחדל"""

save_addition = """            config['campaign_name'] = campaign_var.get().strip()
            
            # שמירת הגדרות צלילים
            config['sounds_enabled'] = '1' if sounds_enabled_var.get() else '0'
            config['sound_volume'] = str(volume_var.get())
            
            # שמירת הגדרת מדפסת ברירת מחדל"""

content = content.replace(save_marker, save_addition)

with open('admin_station.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("הוספת הגדרות צלילים בהגדרות מערכת הושלמה!")
