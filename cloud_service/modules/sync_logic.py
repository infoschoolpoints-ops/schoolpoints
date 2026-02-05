import json
import gzip
import secrets
import logging
from typing import Dict, Any, List, Optional

from .db import get_db_connection, sql_placeholder, table_columns, tenant_db_connection
from .utils import time_to_minutes
from .config import USE_POSTGRES

logger = logging.getLogger("schoolpoints.sync")

def make_event_id(station_id: Optional[str], local_id: Optional[int], created_at: Optional[str]) -> str:
    sid = str(station_id or '').strip() or 'unknown'
    lid = 0
    try:
        lid = int(local_id or 0)
    except Exception:
        pass
    ca = str(created_at or '').strip()
    try:
        if ca.lower() in ('none', 'null'):
            ca = ''
    except Exception:
        pass
    if lid:
        return f"{sid}:{lid}"
    if ca:
        return f"{sid}:{ca}"
    return f"{sid}:{secrets.token_hex(8)}"

def record_sync_event(
    *,
    tenant_id: str,
    station_id: str,
    entity_type: str,
    entity_id: Optional[str],
    action_type: str,
    payload: Optional[Dict[str, Any]],
    created_at: Optional[str] = None,
) -> str:
    ev_id = make_event_id(station_id, None, created_at)
    payload_json = None
    try:
        payload_json = json.dumps(payload or {}, ensure_ascii=False)
    except Exception:
        payload_json = '{}'

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        # raw change log (admin visibility)
        try:
            cur.execute(
                sql_placeholder(
                    '''
                    INSERT INTO changes (tenant_id, station_id, entity_type, entity_id, action_type, payload_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    '''
                ),
                (
                    str(tenant_id or '').strip(),
                    str(station_id or '').strip(),
                    str(entity_type or '').strip(),
                    (str(entity_id).strip() if entity_id is not None else None),
                    str(action_type or '').strip(),
                    payload_json,
                    (str(created_at).strip() if created_at else None),
                )
            )
        except Exception:
            pass

        # sync stream
        cur.execute(
            sql_placeholder(
                '''
                INSERT INTO sync_events (tenant_id, event_id, station_id, change_local_id, entity_type, entity_id, action_type, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                '''
            ),
            (
                str(tenant_id or '').strip(),
                str(ev_id),
                str(station_id or '').strip(),
                None,
                str(entity_type or '').strip(),
                (str(entity_id).strip() if entity_id is not None else None),
                str(action_type or '').strip(),
                payload_json,
                (str(created_at).strip() if created_at else None),
            )
        )
        conn.commit()
        return str(ev_id)
    finally:
        try:
            conn.close()
        except Exception:
            pass

def apply_change_to_tenant_db(tconn, ch: Dict[str, Any]) -> None:
    et = str(ch.get('entity_type') or '').strip()
    at = str(ch.get('action_type') or '').strip()
    payload = {}
    try:
        pj = ch.get('payload_json')
        payload = json.loads(pj or '{}') if (pj is not None) else {}
    except Exception:
        payload = {}

    entity_id_str = ch.get('entity_id')
    
    if et == 'student_points' and at == 'update':
        try:
            student_id = int(entity_id_str or 0)
        except:
            return
            
        if student_id <= 0:
            return
            
        old_points = int(payload.get('old_points') or 0)
        new_points = int(payload.get('new_points') or 0)
        delta = int(new_points - old_points)
        reason = str(payload.get('reason') or '').strip()

        cur = tconn.cursor()
        cur.execute(sql_placeholder('SELECT points FROM students WHERE id = ? LIMIT 1'), (student_id,))
        row = cur.fetchone()
        if not row:
            return
        
        cur_points = 0
        if isinstance(row, dict):
            cur_points = int(row.get('points') or 0)
        else:
            # tuple/row fallback
            try:
                cur_points = int(row[0] or 0)
            except:
                pass
                
        final_points = int(cur_points + delta)
        cur.execute(
            sql_placeholder('UPDATE students SET points = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?'),
            (final_points, student_id)
        )
        try:
            cur.execute(
                sql_placeholder(
                    'INSERT INTO points_log (student_id, points, reason, teacher_name) VALUES (?, ?, ?, ?)'
                ),
                (student_id, final_points, reason, 'Sync')
            )
        except Exception:
            pass
        tconn.commit()

def save_snapshot2_blob(tenant_id: str, blob: bytes) -> None:
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        # Create table if not exists
        if USE_POSTGRES:
            cur.execute('''
                CREATE TABLE IF NOT EXISTS snapshots2 (
                    tenant_id TEXT PRIMARY KEY,
                    blob BYTEA,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
        else:
            cur.execute('''
                CREATE TABLE IF NOT EXISTS snapshots2 (
                    tenant_id TEXT PRIMARY KEY,
                    blob BLOB,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')
        
        cur.execute(
            sql_placeholder(
                'INSERT INTO snapshots2 (tenant_id, blob, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) '
                'ON CONFLICT(tenant_id) DO UPDATE SET blob = excluded.blob, updated_at = CURRENT_TIMESTAMP'
            ),
            (tenant_id, blob)
        )
        conn.commit()
    finally:
        try: conn.close()
        except: pass

def load_snapshot2_blob(tenant_id: str) -> Optional[bytes]:
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        try:
            cur.execute(sql_placeholder('SELECT blob FROM snapshots2 WHERE tenant_id = ? LIMIT 1'), (tenant_id,))
            row = cur.fetchone()
            if row:
                if isinstance(row, dict):
                    return row['blob']
                return row[0]
        except Exception:
            pass
        return None
    finally:
        try: conn.close()
        except: pass

def list_user_tables(tconn) -> List[str]:
    # Exclude sqlite specific or system tables
    excludes = {
        'sqlite_sequence', 'sqlite_stat1', 'sqlite_master', 
        'android_metadata', 'schema_migrations', 'sync_events', 'changes'
    }
    
    if USE_POSTGRES:
        try:
            cur = tconn.cursor()
            cur.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = current_schema() 
                AND table_type = 'BASE TABLE'
            """)
            rows = cur.fetchall()
            tables = []
            for r in rows:
                tn = r['table_name'] if isinstance(r, dict) else r[0]
                if tn not in excludes:
                    tables.append(tn)
            return tables
        except:
            return []
            
    # SQLite
    try:
        cur = tconn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        rows = cur.fetchall()
        tables = []
        for r in rows:
            name = r['name'] if isinstance(r, dict) else r[0]
            if name not in excludes:
                tables.append(name)
        return tables
    except:
        return []

def fetch_table_rows_any(conn, table: str) -> List[Dict[str, Any]]:
    cols = table_columns(conn, table)
    if not cols:
        return []
    try:
        cur = conn.cursor()
        # For Postgres we prefer RealDictCursor which is default in our get_db_connection for PG
        # For SQLite we used Row factory.
        # So fetching all should result in accessible dict-like objects.
        col_str = ','.join(f'"{c}"' if USE_POSTGRES else c for c in cols) # quote cols for safety
        if not USE_POSTGRES:
             col_str = ','.join(cols) 
             
        cur.execute(f'SELECT {col_str} FROM {table}')
        rows = cur.fetchall() or []
        
        # Convert to pure dicts
        out = []
        for r in rows:
            if isinstance(r, dict):
                out.append(dict(r))
            elif hasattr(r, 'keys'): # sqlite3.Row
                out.append(dict(r))
            else:
                # tuple fallback if something weird
                out.append({cols[i]: r[i] for i in range(len(cols))})
        return out
    except Exception as e:
        logger.error(f"Error fetching rows for {table}: {e}")
        return []

def apply_full_snapshot_sqlite(tconn, snap: Dict[str, Any]) -> Dict[str, int]:
    applied: Dict[str, int] = {}
    if not isinstance(snap, dict):
        return applied
        
    core_tables = ['students', 'teachers', 'classes', 'messages', 'time_bonus_schedules', 'special_bonus_schedules']
    other_tables = [t for t in snap.keys() if t not in core_tables]
    
    # Process core first (though for full snapshot we usually wipe anyway)
    # Since we want to replace data, we should ideally truncate/delete all first.
    # But to be safe on order, let's just process.
    
    # Actually, proper full snapshot application usually means:
    # 1. Disable FK constraints (if any)
    # 2. Truncate tables
    # 3. Insert new data
    
    tables_to_process = core_tables + other_tables
    
    # We will just iterate what is in the snapshot
    for table in tables_to_process:
        if table not in snap:
            continue
        rows = snap[table]
        if not isinstance(rows, list):
            continue
            
        # Get columns for this table from the first row or DB? 
        # Better to check DB columns.
        db_cols = set(table_columns(tconn, table))
        if not db_cols:
            continue # Table doesn't exist in destination or empty
            
        # Prepare data
        valid_rows = []
        for r in rows:
            if not isinstance(r, dict): continue
            # filter keys that exist in DB
            valid_r = {k: v for k, v in r.items() if k in db_cols}
            valid_rows.append(valid_r)
            
        if not valid_rows:
            continue
            
        # Replace
        try:
            _replace_rows(tconn, table, valid_rows)
            applied[table] = len(valid_rows)
        except Exception as e:
            logger.error(f"Failed to replace rows for {table}: {e}")
            
    return applied

def _replace_rows(conn, table: str, rows: List[Dict[str, Any]]) -> int:
    if not rows:
        return 0
    
    # Truncate/Delete
    cur = conn.cursor()
    cur.execute(f"DELETE FROM {table}")
    
    # Insert
    keys = list(rows[0].keys())
    if not keys: 
        return 0
        
    placeholders = ','.join(['?' for _ in keys])
    if USE_POSTGRES:
        placeholders = ','.join(['%s' for _ in keys])
        
    cols_str = ','.join(keys)
    sql = f"INSERT INTO {table} ({cols_str}) VALUES ({placeholders})"
    
    params = []
    for r in rows:
        params.append([r.get(k) for k in keys])
        
    if USE_POSTGRES:
        import psycopg2.extras
        psycopg2.extras.execute_batch(cur, sql, params)
    else:
        cur.executemany(sql, params)
        
    conn.commit()
    return len(rows)
