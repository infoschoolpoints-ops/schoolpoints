import json
import threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from typing import Any, Dict, List, Optional
import sqlite3
import socket
import uuid

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
            except Exception:
                pass
            sync_agent._ensure_change_log(self._conn)
        return self._conn

    def execute_many(self, statements: list) -> list:
        """Execute SQL statements under a single lock + connection."""
        with self._lock:
            conn = self._get_conn()
            cur = conn.cursor()
            results = []
            try:
                for stmt in statements:
                    if not isinstance(stmt, dict):
                        continue
                    sql = str(stmt.get('sql') or '').strip()
                    params = stmt.get('params') or []
                    if not sql:
                        continue
                    sql_upper = sql.upper().strip()
                    if any(kw in sql_upper for kw in ('DROP ', 'ALTER ', 'ATTACH ', 'DETACH ', 'PRAGMA ', 'VACUUM')):
                        continue
                    cur.execute(sql, params)
                    results.append({'lastrowid': cur.lastrowid, 'rowcount': cur.rowcount})
                conn.commit()
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
        except Exception:
            pass
        sync_agent._ensure_change_log(conn)
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
    cur = conn.cursor()
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
        item = dict(r)
        eid = _ensure_event_id(conn, int(item.get('id') or 0), item.get('event_id'))
        sid = _ensure_station_id(conn, int(item.get('id') or 0), item.get('station_id'))
        item['event_id'] = eid
        item['station_id'] = sid
        # אם ה-payload ריק (מ-trigger אוטומטי), מלא אותו מהטבלה
        pj = str(item.get('payload_json') or '').strip()
        if not pj or pj == '{}':
            try:
                filled = _fill_payload_from_table(conn, item)
                if filled:
                    item['payload_json'] = filled
            except Exception:
                pass
        items.append(item)
    return items


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
            # הסר points מ-student entity - נקודות מסונכרנות רק דרך student_points delta
            if entity_type == 'student':
                d.pop('points', None)
            return json.dumps(d, ensure_ascii=False)
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
    11+ עמדות: 45 שניות
    """
    if num_stations <= 2:
        return 10
    elif num_stations <= 4:
        return 15
    elif num_stations <= 7:
        return 20
    elif num_stations <= 10:
        return 30
    else:
        return 45


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
                conn = self._open_conn()
                try:
                    items = _fetch_changes(conn, since_id, limit)
                    max_id = since_id
                    for it in items:
                        try:
                            max_id = max(max_id, int(it.get('id') or 0))
                        except Exception:
                            pass
                finally:
                    conn.close()
                n = self._active_station_count()
                return _json_response(self, 200, {
                    'ok': True,
                    'tenant_id': str(tenant_id or ''),
                    'since_id': int(since_id or 0),
                    'next_since_id': int(max_id),
                    'items': items,
                    'recommended_interval': _calc_recommended_interval(n),
                    'stations': n,
                })

            if parsed.path == '/sync/snapshot':
                if not self._auth_ok():
                    return _json_response(self, 401, {'ok': False, 'error': 'invalid api_key'})
                conn = self._open_conn()
                try:
                    payload = _build_snapshot_payload(conn)
                finally:
                    conn.close()
                return _json_response(self, 200, payload)

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
                conn = self._open_conn()
                try:
                    cur = conn.cursor()
                    cur.execute(sql, params)
                    conn.commit()
                    lastrowid = cur.lastrowid
                    rowcount = cur.rowcount
                    # אם זה SELECT, החזר תוצאות
                    rows = None
                    if sql_upper.startswith('SELECT'):
                        rows = [dict(r) for r in cur.fetchall()]
                    return _json_response(self, 200, {
                        'ok': True,
                        'lastrowid': lastrowid,
                        'rowcount': rowcount,
                        'rows': rows
                    })
                except Exception as e:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                    return _json_response(self, 500, {'ok': False, 'error': str(e)})
                finally:
                    conn.close()

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

            conn = self._open_conn()
            applied = 0
            try:
                for ch in changes:
                    if not isinstance(ch, dict):
                        continue
                    if not ch.get('event_id'):
                        ch['event_id'] = uuid.uuid4().hex
                    if not ch.get('station_id'):
                        ch['station_id'] = str(socket.gethostname() or '').strip() or 'client'
                    _insert_change(conn, ch)
                applied = _apply_changes(conn, changes)
            finally:
                conn.close()

            return _json_response(self, 200, {
                'ok': True,
                'received': len(changes),
                'applied': int(applied)
            })

    return LocalSyncHandler


def run_server(host: str = '0.0.0.0', port: int = _DEFAULT_PORT, *, db_path: Optional[str] = None, api_key: str = 'local', tenant_id: str = 'local') -> None:
    db_path = db_path or Database().db_path
    handler = make_handler(db_path, api_key, tenant_id)
    try:
        server = ThreadingHTTPServer((host, int(port)), handler)
        server.serve_forever()
    except OSError as e:
        # פורט תפוס - שרת כבר רץ, לא קריטי
        print(f"[LocalSync] Port {port} already in use: {e}")


def start_in_thread(host: str = '0.0.0.0', port: int = _DEFAULT_PORT, *, db_path: Optional[str] = None, api_key: str = 'local', tenant_id: str = 'local') -> threading.Thread:
    t = threading.Thread(
        target=run_server,
        args=(host, int(port)),
        kwargs={'db_path': db_path, 'api_key': api_key, 'tenant_id': tenant_id},
        daemon=True
    )
    t.start()
    return t
