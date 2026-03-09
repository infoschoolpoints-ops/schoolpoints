import json
import os
import threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from typing import Any, Dict, List, Optional
import sqlite3
import socket
import uuid
import time

from database import Database
import sync_agent


_DEFAULT_PORT = 8765


class _WriteSerializer:
    """כתיבות ל-DB דרך connection אחד + lock.
    מונע 50 threads שנלחמים על SQLite locks.
    """
    def __init__(self, db_path: str):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._conn = None

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self._db_path, timeout=10, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            try:
                self._conn.execute('PRAGMA journal_mode=WAL')
                self._conn.execute('PRAGMA busy_timeout=5000')
                self._conn.execute('PRAGMA synchronous=NORMAL')
                self._conn.execute('PRAGMA cache_size=-8000')
                self._conn.execute('PRAGMA temp_store=MEMORY')
                self._conn.execute('PRAGMA mmap_size=67108864')
            except Exception:
                pass
            sync_agent._ensure_change_log(self._conn)
        return self._conn

    def execute_many(self, statements: list) -> list:
        """Execute SQL statements under a single lock + connection.
        Uses savepoints so a failed non-critical statement (e.g. INSERT INTO change_log)
        doesn't roll back the actual data changes (e.g. UPDATE students).
        """
        with self._lock:
            conn = self._get_conn()
            cur = conn.cursor()
            results = []
            failed_count = 0
            try:
                for i, stmt in enumerate(statements):
                    if not isinstance(stmt, dict):
                        continue
                    sql = str(stmt.get('sql') or '').strip()
                    params = stmt.get('params') or []
                    if not sql:
                        continue
                    sql_upper = sql.upper().strip()
                    if any(kw in sql_upper for kw in ('DROP ', 'ALTER ', 'ATTACH ', 'DETACH ', 'PRAGMA ', 'VACUUM')):
                        continue
                    try:
                        cur.execute(f'SAVEPOINT sp_{i}')
                        cur.execute(sql, params)
                        cur.execute(f'RELEASE sp_{i}')
                        results.append({'lastrowid': cur.lastrowid, 'rowcount': cur.rowcount})
                    except Exception as stmt_err:
                        failed_count += 1
                        try:
                            cur.execute(f'ROLLBACK TO sp_{i}')
                            cur.execute(f'RELEASE sp_{i}')
                        except Exception:
                            pass
                        try:
                            print(f"[LOCAL-SYNC] execute_many stmt[{i}] FAILED: {stmt_err}")
                            print(f"[LOCAL-SYNC]   sql={sql[:120]}")
                        except Exception:
                            pass
                        results.append({'error': str(stmt_err)})
                conn.commit()
                if failed_count > 0:
                    try:
                        print(f"[LOCAL-SYNC] execute_many: {len(results)-failed_count} OK, {failed_count} failed")
                    except Exception:
                        pass
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
                # חיבור יכול להיות פגום – ננסה מחדש
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None
                raise
            return results

    def read_conn(self) -> sqlite3.Connection:
        """חיבור נפרד לקריאה בלבד (WAL מאפשר קריאות מקבילות)."""
        conn = sqlite3.connect(self._db_path, timeout=10, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('PRAGMA busy_timeout=5000')
            conn.execute('PRAGMA cache_size=-8000')
            conn.execute('PRAGMA temp_store=MEMORY')
            conn.execute('PRAGMA mmap_size=67108864')
        except Exception:
            pass
        try:
            sync_agent._ensure_change_log(conn)
        except Exception as e:
            try:
                print(f"[LOCAL-SYNC] _ensure_change_log error: {e}")
            except Exception:
                pass
        # Validate connection can actually read
        try:
            conn.execute('SELECT 1 FROM change_log LIMIT 0')
        except Exception as ve:
            try:
                print(f"[LOCAL-SYNC] read_conn validation failed: {ve}")
            except Exception:
                pass
            raise
        return conn

    def write_with_conn(self, fn):
        """Execute a function that needs write access under the lock."""
        with self._lock:
            conn = self._get_conn()
            try:
                return fn(conn)
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None
                raise


def _read_body(handler: BaseHTTPRequestHandler) -> bytes:
    try:
        length = int(handler.headers.get('Content-Length') or '0')
    except Exception:
        length = 0
    if length <= 0:
        return b''
    return handler.rfile.read(length)


def _get_api_key(handler: BaseHTTPRequestHandler) -> str:
    try:
        return str(handler.headers.get('api-key') or handler.headers.get('x-api-key') or '').strip()
    except Exception:
        return ''


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: Dict[str, Any]) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json; charset=utf-8')
    handler.send_header('Content-Length', str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def _ensure_event_id(conn: sqlite3.Connection, row_id: int, event_id: Optional[str]) -> str:
    if event_id:
        return event_id
    new_eid = uuid.uuid4().hex
    try:
        cur = conn.cursor()
        cur.execute('UPDATE change_log SET event_id = ? WHERE id = ?', (new_eid, int(row_id)))
        conn.commit()
    except Exception:
        pass
    return new_eid


def _ensure_station_id(conn: sqlite3.Connection, row_id: int, station_id: Optional[str]) -> str:
    if station_id:
        return station_id
    sid = str(socket.gethostname() or '').strip() or 'master'
    try:
        cur = conn.cursor()
        cur.execute('UPDATE change_log SET station_id = ? WHERE id = ?', (sid, int(row_id)))
        conn.commit()
    except Exception:
        pass
    return sid


def _fetch_changes(conn: sqlite3.Connection, since_id: int, limit: int) -> List[Dict[str, Any]]:
    """משיכת שינויים עם טיפול בנעילה"""
    # Safety: ensure _sync_paused is not stuck (would block ALL triggers)
    try:
        _pc = conn.execute('SELECT flag FROM _sync_paused WHERE rowid = 1').fetchone()
        if _pc and int(_pc[0] or 0) != 0:
            conn.execute('UPDATE _sync_paused SET flag = 0 WHERE rowid = 1')
            conn.commit()
            try:
                print("[LOCAL-SYNC] WARNING: _sync_paused was stuck at 1 — reset to 0")
            except Exception:
                pass
    except Exception:
        pass
    cur = conn.cursor()
    max_retries = 3
    for attempt in range(max_retries):
        try:
            cur.execute(
                """
                SELECT id, event_id, station_id, entity_type, entity_id, action_type, payload_json, created_at
                  FROM change_log
                 WHERE id > ?
                 ORDER BY id ASC
                 LIMIT ?
                """,
                (int(since_id), int(limit))
            )
            rows = cur.fetchall() or []
            items: List[Dict[str, Any]] = []
            for r in rows:
                item = {
                    'id': r[0],
                    'event_id': r[1],
                    'station_id': r[2],
                    'entity_type': r[3],
                    'entity_id': r[4],
                    'action_type': r[5],
                    'payload_json': r[6],
                    'created_at': r[7]
                }
                # מילוי payload ריק מהטבלה (trigger-generated entries)
                pj = str(item.get('payload_json') or '').strip()
                if pj in ('', '{}') and str(item.get('action_type') or '') != 'delete':
                    try:
                        filled = _fill_payload_from_table(conn, item)
                        if filled and filled != '{}':
                            item['payload_json'] = filled
                    except Exception:
                        pass
                items.append(item)
            return items
        except sqlite3.OperationalError as e:
            if 'database is locked' in str(e).lower() and attempt < max_retries - 1:
                # המתנה קצרה וניסיון חוזר
                time.sleep(0.1 * (attempt + 1))
                continue
            else:
                # אם זו לא שגיאת נעילה או נגמרו הניסיונות, זרוק את השגיאה
                raise
    return []


# מיפוי entity_type -> (table_name, id_column)
_ENTITY_TABLE_MAP = {
    'student': ('students', 'id'),
    'teacher': ('teachers', 'id'),
    'product': ('products', 'id'),
    'product_variant': ('product_variants', 'id'),
    'product_category': ('product_categories', 'id'),
    'setting': ('settings', 'key'),
    'static_message': ('static_messages', 'id'),
    'threshold_message': ('threshold_messages', 'id'),
    'news_item': ('news_items', 'id'),
    'ads_item': ('ads_items', 'id'),
    'student_message': ('student_messages', 'id'),
    'time_bonus': ('time_bonus_schedules', 'id'),
    'teacher_bonus': ('teacher_bonus', 'teacher_id'),
    'activity': ('activities', 'id'),
    'activity_schedule': ('activity_schedules', 'id'),
    'scheduled_service': ('scheduled_services', 'id'),
    'scheduled_service_date': ('scheduled_service_dates', 'id'),
    'public_closure': ('public_closures', 'id'),
    'teacher_class': ('teacher_classes', 'id'),
    'student_tier': ('student_tier_state', 'student_id'),
    'time_bonus_given': ('time_bonus_given', 'id'),
    'card_block': ('card_blocks', 'id'),
    'cashier_responsible': ('cashier_responsibles', 'student_id'),
    'activity_claim': ('activity_claims', 'id'),
    'service_reservation': ('scheduled_service_reservations', 'id'),
    'purchase': ('purchases_log', 'id'),
    'refund': ('refunds_log', 'id'),
}


def _fill_payload_from_table(conn: sqlite3.Connection, item: Dict[str, Any]) -> str:
    """מילוי payload מהטבלה עצמה כשה-trigger רשם payload ריק."""
    entity_type = str(item.get('entity_type') or '').strip()
    entity_id = str(item.get('entity_id') or '').strip()
    action_type = str(item.get('action_type') or '').strip()

    if action_type == 'delete':
        return json.dumps({}, ensure_ascii=False)

    mapping = _ENTITY_TABLE_MAP.get(entity_type)
    if not mapping:
        return ''
    table, id_col = mapping

    try:
        cur = conn.cursor()
        if id_col == 'key':
            cur.execute(f"SELECT * FROM {table} WHERE {id_col} = ? LIMIT 1", (entity_id,))
        else:
            cur.execute(f"SELECT * FROM {table} WHERE {id_col} = ? LIMIT 1", (int(entity_id),))
        row = cur.fetchone()
        if row:
            d = dict(row)
            # המר datetime objects ל-string
            for k, v in d.items():
                if v is not None and not isinstance(v, (int, float, str, bool)):
                    d[k] = str(v)
            return json.dumps(d, ensure_ascii=False)
        else:
            # Entity was deleted after trigger fired
            return ''
    except Exception as e:
        try:
            print(f"[LOCAL-SYNC] _fill_payload error: {entity_type}/{entity_id}: {e}")
        except Exception:
            pass
    return ''


def _insert_change(conn: sqlite3.Connection, change: Dict[str, Any]) -> None:
    try:
        entity_type = str(change.get('entity_type') or '').strip()
        entity_id = str(change.get('entity_id') or '').strip()
        action_type = str(change.get('action_type') or '').strip()
        payload_json = change.get('payload_json')
        if payload_json is None and isinstance(change.get('payload'), dict):
            try:
                payload_json = json.dumps(change.get('payload') or {}, ensure_ascii=False)
            except Exception:
                payload_json = '{}'
        payload_json = str(payload_json or '')
        event_id = str(change.get('event_id') or '').strip() or uuid.uuid4().hex
        station_id = str(change.get('station_id') or '').strip() or str(socket.gethostname() or '').strip() or 'client'
        created_at = str(change.get('created_at') or '').strip()

        cur = conn.cursor()
        try:
            cur.execute('SELECT 1 FROM change_log WHERE event_id = ? LIMIT 1', (event_id,))
            if cur.fetchone():
                return
        except Exception:
            pass

        if created_at:
            cur.execute(
                '''
                INSERT INTO change_log (entity_type, entity_id, action_type, payload_json, event_id, station_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ''',
                (entity_type, entity_id, action_type, payload_json, event_id, station_id, created_at)
            )
        else:
            cur.execute(
                '''
                INSERT INTO change_log (entity_type, entity_id, action_type, payload_json, event_id, station_id)
                VALUES (?, ?, ?, ?, ?, ?)
                ''',
                (entity_type, entity_id, action_type, payload_json, event_id, station_id)
            )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass


def _apply_changes(conn: sqlite3.Connection, changes: List[Dict[str, Any]]) -> int:
    if not changes:
        return 0
    return sync_agent.apply_pull_events(conn, changes)


def _build_snapshot_payload(conn: sqlite3.Connection) -> Dict[str, Any]:
    snap = sync_agent.build_snapshot(conn)
    last_id = 0
    try:
        cur = conn.cursor()
        cur.execute('SELECT MAX(id) FROM change_log')
        r = cur.fetchone()
        if r:
            try:
                last_id = int((r.get('MAX(id)') if isinstance(r, dict) else r[0]) or 0)
            except Exception:
                try:
                    last_id = int(r[0] or 0)
                except Exception:
                    last_id = 0
    except Exception:
        last_id = 0
    return {
        'ok': True,
        'snapshot': snap.get('snapshot') if isinstance(snap, dict) else {},
        'last_event_id': int(last_id or 0)
    }


def _calc_recommended_interval(num_stations: int) -> int:
    """חישוב interval מומלץ לפי מספר עמדות מחוברות.
    1-2 עמדות: 10 שניות (מהיר)
    3-4 עמדות: 15 שניות
    5-7 עמדות: 20 שניות
    8-10 עמדות: 30 שניות
    11-29 עמדות: 45 שניות
    30-49 עמדות: 60 שניות
    50+ עמדות: 90 שניות
    """
    if num_stations <= 2:
        return 10
    elif num_stations <= 4:
        return 15
    elif num_stations <= 7:
        return 20
    elif num_stations <= 10:
        return 30
    elif num_stations <= 29:
        return 45
    elif num_stations <= 49:
        return 60
    else:
        return 90


def make_handler(db_path: str, api_key: str, tenant_id: str):
    _serializer = _WriteSerializer(db_path)
    # מעקב אחרי עמדות מחוברות (IP -> last_seen timestamp)
    _connected_stations: Dict[str, float] = {}
    _STATION_TIMEOUT = 120  # עמדה נחשבת מנותקת אחרי 120 שניות ללא פעילות

    class LocalSyncHandler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            return

        def _track_station(self) -> None:
            """רישום עמדה מחוברת לפי IP"""
            try:
                ip = str(self.client_address[0] or '') if self.client_address else ''
                if ip:
                    _connected_stations[ip] = time.time()
                    # ניקוי עמדות ישנות
                    cutoff = time.time() - _STATION_TIMEOUT
                    stale = [k for k, v in _connected_stations.items() if v < cutoff]
                    for k in stale:
                        del _connected_stations[k]
            except Exception:
                pass

        def _active_station_count(self) -> int:
            """מספר עמדות פעילות (כולל ראשית)"""
            try:
                cutoff = time.time() - _STATION_TIMEOUT
                active = sum(1 for v in _connected_stations.values() if v >= cutoff)
                return active + 1  # +1 לעמדה הראשית עצמה
            except Exception:
                return 1

        def _open_conn(self) -> sqlite3.Connection:
            return _serializer.read_conn()

        def _auth_ok(self) -> bool:
            return _get_api_key(self) == str(api_key or '')

        def do_GET(self) -> None:
            self._track_station()
            parsed = urlparse(self.path)
            if parsed.path == '/sync/status':
                n = self._active_station_count()
                return _json_response(self, 200, {'ok': True, 'stations': n, 'recommended_interval': _calc_recommended_interval(n)})
            if parsed.path == '/sync/pull':
                if not self._auth_ok():
                    return _json_response(self, 401, {'ok': False, 'error': 'invalid api_key'})
                qs = parse_qs(parsed.query or '')
                try:
                    since_id = int((qs.get('since_id') or ['0'])[0])
                except Exception:
                    since_id = 0
                try:
                    limit = int((qs.get('limit') or ['500'])[0])
                except Exception:
                    limit = 500
                limit = max(1, min(2000, limit))
                conn = None
                try:
                    conn = self._open_conn()
                    items = _fetch_changes(conn, since_id, limit)
                    max_id = 0
                    for it in items:
                        try:
                            max_id = max(max_id, int(it.get('id') or 0))
                        except Exception:
                            pass
                    # אם אין פריטים, החזר את ה-max האמיתי של change_log
                    # כדי שהלקוח יזהה אם ה-since_id שלו גבוה מדי
                    if not items:
                        try:
                            cur = conn.cursor()
                            cur.execute('SELECT MAX(id) FROM change_log')
                            r = cur.fetchone()
                            if r and r[0] is not None:
                                max_id = int(r[0])
                        except Exception:
                            pass
                    # אם עדיין 0 ויש since_id, שמור על since_id רק אם הוא סביר
                    if max_id == 0 and items:
                        max_id = since_id
                    n = self._active_station_count()
                    try:
                        if items or max_id != since_id:
                            print(f"[LOCAL-SYNC] pull since_id={since_id} -> items={len(items)} max_id={max_id} next_since_id={max_id}")
                    except Exception:
                        pass
                    return _json_response(self, 200, {'ok': True, 'items': items, 'max_id': max_id, 'next_since_id': max_id, 'stations': n, 'recommended_interval': _calc_recommended_interval(n)})
                except sqlite3.OperationalError as e:
                    if 'database is locked' in str(e).lower():
                        # DB נעול - החזר שגיאה ספציפית
                        return _json_response(self, 503, {'ok': False, 'error': 'database_locked', 'retry_after': 1})
                    else:
                        # שגיאת DB אחרת
                        print(f"[SYNC] DB error in _fetch_changes: {e}")
                        return _json_response(self, 500, {'ok': False, 'error': 'database_error'})
                except Exception as e:
                    import traceback
                    print(f"[SYNC] Unexpected error in pull: {e}")
                    traceback.print_exc()
                    return _json_response(self, 500, {'ok': False, 'error': str(e)})
                finally:
                    if conn:
                        try:
                            conn.close()
                        except Exception:
                            pass

            if parsed.path == '/sync/snapshot':
                if not self._auth_ok():
                    return _json_response(self, 401, {'ok': False, 'error': 'invalid api_key'})
                conn = self._open_conn()
                try:
                    payload = _build_snapshot_payload(conn)
                finally:
                    conn.close()
                return _json_response(self, 200, payload)

            if parsed.path == '/health':
                # endpoint ניטור — לא דורש auth, קריאה בלבד
                health = {'ok': True}
                try:
                    n = self._active_station_count()
                    health['active_stations'] = n
                    health['recommended_interval'] = _calc_recommended_interval(n)
                except Exception:
                    pass
                conn = None
                try:
                    conn = self._open_conn()
                    cur = conn.cursor()
                    # גודל change_log (כמה רשומות ממתינות)
                    try:
                        cur.execute('SELECT COUNT(*) FROM change_log WHERE synced_at IS NULL')
                        r = cur.fetchone()
                        health['pending_changes'] = int(r[0] or 0) if r else 0
                    except Exception:
                        pass
                    try:
                        cur.execute('SELECT COUNT(*) FROM change_log')
                        r = cur.fetchone()
                        health['total_changes'] = int(r[0] or 0) if r else 0
                    except Exception:
                        pass
                    # גודל DB
                    try:
                        health['db_size_mb'] = round(os.path.getsize(db_path) / (1024 * 1024), 1)
                    except Exception:
                        pass
                    # גודל WAL
                    try:
                        wal_path = db_path + '-wal'
                        if os.path.exists(wal_path):
                            health['wal_size_mb'] = round(os.path.getsize(wal_path) / (1024 * 1024), 1)
                        else:
                            health['wal_size_mb'] = 0
                    except Exception:
                        pass
                except Exception:
                    pass
                finally:
                    try:
                        if conn:
                            conn.close()
                    except Exception:
                        pass
                return _json_response(self, 200, health)

            if parsed.path == '/sync/reconnect':
                # Force reconnect: drop cached write connection so next request uses fresh one
                try:
                    with _serializer._lock:
                        if _serializer._conn:
                            try:
                                _serializer._conn.close()
                            except Exception:
                                pass
                            _serializer._conn = None
                    print("[LOCAL-SYNC] Reconnect: write connection reset")
                except Exception as e:
                    print(f"[LOCAL-SYNC] Reconnect error: {e}")
                # Verify read works
                test_ok = False
                try:
                    tc = self._open_conn()
                    tc.execute('SELECT COUNT(*) FROM change_log')
                    tc.close()
                    test_ok = True
                except Exception as te:
                    print(f"[LOCAL-SYNC] Reconnect read test failed: {te}")
                return _json_response(self, 200, {'ok': test_ok, 'reconnected': True})

            return _json_response(self, 404, {'ok': False, 'error': 'not_found'})

        def do_POST(self) -> None:
            self._track_station()
            parsed = urlparse(self.path)

            # נתיב חדש: הרצת SQL מרחוק (לעמדות משניות)
            if parsed.path == '/db/execute':
                if not self._auth_ok():
                    return _json_response(self, 401, {'ok': False, 'error': 'invalid api_key'})
                raw = _read_body(self)
                try:
                    payload = json.loads(raw.decode('utf-8', errors='ignore') or '{}')
                except Exception:
                    return _json_response(self, 400, {'ok': False, 'error': 'invalid json'})
                sql = str(payload.get('sql') or '').strip()
                params = payload.get('params') or []
                if not sql:
                    return _json_response(self, 400, {'ok': False, 'error': 'missing sql'})
                # חסימת פקודות מסוכנות
                sql_upper = sql.upper().strip()
                if any(kw in sql_upper for kw in ('DROP ', 'ALTER ', 'ATTACH ', 'DETACH ', 'PRAGMA ', 'VACUUM')):
                    return _json_response(self, 403, {'ok': False, 'error': 'forbidden sql'})
                # SELECT: חיבור קריאה נפרד (לא חוסם כתיבות)
                if sql_upper.startswith('SELECT'):
                    conn = self._open_conn()
                    try:
                        cur = conn.cursor()
                        cur.execute(sql, params)
                        rows = [dict(r) for r in cur.fetchall()]
                        return _json_response(self, 200, {'ok': True, 'lastrowid': 0, 'rowcount': 0, 'rows': rows})
                    except Exception as e:
                        return _json_response(self, 500, {'ok': False, 'error': str(e)})
                    finally:
                        conn.close()
                # כתיבה: דרך ה-serializer (lock + connection אחד) — מונע database is locked
                try:
                    results = _serializer.execute_many([{'sql': sql, 'params': params}])
                    r = results[0] if results else {}
                    return _json_response(self, 200, {
                        'ok': True,
                        'lastrowid': r.get('lastrowid', 0),
                        'rowcount': r.get('rowcount', 0),
                        'rows': None
                    })
                except Exception as e:
                    return _json_response(self, 500, {'ok': False, 'error': str(e)})

            # נתיב חדש: הרצת כמה פקודות SQL בטרנזקציה אחת
            if parsed.path == '/db/execute_many':
                if not self._auth_ok():
                    return _json_response(self, 401, {'ok': False, 'error': 'invalid api_key'})
                raw = _read_body(self)
                try:
                    payload = json.loads(raw.decode('utf-8', errors='ignore') or '{}')
                except Exception:
                    return _json_response(self, 400, {'ok': False, 'error': 'invalid json'})
                statements = payload.get('statements') or []
                if not isinstance(statements, list):
                    return _json_response(self, 400, {'ok': False, 'error': 'missing statements'})
                try:
                    results = _serializer.execute_many(statements)
                    return _json_response(self, 200, {'ok': True, 'results': results})
                except Exception as e:
                    print(f"[LocalSync] execute_many error: {e}")
                    for i, s in enumerate(statements[:5]):
                        print(f"[LocalSync]   stmt[{i}]: sql={str(s.get('sql',''))[:80]} params={str(s.get('params',''))[:80]}")
                    return _json_response(self, 500, {'ok': False, 'error': str(e)})

            if parsed.path != '/sync/push':
                return _json_response(self, 404, {'ok': False, 'error': 'not_found'})
            if not self._auth_ok():
                return _json_response(self, 401, {'ok': False, 'error': 'invalid api_key'})
            raw = _read_body(self)
            try:
                payload = json.loads(raw.decode('utf-8', errors='ignore') or '{}')
            except Exception:
                payload = {}
            changes = payload.get('changes') or []
            if not isinstance(changes, list):
                changes = []

            # כתיבות דרך ה-serializer למניעת database is locked ביום יריד
            for ch in changes:
                if not isinstance(ch, dict):
                    continue
                if not ch.get('event_id'):
                    ch['event_id'] = uuid.uuid4().hex
                if not ch.get('station_id'):
                    ch['station_id'] = str(socket.gethostname() or '').strip() or 'client'

            def _do_push(conn):
                for ch in changes:
                    if not isinstance(ch, dict):
                        continue
                    _insert_change(conn, ch)
                return _apply_changes(conn, changes)

            applied = 0
            try:
                applied = _serializer.write_with_conn(_do_push)
            except Exception as e:
                try:
                    print(f"[LocalSync] push error: {e}")
                except Exception:
                    pass

            return _json_response(self, 200, {
                'ok': True,
                'received': len(changes),
                'applied': int(applied)
            })

    return LocalSyncHandler


def run_server(host: str = '0.0.0.0', port: int = _DEFAULT_PORT, *, db_path: Optional[str] = None, api_key: str = 'local', tenant_id: str = 'local') -> None:
    try:
        if not db_path:
            try:
                print(f"[LocalSync] db_path=None, resolving via Database()...")
            except Exception:
                pass
            db_path = Database().db_path
        print(f"[LocalSync] Starting server on {host}:{port} db={db_path}")
    except Exception as e:
        try:
            print(f"[LocalSync] ERROR resolving db_path: {e}")
        except Exception:
            pass
        return
    handler = make_handler(db_path, api_key, tenant_id)
    try:
        server = ThreadingHTTPServer((host, int(port)), handler)
        print(f"[LocalSync] Server listening on port {port}")
        server.serve_forever()
    except OSError as e:
        # פורט תפוס - שרת כבר רץ, לא קריטי
        print(f"[LocalSync] Port {port} already in use: {e}")
    except Exception as e:
        print(f"[LocalSync] Server error: {e}")


def start_in_thread(host: str = '0.0.0.0', port: int = _DEFAULT_PORT, *, db_path: Optional[str] = None, api_key: str = 'local', tenant_id: str = 'local') -> threading.Thread:
    t = threading.Thread(
        target=run_server,
        args=(host, int(port)),
        kwargs={'db_path': db_path, 'api_key': api_key, 'tenant_id': tenant_id},
        daemon=True
    )
    t.start()
    return t
