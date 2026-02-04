"""
Sync Agent (שלב A)

מטרת הקובץ: לספק בסיס לסנכרון עתידי (לא מופעל אוטומטית).
אין שינוי בעמדות פעילות. אפשר להריץ ידנית בעתיד.
"""
import json
import os
import time
import sqlite3
import urllib.request
import urllib.error
import urllib.parse
import argparse
import hashlib
import atexit
from typing import List, Dict, Any, Optional
from datetime import datetime

try:
    from database import Database
except Exception:
    Database = None

try:
    from sync_file_module import sync_files_cycle
except ImportError:
    def sync_files_cycle(*args, **kwargs):
        pass


DEFAULT_PUSH_URL = ""
DEFAULT_BATCH_SIZE = 200
DEFAULT_PULL_LIMIT = 500


_LOCK_FD: Optional[int] = None


def _lock_dir(base_dir: str) -> str:
    try:
        cfg_path = _get_config_file_path(base_dir)
        d = os.path.dirname(os.path.abspath(cfg_path))
        if d and os.path.isdir(d):
            return d
    except Exception:
        pass
    return base_dir


def _lock_path_for_db(base_dir: str, db_path: str) -> str:
    try:
        norm = os.path.abspath(str(db_path or '')).lower()
    except Exception:
        norm = str(db_path or '')
    h = hashlib.md5(norm.encode('utf-8', errors='ignore')).hexdigest()[:16]
    return os.path.join(_lock_dir(base_dir), f"sync_agent_{h}.lock")


def _acquire_db_lock(base_dir: str, db_path: str) -> bool:
    global _LOCK_FD
    if _LOCK_FD is not None:
        return True
    lock_path = _lock_path_for_db(base_dir, db_path)
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
    except FileExistsError:
        try:
            existing = ''
            try:
                with open(lock_path, 'r', encoding='utf-8', errors='ignore') as f:
                    existing = (f.read() or '').strip()
            except Exception:
                existing = ''
            msg = f"[LOCK] Another sync_agent seems to be running for this DB (lock exists: {lock_path})"
            if existing:
                msg += f" | {existing}"
            print(msg)
        except Exception:
            pass
        return False
    except Exception as exc:
        try:
            print(f"[LOCK] Failed to create lockfile: {lock_path} ({exc})")
        except Exception:
            pass
        return False

    try:
        os.write(fd, f"pid={os.getpid()} db={db_path}\n".encode('utf-8', errors='ignore'))
    except Exception:
        pass
    _LOCK_FD = fd

    def _cleanup() -> None:
        global _LOCK_FD
        try:
            if _LOCK_FD is not None:
                try:
                    os.close(_LOCK_FD)
                except Exception:
                    pass
                _LOCK_FD = None
            try:
                os.remove(lock_path)
            except Exception:
                pass
        except Exception:
            pass

    atexit.register(_cleanup)
    return True


def _get_config_file_path(base_dir: str) -> str:
    for env_name in ("PROGRAMDATA", "LOCALAPPDATA", "APPDATA"):
        root = os.environ.get(env_name)
        if not root:
            continue
        try:
            if os.path.isdir(root) and os.access(root, os.W_OK):
                cfg_dir = os.path.join(root, "SchoolPoints")
                try:
                    os.makedirs(cfg_dir, exist_ok=True)
                except Exception:
                    pass
                return os.path.join(cfg_dir, "config.json")
        except Exception:
            continue
    return os.path.join(base_dir, 'config.json')


def _is_unc_path(path: str) -> bool:
    try:
        p = str(path or '')
    except Exception:
        return False
    return p.startswith('\\') or p.startswith('//')


def _apply_pragmas(conn: sqlite3.Connection, *, db_path: str) -> None:
    try:
        conn.execute('PRAGMA foreign_keys = ON')
    except Exception:
        pass
    try:
        conn.execute('PRAGMA busy_timeout = 5000')
    except Exception:
        pass
    try:
        if _is_unc_path(db_path):
            conn.execute('PRAGMA journal_mode = DELETE')
            conn.execute('PRAGMA synchronous = FULL')
        else:
            conn.execute('PRAGMA journal_mode = WAL')
            conn.execute('PRAGMA synchronous = NORMAL')
    except Exception:
        pass


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    _apply_pragmas(conn, db_path=db_path)
    return conn


def _table_columns(conn: sqlite3.Connection, table: str) -> List[str]:
    try:
        cur = conn.cursor()
        cur.execute(f"PRAGMA table_info({table})")
        rows = cur.fetchall() or []
        cols: List[str] = []
        for r in rows:
            try:
                cols.append(str(r['name']))
            except Exception:
                try:
                    cols.append(str(r[1]))
                except Exception:
                    pass
        return [c for c in cols if c]
    except Exception:
        return []


def _replace_rows_local(conn: sqlite3.Connection, table: str, rows: List[Dict[str, Any]]) -> int:
    cols = _table_columns(conn, table)
    if not cols:
        return 0
    cur = conn.cursor()
    cur.execute(f"DELETE FROM {table}")
    if not rows:
        return 0

    allowed = set(cols)
    # don't attempt to write timestamps that might have defaults
    allowed.discard('created_at')
    allowed.discard('updated_at')

    insert_cols: List[str] = []
    for k in (rows[0] or {}).keys():
        if k in allowed:
            insert_cols.append(k)
    if not insert_cols:
        for k in cols:
            if k in allowed:
                insert_cols.append(k)
    if not insert_cols:
        return 0

    placeholders = ','.join(['?'] * len(insert_cols))
    sql = f"INSERT INTO {table} ({','.join(insert_cols)}) VALUES ({placeholders})"
    values = []
    for r in rows:
        r = r or {}
        values.append([r.get(c) for c in insert_cols])
    cur.executemany(sql, values)
    return int(len(values))


def _snapshot_url_from_push(push_url: str, cfg: Dict[str, Any]) -> str:
    url = str(cfg.get('sync_snapshot_url') or '').strip()
    if url:
        return url
    if push_url and push_url.endswith('/sync/push'):
        return push_url[:-len('/sync/push')] + '/sync/snapshot'
    return ''


def _snapshot2_url_from_snapshot(snapshot_url: str) -> str:
    try:
        u = str(snapshot_url or '').strip()
    except Exception:
        return ''
    if not u:
        return ''
    u = u.rstrip('/')
    if u.endswith('/sync/snapshot'):
        return u + '2'
    return ''


def pull_snapshot(snapshot_url: str, *, api_key: str = '', tenant_id: str = '') -> Dict[str, Any] | None:
    if not snapshot_url:
        return None

    def _do_pull(url: str, timeout_s: int) -> Dict[str, Any] | None:
        q = f"tenant_id={urllib.parse.quote(str(tenant_id or ''))}"
        full_url = url + ('&' if '?' in url else '?') + q
        req = urllib.request.Request(
            full_url,
            headers={
                'Content-Type': 'application/json',
                'Accept-Encoding': 'gzip',
                'api-key': str(api_key or ''),
                'x-api-key': str(api_key or ''),
            }
        )
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            body = resp.read() or b''
            try:
                enc = str(resp.headers.get('Content-Encoding') or '').strip().lower()
            except Exception:
                enc = ''
        if enc == 'gzip':
            try:
                import gzip as _gz
                body = _gz.decompress(body)
            except Exception:
                pass
        try:
            data = json.loads(body.decode('utf-8', errors='ignore') or '{}')
        except Exception:
            data = None
        if not isinstance(data, dict):
            return None
        return data

    url2 = _snapshot2_url_from_snapshot(snapshot_url)
    if url2:
        try:
            data2 = _do_pull(url2, timeout_s=60)
            if isinstance(data2, dict) and data2.get('ok'):
                return data2
        except urllib.error.HTTPError as exc:
            if int(getattr(exc, 'code', 0) or 0) not in (404, 405):
                try:
                    body = exc.read().decode('utf-8', errors='ignore')
                except Exception:
                    body = ''
                print(f"[SNAPSHOT2-PULL] HTTP {exc.code}: {body}")
        except Exception as exc:
            print(f"[SNAPSHOT2-PULL] Request error: {exc}")

    try:
        return _do_pull(snapshot_url, timeout_s=25)
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode('utf-8', errors='ignore')
        except Exception:
            body = ''
        print(f"[SNAPSHOT-PULL] HTTP {exc.code}: {body}")
        return None
    except Exception as exc:
        print(f"[SNAPSHOT-PULL] Request error: {exc}")
        return None


def _is_db_empty_for_bootstrap(conn: sqlite3.Connection) -> bool:
    try:
        cur = conn.cursor()
        cur.execute('SELECT COUNT(*) FROM teachers')
        t = int(cur.fetchone()[0] or 0)
        cur.execute('SELECT COUNT(*) FROM students')
        s = int(cur.fetchone()[0] or 0)
        return (t == 0 and s == 0)
    except Exception:
        return True


def apply_snapshot(conn: sqlite3.Connection, snapshot: Dict[str, Any]) -> Dict[str, Any]:
    # snapshot can be {snapshot:{table:[rows]}} or direct dict
    snap = snapshot.get('snapshot') if isinstance(snapshot, dict) else None
    if not isinstance(snap, dict):
        snap = snapshot if isinstance(snapshot, dict) else {}

    exclude = {
        'change_log',
        'applied_events',
        'purchase_holds',
        'sync_state',
        'sqlite_sequence',
    }

    tables = [
        'teachers',
        'teacher_classes',
        'students',
        'messages',
        'static_messages',
        'threshold_messages',
        'news_items',
        'ads_items',
        'student_messages',
        'settings',
        'product_categories',
        'products',
        'product_variants',
        'cashier_responsibles',
        'time_bonus_schedules',
        'public_closures',
        'activities',
        'activity_schedules',
        'activity_claims',
        'scheduled_services',
        'scheduled_service_dates',
        'scheduled_service_slots',
        'scheduled_service_reservations',
        'points_log',
        'web_settings',
        'card_blocks',
        'card_validations',
        'anti_spam_events',
        'points_history',
        'refunds_log',
        'time_bonus_given',
    ]

    # Apply any additional tables included in the snapshot (forward-compatible)
    try:
        extra_tables: List[str] = []
        for t in (snap.keys() if isinstance(snap, dict) else []):
            if not isinstance(t, str):
                continue
            if t in exclude:
                continue
            if t in tables:
                continue
            if not _safe_table_name(t):
                continue
            extra_tables.append(t)
        if extra_tables:
            tables = list(tables) + sorted(set(extra_tables))
    except Exception:
        pass
    applied: Dict[str, int] = {}
    cur = conn.cursor()
    cur.execute('BEGIN IMMEDIATE')
    try:
        for t in tables:
            try:
                rows = snap.get(t) if isinstance(snap, dict) else None
                if not isinstance(rows, list):
                    rows = []
                applied[t] = _replace_rows_local(conn, t, rows)
            except Exception:
                applied[t] = 0
        
        # Update pull cursor if present (server-side event cursor)
        last_id = snapshot.get('last_event_id')
        if last_id is None:
            # Backward compatibility (older server returned last_change_id)
            last_id = snapshot.get('last_change_id')
        if last_id is not None:
            try:
                _set_sync_state(conn, 'pull_since_id', str(last_id))
            except Exception:
                pass
                
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    return {'ok': True, 'tables': applied}


def _load_config(base_dir: str) -> Dict[str, Any]:
    live_config = _get_config_file_path(base_dir)
    base_config = os.path.join(base_dir, 'config.json')

    local_cfg: Dict[str, Any] = {}
    try:
        if os.path.exists(live_config):
            with open(live_config, 'r', encoding='utf-8') as f:
                local_cfg = json.load(f) or {}
    except Exception:
        local_cfg = {}

    shared_folder = None
    try:
        if isinstance(local_cfg, dict):
            shared_folder = local_cfg.get('shared_folder') or local_cfg.get('network_root')
    except Exception:
        shared_folder = None

    if shared_folder and os.path.isdir(shared_folder):
        shared_config_path = os.path.join(shared_folder, 'config.json')
        if os.path.exists(shared_config_path):
            try:
                with open(shared_config_path, 'r', encoding='utf-8') as f:
                    shared_cfg = json.load(f) or {}
                if isinstance(shared_cfg, dict):
                    # keep db_path from local if it exists
                    try:
                        if isinstance(local_cfg, dict) and local_cfg.get('db_path'):
                            merged = dict(shared_cfg)
                            merged['db_path'] = local_cfg.get('db_path')
                            return merged
                    except Exception:
                        pass
                    return shared_cfg
            except Exception:
                pass

    if isinstance(local_cfg, dict) and local_cfg:
        return local_cfg

    try:
        if os.path.exists(base_config):
            with open(base_config, 'r', encoding='utf-8') as f:
                return json.load(f) or {}
    except Exception:
        pass
    return {}


def _check_db_path_file(base_dir: str) -> Optional[str]:
    try:
        p = os.path.join(base_dir, 'db_path.txt')
        if os.path.exists(p):
            with open(p, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        return line
    except Exception:
        pass
    return None


def _default_db_path(base_dir: str, cfg: Dict[str, Any]) -> str:
    try:
        if cfg.get('db_path'):
            return str(cfg.get('db_path'))
        shared = cfg.get('shared_folder') or cfg.get('network_root')
        if shared:
            return os.path.join(shared, 'school_points.db')
    except Exception:
        pass

    # Check for db_path.txt override (e.g. linked station)
    custom = _check_db_path_file(base_dir)
    if custom:
        return custom

    return os.path.join(base_dir, 'school_points.db')


def _ensure_sync_state(conn: sqlite3.Connection) -> None:
    try:
        cur = conn.cursor()
        cur.execute(
            '''
            CREATE TABLE IF NOT EXISTS sync_state (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            '''
        )
        conn.commit()
    except Exception:
        pass


def _get_sync_state(conn: sqlite3.Connection, key: str, default: str = '') -> str:
    try:
        cur = conn.cursor()
        cur.execute('SELECT value FROM sync_state WHERE key = ? LIMIT 1', (str(key),))
        row = cur.fetchone()
        if not row:
            return default
        try:
            return str(row['value'] if isinstance(row, sqlite3.Row) else row[0] or '')
        except Exception:
            return str(row[0] or '')
    except Exception:
        _ensure_sync_state(conn)
        return default


def _set_sync_state(conn: sqlite3.Connection, key: str, value: str) -> None:
    try:
        cur = conn.cursor()
        cur.execute('INSERT INTO sync_state (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP', (str(key), str(value)))
        conn.commit()
    except sqlite3.OperationalError:
        _ensure_sync_state(conn)
        try:
            cur = conn.cursor()
            cur.execute('UPDATE sync_state SET value = ?, updated_at = CURRENT_TIMESTAMP WHERE key = ?', (str(value), str(key)))
            if cur.rowcount == 0:
                cur.execute('INSERT INTO sync_state (key, value) VALUES (?, ?)', (str(key), str(value)))
            conn.commit()
        except Exception:
            pass
    except Exception:
        pass


def _resolve_db_path(base_dir: str, cfg: Dict[str, Any]) -> str:
    if Database is not None:
        try:
            db = Database()
            if getattr(db, 'db_path', None):
                return str(db.db_path)
        except Exception:
            pass
    return _default_db_path(base_dir, cfg)


def _ensure_change_log(conn: sqlite3.Connection) -> None:
    try:
        cur = conn.cursor()
        cur.execute(
            '''
            CREATE TABLE IF NOT EXISTS change_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_type TEXT NOT NULL,
                entity_id TEXT,
                action_type TEXT NOT NULL,
                payload_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                synced_at TIMESTAMP
            )
            '''
        )
        conn.commit()
    except Exception:
        pass


def fetch_pending_changes(conn: sqlite3.Connection, limit: int = DEFAULT_BATCH_SIZE) -> List[Dict[str, Any]]:
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT id, entity_type, entity_id, action_type, payload_json, created_at
            FROM change_log
            WHERE synced_at IS NULL
            ORDER BY id ASC
            LIMIT ?
            """,
            (int(limit),)
        )
        rows = cur.fetchall() or []
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        _ensure_change_log(conn)
        return []


def mark_changes_synced(conn: sqlite3.Connection, ids: List[int]) -> None:
    if not ids:
        return
    cur = conn.cursor()
    cur.execute(
        f"UPDATE change_log SET synced_at = CURRENT_TIMESTAMP WHERE id IN ({','.join(['?'] * len(ids))})",
        [int(x) for x in ids]
    )
    conn.commit()


def push_changes(push_url: str, changes: List[Dict[str, Any]], *, api_key: str = '', tenant_id: str = '', station_id: str = '') -> bool:
    if not push_url:
        return False
    payload = json.dumps({
        'tenant_id': str(tenant_id or ''),
        'station_id': str(station_id or ''),
        'changes': changes
    }, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(
        push_url,
        data=payload,
        headers={
            'Content-Type': 'application/json',
            'api-key': str(api_key or ''),
            'x-api-key': str(api_key or ''),
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            _ = resp.read()
        return True
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode('utf-8', errors='ignore')
        except Exception:
            body = ''
        print(f"[SYNC] HTTP {exc.code}: {body}")
        return False
    except Exception as exc:
        print(f"[SYNC] Request error: {exc}")
        return False


def _fetch_all(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall() or []
    return [dict(r) for r in rows]


def _safe_table_name(name: str) -> bool:
    try:
        n = str(name or '').strip()
    except Exception:
        return False
    if not n:
        return False
    for ch in n:
        if not (ch.isalnum() or ch == '_'):
            return False
    return True


def _list_user_tables(conn: sqlite3.Connection) -> List[str]:
    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
        rows = cur.fetchall() or []
        out: List[str] = []
        for r in rows:
            try:
                nm = r['name']
            except Exception:
                try:
                    nm = r[0]
                except Exception:
                    nm = None
            nm = str(nm or '').strip()
            if nm:
                out.append(nm)
        return out
    except Exception:
        return []


def build_snapshot(conn: sqlite3.Connection) -> Dict[str, Any]:
    teachers = []
    students = []
    try:
        teachers = _fetch_all(
            conn,
            """
            SELECT id, name, card_number, card_number2, card_number3, is_admin,
                   can_edit_student_card, can_edit_student_photo,
                   bonus_max_points_per_student, bonus_max_total_runs, bonus_runs_used,
                   bonus_runs_reset_date, bonus_points_used, bonus_points_reset_date,
                   created_at, updated_at
              FROM teachers
            ORDER BY id ASC
            """
        )
    except Exception:
        teachers = []
    try:
        students = _fetch_all(
            conn,
            """
            SELECT id, serial_number, last_name, first_name, class_name, points, card_number,
                   id_number, photo_number, private_message, is_free_fix_blocked, created_at, updated_at
              FROM students
            ORDER BY id ASC
            """
        )
    except Exception:
        students = []

    snapshot: Dict[str, Any] = {}
    exclude = {
        'change_log',
        'applied_events',
        'purchase_holds',
        'sync_state',
        'sqlite_sequence',
    }
    try:
        for t in _list_user_tables(conn):
            if t in exclude:
                continue
            if not _safe_table_name(t):
                continue
            try:
                snapshot[t] = _fetch_all(conn, f"SELECT * FROM {t}")
            except Exception:
                snapshot[t] = []
    except Exception:
        snapshot = {}

    return {
        'teachers': teachers,
        'students': students,
        'snapshot': snapshot,
    }


def push_snapshot(snapshot_url: str, snapshot: Dict[str, Any], *, api_key: str = '', tenant_id: str = '', station_id: str = '') -> bool:
    if not snapshot_url:
        return False
    payload = json.dumps({
        'tenant_id': str(tenant_id or ''),
        'station_id': str(station_id or ''),
        'teachers': snapshot.get('teachers') or [],
        'students': snapshot.get('students') or [],
    }, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(
        snapshot_url,
        data=payload,
        headers={
            'Content-Type': 'application/json',
            'api-key': str(api_key or ''),
            'x-api-key': str(api_key or ''),
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            body_bytes = resp.read() or b''
        try:
            body_text = body_bytes.decode('utf-8', errors='ignore')
        except Exception:
            body_text = ''
        if body_text.strip():
            print(f"[SNAPSHOT] Server response: {body_text.strip()}")
        return True
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode('utf-8', errors='ignore')
        except Exception:
            body = ''
        print(f"[SNAPSHOT] HTTP {exc.code}: {body}")
        return False
    except Exception as exc:
        print(f"[SNAPSHOT] Request error: {exc}")
        return False


def push_snapshot2(snapshot_url: str, snapshot: Dict[str, Any], *, api_key: str = '', tenant_id: str = '', station_id: str = '') -> bool:
    url2 = _snapshot2_url_from_snapshot(snapshot_url)
    if not url2:
        return False
    snap_obj = snapshot.get('snapshot') if isinstance(snapshot, dict) else None
    if not isinstance(snap_obj, dict):
        snap_obj = {}
    payload_raw = json.dumps({
        'tenant_id': str(tenant_id or ''),
        'station_id': str(station_id or ''),
        'snapshot': snap_obj,
    }, ensure_ascii=False).encode('utf-8')
    try:
        import gzip as _gz
        payload = _gz.compress(payload_raw, compresslevel=6)
        content_encoding = 'gzip'
    except Exception:
        payload = payload_raw
        content_encoding = ''
    req = urllib.request.Request(
        url2,
        data=payload,
        headers={
            'Content-Type': 'application/json',
            **({'Content-Encoding': content_encoding} if content_encoding else {}),
            'api-key': str(api_key or ''),
            'x-api-key': str(api_key or ''),
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body_bytes = resp.read() or b''
        try:
            body_text = body_bytes.decode('utf-8', errors='ignore')
        except Exception:
            body_text = ''
        if body_text.strip():
            print(f"[SNAPSHOT2] Server response: {body_text.strip()}")
        return True
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode('utf-8', errors='ignore')
        except Exception:
            body = ''
        print(f"[SNAPSHOT2] HTTP {exc.code}: {body}")
        return False
    except Exception as exc:
        print(f"[SNAPSHOT2] Request error: {exc}")
        return False


def _pull_url_from_push(push_url: str, cfg: Dict[str, Any]) -> str:
    url = str(cfg.get('sync_pull_url') or '').strip()
    if url:
        return url
    if push_url.endswith('/sync/push'):
        return push_url[:-len('/sync/push')] + '/sync/pull'
    return ''


def pull_changes(pull_url: str, *, api_key: str = '', tenant_id: str = '', since_id: int = 0, limit: int = DEFAULT_PULL_LIMIT) -> Dict[str, Any] | None:
    if not pull_url:
        return None
    q = f"tenant_id={urllib.parse.quote(str(tenant_id or ''))}&since_id={int(since_id or 0)}&limit={int(limit or 0)}"
    url = pull_url + ('&' if '?' in pull_url else '?') + q
    req = urllib.request.Request(
        url,
        headers={
            'Content-Type': 'application/json',
            'api-key': str(api_key or ''),
            'x-api-key': str(api_key or ''),
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read() or b''
        try:
            data = json.loads(body.decode('utf-8', errors='ignore') or '{}')
        except Exception:
            data = None
        if not isinstance(data, dict):
            return None
        return data
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode('utf-8', errors='ignore')
        except Exception:
            body = ''
        print(f"[PULL] HTTP {exc.code}: {body}")
        return None
    except Exception as exc:
        print(f"[PULL] Request error: {exc}")
        return None


def _ensure_applied_events(conn: sqlite3.Connection) -> None:
    try:
        cur = conn.cursor()
        cur.execute(
            '''
            CREATE TABLE IF NOT EXISTS applied_events (
                event_id TEXT PRIMARY KEY,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            '''
        )
        conn.commit()
    except Exception:
        pass


def _is_event_applied(conn: sqlite3.Connection, event_id: str) -> bool:
    try:
        cur = conn.cursor()
        cur.execute('SELECT 1 FROM applied_events WHERE event_id = ? LIMIT 1', (str(event_id or ''),))
        return bool(cur.fetchone())
    except Exception:
        _ensure_applied_events(conn)
        return False


def _mark_event_applied(conn: sqlite3.Connection, event_id: str) -> None:
    try:
        cur = conn.cursor()
        cur.execute('INSERT OR IGNORE INTO applied_events (event_id) VALUES (?)', (str(event_id or ''),))
        conn.commit()
    except Exception:
        _ensure_applied_events(conn)
        try:
            cur = conn.cursor()
            cur.execute('INSERT OR IGNORE INTO applied_events (event_id) VALUES (?)', (str(event_id or ''),))
            conn.commit()
        except Exception:
            pass


def _parse_dt_maybe(ts: str | None) -> Optional[datetime]:
    s = str(ts or '').strip()
    if not s:
        return None
    try:
        # common: 'YYYY-MM-DD HH:MM:SS'
        s2 = s.replace('Z', '').replace('T', ' ')
        return datetime.fromisoformat(s2)
    except Exception:
        return None


def apply_pull_events(conn: sqlite3.Connection, items: List[Dict[str, Any]]) -> int:
    if not items:
        return 0
    _ensure_applied_events(conn)
    applied = 0
    cur = conn.cursor()
    for ev in items:
        try:
            event_id = str(ev.get('event_id') or '').strip()
            if event_id and _is_event_applied(conn, event_id):
                continue
            entity_type = str(ev.get('entity_type') or '').strip()
            action_type = str(ev.get('action_type') or '').strip()
            entity_id = str(ev.get('entity_id') or '').strip()
            payload_json = str(ev.get('payload_json') or '').strip()
            payload = {}
            try:
                payload = json.loads(payload_json) if payload_json else {}
            except Exception:
                payload = {}

            if entity_type == 'student_points' and action_type == 'update':
                sid = int(entity_id or '0')
                if sid <= 0:
                    continue
                old_points = int(payload.get('old_points') or 0)
                new_points = int(payload.get('new_points') or 0)
                delta = int(new_points - old_points)
                if delta == 0:
                    if event_id:
                        _mark_event_applied(conn, event_id)
                    continue
                cur.execute('SELECT points FROM students WHERE id = ? LIMIT 1', (int(sid),))
                r0 = cur.fetchone()
                if not r0:
                    continue
                try:
                    cur_points = int((r0.get('points') if isinstance(r0, dict) else r0['points']))
                except Exception:
                    try:
                        cur_points = int(r0[0])
                    except Exception:
                        cur_points = 0
                final_points = int(cur_points + delta)
                cur.execute('UPDATE students SET points = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?', (int(final_points), int(sid)))
                try:
                    reason = str(payload.get('reason') or '').strip()
                    cur.execute(
                        '''
                        INSERT INTO points_log (student_id, old_points, new_points, delta, reason, actor_name, action_type)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        ''',
                        (int(sid), int(cur_points), int(final_points), int(delta), reason, 'sync', 'sync')
                    )
                except Exception:
                    pass
                applied += 1

            if entity_type == 'student' and action_type in ('create', 'update', 'delete'):
                try:
                    sid = int(entity_id or 0)
                    if sid <= 0:
                        sid = int(payload.get('id') or 0)
                    
                    if action_type == 'delete':
                        if sid > 0:
                            # Delete logs first to avoid foreign key issues if any (though usually no FK enforced)
                            try:
                                cur.execute("DELETE FROM points_log WHERE student_id = ?", (sid,))
                            except:
                                pass
                            try:
                                cur.execute("DELETE FROM points_history WHERE student_id = ?", (sid,))
                            except:
                                pass
                            cur.execute("DELETE FROM students WHERE id = ?", (sid,))
                            applied += 1
                        continue

                    # Fields to update
                    # 'points' is handled carefully - if provided, we update it (admin override)
                    # but usually points flow via student_points delta. 
                    # If this is a full profile save, it includes points.
                    
                    serial = str(payload.get('serial_number') or '').strip()
                    first = str(payload.get('first_name') or '').strip()
                    last = str(payload.get('last_name') or '').strip()
                    cls_name = str(payload.get('class_name') or '').strip()
                    card = str(payload.get('card_number') or '').strip()
                    photo = str(payload.get('photo_number') or '').strip()
                    p_msg = str(payload.get('private_message') or '')
                    idn = str(payload.get('id_number') or '').strip()
                    blocked = int(payload.get('is_free_fix_blocked') or 0)
                    
                    # Check if exists
                    exists = False
                    if sid > 0:
                        cur.execute('SELECT 1 FROM students WHERE id = ?', (sid,))
                        exists = bool(cur.fetchone())
                    
                    if not exists and serial:
                        # Try match by serial if ID not found (maybe different ID locally? shouldn't happen with snapshot)
                        cur.execute('SELECT id FROM students WHERE serial_number = ?', (serial,))
                        row = cur.fetchone()
                        if row:
                            sid = int(row[0])
                            exists = True

                    if action_type == 'create' and not exists:
                        # Insert
                        cols = ['serial_number', 'first_name', 'last_name', 'class_name', 'card_number', 'photo_number', 'private_message', 'id_number', 'is_free_fix_blocked', 'created_at', 'updated_at']
                        vals = [serial, first, last, cls_name, card, photo, p_msg, idn, blocked, datetime.now(), datetime.now()]
                        placeholders = '?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?'
                        
                        if sid > 0:
                            cols.insert(0, 'id')
                            vals.insert(0, sid)
                            placeholders = '?, ' + placeholders
                            
                        # If points provided in payload (new student)
                        if 'points' in payload:
                            cols.append('points')
                            vals.append(int(payload['points']))
                            placeholders += ', ?'
                            
                        sql = f"INSERT INTO students ({', '.join(cols)}) VALUES ({placeholders})"
                        cur.execute(sql, vals)
                        applied += 1
                        
                    elif exists:
                        # Update
                        sets = [
                            "serial_number = ?", "first_name = ?", "last_name = ?", 
                            "class_name = ?", "card_number = ?", "photo_number = ?",
                            "private_message = ?", "id_number = ?", "is_free_fix_blocked = ?", "updated_at = ?"
                        ]
                        pvals = [serial, first, last, cls_name, card, photo, p_msg, idn, blocked, datetime.now()]
                        
                        # Only update points if explicitly in payload (Admin edit)
                        if 'points' in payload:
                            sets.append("points = ?")
                            pvals.append(int(payload['points']))
                            
                        pvals.append(sid)
                        
                        sql = f"UPDATE students SET {', '.join(sets)} WHERE id = ?"
                        cur.execute(sql, pvals)
                        applied += 1
                except Exception as e:
                    print(f"[SYNC] Student sync error: {e}")

            if entity_type == 'teacher' and action_type in ('create', 'update', 'delete'):
                try:
                    tid = int(entity_id or 0)
                    if tid <= 0: 
                        tid = int(payload.get('id') or 0)
                        
                    if action_type == 'delete':
                        if tid > 0:
                            cur.execute("DELETE FROM teachers WHERE id = ?", (tid,))
                            applied += 1
                    else:
                        # Create/Update
                        name = str(payload.get('name') or '').strip()
                        card1 = str(payload.get('card_number') or '').strip()
                        card2 = str(payload.get('card_number2') or '').strip()
                        card3 = str(payload.get('card_number3') or '').strip()
                        is_admin = int(payload.get('is_admin') or 0)
                        can_card = int(payload.get('can_edit_student_card') or 0)
                        can_photo = int(payload.get('can_edit_student_photo') or 0)
                        
                        # Check existence
                        exists = False
                        if tid > 0:
                            cur.execute('SELECT 1 FROM teachers WHERE id = ?', (tid,))
                            exists = bool(cur.fetchone())
                            
                        if not exists and action_type == 'create':
                            cols = ['id', 'name', 'card_number', 'card_number2', 'card_number3', 'is_admin', 'can_edit_student_card', 'can_edit_student_photo', 'updated_at']
                            vals = [tid, name, card1, card2, card3, is_admin, can_card, can_photo, datetime.now()]
                            # handle optional bonus fields if present
                            if 'bonus_max_points_per_student' in payload:
                                cols.append('bonus_max_points_per_student')
                                vals.append(payload['bonus_max_points_per_student'])
                            if 'bonus_max_total_runs' in payload:
                                cols.append('bonus_max_total_runs')
                                vals.append(payload['bonus_max_total_runs'])
                                
                            q = f"INSERT INTO teachers ({', '.join(cols)}) VALUES ({', '.join(['?']*len(cols))})"
                            cur.execute(q, vals)
                            applied += 1
                        elif exists:
                            sets = [
                                "name=?", "card_number=?", "card_number2=?", "card_number3=?",
                                "is_admin=?", "can_edit_student_card=?", "can_edit_student_photo=?", "updated_at=?"
                            ]
                            vals = [name, card1, card2, card3, is_admin, can_card, can_photo, datetime.now()]
                            
                            if 'bonus_max_points_per_student' in payload:
                                sets.append("bonus_max_points_per_student=?")
                                vals.append(payload['bonus_max_points_per_student'])
                            if 'bonus_max_total_runs' in payload:
                                sets.append("bonus_max_total_runs=?")
                                vals.append(payload['bonus_max_total_runs'])
                                
                            vals.append(tid)
                            q = f"UPDATE teachers SET {', '.join(sets)} WHERE id=?"
                            cur.execute(q, vals)
                            applied += 1
                except Exception as e:
                    print(f"[SYNC] Teacher sync error: {e}")

            if entity_type == 'class':
                try:
                    if action_type == 'rename':
                        old_name = str(payload.get('old_name') or '').strip()
                        new_name = str(payload.get('new_name') or '').strip()
                        if old_name and new_name:
                            cur.execute("UPDATE students SET class_name = ? WHERE class_name = ?", (new_name, old_name))
                            applied += 1
                    elif action_type == 'delete':
                        class_name = str(payload.get('class_name') or '').strip()
                        if class_name:
                            cur.execute("UPDATE students SET class_name = '' WHERE class_name = ?", (class_name,))
                            applied += 1
                except Exception as e:
                    print(f"[SYNC] Class sync error: {e}")

            if entity_type == 'product' and action_type in ('create', 'update', 'delete'):
                try:
                    pid = int(entity_id or 0)
                    if pid <= 0:
                        pid = int(payload.get('id') or 0)
                        
                    if action_type == 'delete':
                        if pid > 0:
                            # Soft delete to match web behavior
                            cur.execute("UPDATE products SET is_active = 0 WHERE id = ?", (pid,))
                            if cur.rowcount == 0:
                                # If not found, maybe it doesn't exist, but let's ensure it's "deleted"
                                # If we want to hard delete: cur.execute("DELETE FROM products WHERE id = ?", (pid,))
                                pass
                            applied += 1
                    else:
                        # Create/Update
                        name = str(payload.get('name') or '').strip()
                        price = int(payload.get('price_points') or 0)
                        stock = payload.get('stock_qty')
                        if stock is not None:
                            stock = int(stock)
                        
                        # Check existence
                        exists = False
                        if pid > 0:
                            cur.execute('SELECT 1 FROM products WHERE id = ?', (pid,))
                            exists = bool(cur.fetchone())
                            
                        if not exists and action_type == 'create':
                            cols = ['id', 'name', 'price_points', 'is_active', 'updated_at']
                            vals = [pid, name, price, 1, datetime.now()]
                            placeholders = '?, ?, ?, ?, ?'
                            
                            if stock is not None:
                                cols.append('stock_qty')
                                vals.append(stock)
                                placeholders += ', ?'
                                
                            sql = f"INSERT INTO products ({', '.join(cols)}) VALUES ({placeholders})"
                            cur.execute(sql, vals)
                            applied += 1
                        elif exists:
                            sets = ["name=?", "price_points=?", "updated_at=?"]
                            vals = [name, price, datetime.now()]
                            
                            if stock is not None:
                                sets.append("stock_qty=?")
                                vals.append(stock)
                            else:
                                # If payload explicit null, maybe set null? Web UI sends null for infinity
                                sets.append("stock_qty=?")
                                vals.append(None)
                                
                            # Ensure active on update
                            sets.append("is_active=1")
                                
                            vals.append(pid)
                            sql = f"UPDATE products SET {', '.join(sets)} WHERE id=?"
                            cur.execute(sql, vals)
                            applied += 1
                except Exception as e:
                    print(f"[SYNC] Product sync error: {e}")

            if entity_type == 'setting' and action_type in ('create', 'update'):
                key = str(payload.get('key') or payload.get('name') or payload.get('setting') or '').strip()
                value = str(payload.get('value') or payload.get('val') or '').strip()
                if not key:
                    continue
                incoming_dt = _parse_dt_maybe(ev.get('created_at'))
                try:
                    cur.execute('SELECT value, updated_at FROM settings WHERE key = ? LIMIT 1', (key,))
                    ex = cur.fetchone()
                except Exception:
                    ex = None

                if ex:
                    try:
                        ex_value = str(ex.get('value') if isinstance(ex, dict) else ex['value'])
                    except Exception:
                        try:
                            ex_value = str(ex[0])
                        except Exception:
                            ex_value = ''
                    try:
                        ex_updated_at = (ex.get('updated_at') if isinstance(ex, dict) else ex['updated_at'])
                    except Exception:
                        try:
                            ex_updated_at = ex[1]
                        except Exception:
                            ex_updated_at = None
                    existing_dt = _parse_dt_maybe(ex_updated_at)
                    # Prefer newer action time; if cannot parse, default to applying incoming
                    if incoming_dt and existing_dt and incoming_dt < existing_dt and ex_value != value:
                        # keep existing newer value
                        if event_id:
                            _mark_event_applied(conn, event_id)
                        continue

                try:
                    cur.execute(
                        'INSERT INTO settings (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) '
                        'ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP',
                        (key, value)
                    )
                except Exception:
                    try:
                        cur.execute('UPDATE settings SET value = ?, updated_at = CURRENT_TIMESTAMP WHERE key = ?', (value, key))
                        if cur.rowcount == 0:
                            cur.execute('INSERT INTO settings (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)', (key, value))
                    except Exception:
                        pass
                applied += 1
            
            # Handle message entities
            table_map = {
                'static_message': 'static_messages',
                'threshold_message': 'threshold_messages',
                'news_item': 'news_items',
                'ads_item': 'ads_items',
                'student_message': 'student_messages',
                'time_bonus_given': 'time_bonus_given'
            }
            
            if entity_type in table_map:
                table = table_map[entity_type]
                eid = int(entity_id or '0')
                if action_type == 'delete':
                    cur.execute(f"DELETE FROM {table} WHERE id = ?", (eid,))
                    applied += 1
                elif action_type in ('create', 'update'):
                    # We use _replace_rows_local for convenience if payload matches columns
                    # Payload usually contains all fields from the API save
                    # We construct a single row list
                    row = dict(payload)
                    row['id'] = eid # Ensure ID is set
                    _replace_rows_local(conn, table, [row])
                    applied += 1

            if event_id:
                _mark_event_applied(conn, event_id)
        except Exception:
            pass
    conn.commit()
    return applied


def run_once(db_path: str, push_url: str, *, api_key: str = '', tenant_id: str = '', station_id: str = '', limit: int = DEFAULT_BATCH_SIZE) -> bool:
    conn = _connect(db_path)
    try:
        changes = fetch_pending_changes(conn, limit=limit)
        if not changes:
            print('[SYNC] No changes to send')
            return True
        try:
            types = {}
            for c in changes:
                t = str(c.get('entity_type') or '').strip() or 'unknown'
                types[t] = int(types.get(t, 0)) + 1
            types_txt = ', '.join([f"{k}:{v}" for k, v in sorted(types.items(), key=lambda kv: (-kv[1], kv[0]))])
            print(f"[SYNC] Pending summary: {types_txt}")
            last = changes[-1] if changes else {}
            print(f"[SYNC] Last change: id={last.get('id')} type={last.get('entity_type')} action={last.get('action_type')} entity_id={last.get('entity_id')}")
        except Exception:
            pass
        ok = push_changes(push_url, changes, api_key=api_key, tenant_id=tenant_id, station_id=station_id)
        if ok:
            print(f"[SYNC] Sent {len(changes)} change(s) OK")
            ids = [int(c.get('id') or 0) for c in changes if int(c.get('id') or 0) > 0]
            mark_changes_synced(conn, ids)
        else:
            print(f"[SYNC] Failed to send {len(changes)} change(s)")
        return ok
    finally:
        conn.close()


def _print_pending(db_path: str, *, limit: int = 20, include_synced: bool = False) -> None:
    conn = _connect(db_path)
    try:
        cur = conn.cursor()
        where = '' if include_synced else 'WHERE synced_at IS NULL'
        cur.execute(
            f"""
            SELECT id, entity_type, entity_id, action_type, created_at, synced_at, payload_json
              FROM change_log
              {where}
              ORDER BY id DESC
              LIMIT ?
            """,
            (int(limit),)
        )
        rows = cur.fetchall() or []
        if not rows:
            print('[CHANGES] No rows')
            return
        print(f"[CHANGES] Showing {len(rows)} row(s) (db={db_path})")
        for r in rows:
            payload = (r['payload_json'] or '')
            payload_snip = payload[:200].replace('\n', ' ') if payload else ''
            print(
                f"{r['id']} | {r['entity_type']} | {r['action_type']} | {r['entity_id'] or ''} | created={r['created_at']} | synced={r['synced_at'] or ''} | {payload_snip}"
            )
    finally:
        conn.close()


def main_loop(interval_sec: int = 60, db_path: Optional[str] = None, push_url: Optional[str] = None) -> None:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    cfg = _load_config(base_dir)
    db_path = db_path or _resolve_db_path(base_dir, cfg)
    push_url = push_url or str(cfg.get('sync_push_url') or DEFAULT_PUSH_URL).strip()
    api_key = str(cfg.get('sync_api_key') or '').strip()
    tenant_id = str(cfg.get('sync_tenant_id') or '').strip()
    station_id = str(cfg.get('sync_station_id') or '').strip()
    pull_url = _pull_url_from_push(push_url, cfg)

    snapshot_url = _snapshot_url_from_push(push_url, cfg)
    try:
        force_bootstrap = str(cfg.get('sync_bootstrap_force') or '').strip() in ('1', 'true', 'yes')
    except Exception:
        force_bootstrap = False

    if not _acquire_db_lock(base_dir, str(db_path)):
        return

    # Bootstrap full sync for a new machine (once)
    try:
        conn0 = _connect(str(db_path))
        try:
            _ensure_sync_state(conn0)
            done = str(_get_sync_state(conn0, 'bootstrap_snapshot_done', '0') or '0').strip()
            should_run = force_bootstrap or (done != '1')
            if should_run and tenant_id and api_key and snapshot_url:
                if force_bootstrap or _is_db_empty_for_bootstrap(conn0):
                    print(f"[BOOTSTRAP] Pulling full snapshot from cloud...")
                    resp = pull_snapshot(snapshot_url, api_key=api_key, tenant_id=tenant_id)
                    if isinstance(resp, dict) and resp.get('ok'):
                        try:
                            res = apply_snapshot(conn0, resp)
                            print(f"[BOOTSTRAP] Applied snapshot (teachers={res.get('tables',{}).get('teachers',0)} students={res.get('tables',{}).get('students',0)})")
                            _set_sync_state(conn0, 'bootstrap_snapshot_done', '1')
                        except Exception as e:
                            print(f"[BOOTSTRAP] Apply snapshot failed: {e}")
                    else:
                        print('[BOOTSTRAP] Snapshot pull failed')
                else:
                    print('[BOOTSTRAP] Skipped (local DB not empty)')
                    _set_sync_state(conn0, 'bootstrap_snapshot_done', '1')
        finally:
            conn0.close()
    except Exception:
        pass

    last_file_sync = 0.0
    pull_enabled = bool(pull_url and api_key and tenant_id)
    try:
        print(f"[CFG] tenant_id={tenant_id or '-'} station_id={station_id or '-'} push_url={'set' if bool(push_url) else '-'} pull_url={'set' if bool(pull_url) else '-'} pull_enabled={1 if pull_enabled else 0}")
    except Exception:
        pass
    backoff = 0

    while True:
        # --- FILE SYNC (Every 5 minutes) ---
        try:
            now = time.time()
            if push_url and api_key and tenant_id:
                if now - last_file_sync > 300:
                    try:
                        print("[FILE-SYNC] Starting file sync cycle...")
                        assets_base = os.path.dirname(str(db_path))
                        sync_files_cycle(str(push_url), str(api_key), str(tenant_id), str(assets_base))
                        last_file_sync = now
                    except Exception as e:
                        print(f"[FILE-SYNC] Errors {e}")
        except Exception:
            pass
        # -----------------------------------

        conn = _connect(db_path)
        try:
            _ensure_change_log(conn)
            _ensure_sync_state(conn)
            since_id_s = _get_sync_state(conn, 'pull_since_id', '0')
            try:
                since_id = int(str(since_id_s or '0').strip() or '0')
            except Exception:
                since_id = 0

            # 1) pull from cloud
            pull_ok = True
            if pull_url and api_key and tenant_id:
                resp = pull_changes(pull_url, api_key=api_key, tenant_id=tenant_id, since_id=since_id)
                if isinstance(resp, dict) and resp.get('ok'):
                    items = resp.get('items') or []
                    if isinstance(items, list):
                        applied = apply_pull_events(conn, items)
                    else:
                        applied = 0
                    next_since = resp.get('next_since_id')
                    try:
                        next_since_i = int(next_since or since_id)
                    except Exception:
                        next_since_i = since_id
                    items_count = (len(items) if isinstance(items, list) else 0)
                    if next_since_i != since_id:
                        _set_sync_state(conn, 'pull_since_id', str(next_since_i))
                        print(f"[PULL] OK items={items_count} applied={applied} since_id={since_id} -> {next_since_i}")
                    else:
                        print(f"[PULL] OK items={items_count} applied={applied} since_id={since_id}")
                else:
                    pull_ok = False
            else:
                try:
                    if not pull_url:
                        print('[PULL] Skipped (missing pull_url)')
                    elif not tenant_id:
                        print('[PULL] Skipped (missing tenant_id)')
                    elif not api_key:
                        print('[PULL] Skipped (missing api_key)')
                except Exception:
                    pass

            # 2) push local changes
            push_ok = True
            if push_url and api_key and tenant_id:
                push_ok = run_once(db_path, push_url, api_key=api_key, tenant_id=tenant_id, station_id=station_id)

            if pull_ok and push_ok:
                backoff = 0
            else:
                backoff = min(300, max(5, backoff * 2 if backoff else 5))
        finally:
            conn.close()

        sleep_s = max(5, int(interval_sec))
        if backoff:
            sleep_s = max(sleep_s, int(backoff))
        time.sleep(sleep_s)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description='SchoolPoints Sync Agent')
    p.add_argument('--once', action='store_true', help='Run one change-log push iteration and exit')
    p.add_argument('--snapshot', action='store_true', help='Send a full snapshot (teachers+students) and exit')
    p.add_argument('--show-pending', action='store_true', help='Print pending changes in change_log and exit')
    p.add_argument('--show-all-changes', action='store_true', help='Print recent changes (including synced) and exit')
    p.add_argument('--limit', default=20, type=int, help='Limit for --show-pending/--show-all-changes (default: 20)')
    p.add_argument('--interval-sec', default=60, type=int, help='Sync loop interval in seconds (default: 60)')
    p.add_argument('--db-path', default=None, help='Override DB path')
    p.add_argument('--push-url', default=None, help='Override push URL (/sync/push)')
    p.add_argument('--snapshot-url', default=None, help='Override snapshot URL (/sync/snapshot)')
    return p.parse_args()


if __name__ == '__main__':
    args = _parse_args()
    base_dir = os.path.dirname(os.path.abspath(__file__))
    cfg = _load_config(base_dir)
    db_path = args.db_path or _resolve_db_path(base_dir, cfg)
    api_key = str(cfg.get('sync_api_key') or cfg.get('api_key') or cfg.get('sync_key') or '').strip()
    tenant_id = str(cfg.get('sync_tenant_id') or '').strip()
    station_id = str(cfg.get('sync_station_id') or '').strip()

    if not _acquire_db_lock(base_dir, str(db_path)):
        raise SystemExit(2)

    if args.show_pending:
        _print_pending(db_path, limit=int(args.limit or 20), include_synced=False)
    elif args.show_all_changes:
        _print_pending(db_path, limit=int(args.limit or 20), include_synced=True)
    elif args.snapshot:
        snapshot_url = args.snapshot_url or str(cfg.get('sync_snapshot_url') or '').strip()
        if not snapshot_url:
            base = str(cfg.get('sync_push_url') or '').strip()
            if base.endswith('/sync/push'):
                snapshot_url = base[:-len('/sync/push')] + '/sync/snapshot'
        conn = _connect(db_path)
        try:
            snap = build_snapshot(conn)
        finally:
            conn.close()
        print(f"[SNAPSHOT] Teachers: {len(snap.get('teachers') or [])} | Students: {len(snap.get('students') or [])}")
        ok = push_snapshot(snapshot_url, snap, api_key=api_key, tenant_id=tenant_id, station_id=station_id)
        print('[SNAPSHOT] OK' if ok else '[SNAPSHOT] FAILED')
    elif args.once:
        push_url = args.push_url or str(cfg.get('sync_push_url') or DEFAULT_PUSH_URL).strip()
        ok = run_once(db_path, push_url, api_key=api_key, tenant_id=tenant_id, station_id=station_id)
        print('[SYNC] OK' if ok else '[SYNC] FAILED')
    else:
        main_loop(interval_sec=max(5, int(args.interval_sec or 60)))
