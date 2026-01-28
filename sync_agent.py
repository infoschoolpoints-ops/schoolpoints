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
from typing import List, Dict, Any, Optional

try:
    from database import Database
except Exception:
    Database = None


DEFAULT_PUSH_URL = ""
DEFAULT_BATCH_SIZE = 200
DEFAULT_PULL_LIMIT = 500


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _load_config(base_dir: str) -> Dict[str, Any]:
    cfg_path = os.path.join(base_dir, 'config.json')
    if os.path.exists(cfg_path):
        try:
            with open(cfg_path, 'r', encoding='utf-8') as f:
                return json.load(f) or {}
        except Exception:
            return {}
    return {}


def _default_db_path(base_dir: str, cfg: Dict[str, Any]) -> str:
    try:
        if cfg.get('db_path'):
            return str(cfg.get('db_path'))
        shared = cfg.get('shared_folder') or cfg.get('network_root')
        if shared:
            return os.path.join(shared, 'school_points.db')
    except Exception:
        pass

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
            'api_key': str(api_key or '')
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
                   id_number, photo_number, private_message, created_at, updated_at
              FROM students
            ORDER BY id ASC
            """
        )
    except Exception:
        students = []
    return {
        'teachers': teachers,
        'students': students,
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
            'api_key': str(api_key or '')
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
            'api_key': str(api_key or '')
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
                new_points = int(payload.get('new_points') or 0)
                cur.execute('UPDATE students SET points = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?', (int(new_points), int(sid)))
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

    backoff = 0

    while True:
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
                    if next_since_i != since_id:
                        _set_sync_state(conn, 'pull_since_id', str(next_since_i))
                    if applied:
                        print(f"[PULL] Applied {applied} event(s)")
                else:
                    pull_ok = False

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
