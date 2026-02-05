import sqlite3
import sys
import os

def analyze(db_path):
    print(f"Analyzing: {db_path}")
    if not os.path.exists(db_path):
        print("File not found.")
        return
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get tables
        try:
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [r[0] for r in cursor.fetchall()]
            print(f"Found {len(tables)} tables: {', '.join(tables)}")
        except Exception as e:
            print(f"Error reading schema: {e}")
            return

        for table in tables:
            print(f"Checking {table}...", end=' ')
            try:
                cursor.execute(f"SELECT count(*) FROM {table}")
                count = cursor.fetchone()[0]
                print(f"OK ({count} rows)")
            except Exception as e:
                print(f"FAILED ({e})")
                
        conn.close()
    except Exception as e:
        print(f"Connection error: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        analyze(sys.argv[1])
