"""
תיקון פשוט של טבלאות דוח זמני - RTL ושורות לסירוגין
"""

with open('admin_station.py', 'r', encoding='utf-8') as f:
    content = f.read()

# החלפת הקוד הישן בקוד חדש עם RTL ושורות לסירוגין
old_code = """            for col in columns:
                tree.heading(col, text=str(col))
                tree.column(col, width=120, anchor='center')
            
            for idx, row in df.iterrows():
                values = [str(val) if val is not None else '' for val in row]
                tree.insert('', 'end', values=values)"""

new_code = """            for col in columns:
                tree.heading(col, text=str(col), anchor='e')
                tree.column(col, width=120, anchor='e')
            
            # Configure tags for alternating row colors
            tree.tag_configure('oddrow', background='#FFFFFF')
            tree.tag_configure('evenrow', background='#F0F0F0')
            
            for idx, row in df.iterrows():
                values = [str(val) if val is not None else '' for val in row]
                tag = 'evenrow' if idx % 2 == 0 else 'oddrow'
                tree.insert('', 'end', values=values, tags=(tag,))"""

content = content.replace(old_code, new_code)

with open('admin_station.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("תיקון 6 הושלם - טבלאות דוח זמני עם RTL ושורות לסירוגין")
