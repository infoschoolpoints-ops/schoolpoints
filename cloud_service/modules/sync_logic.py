import json
import gzip
import secrets
import logging
from typing import Dict, Any, List, Optional

from .db import get_db_connection, sql_placeholder, table_columns, tenant_db_connection, integrity_errors
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
    local_id: Optional[int] = None,
) -> str:
    ev_id = make_event_id(station_id, local_id, created_at)
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
        insert_sql = '''
            INSERT INTO sync_events (tenant_id, event_id, station_id, change_local_id, entity_type, entity_id, action_type, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        '''
        if USE_POSTGRES:
            insert_sql = insert_sql.rstrip() + ' ON CONFLICT (tenant_id, event_id) DO NOTHING'
        else:
            insert_sql = insert_sql.replace('INSERT INTO', 'INSERT OR IGNORE INTO', 1)
        cur.execute(
            sql_placeholder(insert_sql),
            (
                str(tenant_id or '').strip(),
                str(ev_id),
                str(station_id or '').strip(),
                (int(local_id) if local_id is not None else None),
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
        return

    if et == 'setting' and at in ('create', 'update'):
        key = str(
            payload.get('key')
            or payload.get('name')
            or payload.get('setting')
            or entity_id_str
            or ''
        ).strip()
        if not key:
            return
        raw_val = payload.get('value')
        if raw_val is None:
            raw_val = payload.get('val')
        value = '' if raw_val is None else str(raw_val)
        cur = tconn.cursor()
        try:
            cur.execute(
                sql_placeholder(
                    'INSERT INTO settings (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) '
                    'ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP'
                ),
                (key, value)
            )
        except Exception:
            try:
                cur.execute(
                    sql_placeholder('UPDATE settings SET value = ?, updated_at = CURRENT_TIMESTAMP WHERE key = ?'),
                    (value, key)
                )
                if cur.rowcount == 0:
                    cur.execute(
                        sql_placeholder('INSERT INTO settings (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)'),
                        (key, value)
                    )
            except Exception:
                return
        tconn.commit()
        return

    if et == 'setting' and at == 'delete':
        key = str(entity_id_str or '').strip()
        if not key:
            return
        cur = tconn.cursor()
        try:
            cur.execute(sql_placeholder('DELETE FROM settings WHERE key = ?'), (key,))
            tconn.commit()
        except Exception:
            return

    if et == 'purchase' and at in ('insert', 'create'):
        try:
            pid = int(entity_id_str or 0)
        except Exception:
            pid = 0
        student_id = int(payload.get('student_id') or 0)
        product_id = int(payload.get('product_id') or 0)
        variant_id = int(payload.get('variant_id') or 0)
        qty = int(payload.get('qty') or 1)
        total_points = int(payload.get('total_points') or 0)
        deduct_points = int(payload.get('deduct_points') or 1)
        station_type = str(payload.get('station_type') or '').strip()
        cur = tconn.cursor()
        try:
            cols = ['student_id', 'product_id', 'variant_id', 'qty', 'points_each', 'total_points', 'deduct_points', 'station_type']
            vals = [student_id, product_id, (variant_id if variant_id > 0 else None), qty, 0, total_points, deduct_points, station_type]
            placeholders = ','.join(['?' for _ in cols])
            if USE_POSTGRES:
                placeholders = ','.join(['%s' for _ in cols])
            if pid > 0:
                cols.insert(0, 'id')
                vals.insert(0, pid)
                placeholders = ('?, ' + placeholders) if not USE_POSTGRES else ('%s, ' + placeholders)
            sql = f"INSERT INTO purchases_log ({','.join(cols)}) VALUES ({placeholders})"
            if USE_POSTGRES:
                sql += ' ON CONFLICT (id) DO NOTHING'
            else:
                sql = sql.replace('INSERT INTO', 'INSERT OR IGNORE INTO', 1)
            cur.execute(sql_placeholder(sql), vals)
            tconn.commit()
        except Exception:
            return
        return

    if et == 'card_validation' and at in ('insert', 'create'):
        student_id = int(payload.get('student_id') or 0)
        card_number = str(payload.get('card_number') or '').strip()
        if student_id <= 0 or not card_number:
            return
        cur = tconn.cursor()
        try:
            cur.execute(
                sql_placeholder('INSERT INTO card_validations (student_id, card_number) VALUES (?, ?)'),
                (student_id, card_number)
            )
            tconn.commit()
        except Exception:
            return
        return

    # --- Generic handler for all other entity types ---
    _GENERIC_TABLE_MAP = {
        'student': ('students', 'id'),
        'teacher': ('teachers', 'id'),
        'product': ('products', 'id'),
        'product_variant': ('product_variants', 'id'),
        'product_category': ('product_categories', 'id'),
        'static_message': ('static_messages', 'id'),
        'threshold_message': ('threshold_messages', 'id'),
        'news_item': ('news_items', 'id'),
        'ads_item': ('ads_items', 'id'),
        'student_message': ('student_messages', 'id'),
        'time_bonus': ('time_bonus_schedules', 'id'),
        'time_bonus_given': ('time_bonus_given', 'id'),
        'teacher_bonus': ('teacher_bonus', 'teacher_id'),
        'activity': ('activities', 'id'),
        'activity_schedule': ('activity_schedules', 'id'),
        'scheduled_service': ('scheduled_services', 'id'),
        'scheduled_service_date': ('scheduled_service_dates', 'id'),
        'public_closure': ('public_closures', 'id'),
        'teacher_class': ('teacher_classes', 'id'),
        'student_tier': ('student_tier_state', 'student_id'),
        'card_block': ('card_blocks', 'id'),
        'cashier_responsible': ('cashier_responsibles', 'student_id'),
        'activity_claim': ('activity_claims', 'id'),
        'service_reservation': ('scheduled_service_reservations', 'id'),
        'purchase': ('purchases_log', 'id'),
        'refund': ('refunds_log', 'id'),
    }

    if et in _GENERIC_TABLE_MAP:
        table, pk_col = _GENERIC_TABLE_MAP[et]
        try:
            eid = int(entity_id_str or 0)
        except (ValueError, TypeError):
            eid = entity_id_str

        if at == 'delete':
            try:
                cur = tconn.cursor()
                cur.execute(sql_placeholder(f"DELETE FROM {table} WHERE {pk_col} = ?"), (eid,))
                tconn.commit()
            except Exception:
                pass
            return

        if at in ('create', 'update'):
            if not payload:
                return
            _generic_upsert(tconn, table, pk_col, eid, payload)
            return


def _generic_upsert(conn, table: str, pk_col: str, pk_val, payload: Dict[str, Any]) -> None:
    """Generic upsert: insert or update a single row in a tenant DB table."""
    cols = table_columns(conn, table)
    if not cols:
        return
    allowed = set(cols)
    row = {k: v for k, v in payload.items() if k in allowed}
    row[pk_col] = pk_val

    insert_cols = [k for k in row.keys() if k in allowed]
    if not insert_cols:
        return
    if pk_col not in insert_cols:
        insert_cols.append(pk_col)

    placeholders = ','.join(['?' for _ in insert_cols])
    col_names = ','.join(insert_cols)
    update_cols = [c for c in insert_cols if c != pk_col]
    values = [row.get(c) for c in insert_cols]

    cur = conn.cursor()
    if update_cols:
        if USE_POSTGRES:
            pg_placeholders = ','.join(['%s' for _ in insert_cols])
            update_clause = ', '.join([f"{c} = EXCLUDED.{c}" for c in update_cols])
            sql = f'INSERT INTO {table} ({col_names}) VALUES ({pg_placeholders}) ON CONFLICT ({pk_col}) DO UPDATE SET {update_clause}'
            try:
                cur.execute(sql, values)
                conn.commit()
                return
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
        else:
            update_clause = ', '.join([f"{c} = excluded.{c}" for c in update_cols])
            sql = f'INSERT INTO {table} ({col_names}) VALUES ({placeholders}) ON CONFLICT({pk_col}) DO UPDATE SET {update_clause}'
            try:
                cur.execute(sql_placeholder(sql), values)
                conn.commit()
                return
            except Exception:
                pass

    # Fallback: delete + insert
    try:
        cur.execute(sql_placeholder(f"DELETE FROM {table} WHERE {pk_col} = ?"), (pk_val,))
        sql = f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})"
        cur.execute(sql_placeholder(sql), values)
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass


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
