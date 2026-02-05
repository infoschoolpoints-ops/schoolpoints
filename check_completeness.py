import sqlite3
import sys
import os

def check_completeness(db_path):
    print(f"Checking completeness: {db_path}")
    if not os.path.exists(db_path):
        print("File not found.")
        return
    
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get all tables
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r['name'] for r in cursor.fetchall()]
        
        print(f"\nFound {len(tables)} tables.")
        
        # Check sqlite_sequence for expected max IDs
        seq_map = {}
        if 'sqlite_sequence' in tables:
            print("\n--- Expected Max IDs (from sqlite_sequence) ---")
            cursor.execute("SELECT name, seq FROM sqlite_sequence")
            for row in cursor.fetchall():
                seq_map[row['name']] = row['seq']
                print(f"{row['name']}: {row['seq']}")
        
        print("\n--- Actual Row Counts & Max IDs ---")
        print(f"{'Table':<30} | {'Count':<10} | {'Max ID':<10} | {'Missing (Approx)'}")
        print("-" * 70)
        
        for table in tables:
            if table == 'sqlite_sequence': continue
            
            try:
                # Get count
                cursor.execute(f"SELECT count(*) FROM {table}")
                count = cursor.fetchone()[0]
                
                # Get max id if 'id' column exists
                max_id = "N/A"
                missing = ""
                
                # Check if table has 'id' column
                cursor.execute(f"PRAGMA table_info({table})")
                cols = [c['name'] for c in cursor.fetchall()]
                
                if 'id' in cols:
                    cursor.execute(f"SELECT MAX(id) FROM {table}")
                    res = cursor.fetchone()
                    max_id = res[0] if res and res[0] is not None else 0
                    
                    if table in seq_map:
                        expected = seq_map[table]
                        if isinstance(max_id, int) and expected > max_id:
                             missing = f"{expected - max_id} rows?"
                
                print(f"{table:<30} | {count:<10} | {max_id:<10} | {missing}")
                
            except Exception as e:
                print(f"{table:<30} | Error: {e}")

        conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        check_completeness(sys.argv[1])
