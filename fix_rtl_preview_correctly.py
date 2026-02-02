# -*- coding: utf-8 -*-
"""
תיקון נכון של RTL בדוחות - סיבוב גם של הנתונים
"""

with open('admin_station.py', 'r', encoding='utf-8') as f:
    content = f.read()

# מחיקת הקוד הישן שלא עבד
old_code = """            columns = list(df.columns)
            
            # Configure RTL style for preview table
            preview_style = ttk.Style()
            preview_style.configure("Preview.Treeview", 
                                   background="#ffffff",
                                   foreground="#000000",
                                   fieldbackground="#ffffff",
                                   font=('Arial', 10))
            preview_style.configure("Preview.Treeview.Heading",
                                   font=('Arial', 10, 'bold'),
                                   background="#4472C4",
                                   foreground="#ffffff",
                                   anchor='e')
            preview_style.layout("Preview.Treeview", [('Preview.Treeview.treearea', {'sticky': 'nswe'})])
            
            tree = ttk.Treeview(tree_frame, columns=columns, show='headings', height=25, style="Preview.Treeview")
            
            # Reverse column order for RTL display
            reversed_cols = list(reversed(columns))
            tree['columns'] = reversed_cols
            
            for col in reversed_cols:
                tree.heading(col, text=str(col), anchor='e')
                tree.column(col, width=120, anchor='e')"""

# קוד חדש שעובד - סיבוב גם של DataFrame
new_code = """            columns = list(df.columns)
            
            # Reverse DataFrame columns for RTL
            df_rtl = df[list(reversed(columns))]
            columns_rtl = list(df_rtl.columns)
            
            tree = ttk.Treeview(tree_frame, columns=columns_rtl, show='headings', height=25)
            
            for col in columns_rtl:
                tree.heading(col, text=str(col), anchor='e')
                tree.column(col, width=120, anchor='e')"""

content = content.replace(old_code, new_code)

# עדכון גם את הלולאה שמוסיפה שורות
old_insert = """            # Configure tags for alternating row colors
            tree.tag_configure('oddrow', background='#FFFFFF')
            tree.tag_configure('evenrow', background='#F0F0F0')
            
            for idx, row in df.iterrows():
                values = [str(val) if val is not None else '' for val in row]
                tag = 'evenrow' if idx % 2 == 0 else 'oddrow'
                tree.insert('', 'end', values=values, tags=(tag,))"""

new_insert = """            # Configure tags for alternating row colors
            tree.tag_configure('oddrow', background='#FFFFFF')
            tree.tag_configure('evenrow', background='#F0F0F0')
            
            for idx, row in df_rtl.iterrows():
                values = [str(val) if val is not None else '' for val in row]
                tag = 'evenrow' if idx % 2 == 0 else 'oddrow'
                tree.insert('', 'end', values=values, tags=(tag,))"""

content = content.replace(old_insert, new_insert)

with open('admin_station.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("תיקון 1: RTL בדוחות - הושלם!")
