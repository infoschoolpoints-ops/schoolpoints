"""
תיקון טבלאות דוח זמני - RTL ושורות לסירוגין
"""

with open('admin_station.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# מציאת הפונקציה _show_preview_window
for i, line in enumerate(lines):
    if 'def _show_preview_window(self, df, title: str):' in line:
        # מציאת השורה של יצירת ה-Treeview
        for j in range(i, min(i + 50, len(lines))):
            if 'tree = ttk.Treeview(tree_frame, columns=columns' in lines[j]:
                # הוספת קוד RTL ושורות לסירוגין אחרי יצירת העץ
                insert_pos = j + 1
                
                # מציאת הלולאה שמוסיפה כותרות
                for k in range(j, min(j + 20, len(lines))):
                    if 'for col in columns:' in lines[k]:
                        # מציאת סוף הלולאה
                        for m in range(k, min(k + 15, len(lines))):
                            if 'tree.pack(side=tk.LEFT' in lines[m]:
                                # הוספת קוד RTL לפני ה-pack
                                rtl_code = """            
            # RTL configuration and alternating row colors
            try:
                # Configure tags for alternating row colors
                tree.tag_configure('oddrow', background='#FFFFFF')
                tree.tag_configure('evenrow', background='#F0F0F0')
                
                # Insert data with alternating colors
                for idx, row in df.iterrows():
                    values = [str(row[col]) if pd.notna(row[col]) else '' for col in columns]
                    tag = 'evenrow' if idx % 2 == 0 else 'oddrow'
                    tree.insert('', tk.END, values=values, tags=(tag,))
            except Exception:
                # Fallback without colors
                for idx, row in df.iterrows():
                    values = [str(row[col]) if pd.notna(row[col]) else '' for col in columns]
                    tree.insert('', tk.END, values=values)
            
"""
                                # מחיקת הקוד הישן שמוסיף שורות
                                # מחפשים את הלולאה הישנה
                                old_insert_start = None
                                old_insert_end = None
                                for n in range(k + 5, min(m, len(lines))):
                                    if 'for idx, row in df.iterrows():' in lines[n]:
                                        old_insert_start = n
                                        for p in range(n, min(n + 5, len(lines))):
                                            if 'tree.insert' in lines[p]:
                                                old_insert_end = p + 1
                                                break
                                        break
                                
                                if old_insert_start and old_insert_end:
                                    # מחיקת הקוד הישן
                                    for idx in range(old_insert_end - 1, old_insert_start - 1, -1):
                                        del lines[idx]
                                
                                # הוספת הקוד החדש
                                lines.insert(m, rtl_code)
                                break
                        break
                break
        break

# שמירת הקובץ
with open('admin_station.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)

print("תיקון טבלאות דוח זמני הושלם")
