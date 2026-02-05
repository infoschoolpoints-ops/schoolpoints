import sqlite3
import os
import sys
import shutil
import time

def find_db_path():
    # Try standard locations
    base_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(base_dir, 'school_points.db'),
        os.path.join(os.environ.get('APPDATA', ''), 'SchoolPoints', 'school_points.db'),
        os.path.join(os.environ.get('LOCALAPPDATA', ''), 'SchoolPoints', 'school_points.db'),
        os.path.join(os.environ.get('PROGRAMDATA', ''), 'SchoolPoints', 'school_points.db'),
    ]
    
    # Check config.json
    config_path = os.path.join(os.environ.get('PROGRAMDATA', ''), 'SchoolPoints', 'config.json')
    if os.path.exists(config_path):
        try:
            import json
            with open(config_path, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
                if cfg.get('db_path'):
                    candidates.insert(0, cfg.get('db_path'))
        except:
            pass

    for p in candidates:
        if p and os.path.exists(p):
            return p
    return None

def repair_database(db_path):
    print(f"Target DB: {db_path}")
    if not os.path.exists(db_path):
        print("File does not exist.")
        return

    # 1. Backup
    ts = int(time.time())
    bak_path = f"{db_path}.corrupt_{ts}.bak"
    try:
        shutil.copy2(db_path, bak_path)
        print(f"Backed up corrupt DB to: {bak_path}")
    except Exception as e:
        print(f"Failed to backup: {e}")
        return

    # 2. Dump content
    dump_path = f"{db_path}.dump_{ts}.sql"
    print("Attempting to dump data...")
    try:
        # We try to use the shell via subprocess if sqlite3 is in path, usually better for corruption
        import subprocess
        # Try finding sqlite3 executable
        sqlite_exe = "sqlite3"
        # Check if we can run it
        cmd = [sqlite_exe, db_path, ".dump"]
        with open(dump_path, "w", encoding="utf-8") as f:
            subprocess.check_call(cmd, stdout=f, shell=True)
        print("Dumped using sqlite3 command line.")
    except Exception as e:
        print(f"sqlite3 command line failed ({e}), trying Python iterdump (might fail on corruption)...")
        try:
            conn = sqlite3.connect(db_path)
            with open(dump_path, 'w', encoding='utf-8') as f:
                for line in conn.iterdump():
                    f.write('%s\n' % line)
            conn.close()
            print("Dumped using Python iterdump.")
        except Exception as e2:
            print(f"Python dump failed too: {e2}")
            print("Cannot recover data automatically.")
            return

    # 3. Create new DB from dump
    print("Creating new database from dump...")
    new_db_path = f"{db_path}.repaired"
    if os.path.exists(new_db_path):
        os.remove(new_db_path)
    
    try:
        # Filter out transaction statements that might cause issues if partial
        with open(dump_path, 'r', encoding='utf-8') as f:
            sql_content = f.read()
            
        # Remove "ROLLBACK" if present at the end due to error
        if "ROLLBACK;" in sql_content:
            print("Removing ROLLBACK from dump...")
            sql_content = sql_content.replace("ROLLBACK;", "")
            
        # Use sqlite3 command line if possible for restore
        try:
            import subprocess
            cmd = f'sqlite3 "{new_db_path}"'
            p = subprocess.Popen(cmd, stdin=subprocess.PIPE, shell=True)
            p.communicate(input=sql_content.encode('utf-8'))
            if p.returncode != 0:
                raise Exception("sqlite3 restore returned non-zero")
        except Exception:
            # Fallback to python
            conn_new = sqlite3.connect(new_db_path)
            conn_new.executescript(sql_content)
            conn_new.close()
            
        print(f"Repaired DB created at: {new_db_path}")
        
        # 4. Swap
        print("Replacing original file...")
        shutil.move(new_db_path, db_path)
        print("SUCCESS. Database repaired.")
        
    except Exception as e:
        print(f"Failed to restore from dump: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        path = sys.argv[1]
    else:
        path = find_db_path()
    
    if path:
        repair_database(path)
    else:
        print("Could not find school_points.db automatically. Please drag and drop the file onto this script.")
        input("Press Enter to exit...")
