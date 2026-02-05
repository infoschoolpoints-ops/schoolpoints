import sqlite3
import sys
import os

def check_dates(db_path):
    print(f"Checking dates in: {db_path}")
    if not os.path.exists(db_path):
        print("File not found.")
        return
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        tables = ['points_log', 'card_validations', 'anti_spam_events', 'change_log']
        for t in tables:
            try:
                cursor.execute(f"SELECT MAX(created_at) FROM {t}")
                res = cursor.fetchone()
                print(f"Max date in {t}: {res[0] if res else 'None'}")
            except Exception as e:
                print(f"Could not read {t}: {e}")
        
        conn.close()
    except Exception as e:
        print(f"Connection error: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        check_dates(sys.argv[1])
