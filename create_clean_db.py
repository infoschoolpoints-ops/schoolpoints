"""
סקריפט ליצירת מסד נתונים ריק לבסיס התקנה
"""
import os
import sys

# הוסף את התיקייה הנוכחית ל-path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import Database

# יצירת DB ריק בתיקיית _clean_install
clean_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_clean_install')
db_path = os.path.join(clean_dir, 'school_points.db')

# מחק DB ישן אם קיים
if os.path.exists(db_path):
    os.remove(db_path)
    print("[OK] Deleted old DB")

# צור DB חדש ריק
db = Database(db_path=db_path)
print(f"[OK] Created clean DB: {db_path}")

# בדוק שאין נתונים
conn = db.get_connection()
cursor = conn.cursor()

# ספור תלמידים
cursor.execute("SELECT COUNT(*) FROM students")
student_count = cursor.fetchone()[0]
print(f"  - תלמידים: {student_count}")

# ספור מורים
cursor.execute("SELECT COUNT(*) FROM teachers")
teacher_count = cursor.fetchone()[0]
print(f"  - מורים: {teacher_count}")

# ספור הודעות
cursor.execute("SELECT COUNT(*) FROM messages")
message_count = cursor.fetchone()[0]
print(f"  - הודעות: {message_count}")

conn.close()

if student_count == 0 and teacher_count == 0 and message_count == 0:
    print("\n[SUCCESS] Database is empty and ready for installation!")
else:
    print("\n[WARNING] Database has data! Something is wrong...")
