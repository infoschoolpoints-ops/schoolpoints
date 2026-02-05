import sqlite3
import sys
import os

def check_integrity(db_path):
    print(f"Checking: {db_path}")
    if not os.path.exists(db_path):
        print("File not found.")
        return
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA integrity_check")
        result = cursor.fetchall()
        print(f"Integrity check result: {result}")
        
        cursor.execute("SELECT count(*) FROM students")
        count = cursor.fetchone()[0]
        print(f"Student count: {count}")
        conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        check_integrity(sys.argv[1])
