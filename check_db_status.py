import sqlite3
import json
import os
from datetime import datetime

db_path = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'SchoolPoints', 'school_points.db')
print(f"Checking DB: {db_path}")

try:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Check settings for license
    print("\n=== Settings (license/sync related) ===")
    cursor.execute("SELECT key, value FROM settings WHERE key IN ('_cloud_license', 'license_type', 'license_expiry', 'deployment_mode', 'sync_tenant_id', '_cloud_sync_enabled') ORDER BY key")
    for row in cursor.fetchall():
        value = row['value']
        if row['key'] == '_cloud_license':
            try:
                lic = json.loads(value)
                print(f"{row['key']}: type={lic.get('type')}, expiry={lic.get('expiry')}, institution_id={lic.get('institution_id')}")
            except:
                print(f"{row['key']}: {value}")
        else:
            print(f"{row['key']}: {value}")
    
    # Check sync state
    print("\n=== Sync State ===")
    cursor.execute("SELECT * FROM sync_state ORDER BY key")
    for row in cursor.fetchall():
        print(f"{row['key']}: {row['value']}")
    
    # Check change_log
    print("\n=== Recent Change Log (last 5) ===")
    cursor.execute("SELECT id, entity_type, action_type, created_at, synced_at FROM change_log ORDER BY id DESC LIMIT 5")
    for row in cursor.fetchall():
        print(f"ID:{row['id']} {row['entity_type']}/{row['action_type']} created:{row['created_at']} synced:{row['synced_at']}")
    
    # Count pending changes
    cursor.execute("SELECT COUNT(*) as pending FROM change_log WHERE synced_at IS NULL")
    pending = cursor.fetchone()['pending']
    print(f"\nPending changes to sync: {pending}")
    
    # Check students/teachers count
    cursor.execute("SELECT COUNT(*) as cnt FROM students")
    students = cursor.fetchone()['cnt']
    cursor.execute("SELECT COUNT(*) as cnt FROM teachers") 
    teachers = cursor.fetchone()['cnt']
    print(f"\nLocal data: {students} students, {teachers} teachers")
    
    conn.close()
    
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
