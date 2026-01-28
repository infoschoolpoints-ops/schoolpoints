"""Cloud Sync Service (minimal skeleton)

Run locally:
  pip install -r cloud_service/requirements.txt
  uvicorn cloud_service.app:app --host 0.0.0.0 --port 8000
"""
from typing import Dict, Any, List
import os
import sys
import sqlite3
import csv
import io
import json
import secrets
import hashlib
import hmac
import shutil

try:
    import psycopg2
    import psycopg2.extras
except Exception:
    psycopg2 = None  # type: ignore[assignment]
    psycopg2_extras = None  # type: ignore[assignment]
from fastapi import FastAPI, Header, HTTPException, Form, Query, Request
from fastapi.responses import HTMLResponse, Response, RedirectResponse, FileResponse
from pydantic import BaseModel

app = FastAPI(title="SchoolPoints Sync")


@app.get("/", include_in_schema=False)
def root() -> Response:
    return RedirectResponse(url="/web/login", status_code=302)

APP_BUILD_TAG = "2026-01-28-managed-postgres"


@app.get("/health", include_in_schema=False)
def health() -> Dict[str, Any]:
    return {
        "ok": True,
        "build": APP_BUILD_TAG,
    }

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
DATA_DIR = str(os.getenv('CLOUD_DATA_DIR') or '').strip() or os.path.join(BASE_DIR, 'data')
DB_PATH = os.path.join(DATA_DIR, 'cloud.db')
DATABASE_URL = str(os.getenv('DATABASE_URL') or '').strip()
USE_POSTGRES = bool(DATABASE_URL)

if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

try:
    from database import Database
except Exception:
    Database = None


def _db():
    if USE_POSTGRES:
        if psycopg2 is None:
            raise RuntimeError('DATABASE_URL is set but psycopg2 is not installed')
        return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _sql_placeholder(sql: str) -> str:
    if not USE_POSTGRES:
        return sql
    return sql.replace('?', '%s')


def _integrity_errors():
    errs = [sqlite3.IntegrityError]
    try:
        if psycopg2 is not None:
            errs.append(psycopg2.IntegrityError)  # type: ignore[attr-defined]
    except Exception:
        pass
    return tuple(errs)


def _now_expr() -> str:
    return 'CURRENT_TIMESTAMP'


def _tenant_schema(tenant_id: str) -> str:
    safe = ''.join([c for c in str(tenant_id or '').strip().lower() if (c.isalnum() or c == '_')])
    if not safe:
        safe = 'unknown'
    if safe[0].isdigit():
        safe = f"t_{safe}"
    return f"tenant_{safe}"


def _load_local_config() -> Dict[str, Any]:
    cfg_path = os.path.join(ROOT_DIR, 'config.json')
    if not os.path.exists(cfg_path):
        return {}
    try:
        with open(cfg_path, 'r', encoding='utf-8') as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _current_tenant_id() -> str:
    cfg = _load_local_config()
    return str(cfg.get('sync_tenant_id') or '').strip()


def _institutions() -> List[Dict[str, Any]]:
    conn = _db()
    cur = conn.cursor()
    cur.execute('SELECT tenant_id, name, api_key FROM institutions ORDER BY name')
    rows = cur.fetchall() or []
    conn.close()
    return [dict(r) for r in rows]


def _tenant_guard(tenant_id: str) -> bool:
    active = _current_tenant_id()
    if not active:
        return True
    return str(tenant_id or '').strip() == active


def _sync_status_info() -> Dict[str, Any]:
    conn = _db()
    cur = conn.cursor()
    cur.execute('SELECT COUNT(*) AS total FROM changes')
    row = cur.fetchone() or {}
    changes_total = int((row.get('total') if isinstance(row, dict) else row[0]) or 0)
    cur.execute('SELECT COUNT(*) AS total FROM institutions')
    row = cur.fetchone() or {}
    inst_total = int((row.get('total') if isinstance(row, dict) else row[0]) or 0)
    cur.execute('SELECT MAX(received_at) AS last_received FROM changes')
    row = cur.fetchone() or {}
    last_received = (row.get('last_received') if isinstance(row, dict) else row[0])
    conn.close()
    return {
        'changes_total': changes_total,
        'inst_total': inst_total,
        'last_received': last_received or '—',
    }


def _admin_status_bar() -> str:
    status = _sync_status_info()
    tenant_id = _current_tenant_id() or '—'
    return (
        f"<div style=\"font-size:12px;color:#637381;margin:0 0 10px;\">"
        f"Tenant: {tenant_id} | מוסדות: {status['inst_total']} | שינויים: {status['changes_total']} | שינוי אחרון: {status['last_received']}"
        f"</div>"
    )


def _admin_expected_key() -> str:
    return str(os.getenv('ADMIN_KEY') or '').strip()


def _admin_key_from_request(request: Request, admin_key: str) -> str:
    if admin_key:
        return str(admin_key)
    try:
        return str(request.cookies.get('admin_key') or '')
    except Exception:
        return ''


def _admin_require(request: Request, admin_key: str) -> Response | None:
    expected = _admin_expected_key()
    if not expected:
        return None
    provided = _admin_key_from_request(request, admin_key).strip()
    if provided != expected:
        return RedirectResponse(url="/admin/login", status_code=302)
    return None


@app.get('/admin/login', response_class=HTMLResponse)
def admin_login_form() -> str:
    return """
    <!doctype html>
    <html lang="he">
    <head>
      <meta charset="utf-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      <title>Admin Login</title>
      <style>
        body { margin:0; font-family: Arial, sans-serif; background:#f2f5f6; color:#1f2d3a; direction: rtl; }
        .wrap { max-width: 520px; margin: 30px auto; padding: 0 16px; }
        .card { background:#fff; border-radius:14px; padding:20px; border:1px solid #e1e8ee; }
        label { display:block; margin:10px 0 6px; font-weight:600; }
        input { width:100%; padding:10px; border:1px solid #d9e2ec; border-radius:8px; }
        button { margin-top:14px; padding:10px 16px; border:none; border-radius:8px; background:#1abc9c; color:#fff; font-weight:600; cursor:pointer; }
        .hint { margin-top:10px; font-size:12px; color:#637381; }
      </style>
    </head>
    <body>
      <div class="wrap">
        <div class="card">
          <h2>כניסת מנהל</h2>
          <form method="post" action="/admin/login">
            <label>Admin Key</label>
            <input name="admin_key" type="password" required />
            <button type="submit">כניסה</button>
          </form>
          <div class="hint">build: """ + APP_BUILD_TAG + """</div>
        </div>
      </div>
    </body>
    </html>
    """


@app.post('/admin/login')
def admin_login_submit(admin_key: str = Form(...)) -> Response:
    expected = _admin_expected_key()
    if expected and str(admin_key or '').strip() != expected:
        return HTMLResponse("<h3>Invalid admin key</h3>")
    resp = RedirectResponse(url="/admin/institutions", status_code=302)
    resp.set_cookie('admin_key', str(admin_key or '').strip(), httponly=True, samesite='lax', max_age=60 * 60 * 24 * 30)
    return resp


@app.get('/admin/logout')
def admin_logout() -> Response:
    resp = RedirectResponse(url="/admin/login", status_code=302)
    resp.delete_cookie('admin_key')
    return resp


def _web_auth_enabled() -> bool:
    return True


def _web_auth_credentials() -> Dict[str, str]:
    return {
        'user': str(os.getenv('WEB_ADMIN_USER') or 'admin').strip(),
        'pass': str(os.getenv('WEB_ADMIN_PASSWORD') or 'admin').strip(),
    }


def _web_auth_ok(request: Request) -> bool:
    if not _web_auth_enabled():
        return True
    return bool(request.cookies.get('web_user'))


def _web_tenant_from_cookie(request: Request) -> str:
    return str(request.cookies.get('web_tenant') or '').strip()


def _web_teacher_from_cookie(request: Request) -> str:
    return str(request.cookies.get('web_teacher') or '').strip()


def _web_require_login(request: Request) -> Response | None:
    if _web_auth_ok(request):
        return None
    return RedirectResponse(url="/web/login", status_code=302)


def _web_require_tenant(request: Request) -> Response | None:
    tenant_id = _web_tenant_from_cookie(request)
    if tenant_id:
        return None
    return RedirectResponse(url="/web/signin", status_code=302)


def _web_require_teacher(request: Request) -> Response | None:
    tenant_guard = _web_require_tenant(request)
    if tenant_guard:
        return tenant_guard
    if _web_teacher_from_cookie(request):
        return None
    return RedirectResponse(url="/web/teacher-login", status_code=302)


@app.get("/web/build")
def web_build() -> Dict[str, Any]:
    routes = []
    for r in getattr(app, "routes", []) or []:
        path = getattr(r, "path", None)
        if path:
            routes.append(path)
    routes = sorted(set(routes))
    return {
        "build": APP_BUILD_TAG,
        "routes": routes,
    }


def _read_text_file(path: str) -> str:
    if not path or not os.path.isfile(path):
        return ""
    for enc in ("utf-8", "utf-8-sig", "cp1255", "windows-1255", "latin-1"):
        try:
            with open(path, 'r', encoding=enc) as f:
                return f.read()
        except Exception:
            continue
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()
    except Exception:
        return ""


def _public_web_shell(title: str, body_html: str) -> str:
    footer = """
      <div style="margin-top:18px; padding-top:14px; border-top:1px solid var(--line); display:flex; gap:12px; flex-wrap:wrap; justify-content:space-between; align-items:center;">
        <div style="font-size:13px; color:#637381;">
          <div style="font-weight:800; color:#1f2d3a;">אזור אישי</div>
          <div id="whoami" style="margin-top:4px;">
            <a href="/web/signin" style="color:#1f2d3a; text-decoration:none; font-weight:700;">התחברות</a>
          </div>
        </div>
        <div class="actionbar" style="justify-content:flex-end; margin-top:0;">
          <a class="blue" href="/web/login">דף הבית</a>
          <a class="gray" href="javascript:history.back()">אחורה</a>
        </div>
      </div>
      <script>
        (async function() {
          const el = document.getElementById('whoami');
          if (!el) return;
          try {
            const resp = await fetch('/web/whoami', { credentials: 'same-origin' });
            if (!resp.ok) return;
            const data = await resp.json();
            if (!data || !data.tenant_id) return;
            const name = (data.institution_name || data.tenant_id || '').toString();
            el.innerHTML = `
              <div style="display:flex; gap:10px; align-items:center; flex-wrap:wrap;">
                <span style="font-weight:800; color:#1f2d3a;">${name}</span>
                <a href="/web/account" style="color:#1f2d3a; text-decoration:none; font-weight:700;">תפריט מוסד</a>
                <a href="/web/logout" style="color:#1f2d3a; text-decoration:none; font-weight:700;">יציאה</a>
              </div>
            `;
          } catch (e) {
          }
        })();
      </script>
    """
    return f"""
    <!doctype html>
    <html lang="he">
    <head>
      <meta charset="utf-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      <title>{title}</title>
      <link rel="icon" href="/web/assets/icons/public.png" />
      <style>
        :root {{ --navy:#2f3e4e; --mint:#1abc9c; --sky:#3498db; --bg:#eef2f4; --line:#d6dde3; --tab:#ecf0f1; }}
        body {{ margin:0; font-family: "Segoe UI", Arial, sans-serif; background:var(--bg); color:#1f2d3a; direction: rtl; }}
        .wrap {{ max-width: 980px; margin: 24px auto; padding: 0 16px; }}
        .card {{ background:#fff; border-radius:10px; padding:20px; border:1px solid var(--line); box-shadow:0 6px 18px rgba(40,55,70,.08); }}
        .titlebar {{ background:var(--navy); color:#fff; padding:14px 18px; border-radius:10px 10px 0 0; margin:-20px -20px 16px; }}
        .titlebar h2 {{ margin:0; font-size:20px; }}
        .actionbar {{ margin-top:14px; display:flex; gap:10px; flex-wrap:wrap; justify-content:center; }}
        .actionbar a {{ padding:10px 14px; border-radius:8px; color:#fff; text-decoration:none; border:none; font-weight:700; }}
        .actionbar .green {{ background:#2ecc71; }}
        .actionbar .blue {{ background:#3498db; }}
        .actionbar .gray {{ background:#95a5a6; }}
        .small {{ font-size:13px; color:#637381; text-align:center; margin-top:10px; }}
        .small a {{ color:#1f2d3a; }}
      </style>
    </head>
    <body>
      <div class="wrap">
        <div class="card">
          <div class="titlebar"><h2>{title}</h2></div>
          {body_html}
          {footer}
        </div>
      </div>
    </body>
    </html>
    """


def _init_db() -> None:
    conn = _db()
    cur = conn.cursor()
    if USE_POSTGRES:
        cur.execute(
            '''
            CREATE TABLE IF NOT EXISTS institutions (
                id BIGSERIAL PRIMARY KEY,
                tenant_id TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                api_key TEXT NOT NULL,
                password_hash TEXT,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
            '''
        )
        cur.execute(
            '''
            CREATE TABLE IF NOT EXISTS changes (
                id BIGSERIAL PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                station_id TEXT,
                entity_type TEXT NOT NULL,
                entity_id TEXT,
                action_type TEXT NOT NULL,
                payload_json TEXT,
                created_at TEXT,
                received_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
            '''
        )
        cur.execute(
            '''
            CREATE TABLE IF NOT EXISTS sync_events (
                id BIGSERIAL PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                station_id TEXT,
                change_local_id BIGINT,
                entity_type TEXT NOT NULL,
                entity_id TEXT,
                action_type TEXT NOT NULL,
                payload_json TEXT,
                created_at TEXT,
                received_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(tenant_id, event_id)
            )
            '''
        )
        cur.execute(
            '''
            CREATE TABLE IF NOT EXISTS contact_messages (
                id BIGSERIAL PRIMARY KEY,
                name TEXT,
                email TEXT,
                subject TEXT,
                message TEXT,
                created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
            '''
        )
    else:
        cur.execute(
            '''
            CREATE TABLE IF NOT EXISTS institutions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                api_key TEXT NOT NULL,
                password_hash TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            '''
        )
        try:
            cur.execute('ALTER TABLE institutions ADD COLUMN password_hash TEXT')
        except Exception:
            pass
        cur.execute(
            '''
            CREATE TABLE IF NOT EXISTS changes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL,
                station_id TEXT,
                entity_type TEXT NOT NULL,
                entity_id TEXT,
                action_type TEXT NOT NULL,
                payload_json TEXT,
                created_at TEXT,
                received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            '''
        )
        cur.execute(
            '''
            CREATE TABLE IF NOT EXISTS sync_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                station_id TEXT,
                change_local_id INTEGER,
                entity_type TEXT NOT NULL,
                entity_id TEXT,
                action_type TEXT NOT NULL,
                payload_json TEXT,
                created_at TEXT,
                received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(tenant_id, event_id)
            )
            '''
        )
        cur.execute(
            '''
            CREATE TABLE IF NOT EXISTS contact_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                email TEXT,
                subject TEXT,
                message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            '''
        )
    conn.commit()
    conn.close()


@app.get('/web/whoami')
def web_whoami(request: Request) -> Dict[str, Any]:
    tenant_id = _web_tenant_from_cookie(request)
    teacher_id = _web_teacher_from_cookie(request)
    inst_name = ''
    if tenant_id:
        try:
            conn = _db()
            cur = conn.cursor()
            cur.execute(_sql_placeholder('SELECT name FROM institutions WHERE tenant_id = ? LIMIT 1'), (tenant_id,))
            row = cur.fetchone() or {}
            conn.close()
            inst_name = (row.get('name') if isinstance(row, dict) else row[0]) or ''
        except Exception:
            inst_name = ''
    return {
        'tenant_id': tenant_id or '',
        'institution_name': str(inst_name or '').strip(),
        'teacher_id': teacher_id or '',
        'is_logged_in': bool(tenant_id),
        'is_teacher': bool(teacher_id),
    }


def _save_contact_message(name: str, email: str, subject: str, message: str) -> None:
    conn = _db()
    try:
        cur = conn.cursor()
        cur.execute(
            _sql_placeholder('INSERT INTO contact_messages (name, email, subject, message) VALUES (?, ?, ?, ?)'),
            (name, email, subject, message)
        )
        conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _pbkdf2_hash(password: str, salt: bytes | None = None) -> str:
    if salt is None:
        salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 200_000)
    return f"pbkdf2_sha256$200000${salt.hex()}${dk.hex()}"


def _pbkdf2_verify(password: str, hashed: str) -> bool:
    try:
        scheme, iters_s, salt_hex, dk_hex = (hashed or '').split('$', 3)
        if scheme != 'pbkdf2_sha256':
            return False
        iters = int(iters_s)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(dk_hex)
        actual = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, iters)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def _tenant_db_dir() -> str:
    path = os.path.join(DATA_DIR, 'tenants')
    os.makedirs(path, exist_ok=True)
    return path


def _tenant_school_db_path(tenant_id: str) -> str:
    safe = ''.join([c for c in str(tenant_id or '').strip() if c.isalnum() or c in ('-', '_')])
    if not safe:
        safe = 'unknown'
    return os.path.join(_tenant_db_dir(), f"{safe}.db")


def _ensure_tenant_db_exists(tenant_id: str) -> str:
    if USE_POSTGRES:
        schema = _tenant_schema(tenant_id)
        conn = _db()
        try:
            cur = conn.cursor()
            cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
            cur.execute(
                f'''
                CREATE TABLE IF NOT EXISTS "{schema}".teachers (
                    id BIGINT PRIMARY KEY,
                    name TEXT,
                    card_number TEXT,
                    card_number2 TEXT,
                    card_number3 TEXT,
                    is_admin INTEGER DEFAULT 0,
                    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                )
                '''
            )
            cur.execute(
                f'''
                CREATE TABLE IF NOT EXISTS "{schema}".students (
                    id BIGINT PRIMARY KEY,
                    first_name TEXT,
                    last_name TEXT,
                    class_name TEXT,
                    points INTEGER DEFAULT 0,
                    card_number TEXT,
                    id_number TEXT,
                    serial_number BIGINT,
                    photo_number BIGINT,
                    private_message TEXT,
                    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                )
                '''
            )
            cur.execute(
                f'''
                CREATE TABLE IF NOT EXISTS "{schema}".settings (
                    "key" TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                )
                '''
            )
            cur.execute(
                f'''
                CREATE TABLE IF NOT EXISTS "{schema}".points_log (
                    id BIGSERIAL PRIMARY KEY,
                    student_id BIGINT,
                    old_points INTEGER,
                    new_points INTEGER,
                    delta INTEGER,
                    reason TEXT,
                    actor_name TEXT,
                    action_type TEXT,
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                )
                '''
            )
            conn.commit()
            return schema
        except Exception as e:
            try:
                print(f"[TENANT-DB] ensure failed tenant={tenant_id} schema={schema}: {e}", file=sys.stderr)
            except Exception:
                pass
            raise
        finally:
            try:
                conn.close()
            except Exception:
                pass

    dst = _tenant_school_db_path(tenant_id)
    if os.path.isfile(dst):
        return dst
    template = _school_db_path()
    try:
        if os.path.isfile(template):
            shutil.copyfile(template, dst)
            return dst
    except Exception:
        pass
    # minimal fallback
    conn = sqlite3.connect(dst)
    cur = conn.cursor()
    cur.execute(
        '''
        CREATE TABLE IF NOT EXISTS teachers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            card_number TEXT,
            card_number2 TEXT,
            card_number3 TEXT,
            is_admin INTEGER DEFAULT 0
        )
        '''
    )
    cur.execute(
        '''
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            first_name TEXT,
            last_name TEXT,
            class_name TEXT,
            points INTEGER DEFAULT 0,
            card_number TEXT,
            id_number TEXT,
            serial_number INTEGER,
            photo_number INTEGER,
            private_message TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        '''
    )
    conn.commit()
    conn.close()
    return dst


def _school_db_path() -> str:
    if Database is not None:
        try:
            return Database().db_path
        except Exception:
            pass
    return os.path.join(ROOT_DIR, 'school_points.db')


def _school_db() -> sqlite3.Connection:
    db_path = _school_db_path()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _tenant_school_db(tenant_id: str):
    if USE_POSTGRES:
        schema = _ensure_tenant_db_exists(tenant_id)
        conn = _db()
        cur = conn.cursor()
        cur.execute(f'SET search_path TO "{schema}", public')
        return conn
    db_path = _ensure_tenant_db_exists(tenant_id)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


@app.on_event("startup")
def _startup() -> None:
    _init_db()


class ChangeItem(BaseModel):
    id: int
    entity_type: str
    entity_id: str | None = None
    action_type: str
    payload_json: str | None = None
    created_at: str | None = None


class SyncPushRequest(BaseModel):
    tenant_id: str
    station_id: str | None = None
    changes: List[ChangeItem]


class SnapshotPayload(BaseModel):
    tenant_id: str
    station_id: str | None = None
    teachers: List[Dict[str, Any]] = []
    students: List[Dict[str, Any]] = []


class StudentUpdatePayload(BaseModel):
    student_id: int
    points: int | None = None
    private_message: str | None = None


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default


def _safe_str(v: Any) -> str:
    try:
        return str(v)
    except Exception:
        return ''


def _make_event_id(station_id: str | None, local_id: int | None, created_at: str | None) -> str:
    sid = _safe_str(station_id).strip() or 'unknown'
    lid = _safe_int(local_id, 0)
    ca = _safe_str(created_at).strip()
    if lid:
        return f"{sid}:{lid}"
    if ca:
        return f"{sid}:{ca}"
    return f"{sid}:{secrets.token_hex(8)}"


def _get_api_key(request: Request, api_key: str) -> str:
    if api_key:
        return str(api_key)
    try:
        # accept both conventions
        return str(request.headers.get('api_key') or request.headers.get('api-key') or '')
    except Exception:
        return ''


def _apply_change_to_tenant_db(tconn, ch: Dict[str, Any]) -> None:
    et = str(ch.entity_type or '').strip()
    at = str(ch.action_type or '').strip()
    payload = {}
    try:
        payload = json.loads(ch.payload_json or '{}') if (ch.payload_json is not None) else {}
    except Exception:
        payload = {}

    if et == 'student_points' and at == 'update':
        student_id = _safe_int(ch.entity_id, 0)
        if student_id <= 0:
            return
        old_points = _safe_int(payload.get('old_points'), 0)
        new_points = _safe_int(payload.get('new_points'), 0)
        delta = int(new_points - old_points)
        reason = _safe_str(payload.get('reason') or '').strip()

        cur = tconn.cursor()
        cur.execute(_sql_placeholder('SELECT points FROM students WHERE id = ? LIMIT 1'), (student_id,))
        row = cur.fetchone()
        if not row:
            return
        if isinstance(row, dict):
            cur_points = _safe_int(row.get('points'), 0)
        else:
            try:
                cur_points = _safe_int(row['points'], 0)
            except Exception:
                cur_points = _safe_int(row[0], 0)
        final_points = int(cur_points + delta)
        cur.execute(
            _sql_placeholder('UPDATE students SET points = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?'),
            (final_points, student_id)
        )
        try:
            cur.execute(
                _sql_placeholder(
                    '''
                    INSERT INTO points_log (student_id, old_points, new_points, delta, reason, actor_name, action_type)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    '''
                ),
                (int(student_id), int(cur_points), int(final_points), int(delta), reason, 'sync', 'sync')
            )
        except Exception:
            pass
        return

    if et == 'setting':
        key = _safe_str(payload.get('key') or payload.get('name') or payload.get('setting') or '').strip()
        value = _safe_str(payload.get('value') or payload.get('val') or '').strip()
        if not key:
            return
        cur = tconn.cursor()
        try:
            cur.execute(
                _sql_placeholder(
                    '''
                    INSERT INTO settings ("key", value) VALUES (?, ?)
                    ON CONFLICT("key") DO UPDATE SET value = EXCLUDED.value
                    '''
                ),
                (key, value)
            )
        except Exception:
            try:
                cur.execute(_sql_placeholder('UPDATE settings SET value = ? WHERE "key" = ?'), (value, key))
                if cur.rowcount == 0:
                    cur.execute(_sql_placeholder('INSERT INTO settings ("key", value) VALUES (?, ?)'), (key, value))
            except Exception:
                pass
        return


def _replace_rows_postgres(conn, table: str, rows: List[Dict[str, Any]]) -> int:
    cur = conn.cursor()
    cur.execute(f'TRUNCATE TABLE {table}')
    if not rows:
        return 0

    existing_cols = _table_columns_postgres(conn, table)
    if not existing_cols:
        return 0
    allowed = set(existing_cols)
    allowed.discard('created_at')
    allowed.discard('updated_at')

    cols = [c for c in list((rows[0] or {}).keys()) if c in allowed]
    if not cols:
        cols = [c for c in existing_cols if c in allowed]
    if not cols:
        return 0

    template = '(' + ','.join(['%s'] * len(cols)) + ')'
    values = [[(r or {}).get(c) for c in cols] for r in rows]
    psycopg2.extras.execute_values(
        cur,
        f'INSERT INTO {table} ({",".join(cols)}) VALUES %s',
        values,
        template=template,
        page_size=500
    )
    return int(len(values))


def _begin_tenant_write(conn) -> None:
    if USE_POSTGRES:
        return
    try:
        conn.execute('BEGIN IMMEDIATE')
    except Exception:
        pass


@app.post("/sync/push")
def sync_push(payload: SyncPushRequest, request: Request, api_key: str = Header(default="")) -> Dict[str, Any]:
    if not payload.tenant_id:
        raise HTTPException(status_code=400, detail="missing tenant_id")
    api_key = _get_api_key(request, api_key).strip()
    if not api_key:
        raise HTTPException(status_code=401, detail="missing api_key")

    conn = _db()
    cur = conn.cursor()
    cur.execute(
        _sql_placeholder('SELECT id FROM institutions WHERE tenant_id = ? AND api_key = ? LIMIT 1'),
        (payload.tenant_id, api_key)
    )
    row = cur.fetchone()
    if not row:
        allow_auto = str(os.getenv('AUTO_CREATE_TENANT') or '').strip() == '1'
        if allow_auto:
            try:
                cur.execute(
                    _sql_placeholder('INSERT INTO institutions (tenant_id, name, api_key) VALUES (?, ?, ?)'),
                    (payload.tenant_id, payload.tenant_id, api_key)
                )
                conn.commit()
                cur.execute(
                    _sql_placeholder('SELECT id FROM institutions WHERE tenant_id = ? AND api_key = ? LIMIT 1'),
                    (payload.tenant_id, api_key)
                )
                row = cur.fetchone()
            except _integrity_errors():
                row = None
        if not row:
            conn.close()
            raise HTTPException(status_code=401, detail="invalid api_key")

    applied = 0
    skipped = 0
    errors = 0

    tconn = _tenant_school_db(payload.tenant_id)
    try:
        _begin_tenant_write(tconn)

        for ch in payload.changes:
            # always record raw change
            cur.execute(
                _sql_placeholder(
                    '''
                    INSERT INTO changes (tenant_id, station_id, entity_type, entity_id, action_type, payload_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    '''
                ),
                (
                    payload.tenant_id,
                    payload.station_id,
                    ch.entity_type,
                    ch.entity_id,
                    ch.action_type,
                    ch.payload_json,
                    ch.created_at
                )
            )

            event_id = _make_event_id(payload.station_id, ch.id, ch.created_at)
            try:
                cur.execute(
                    _sql_placeholder(
                        '''
                        INSERT INTO sync_events (tenant_id, event_id, station_id, change_local_id, entity_type, entity_id, action_type, payload_json, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        '''
                    ),
                    (
                        payload.tenant_id,
                        event_id,
                        payload.station_id,
                        int(ch.id or 0),
                        ch.entity_type,
                        ch.entity_id,
                        ch.action_type,
                        ch.payload_json,
                        ch.created_at,
                    )
                )
            except _integrity_errors():
                skipped += 1
                continue
            except Exception:
                errors += 1
                continue

            try:
                _apply_change_to_tenant_db(tconn, ch)
                applied += 1
            except Exception:
                errors += 1

        conn.commit()
        tconn.commit()
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        try:
            tconn.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"sync push failed: {e}")
    finally:
        conn.close()
        tconn.close()

    return {
        "ok": True,
        "received": len(payload.changes),
        "applied": applied,
        "skipped": skipped,
        "errors": errors,
        "tenant_id": payload.tenant_id,
        "station_id": payload.station_id,
    }


def _table_columns(conn: sqlite3.Connection, table: str) -> List[str]:
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    rows = cur.fetchall() or []
    cols = []
    for r in rows:
        try:
            cols.append(str(r[1]))
        except Exception:
            try:
                cols.append(str(r['name']))
            except Exception:
                pass
    return cols


def _table_columns_postgres(conn, table: str) -> List[str]:
    try:
        cur = conn.cursor()
        cur.execute(
            _sql_placeholder(
                '''
                SELECT column_name
                  FROM information_schema.columns
                 WHERE table_schema = current_schema()
                   AND table_name = ?
                 ORDER BY ordinal_position
                '''
            ),
            (str(table),)
        )
        rows = cur.fetchall() or []
        cols: List[str] = []
        for r in rows:
            if isinstance(r, dict):
                cols.append(str(r.get('column_name') or ''))
            else:
                cols.append(str(r[0]))
        return [c for c in cols if c]
    except Exception:
        return []


def _replace_rows(conn: sqlite3.Connection, table: str, rows: List[Dict[str, Any]]) -> int:
    if USE_POSTGRES:
        return _replace_rows_postgres(conn, table, rows)
    cur = conn.cursor()
    cur.execute(f"DELETE FROM {table}")
    if not rows:
        return 0

    cols = _table_columns(conn, table)
    if not cols:
        return 0

    allowed = set(cols)
    allowed.discard('created_at')
    allowed.discard('updated_at')

    insert_cols = []
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


@app.post("/sync/snapshot")
def sync_snapshot(payload: SnapshotPayload, request: Request, api_key: str = Header(default="")) -> Dict[str, Any]:
    if not payload.tenant_id:
        raise HTTPException(status_code=400, detail="missing tenant_id")
    api_key = _get_api_key(request, api_key).strip()
    if not api_key:
        raise HTTPException(status_code=401, detail="missing api_key")

    conn = _db()
    cur = conn.cursor()
    cur.execute(
        _sql_placeholder('SELECT id FROM institutions WHERE tenant_id = ? AND api_key = ? LIMIT 1'),
        (payload.tenant_id, api_key)
    )
    row = cur.fetchone()
    if not row:
        allow_auto = str(os.getenv('AUTO_CREATE_TENANT') or '').strip() == '1'
        if allow_auto:
            try:
                cur.execute(
                    _sql_placeholder('INSERT INTO institutions (tenant_id, name, api_key) VALUES (?, ?, ?)'),
                    (payload.tenant_id, payload.tenant_id, api_key)
                )
                conn.commit()
                cur.execute(
                    _sql_placeholder('SELECT id FROM institutions WHERE tenant_id = ? AND api_key = ? LIMIT 1'),
                    (payload.tenant_id, api_key)
                )
                row = cur.fetchone()
            except _integrity_errors():
                row = None
        if not row:
            conn.close()
            raise HTTPException(status_code=401, detail="invalid api_key")
    conn.close()

    try:
        tconn = _tenant_school_db(payload.tenant_id)
    except Exception as e:
        try:
            print(f"[SNAPSHOT] open tenant db failed tenant={payload.tenant_id}: {e}", file=sys.stderr)
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"snapshot failed: cannot open tenant db: {e}")
    try:
        _begin_tenant_write(tconn)
        teachers_n = 0
        students_n = 0
        try:
            teachers_n = _replace_rows(tconn, 'teachers', payload.teachers or [])
        except Exception:
            teachers_n = 0
        try:
            students_n = _replace_rows(tconn, 'students', payload.students or [])
        except Exception:
            students_n = 0
        tconn.commit()
    except Exception as e:
        try:
            tconn.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"snapshot failed: {e}")
    finally:
        tconn.close()

    return {
        'ok': True,
        'tenant_id': payload.tenant_id,
        'station_id': payload.station_id,
        'teachers': teachers_n,
        'students': students_n,
    }


def _scalar_or_none(cur: sqlite3.Cursor) -> Any:
    row = cur.fetchone()
    if not row:
        return None
    if isinstance(row, dict):
        try:
            return list(row.values())[0]
        except Exception:
            return None
    try:
        return row[0]
    except Exception:
        try:
            return list(row)[0]
        except Exception:
            return None


@app.get('/sync/status')
def sync_status(tenant_id: str, request: Request, api_key: str = Header(default="")) -> Dict[str, Any]:
    if not tenant_id:
        raise HTTPException(status_code=400, detail='missing tenant_id')
    api_key = _get_api_key(request, api_key).strip()
    if not api_key:
        raise HTTPException(status_code=401, detail='missing api_key')

    conn = _db()
    cur = conn.cursor()
    cur.execute(
        _sql_placeholder('SELECT id FROM institutions WHERE tenant_id = ? AND api_key = ? LIMIT 1'),
        (tenant_id, api_key)
    )
    row = cur.fetchone()
    if not row:
        allow_auto = str(os.getenv('AUTO_CREATE_TENANT') or '').strip() == '1'
        if allow_auto:
            try:
                cur.execute(
                    _sql_placeholder('INSERT INTO institutions (tenant_id, name, api_key) VALUES (?, ?, ?)'),
                    (tenant_id, tenant_id, api_key)
                )
                conn.commit()
                cur.execute(
                    _sql_placeholder('SELECT id FROM institutions WHERE tenant_id = ? AND api_key = ? LIMIT 1'),
                    (tenant_id, api_key)
                )
                row = cur.fetchone()
            except _integrity_errors():
                row = None
        if not row:
            conn.close()
            raise HTTPException(status_code=401, detail='invalid api_key')
    conn.close()

    tconn = _tenant_school_db(tenant_id)
    try:
        tcur = tconn.cursor()

        teachers_count = 0
        students_count = 0
        teachers_max_updated_at = None
        students_max_updated_at = None

        try:
            tcur.execute('SELECT COUNT(*) FROM teachers')
            teachers_count = _safe_int(_scalar_or_none(tcur), 0)
        except Exception:
            teachers_count = 0
        try:
            tcur.execute('SELECT COUNT(*) FROM students')
            students_count = _safe_int(_scalar_or_none(tcur), 0)
        except Exception:
            students_count = 0

        try:
            tcur.execute('SELECT MAX(updated_at) FROM teachers')
            teachers_max_updated_at = _scalar_or_none(tcur)
        except Exception:
            teachers_max_updated_at = None
        try:
            tcur.execute('SELECT MAX(updated_at) FROM students')
            students_max_updated_at = _scalar_or_none(tcur)
        except Exception:
            students_max_updated_at = None

    finally:
        tconn.close()

    cconn = _db()
    try:
        ccur = cconn.cursor()
        events_count = 0
        events_last_created_at = None
        try:
            ccur.execute(_sql_placeholder('SELECT COUNT(*) FROM sync_events WHERE tenant_id = ?'), (tenant_id,))
            events_count = _safe_int(_scalar_or_none(ccur), 0)
        except Exception:
            events_count = 0
        try:
            ccur.execute(_sql_placeholder('SELECT MAX(created_at) FROM sync_events WHERE tenant_id = ?'), (tenant_id,))
            events_last_created_at = _scalar_or_none(ccur)
        except Exception:
            events_last_created_at = None
    finally:
        cconn.close()

    return {
        'ok': True,
        'tenant_id': tenant_id,
        'teachers_count': teachers_count,
        'students_count': students_count,
        'teachers_max_updated_at': teachers_max_updated_at,
        'students_max_updated_at': students_max_updated_at,
        'events_count': events_count,
        'events_last_created_at': events_last_created_at,
    }


@app.get("/admin/setup", response_class=HTMLResponse)
def admin_setup_form(request: Request, admin_key: str = '') -> str:
    guard = _admin_require(request, admin_key)
    if guard:
        return guard  # type: ignore[return-value]
    return """
    <!doctype html>
    <html lang="he">
    <head>
      <meta charset="utf-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      <title>רישום מוסד - SchoolPoints</title>
      <style>
        body { margin:0; font-family: Arial, sans-serif; background:#f2f5f6; color:#1f2d3a; direction: rtl; }
        .wrap { max-width: 720px; margin: 30px auto; padding: 0 16px; }
        .card { background:#fff; border-radius:14px; padding:20px; border:1px solid #e1e8ee; }
        label { display:block; margin:10px 0 6px; font-weight:600; }
        input { width:100%; padding:10px; border:1px solid #d9e2ec; border-radius:8px; }
        button { margin-top:14px; padding:10px 16px; border:none; border-radius:8px; background:#1abc9c; color:#fff; font-weight:600; cursor:pointer; }
        .links { margin-top:16px; font-size:13px; }
        .links a { color:#1f2d3a; text-decoration:none; margin-left:10px; }
      </style>
    </head>
    <body>
      <div class="wrap">
        <div class="card">
          """ + _admin_status_bar() + """
          <h2>רישום מוסד חדש</h2>
          <form method="post">
            <label>שם מוסד</label>
            <input name="name" required />
            <label>Tenant ID</label>
            <input name="tenant_id" required />
            <label>סיסמת מוסד</label>
            <input name="institution_password" type="password" required />
            <label>API Key (אופציונלי - יווצר אוטומטית)</label>
            <input name="api_key" placeholder="השאר ריק ליצירה אוטומטית" />
            <button type="submit">צור מוסד</button>
          </form>
          <div class="links">
            <a href="/admin/setup">רישום מוסד חדש</a>
            <a href="/admin/sync-status">סטטוס סינכרון</a>
            <a href="/admin/changes">שינויים אחרונים</a>
            <a href="/admin/logout">יציאה</a>
          </div>
        </div>
      </div>
    </body>
    </html>
    """


@app.get("/__version")
def app_version() -> Dict[str, Any]:
    return {
        "build": APP_BUILD_TAG,
        "has_web_login": True,
    }


@app.get("/web/equipment-required", response_class=HTMLResponse)
def web_equipment_required() -> str:
    path = os.path.join(ROOT_DIR, 'equipment_required.html')
    html = _read_text_file(path)
    if not html:
        body = "<h2>רשימת ציוד נדרש</h2><p>העמוד עדיין לא זמין.</p>"
        return _public_web_shell("רשימת ציוד נדרש", body)
    return web_equipment_required_content()


@app.get("/web/equipment-required/content", response_class=HTMLResponse)
def web_equipment_required_content() -> str:
    path = os.path.join(ROOT_DIR, 'equipment_required.html')
    html = _read_text_file(path)
    if not html:
        body = "<h2>רשימת ציוד נדרש</h2><p>העמוד עדיין לא זמין.</p>"
        return _public_web_shell("רשימת ציוד נדרש", body)
    html = str(html)
    html = html.replace('src="equipment_required_files/', 'src="/web/assets/equipment_required_files/')
    html = html.replace("src='equipment_required_files/", "src='/web/assets/equipment_required_files/")
    if '</head>' in html:
        html = html.replace('</head>', '<link rel="icon" href="/web/assets/icons/public.png" /></head>')
    return html


@app.get("/web/download", response_class=HTMLResponse)
def web_download() -> str:
    download_url = "https://drive.google.com/drive/folders/1jM8CpSPbO0avrmNLA3MBcCPXpdC0JGxc?usp=sharing"
    body = f"""
    <div style=\"text-align:center;\">
      <div style=\"font-size:22px;font-weight:900;\">הורדת התוכנה</div>
      <div style=\"margin-top:10px;line-height:1.8;\">ההתקנה נמצאת בתיקיית Google Drive.</div>
      <div class=\"actionbar\" style=\"justify-content:center;\">
        <a class=\"green\" href=\"{download_url}\" target=\"_blank\" rel=\"noopener\">להורדה</a>
        <a class=\"blue\" href=\"/web/guide\">מדריך</a>
        <a class=\"gray\" href=\"/web/login\">חזרה</a>
      </div>
      <div class=\"small\">build: {APP_BUILD_TAG}</div>
    </div>
    """
    return _public_web_shell("הורדה", body)


@app.get("/web/account", response_class=HTMLResponse)
def web_account(request: Request) -> str:
    tenant_id = _web_tenant_from_cookie(request)
    if not tenant_id:
        return _public_web_shell("אזור אישי", "<h2>אזור אישי</h2><p>יש להתחבר כדי לצפות בפרטי המוסד.</p>")
    body = f"""
    <h2>תפריט מוסד</h2>
    <div style=\"color:#637381; margin-top:-6px;\">מוסד: <b>{tenant_id}</b></div>
    <div class=\"actionbar\" style=\"justify-content:flex-start;\">
      <a class=\"blue\" href=\"/web/account/password\">החלפת סיסמה</a>
      <a class=\"blue\" href=\"/web/account/forgot\">שכחתי סיסמה</a>
      <a class=\"blue\" href=\"/web/account/payments\">תשלומים</a>
      <a class=\"gray\" href=\"/web/admin\">ניהול</a>
    </div>
    """
    return _public_web_shell("אזור אישי", body)


@app.get("/web/account/password", response_class=HTMLResponse)
def web_account_password(request: Request) -> str:
    tenant_id = _web_tenant_from_cookie(request)
    if not tenant_id:
        return _public_web_shell("החלפת סיסמה", "<h2>החלפת סיסמה</h2><p>יש להתחבר כדי להחליף סיסמה.</p>")
    body = """
    <h2>החלפת סיסמה</h2>
    <p>מסך החלפת סיסמה יושלם כאן.</p>
    <div class=\"actionbar\" style=\"justify-content:flex-start;\">
      <a class=\"gray\" href=\"/web/account\">חזרה</a>
    </div>
    """
    return _public_web_shell("החלפת סיסמה", body)


@app.get("/web/account/forgot", response_class=HTMLResponse)
def web_account_forgot(request: Request) -> str:
    body = """
    <h2>שכחתי סיסמה</h2>
    <p>מסך שחזור סיסמה יושלם כאן.</p>
    <div class=\"actionbar\" style=\"justify-content:flex-start;\">
      <a class=\"gray\" href=\"/web/account\">חזרה</a>
    </div>
    """
    return _public_web_shell("שכחתי סיסמה", body)


@app.get("/web/account/payments", response_class=HTMLResponse)
def web_account_payments(request: Request) -> str:
    tenant_id = _web_tenant_from_cookie(request)
    if not tenant_id:
        return _public_web_shell("תשלומים", "<h2>תשלומים</h2><p>יש להתחבר כדי לצפות בתשלומים.</p>")
    body = """
    <h2>תשלומים</h2>
    <p>מסך תשלומים/רישום יושלם כאן.</p>
    <div class=\"actionbar\" style=\"justify-content:flex-start;\">
      <a class=\"gray\" href=\"/web/account\">חזרה</a>
    </div>
    """
    return _public_web_shell("תשלומים", body)


@app.get("/web/pricing", response_class=HTMLResponse)
def web_pricing() -> str:
    body = f"""
    <div style=\"text-align:center;\">
      <div style=\"font-size:22px;font-weight:900;\">תמחור</div>
      <div style=\"margin-top:8px; color:#637381; line-height:1.8;\">דף תמחור יושלם כאן. בינתיים ניתן ליצור קשר לקבלת הצעה.</div>
    </div>
    <div style=\"margin-top:16px; display:grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap:12px;\">
      <div style=\"border:1px solid var(--line); border-radius:12px; padding:14px; background:#fff;\">
        <div style=\"font-weight:900;\">בסיסי</div>
        <div style=\"margin-top:6px; color:#637381;\">עד 2 תחנות</div>
      </div>
      <div style=\"border:1px solid var(--line); border-radius:12px; padding:14px; background:#fff;\">
        <div style=\"font-weight:900;\">מורחב</div>
        <div style=\"margin-top:6px; color:#637381;\">עד 5 תחנות</div>
      </div>
      <div style=\"border:1px solid var(--line); border-radius:12px; padding:14px; background:#fff;\">
        <div style=\"font-weight:900;\">ללא הגבלה</div>
        <div style=\"margin-top:6px; color:#637381;\">מספר תחנות גבוה</div>
      </div>
    </div>
    <div class=\"actionbar\" style=\"justify-content:center;\">
      <a class=\"green\" href=\"/web/contact\">צור קשר</a>
      <a class=\"blue\" href=\"/web/signin\">כניסה</a>
    </div>
    <div class=\"small\">build: {APP_BUILD_TAG}</div>
    """
    return _public_web_shell("תמחור", body)


@app.get("/web/contact", response_class=HTMLResponse)
def web_contact() -> str:
    body = f"""
    <style>
      form {{ display:grid; grid-template-columns: 1fr; gap:10px; max-width: 560px; margin: 0 auto; }}
      label {{ font-weight:800; font-size:13px; }}
      input, textarea {{ width:100%; padding:12px; border:1px solid var(--line); border-radius:10px; font-size:15px; background:#fff; }}
      textarea {{ min-height: 140px; resize: vertical; }}
      button {{ padding:12px 16px; border:none; border-radius:10px; background:var(--mint); color:#fff; font-weight:900; cursor:pointer; font-size:15px; }}
      .hint {{ text-align:center; font-size:12px; color:#637381; margin-top:10px; }}
    </style>
    <div style=\"text-align:center;\">
      <div style=\"font-size:22px;font-weight:900;\">צור קשר</div>
      <div style=\"margin-top:8px; color:#637381;\">נשמח לעזור. ניתן להשאיר פרטים ונחזור אליך.</div>
    </div>
    <form method=\"post\" action=\"/web/contact\" style=\"margin-top:14px;\">
      <label>שם</label>
      <input name=\"name\" required />
      <label>דוא\"ל</label>
      <input name=\"email\" type=\"email\" required />
      <label>נושא</label>
      <input name=\"subject\" required />
      <label>הודעה</label>
      <textarea name=\"message\" required></textarea>
      <button type=\"submit\">שליחה</button>
    </form>
    <div class=\"hint\">build: {APP_BUILD_TAG}</div>
    """
    return _public_web_shell("צור קשר", body)


@app.post("/web/contact", response_class=HTMLResponse)
def web_contact_submit(
    name: str = Form(...),
    email: str = Form(...),
    subject: str = Form(...),
    message: str = Form(...),
) -> str:
    _save_contact_message(name.strip(), email.strip(), subject.strip(), message.strip())
    body = f"""
    <div style=\"text-align:center;\">
      <div style=\"font-size:22px;font-weight:900;\">הודעה נשלחה</div>
      <div style=\"margin-top:10px;line-height:1.8; color:#637381;\">קיבלנו את ההודעה ונחזור אליך בהקדם.</div>
      <div class=\"actionbar\" style=\"justify-content:center;\">
        <a class=\"green\" href=\"/web/login\">חזרה לדף הבית</a>
        <a class=\"blue\" href=\"/web/contact\">שליחת הודעה נוספת</a>
      </div>
      <div class=\"small\">build: {APP_BUILD_TAG}</div>
    </div>
    """
    return _public_web_shell("צור קשר", body)


@app.get("/web/assets/{asset_path:path}")
def web_assets(asset_path: str) -> Response:
    safe_rel = str(asset_path or '').replace('\\', '/').lstrip('/').strip()
    if not safe_rel or '..' in safe_rel.split('/'):
        raise HTTPException(status_code=404)
    if safe_rel.startswith('icons/'):
        icon_rel = safe_rel[len('icons/'):].strip()
        if not icon_rel or '/' in icon_rel.strip('/'):
            raise HTTPException(status_code=404)
        icon_path = os.path.join(ROOT_DIR, 'icons', icon_rel)
        if os.path.isfile(icon_path):
            return FileResponse(icon_path)
        alt_icon_paths = [
            os.path.join(ROOT_DIR, 'תמונות', 'להוראות', icon_rel),
            os.path.join(ROOT_DIR, 'dist', 'SchoolPoints_Admin', '_internal', 'תמונות', 'להוראות', icon_rel),
        ]
        for p in alt_icon_paths:
            if os.path.isfile(p):
                return FileResponse(p)
        raise HTTPException(status_code=404)
    if safe_rel.startswith('equipment_required_files/'):
        abs_path = os.path.join(ROOT_DIR, safe_rel)
        if os.path.isfile(abs_path):
            return FileResponse(abs_path)
        raise HTTPException(status_code=404)
    abs_path = os.path.join(ROOT_DIR, 'תמונות', safe_rel)
    if not os.path.isfile(abs_path):
        allowed_root_files = {
            'final_logo_correct.png',
            'final_logo_method7.png',
            'optimized_logo_method7.png',
            'user_logo_method7.png',
            'user_logo_minimal.png',
            'לוגו אשראיכם.png',
        }
        if safe_rel in allowed_root_files:
            alt = os.path.join(ROOT_DIR, safe_rel)
            if os.path.isfile(alt):
                return FileResponse(alt)
        raise HTTPException(status_code=404)
    return FileResponse(abs_path)


@app.get("/web/guide", response_class=HTMLResponse)
def web_guide() -> str:
    guide_path = os.path.join(ROOT_DIR, 'guide_user_embedded.html')
    html = _read_text_file(guide_path)
    if not html:
        body = "<h2>מדריך</h2><p>המדריך עדיין לא זמין בקובץ זה.</p>"
        return _public_web_shell("מדריך", body)
    body = """
    <div style=\"height:78vh;\">
      <iframe src=\"/web/guide-content\" style=\"width:100%;height:100%;border:0;border-radius:10px; background:#fff;\"></iframe>
    </div>
    """
    return _public_web_shell("מדריך", body)


@app.get("/web/guide-content", response_class=HTMLResponse)
def web_guide_content() -> str:
    guide_path = os.path.join(ROOT_DIR, 'guide_user_embedded.html')
    html = _read_text_file(guide_path)
    if not html:
        return "<h2>מדריך</h2><p>המדריך עדיין לא זמין בקובץ זה.</p>"
    html = str(html)
    html = html.replace('file:///C:/ProgramData/SchoolPoints/equipment_required.html', '/web/equipment-required')
    html = html.replace('file:///C:/ProgramData/SchoolPoints/guide_user_embedded.html', '/web/guide')
    return html


@app.get("/web/login", response_class=HTMLResponse)
def web_login() -> str:
    template_path = os.path.join(ROOT_DIR, '!DOCTYPE .html')
    template = _read_text_file(template_path)
    if template:
        html = str(template)
        html = html.replace('<div class="logo-placeholder">', '<div class="logo-placeholder"><img src="/web/assets/icons/public.png" alt="SchoolPoints" style="width:100%;height:100%;object-fit:contain;" />')
        html = html.replace('🎓', '')
        html = html.replace('<div class="subtitle">אשראיכם</div>', '<div style="display:flex;justify-content:center;margin:14px 0 6px;"><img src="/web/assets/לוגו%20אשראיכם.png" alt="אשראיכם" style="max-width:520px;width:min(78vw,520px);height:auto;filter:drop-shadow(0 10px 25px rgba(0,0,0,.25));" /></div>')
        html = html.replace('background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);', 'background: radial-gradient(1200px 600px at 20% 10%, #1d4ed8 0%, rgba(29, 78, 216, 0) 55%), radial-gradient(900px 500px at 80% 20%, #7c3aed 0%, rgba(124, 58, 237, 0) 55%), linear-gradient(180deg, #0f172a 0%, #1e293b 100%);')
        html = html.replace('<div class="english-title">SCHOOLPOINTS</div>', '<div class="english-title" style="font-size:18px; letter-spacing: 3px; opacity:.85;">SCHOOLPOINTS</div>')
        html = html.replace('href="#" class="cta-button">צור קשר עכשיו</a>', 'href="/web/signin" class="cta-button">כניסה למערכת</a>')
        if '</head>' in html:
            html = html.replace('</head>', '<link rel="icon" href="/web/assets/icons/public.png" /></head>')
        if '</section>' in html:
            html = html.replace(
                '</section>\n\n    <!-- Features Section -->',
                '</section>\n\n    <section class="cta" style="margin-top:40px;">\n        <div style="display:flex; gap:12px; justify-content:center; flex-wrap:wrap;">\n            <a href="/web/signin" class="cta-button">כניסה למערכת</a>\n            <a href="/web/guide" class="cta-button" style="background:rgba(255,255,255,.92); color:#0f172a;">מדריך</a>\n            <a href="/web/download" class="cta-button" style="background:rgba(255,255,255,.92); color:#0f172a;">הורדה</a>\n            <a href="/web/contact" class="cta-button" style="background:rgba(255,255,255,.92); color:#0f172a;">צור קשר</a>\n        </div>\n        <div style="margin-top:14px; font-size:12px; opacity:.8; color:white;">build: ' + APP_BUILD_TAG + '</div>\n    </section>\n\n    <!-- Features Section -->'
            )
        return html

    body = """
    <div style="text-align:center; padding: 24px 10px;">
      <div style="font-size:40px; font-weight:800;">SCHOOLPOINT</div>
      <div style="font-size:16px; margin-top:8px;">תוכנת הניקוד</div>
      <div class="actionbar" style="margin-top:18px;">
        <a class="green" href="/web/signin">כניסה למערכת</a>
        <a class="blue" href="/web/guide">מדריך</a>
        <a class="gray" href="/web/download">הורדת התוכנה</a>
        <a class="gray" href="/web/contact">צור קשר</a>
      </div>
      <div style="margin-top:12px; font-size:12px; color:#6b7280;">build: """ + APP_BUILD_TAG + """</div>
    </div>
    """
    return _public_web_shell("SchoolPoints", body)


@app.get("/web/signin", response_class=HTMLResponse)
def web_signin() -> str:
    body = """
    <style>
      .hero { display:flex; gap:18px; align-items:center; justify-content:space-between; flex-wrap:wrap; margin-bottom:14px; }
      .brand { display:flex; gap:12px; align-items:center; }
      .brand img { width:64px; height:64px; object-fit:contain; border-radius:12px; background:#fff; border:1px solid var(--line); box-shadow:0 6px 16px rgba(40,55,70,.08); }
      .brand .t1 { font-size:22px; font-weight:900; letter-spacing:.5px; }
      .brand .t2 { font-size:13px; color:#637381; margin-top:2px; }
      .panel { display:grid; grid-template-columns: 1fr; gap:12px; }
      form { display:grid; grid-template-columns: 1fr; gap:10px; max-width: 460px; margin: 6px auto 0; }
      label { font-weight:700; font-size:13px; }
      input { width:100%; padding:12px; border:1px solid var(--line); border-radius:10px; font-size:15px; background:#fff; }
      button { padding:12px 16px; border:none; border-radius:10px; background:var(--mint); color:#fff; font-weight:800; cursor:pointer; font-size:15px; }
      .hint { text-align:center; font-size:12px; color:#637381; margin-top:8px; }
    </style>
    <div class="hero">
      <div class="brand">
        <img src="/web/assets/icons/public.png" alt="SchoolPoints" />
        <div>
          <div class="t1">SCHOOLPOINTS</div>
          <div class="t2">מערכת נקודות לבית ספר</div>
        </div>
      </div>
    </div>
    <div class="panel">
      <form method="post" action="/web/institution-login">
        <label>קוד מוסד</label>
        <input name="tenant_id" placeholder="" required />
        <label>סיסמת מוסד</label>
        <input name="institution_password" type="password" required />
        <button type="submit">התחברות</button>
      </form>
      <div class="hint">build: """ + APP_BUILD_TAG + """</div>
    </div>
    """
    return _public_web_shell("כניסה למערכת", body)


@app.post("/web/institution-login", response_class=HTMLResponse)
def web_institution_login(
    tenant_id: str = Form(...),
    institution_password: str = Form(...)
) -> Response:
    conn = _db()
    cur = conn.cursor()
    cur.execute(
        _sql_placeholder('SELECT tenant_id, password_hash FROM institutions WHERE tenant_id = ? LIMIT 1'),
        (tenant_id.strip(),)
    )
    row = cur.fetchone()
    conn.close()
    if not row or not (row['password_hash'] or '').strip():
        body = "<h2>שגיאת התחברות</h2><p>קוד מוסד או סיסמת מוסד לא תקינים.</p><div class=\"actionbar\"><a class=\"green\" href=\"/web/signin\">נסה שוב</a></div>"
        return HTMLResponse(_public_web_shell("כניסה למערכת", body))
    if not _pbkdf2_verify(institution_password.strip(), str(row['password_hash'])):
        body = "<h2>שגיאת התחברות</h2><p>קוד מוסד או סיסמת מוסד לא תקינים.</p><div class=\"actionbar\"><a class=\"green\" href=\"/web/signin\">נסה שוב</a></div>"
        return HTMLResponse(_public_web_shell("כניסה למערכת", body))

    try:
        _ensure_tenant_db_exists(tenant_id.strip())
    except Exception as e:
        try:
            print(f"[WEB] open tenant db failed tenant={tenant_id.strip()}: {e}", file=sys.stderr)
        except Exception:
            pass
        body = (
            "<h2>שגיאת מערכת</h2>"
            "<p>לא ניתן ליצור/לפתוח את מסד הנתונים של המוסד.</p>"
            "<pre style=\"white-space:pre-wrap;direction:ltr\">" + _safe_str(e) + "</pre>"
            "<div class=\"actionbar\"><a class=\"green\" href=\"/web/signin\">חזרה</a></div>"
        )
        return HTMLResponse(_public_web_shell("כניסה למערכת", body))

    response = RedirectResponse(url="/web/teacher-login", status_code=302)
    response.set_cookie("web_tenant", tenant_id.strip(), httponly=True)
    response.delete_cookie("web_teacher")
    return response


@app.get("/web/teacher-login", response_class=HTMLResponse)
def web_teacher_login(request: Request) -> Response:
    guard = _web_require_tenant(request)
    if guard:
        return guard
    body = """
    <style>
      .panel { display:grid; grid-template-columns: 1fr; gap:12px; }
      form { display:grid; grid-template-columns: 1fr; gap:10px; max-width: 460px; margin: 6px auto 0; }
      label { font-weight:700; font-size:13px; }
      input { width:100%; padding:12px; border:1px solid var(--line); border-radius:10px; font-size:15px; background:#fff; }
      button { padding:12px 16px; border:none; border-radius:10px; background:var(--mint); color:#fff; font-weight:800; cursor:pointer; font-size:15px; }
      .hint { text-align:center; font-size:12px; color:#637381; margin-top:8px; }
    </style>
    <div class="panel">
      <form method="post" action="/web/teacher-login">
        <label>קוד / כרטיס מורה (או מנהל)</label>
        <input name="card_number" type="password" required />
        <button type="submit">כניסה</button>
      </form>
    </div>
    """
    return HTMLResponse(_public_web_shell("כניסה", body))


@app.post("/web/teacher-login", response_class=HTMLResponse)
def web_teacher_login_submit(request: Request, card_number: str = Form(...)) -> Response:
    guard = _web_require_tenant(request)
    if guard:
        return guard
    tenant_id = _web_tenant_from_cookie(request)
    conn = _tenant_school_db(tenant_id)
    cur = conn.cursor()
    cur.execute(
        _sql_placeholder(
            'SELECT id, name, is_admin FROM teachers '
            'WHERE CAST(card_number AS TEXT) = ? OR CAST(card_number2 AS TEXT) = ? OR CAST(card_number3 AS TEXT) = ? '
            'LIMIT 1'
        ),
        (card_number.strip(), card_number.strip(), card_number.strip())
    )
    row = cur.fetchone()
    diag = None
    if not row:
        try:
            cur.execute('SELECT COUNT(*) AS total FROM teachers')
            r = cur.fetchone() or {}
            teachers_total = int((r.get('total') if isinstance(r, dict) else r[0]) or 0)
        except Exception:
            teachers_total = -1
        try:
            cur.execute('SELECT id, name, card_number, card_number2, card_number3 FROM teachers ORDER BY id ASC LIMIT 3')
            sample_rows = cur.fetchall() or []
            sample_txt = "\n".join(
                [
                    f"{(x.get('id') if isinstance(x, dict) else x[0])} | {(x.get('name') if isinstance(x, dict) else x[1])} | {(x.get('card_number') if isinstance(x, dict) else x[2])} | {(x.get('card_number2') if isinstance(x, dict) else x[3])} | {(x.get('card_number3') if isinstance(x, dict) else x[4])}"
                    for x in sample_rows
                ]
            )
        except Exception:
            sample_txt = ''
        diag = f"tenant={tenant_id} | teachers={teachers_total}\n{sample_txt}".strip()
    conn.close()
    if not row:
        body = "<h2>שגיאת התחברות</h2><p>קוד/כרטיס מורה לא תקין.</p>"
        if diag:
            body += "<pre style=\"white-space:pre-wrap;direction:ltr\">" + _safe_str(diag) + "</pre>"
        body += "<div class=\"actionbar\"><a class=\"green\" href=\"/web/teacher-login\">נסה שוב</a></div>"
        return HTMLResponse(_public_web_shell("כניסה", body))
    response = RedirectResponse(url="/web/admin", status_code=302)
    response.set_cookie("web_user", "1", httponly=True)
    response.set_cookie("web_teacher", str(row['id']), httponly=True)
    return response


@app.post("/web/admin-login", response_class=HTMLResponse)
def web_login_submit(
    username: str = Form(...),
    password: str = Form(...),
    tenant_id: str = Form(...)
) -> Response:
    creds = _web_auth_credentials()
    if username.strip() != creds['user'] or password.strip() != creds['pass']:
        body = "<h2>שגיאת התחברות</h2><p>שם משתמש או סיסמה לא תקינים.</p><div class=\"actionbar\"><a class=\"green\" href=\"/web/signin\">נסה שוב</a></div>"
        return HTMLResponse(_public_web_shell("כניסה למערכת", body))
    response = RedirectResponse(url="/web/admin", status_code=302)
    response.set_cookie("web_user", username.strip(), httponly=True)
    response.set_cookie("web_tenant", tenant_id.strip(), httponly=True)
    return response


@app.get("/web/logout")
def web_logout() -> Response:
    response = RedirectResponse(url="/web/login", status_code=302)
    response.delete_cookie("web_user")
    response.delete_cookie("web_tenant")
    response.delete_cookie("web_teacher")
    return response


def _basic_web_shell(title: str, body_html: str) -> str:
    status = _sync_status_info()
    return f"""
    <!doctype html>
    <html lang="he">
    <head>
      <meta charset="utf-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      <title>{title}</title>
      <link rel="icon" href="/web/assets/icons/public.png" />
      <style>
        :root {{ --navy:#2f3e4e; --mint:#1abc9c; --sky:#3498db; --bg:#eef2f4; --line:#d6dde3; --tab:#ecf0f1; }}
        body {{ margin:0; font-family: "Segoe UI", Arial, sans-serif; background:var(--bg); color:#1f2d3a; direction: rtl; }}
        .wrap {{ max-width: 860px; margin: 24px auto; padding: 0 16px; }}
        .card {{ background:#fff; border-radius:10px; padding:20px; border:1px solid var(--line); box-shadow:0 6px 18px rgba(40,55,70,.08); }}
        .titlebar {{ background:var(--navy); color:#fff; padding:14px 18px; border-radius:10px 10px 0 0; margin:-20px -20px 16px; }}
        .titlebar h2 {{ margin:0; font-size:20px; }}
        .tabs {{ margin:6px 0 10px; display:flex; gap:6px; flex-wrap:wrap; }}
        .tab {{ background:var(--tab); padding:6px 10px; border-radius:4px; font-size:12px; text-decoration:none; color:#1f2d3a; border:1px solid var(--line); }}
        label {{ display:block; margin:10px 0 6px; font-weight:600; }}
        input, select {{ width:100%; padding:10px; border:1px solid #d9e2ec; border-radius:8px; }}
        button {{ margin-top:14px; padding:10px 16px; border:none; border-radius:8px; background:#1abc9c; color:#fff; font-weight:600; cursor:pointer; }}
        .btn-blue {{ background:#3498db; }}
        .btn-orange {{ background:#f39c12; }}
        .btn-red {{ background:#e74c3c; }}
        .links {{ margin-top:12px; font-size:13px; }}
        .actionbar {{ margin-top:14px; display:flex; gap:10px; flex-wrap:wrap; justify-content:flex-end; }}
        .actionbar a, .actionbar button {{ padding:8px 12px; border-radius:6px; color:#fff; text-decoration:none; border:none; font-weight:600; }}
        .actionbar .green {{ background:#2ecc71; }}
        .actionbar .blue {{ background:#3498db; }}
        .actionbar .orange {{ background:#f39c12; }}
        .actionbar .gray {{ background:#95a5a6; }}
        .actionbar .purple {{ background:#8e44ad; }}
        .links a {{ color:#1f2d3a; text-decoration:none; margin-left:10px; }}
      </style>
    </head>
    <body>
      <div class="wrap">
        <div class="card">
          <div class="titlebar"><h2>{title}</h2></div>
          <div style="font-size:12px;color:#637381;margin-bottom:8px;">
            מוסדות: {status['inst_total']} | שינויים: {status['changes_total']} | שינוי אחרון: {status['last_received']}
          </div>
          <div class="tabs">
            <a class="tab" href="/web/admin">תלמידים</a>
            <a class="tab" href="/web/upgrades">שדרוגים</a>
            <a class="tab" href="/web/messages">הודעות</a>
            <a class="tab" href="/web/special-bonus">בונוס מיוחד</a>
            <a class="tab" href="/web/time-bonus">בונוס זמנים</a>
            <a class="tab" href="/web/teachers">ניהול מורים</a>
            <a class="tab" href="/web/system-settings">הגדרות מערכת</a>
            <a class="tab" href="/web/display-settings">הגדרות תצוגה</a>
            <a class="tab" href="/web/bonuses">בונוסים</a>
            <a class="tab" href="/web/holidays">חגים/חופשות</a>
            <a class="tab" href="/web/cashier">קופה</a>
            <a class="tab" href="/web/reports">דוחות</a>
            <a class="tab" href="/web/logs">לוגים</a>
          </div>
          {body_html}
          <div class="links">
            <a href="/web/admin">עמדת ניהול</a>
            <a href="/web/logout">יציאה</a>
          </div>
        </div>
      </div>
    </body>
    </html>
    """


@app.get("/web/cashier", response_class=HTMLResponse)
def web_cashier(request: Request):
    guard = _web_require_teacher(request)
    if guard:
        return guard
    body = """
    <h2>עמדת קופה</h2>
    <p>מסך קופה יתווסף כאן.</p>
    <div class="actionbar">
      <a class="green" href="/web/cashier">➕ מוצר חדש</a>
      <a class="blue" href="/web/cashier">🧾 היסטוריית רכישות</a>
      <a class="gray" href="/web/admin">↩️ חזרה לניהול</a>
    </div>
    """
    return _basic_web_shell("עמדת קופה", body)


@app.get("/web/ads-media", response_class=HTMLResponse)
def web_ads_media(request: Request):
    guard = _web_require_teacher(request)
    if guard:
        return guard
    body = """
    <h2>הודעות / פרסומות / מדיה</h2>
    <p>מסך ניהול מדיה יתווסף כאן.</p>
    <div class="actionbar">
      <a class="purple" href="/web/ads-media">⬆️ העלאת מדיה</a>
      <a class="blue" href="/web/messages">↩️ למסך הודעות</a>
      <a class="gray" href="/web/admin">↩️ חזרה לניהול</a>
    </div>
    """
    return _basic_web_shell("מדיה", body)


@app.get("/web/colors", response_class=HTMLResponse)
def web_colors(request: Request):
    guard = _web_require_teacher(request)
    if guard:
        return guard
    body = """
    <h2>צבעים</h2>
    <p>מסך ניהול צבעים/טווחי נקודות יתווסף כאן.</p>
    <div class="actionbar">
      <a class="green" href="/web/colors">➕ טווח חדש</a>
      <a class="gray" href="/web/admin">↩️ חזרה לניהול</a>
    </div>
    """
    return _basic_web_shell("צבעים", body)


@app.get("/web/sounds", response_class=HTMLResponse)
def web_sounds(request: Request):
    guard = _web_require_teacher(request)
    if guard:
        return guard
    body = """
    <h2>צלילים</h2>
    <p>מסך ניהול צלילים יתווסף כאן.</p>
    <div class="actionbar">
      <a class="purple" href="/web/sounds">⬆️ העלאת צליל</a>
      <a class="gray" href="/web/admin">↩️ חזרה לניהול</a>
    </div>
    """
    return _basic_web_shell("צלילים", body)


@app.get("/web/coins", response_class=HTMLResponse)
def web_coins(request: Request):
    guard = _web_require_teacher(request)
    if guard:
        return guard
    body = """
    <h2>מטבעות ויעדים</h2>
    <p>מסך ניהול מטבעות/יעדים יתווסף כאן.</p>
    <div class="actionbar">
      <a class="green" href="/web/coins">➕ הוסף מטבע</a>
      <a class="gray" href="/web/admin">↩️ חזרה לניהול</a>
    </div>
    """
    return _basic_web_shell("מטבעות", body)


@app.get("/web/reports", response_class=HTMLResponse)
def web_reports(request: Request):
    guard = _web_require_teacher(request)
    if guard:
        return guard
    body = """
    <h2>דוחות</h2>
    <p>מסך דוחות יתווסף כאן.</p>
    <div class="actionbar">
      <a class="blue" href="/web/export/download">⬇️ ייצוא תלמידים (CSV)</a>
      <a class="gray" href="/web/admin">↩️ חזרה לניהול</a>
    </div>
    """
    return _basic_web_shell("דוחות", body)


@app.get("/web/students/new", response_class=HTMLResponse)
def web_student_new(request: Request):
    guard = _web_require_teacher(request)
    if guard:
        return guard
    body = """
    <h2>הוספת תלמיד</h2>
    <form method="post">
      <label>שם פרטי</label>
      <input name="first_name" placeholder="שם פרטי" required />
      <label>שם משפחה</label>
      <input name="last_name" placeholder="שם משפחה" required />
      <label>כיתה</label>
      <input name="class_name" placeholder="כיתה" />
      <label>תעודת זהות</label>
      <input name="id_number" placeholder="ת.ז" />
      <label>נקודות</label>
      <input name="points" type="number" placeholder="0" value="0" />
      <button type="submit">שמירה</button>
    </form>
    <div class="actionbar">
      <a class="green" href="/web/students/new">➕ הוספה נוספת</a>
      <a class="gray" href="/web/admin">↩️ חזרה לניהול</a>
    </div>
    """
    return _basic_web_shell("הוספת תלמיד", body)


@app.post("/web/students/new", response_class=HTMLResponse)
def web_student_new_submit(
    request: Request,
    first_name: str = Form(...),
    last_name: str = Form(...),
    class_name: str = Form(default=""),
    id_number: str = Form(default=""),
    points: int = Form(default=0)
):
    guard = _web_require_teacher(request)
    if guard:
        return guard
    tenant_id = _web_tenant_from_cookie(request)
    conn = _tenant_school_db(tenant_id)
    cur = conn.cursor()
    cur.execute(
        _sql_placeholder(
            '''
            INSERT INTO students (first_name, last_name, class_name, id_number, points)
            VALUES (?, ?, ?, ?, ?)
            '''
        ),
        (first_name.strip(), last_name.strip(), class_name.strip(), id_number.strip(), int(points or 0))
    )
    conn.commit()
    conn.close()
    body = """
    <h2>תלמיד נוסף בהצלחה</h2>
    <p>התלמיד נשמר במאגר המקומי.</p>
    """
    return _basic_web_shell("הוספת תלמיד", body)


@app.get("/web/students/edit", response_class=HTMLResponse)
def web_student_edit(request: Request):
    guard = _web_require_teacher(request)
    if guard:
        return guard
    body = """
    <h2>עריכת תלמיד</h2>
    <form method="post">
      <label>מזהה תלמיד (ID)</label>
      <input name="student_id" placeholder="ID" required />
      <label>נקודות</label>
      <input name="points" type="number" placeholder="0" />
      <label>הודעה פרטית</label>
      <input name="private_message" placeholder="הודעה" />
      <button type="submit">עדכון</button>
    </form>
    <div class="actionbar">
      <a class="blue" href="/web/students/edit">🔄 טען נוסף</a>
      <a class="gray" href="/web/admin">↩️ חזרה לניהול</a>
    </div>
    """
    return _basic_web_shell("עריכת תלמיד", body)


@app.post("/web/students/edit", response_class=HTMLResponse)
def web_student_edit_submit(
    request: Request,
    student_id: int = Form(...),
    points: int = Form(default=0),
    private_message: str = Form(default="")
) -> str:
    guard = _web_require_teacher(request)
    if guard:
        return guard
    tenant_id = _web_tenant_from_cookie(request)
    conn = _tenant_school_db(tenant_id)
    cur = conn.cursor()
    cur.execute(
        _sql_placeholder('UPDATE students SET points = ?, private_message = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?'),
        (int(points or 0), private_message.strip(), int(student_id))
    )
    conn.commit()
    conn.close()
    body = """
    <h2>תלמיד עודכן</h2>
    <p>העדכון נשמר.</p>
    """
    return _basic_web_shell("עריכת תלמיד", body)


@app.get("/web/students/delete", response_class=HTMLResponse)
def web_student_delete(request: Request):
    guard = _web_require_teacher(request)
    if guard:
        return guard
    body = """
    <h2>מחיקת תלמיד</h2>
    <form method="post">
      <label>מזהה תלמיד (ID)</label>
      <input name="student_id" placeholder="ID" required />
      <button type="submit" style="background:#e74c3c;">מחיקה</button>
    </form>
    <div class="actionbar">
      <a class="orange" href="/web/students/delete">🗑️ מחיקה נוספת</a>
      <a class="gray" href="/web/admin">↩️ חזרה לניהול</a>
    </div>
    """
    return _basic_web_shell("מחיקת תלמיד", body)


@app.post("/web/students/delete", response_class=HTMLResponse)
def web_student_delete_submit(request: Request, student_id: int = Form(...)):
    guard = _web_require_teacher(request)
    if guard:
        return guard
    tenant_id = _web_tenant_from_cookie(request)
    conn = _tenant_school_db(tenant_id)
    cur = conn.cursor()
    cur.execute(_sql_placeholder('DELETE FROM students WHERE id = ?'), (int(student_id),))
    conn.commit()
    conn.close()
    body = """
    <h2>תלמיד נמחק</h2>
    <p>הרשומה הוסרה.</p>
    """
    return _basic_web_shell("מחיקת תלמיד", body)


@app.get("/web/import", response_class=HTMLResponse)
def web_import(request: Request):
    guard = _web_require_teacher(request)
    if guard:
        return guard
    body = """
    <h2>ייבוא אקסל</h2>
    <p>מסך ייבוא יתווסף. בינתיים ניתן להריץ ייבוא מהתוכנה המקומית.</p>
    <div class="actionbar">
      <a class="purple" href="/web/import">⬆️ העלה קובץ</a>
      <a class="gray" href="/web/admin">↩️ חזרה לניהול</a>
    </div>
    """
    return _basic_web_shell("ייבוא אקסל", body)


@app.get("/web/export", response_class=HTMLResponse)
def web_export(request: Request):
    guard = _web_require_teacher(request)
    if guard:
        return guard
    body = """
    <h2>ייצוא אקסל</h2>
    <p>ניתן להוריד קובץ CSV מהיר של תלמידים.</p>
    <div class="actionbar">
      <a class="blue" href="/web/export/download">⬇️ הורדת CSV</a>
      <a class="gray" href="/web/admin">↩️ חזרה לניהול</a>
    </div>
    """
    return _basic_web_shell("ייצוא אקסל", body)


@app.get("/web/export/download")
def web_export_download(request: Request) -> Response:
    guard = _web_require_teacher(request)
    if guard:
        return guard
    tenant_id = _web_tenant_from_cookie(request)
    conn = _tenant_school_db(tenant_id)
    cur = conn.cursor()
    cur.execute(
        '''
        SELECT id, first_name, last_name, class_name, id_number, card_number, points
        FROM students
        ORDER BY (serial_number IS NULL OR serial_number = 0), serial_number, class_name, last_name, first_name
        '''
    )
    rows = cur.fetchall() or []
    conn.close()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "first_name", "last_name", "class_name", "id_number", "card_number", "points"])
    for r in rows:
        writer.writerow([
            r['id'], r['first_name'], r['last_name'], r['class_name'],
            r['id_number'], r['card_number'], r['points']
        ])
    data = output.getvalue().encode('utf-8-sig')
    return Response(
        content=data,
        media_type='text/csv; charset=utf-8',
        headers={'Content-Disposition': 'attachment; filename=students_export.csv'}
    )


@app.get("/web/bonuses", response_class=HTMLResponse)
def web_bonuses(request: Request):
    guard = _web_require_teacher(request)
    if guard:
        return guard
    body = """
    <h2>בונוסים</h2>
    <p>מסך ניהול בונוסים יתווסף כאן.</p>
    <div class="actionbar">
      <a class="green" href="/web/bonuses">➕ הוסף בונוס</a>
      <a class="gray" href="/web/admin">↩️ חזרה לניהול</a>
    </div>
    """
    return _basic_web_shell("בונוסים", body)


@app.get("/web/holidays", response_class=HTMLResponse)
def web_holidays(request: Request):
    guard = _web_require_teacher(request)
    if guard:
        return guard
    body = """
    <h2>חגים וחופשות</h2>
    <p>מסך ניהול חגים/חופשות יתווסף כאן.</p>
    <div class="actionbar">
      <a class="green" href="/web/holidays">🎉 הוסף חג</a>
      <a class="gray" href="/web/admin">↩️ חזרה לניהול</a>
    </div>
    """
    return _basic_web_shell("חגים וחופשות", body)


@app.get("/web/upgrades", response_class=HTMLResponse)
def web_upgrades(request: Request):
    guard = _web_require_teacher(request)
    if guard:
        return guard
    body = """
    <h2>שדרוגים</h2>
    <p>מסך שדרוגים יתווסף כאן.</p>
    <div class="actionbar">
      <a class="green" href="/web/upgrades">⬆️ העלאת גרסה</a>
      <a class="blue" href="/web/upgrades">📦 ניהול גרסאות</a>
      <a class="gray" href="/web/admin">↩️ חזרה לניהול</a>
    </div>
    """
    return _basic_web_shell("שדרוגים", body)


@app.get("/web/messages", response_class=HTMLResponse)
def web_messages(request: Request):
    guard = _web_require_teacher(request)
    if guard:
        return guard
    body = """
    <h2>הודעות כלליות</h2>
    <p>מסך ניהול הודעות כלליות יתווסף כאן.</p>
    <div class="actionbar">
      <a class="green" href="/web/messages">➕ הודעה חדשה</a>
      <a class="purple" href="/web/ads-media">🖼️ מדיה / פרסומות</a>
      <a class="gray" href="/web/admin">↩️ חזרה לניהול</a>
    </div>
    """
    return _basic_web_shell("הודעות כלליות", body)


@app.get("/web/special-bonus", response_class=HTMLResponse)
def web_special_bonus(request: Request):
    guard = _web_require_teacher(request)
    if guard:
        return guard
    body = """
    <h2>בונוס מיוחד</h2>
    <p>מסך בונוס מיוחד יתווסף כאן.</p>
    <div class="actionbar">
      <a class="green" href="/web/special-bonus">➕ יצירת בונוס מיוחד</a>
      <a class="blue" href="/web/bonuses">↩️ למסך בונוסים</a>
      <a class="gray" href="/web/admin">↩️ חזרה לניהול</a>
    </div>
    """
    return _basic_web_shell("בונוס מיוחד", body)


@app.get("/web/time-bonus", response_class=HTMLResponse)
def web_time_bonus(request: Request):
    guard = _web_require_teacher(request)
    if guard:
        return guard
    body = """
    <h2>בונוס זמנים</h2>
    <p>מסך בונוס זמנים יתווסף כאן.</p>
    <div class="actionbar">
      <a class="green" href="/web/time-bonus">➕ כלל חדש</a>
      <a class="blue" href="/web/holidays">📅 חגים/חופשות</a>
      <a class="gray" href="/web/admin">↩️ חזרה לניהול</a>
    </div>
    """
    return _basic_web_shell("בונוס זמנים", body)


@app.get("/web/teachers", response_class=HTMLResponse)
def web_teachers(request: Request):
    guard = _web_require_teacher(request)
    if guard:
        return guard
    body = """
    <h2>ניהול מורים</h2>
    <p>מסך ניהול מורים והרשאות יתווסף כאן.</p>
    <div class="actionbar">
      <a class="green" href="/web/teachers">➕ הוסף מורה</a>
      <a class="blue" href="/web/teachers">🏷️ ניהול כיתות למורה</a>
      <a class="orange" href="/web/teachers">🔐 הרשאות מנהל</a>
      <a class="gray" href="/web/admin">↩️ חזרה לניהול</a>
    </div>
    """
    return _basic_web_shell("ניהול מורים", body)


@app.get("/web/system-settings", response_class=HTMLResponse)
def web_system_settings(request: Request):
    guard = _web_require_teacher(request)
    if guard:
        return guard
    body = """
    <h2>הגדרות מערכת</h2>
    <p>מסך הגדרות מערכת יתווסף כאן.</p>
    <div class="actionbar">
      <a class="green" href="/web/system-settings">💾 שמירה</a>
      <a class="blue" href="/web/system-settings">📁 תיקייה משותפת</a>
      <a class="blue" href="/web/system-settings">🖼️ לוגו</a>
      <a class="blue" href="/web/system-settings">🧑‍🎓 תיקיית תמונות תלמידים</a>
      <a class="gray" href="/web/admin">↩️ חזרה לניהול</a>
    </div>
    """
    return _basic_web_shell("הגדרות מערכת", body)


@app.get("/web/display-settings", response_class=HTMLResponse)
def web_display_settings(request: Request):
    guard = _web_require_teacher(request)
    if guard:
        return guard
    body = """
    <h2>הגדרות תצוגה</h2>
    <p>מסך הגדרות תצוגה יתווסף כאן.</p>
    <div class="actionbar">
      <a class="blue" href="/web/colors">🎨 צבעים</a>
      <a class="blue" href="/web/sounds">🔊 צלילים</a>
      <a class="blue" href="/web/coins">🪙 מטבעות</a>
      <a class="blue" href="/web/holidays">📅 חגים/חופשות</a>
      <a class="gray" href="/web/admin">↩️ חזרה לניהול</a>
    </div>
    """
    return _basic_web_shell("הגדרות תצוגה", body)


@app.get("/web/logs", response_class=HTMLResponse)
def web_logs(request: Request):
    guard = _web_require_teacher(request)
    if guard:
        return guard
    body = """
    <h2>לוגים</h2>
    <p>מסך לוגים יתווסף כאן.</p>
    <div class="actionbar">
      <a class="blue" href="/web/logs">🔄 רענן</a>
      <a class="gray" href="/web/admin">↩️ חזרה לניהול</a>
    </div>
    """
    return _basic_web_shell("לוגים", body)


@app.get("/web/settings", response_class=HTMLResponse)
def web_settings(request: Request):
    guard = _web_require_teacher(request)
    if guard:
        return guard
    body = """
    <h2>הגדרות מערכת</h2>
    <p>מסך הגדרות יתווסף כאן.</p>
    <div class="actionbar">
      <a class="green" href="/web/settings">💾 שמירה</a>
      <a class="gray" href="/web/admin">↩️ חזרה לניהול</a>
    </div>
    """
    return _basic_web_shell("הגדרות", body)


@app.get("/admin/sync-status", response_class=HTMLResponse)
def admin_sync_status(request: Request, admin_key: str = '') -> str:
    guard = _admin_require(request, admin_key)
    if guard:
        return guard  # type: ignore[return-value]
    conn = _db()
    cur = conn.cursor()
    cur.execute('SELECT COUNT(*) AS total FROM changes')
    row = cur.fetchone() or {}
    total = int((row.get('total') if isinstance(row, dict) else row[0]) or 0)
    cur.execute('SELECT COUNT(*) AS total FROM institutions')
    row = cur.fetchone() or {}
    inst_total = int((row.get('total') if isinstance(row, dict) else row[0]) or 0)
    cur.execute('SELECT MAX(received_at) AS last_received FROM changes')
    row = cur.fetchone() or {}
    last_received = (row.get('last_received') if isinstance(row, dict) else row[0])
    conn.close()
    return f"""
    <!doctype html>
    <html lang="he">
    <head>
      <meta charset="utf-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      <title>סטטוס סינכרון</title>
      <style>
        body {{ margin:0; font-family: Arial, sans-serif; background:#f2f5f6; color:#1f2d3a; direction: rtl; }}
        .wrap {{ max-width: 720px; margin: 30px auto; padding: 0 16px; }}
        .card {{ background:#fff; border-radius:14px; padding:20px; border:1px solid #e1e8ee; }}
        .stat {{ margin:8px 0; font-weight:600; }}
        .links {{ margin-top:12px; font-size:13px; }}
        .links a {{ color:#1f2d3a; text-decoration:none; margin-left:10px; }}
      </style>
    </head>
    <body>
      <div class="wrap">
        <div class="card">
          """ + _admin_status_bar() + """
          <h2>סטטוס סינכרון</h2>
          <div class="stat">כמות מוסדות רשומים: {inst_total}</div>
          <div class="stat">סה"כ שינויים שהתקבלו: {total}</div>
          <div class="stat">תאריך שינוי אחרון: {last_received or '—'}</div>
          <div class="links">
            <a href="/admin/changes">שינויים אחרונים</a>
            <a href="/admin/institutions">מוסדות</a>
            <a href="/admin/logout">יציאה</a>
            <a href="/web/admin">עמדת ניהול ווב</a>
          </div>
        </div>
      </div>
    </body>
    </html>
    """


@app.get("/admin/changes", response_class=HTMLResponse)
def admin_changes(request: Request, admin_key: str = '') -> str:
    guard = _admin_require(request, admin_key)
    if guard:
        return guard  # type: ignore[return-value]
    status_bar = _admin_status_bar()
    conn = _db()
    cur = conn.cursor()
    cur.execute(
        '''
        SELECT received_at, tenant_id, station_id, entity_type, action_type, entity_id, payload_json
        FROM changes
        ORDER BY id DESC
        LIMIT 200
        '''
    )
    rows = cur.fetchall() or []
    conn.close()
    items = "".join(
        f"<tr><td>{r['received_at']}</td><td>{r['tenant_id']}</td><td>{r['station_id'] or ''}</td><td>{r['entity_type']}</td><td>{r['action_type']}</td><td>{r['entity_id'] or ''}</td><td><pre>{r['payload_json'] or ''}</pre></td></tr>"
        for r in rows
    )
    return f"""
    <!doctype html>
    <html lang="he">
    <head>
      <meta charset="utf-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      <title>שינויים אחרונים</title>
      <style>
        body {{ margin:0; font-family: Arial, sans-serif; background:#f2f5f6; color:#1f2d3a; direction: rtl; }}
        .wrap {{ max-width: 1100px; margin: 30px auto; padding: 0 16px; }}
        .card {{ background:#fff; border-radius:14px; padding:20px; border:1px solid #e1e8ee; }}
        table {{ width:100%; border-collapse:collapse; font-size:13px; }}
        th, td {{ padding:8px; border-bottom:1px solid #e8eef2; text-align:right; vertical-align:top; }}
        th {{ background:#f7f9fb; }}
        tbody tr:nth-child(even) {{ background:#f3f6f8; }}
        pre {{ white-space: pre-wrap; margin:0; }}
        .links {{ margin-top:12px; font-size:13px; }}
        .links a {{ color:#1f2d3a; text-decoration:none; margin-left:10px; }}
      </style>
    </head>
    <body>
      <div class="wrap">
        <div class="card">
          {status_bar}
          <h2>שינויים אחרונים</h2>
          <table>
            <thead>
              <tr><th>זמן</th><th>Tenant</th><th>תחנה</th><th>סוג</th><th>פעולה</th><th>Entity</th><th>Payload</th></tr>
            </thead>
            <tbody>{items}</tbody>
          </table>
          <div class="links">
            <a href="/admin/sync-status">סטטוס סינכרון</a>
            <a href="/admin/institutions">מוסדות</a>
            <a href="/admin/logout">יציאה</a>
            <a href="/web/admin">עמדת ניהול ווב</a>
          </div>
        </div>
      </div>
    </body>
    </html>
    """


@app.get("/admin/institutions", response_class=HTMLResponse)
def admin_institutions(request: Request, admin_key: str = '') -> str:
    guard = _admin_require(request, admin_key)
    if guard:
        return guard  # type: ignore[return-value]
    status_bar = _admin_status_bar()
    conn = _db()
    cur = conn.cursor()
    cur.execute('SELECT tenant_id, name, api_key, password_hash, created_at FROM institutions ORDER BY id DESC')
    rows = cur.fetchall() or []
    conn.close()
    items = "".join(
        f"<tr><td>{r['tenant_id']}</td><td>{r['name']}</td><td>{r['api_key']}</td><td>{'כן' if (r['password_hash'] or '').strip() else 'לא'}</td><td><a href='/admin/institutions/password?tenant_id={r['tenant_id']}'>עדכן סיסמה</a></td><td>{r['created_at']}</td></tr>"
        for r in rows
    )
    return f"""
    <!doctype html>
    <html lang="he">
    <head>
      <meta charset="utf-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      <title>מוסדות רשומים</title>
      <style>
        body {{ margin:0; font-family: Arial, sans-serif; background:#f2f5f6; color:#1f2d3a; direction: rtl; }}
        .wrap {{ max-width: 900px; margin: 30px auto; padding: 0 16px; }}
        .card {{ background:#fff; border-radius:14px; padding:20px; border:1px solid #e1e8ee; }}
        table {{ width:100%; border-collapse:collapse; font-size:14px; }}
        th, td {{ padding:8px; border-bottom:1px solid #e8eef2; text-align:right; }}
        th {{ background:#f7f9fb; }}
        tbody tr:nth-child(even) {{ background:#f3f6f8; }}
        .links {{ margin-top:12px; font-size:13px; }}
        .links a {{ color:#1f2d3a; text-decoration:none; margin-left:10px; }}
      </style>
    </head>
    <body>
      <div class="wrap">
        <div class="card">
          {status_bar}
          <h2>מוסדות רשומים</h2>
          <table>
            <thead>
              <tr><th>Tenant ID</th><th>שם מוסד</th><th>API Key</th><th>סיסמה הוגדרה</th><th>סיסמת מוסד</th><th>נוצר</th></tr>
            </thead>
            <tbody>{items}</tbody>
          </table>
          <div class="links">
            <a href="/admin/setup">רישום מוסד חדש</a>
            <a href="/web/admin">עמדת ניהול ווב</a>
          </div>
        </div>
      </div>
    </body>
    </html>
    """


@app.get("/admin/institutions/password", response_class=HTMLResponse)
def admin_institution_password_form(request: Request, tenant_id: str, admin_key: str = '') -> str:
    guard = _admin_require(request, admin_key)
    if guard:
        return guard  # type: ignore[return-value]
    conn = _db()
    cur = conn.cursor()
    cur.execute(_sql_placeholder('SELECT tenant_id, name FROM institutions WHERE tenant_id = ? LIMIT 1'), (tenant_id.strip(),))
    row = cur.fetchone()
    conn.close()
    if not row:
        return "<h3>Tenant not found</h3>"
    return f"""
    <!doctype html>
    <html lang="he">
    <head>
      <meta charset="utf-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      <title>עדכון סיסמת מוסד</title>
      <style>
        body {{ margin:0; font-family: Arial, sans-serif; background:#f2f5f6; color:#1f2d3a; direction: rtl; }}
        .wrap {{ max-width: 720px; margin: 30px auto; padding: 0 16px; }}
        .card {{ background:#fff; border-radius:14px; padding:20px; border:1px solid #e1e8ee; }}
        label {{ display:block; margin:10px 0 6px; font-weight:600; }}
        input {{ width:100%; padding:10px; border:1px solid #d9e2ec; border-radius:8px; }}
        button {{ margin-top:14px; padding:10px 16px; border:none; border-radius:8px; background:#1abc9c; color:#fff; font-weight:600; cursor:pointer; }}
        .links {{ margin-top:16px; font-size:13px; }}
        .links a {{ color:#1f2d3a; text-decoration:none; margin-left:10px; }}
      </style>
    </head>
    <body>
      <div class="wrap">
        <div class="card">
          """ + _admin_status_bar() + f"""
          <h2>עדכון סיסמת מוסד</h2>
          <div style="margin-bottom:10px;">מוסד: <b>{row['name']}</b> ({row['tenant_id']})</div>
          <form method="post" action="/admin/institutions/password">
            <input type="hidden" name="tenant_id" value="{row['tenant_id']}" />
            <label>סיסמת מוסד חדשה</label>
            <input name="institution_password" type="password" required />
            <button type="submit">שמירה</button>
          </form>
          <div class="links">
            <a href="/admin/institutions">חזרה לרשימת מוסדות</a>
            <a href="/admin/logout">יציאה</a>
          </div>
        </div>
      </div>
    </body>
    </html>
    """


@app.post("/admin/institutions/password", response_class=HTMLResponse)
def admin_institution_password_submit(
    request: Request,
    tenant_id: str = Form(...),
    institution_password: str = Form(...),
    admin_key: str = ''
) -> str:
    guard = _admin_require(request, admin_key)
    if guard:
        return guard  # type: ignore[return-value]
    conn = _db()
    cur = conn.cursor()
    pw_hash = _pbkdf2_hash(institution_password.strip())
    cur.execute(_sql_placeholder('UPDATE institutions SET password_hash = ? WHERE tenant_id = ?'), (pw_hash, tenant_id.strip()))
    conn.commit()
    conn.close()
    return "<h3>סיסמת מוסד עודכנה.</h3><p><a href='/admin/institutions'>חזרה לרשימת מוסדות</a></p>"


@app.get("/api/students")
def api_students(
    request: Request,
    q: str = Query(default='', description="search"),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    tenant_id: str = Query(default='')
) -> Dict[str, Any]:
    guard = _web_require_teacher(request)
    if guard:
        return {"items": [], "limit": limit, "offset": offset, "query": q}
    active_tenant = _web_tenant_from_cookie(request)
    if active_tenant and tenant_id and tenant_id != active_tenant:
        return {"items": [], "limit": limit, "offset": offset, "query": q}
    conn = _tenant_school_db(active_tenant)
    cur = conn.cursor()
    query = """
        SELECT id, serial_number, last_name, first_name, class_name, points, private_message,
               card_number, id_number, photo_number
        FROM students
    """
    params: List[Any] = []
    if q:
        query += " WHERE first_name LIKE ? OR last_name LIKE ? OR class_name LIKE ? OR id_number LIKE ?"
        like = f"%{q.strip()}%"
        params.extend([like, like, like, like])
    query += " ORDER BY (serial_number IS NULL OR serial_number = 0), serial_number, class_name, last_name, first_name"
    query += " LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    cur.execute(_sql_placeholder(query), params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return {
        "items": rows,
        "limit": limit,
        "offset": offset,
        "query": q,
    }


@app.post("/api/students/update")
def api_student_update(request: Request, payload: StudentUpdatePayload) -> Dict[str, Any]:
    guard = _web_require_teacher(request)
    if guard:
        raise HTTPException(status_code=401, detail='not authorized')
    tenant_id = _web_tenant_from_cookie(request)
    if not tenant_id:
        raise HTTPException(status_code=401, detail='missing tenant')
    sid = int(payload.student_id or 0)
    if sid <= 0:
        raise HTTPException(status_code=400, detail='invalid student_id')

    points = payload.points
    private_message = payload.private_message

    conn = _tenant_school_db(tenant_id)
    try:
        cur = conn.cursor()
        sets = []
        params: List[Any] = []
        if points is not None:
            sets.append('points = ?')
            params.append(int(points))
        if private_message is not None:
            sets.append('private_message = ?')
            params.append(str(private_message))
        if not sets:
            return {'ok': True, 'updated': False}
        sets.append('updated_at = CURRENT_TIMESTAMP')
        sql = 'UPDATE students SET ' + ', '.join(sets) + ' WHERE id = ?'
        params.append(int(sid))
        cur.execute(_sql_placeholder(sql), params)
        conn.commit()
        return {'ok': True, 'updated': True}
    finally:
        try:
            conn.close()
        except Exception:
            pass


@app.get("/web/admin", response_class=HTMLResponse)
def web_admin(request: Request):
    guard = _web_require_teacher(request)
    if guard:
        return guard
    tenant_id = _web_tenant_from_cookie(request)
    tenant_json = json.dumps(str(tenant_id or ''))
    js = """
      <script>
        const rowsEl = document.getElementById('rows');
        const statusEl = document.getElementById('status');
        const searchEl = document.getElementById('search');
        const selectedEl = document.getElementById('selected');
        const btnEditPoints = document.getElementById('btnEditPoints');
        const btnEditMsg = document.getElementById('btnEditMsg');
        let selectedId = null;
        let timer = null;

        function setSelected(id) {
          selectedId = id;
          const on = (selectedId !== null);
          btnEditPoints.style.opacity = on ? '1' : '.55';
          btnEditMsg.style.opacity = on ? '1' : '.55';
          btnEditPoints.style.pointerEvents = on ? 'auto' : 'none';
          btnEditMsg.style.pointerEvents = on ? 'auto' : 'none';
          selectedEl.textContent = on ? `נבחר תלמיד ID ${selectedId}` : 'לא נבחר תלמיד';
          document.querySelectorAll('tr[data-id]').forEach(tr => {
            tr.style.outline = (String(tr.getAttribute('data-id')) === String(selectedId)) ? '2px solid #1abc9c' : 'none';
          });
        }

        async function updateStudent(patch) {
          if (!selectedId) return;
          const resp = await fetch('/api/students/update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ student_id: selectedId, ...patch })
          });
          if (!resp.ok) {
            const txt = await resp.text();
            alert('שגיאה בעדכון: ' + txt);
            return;
          }
          await load();
        }

        async function load() {
          statusEl.textContent = 'טוען...';
          const q = encodeURIComponent(searchEl.value || '');
          const resp = await fetch(`/api/students?q=${q}`);
          const data = await resp.json();
          rowsEl.innerHTML = data.items.map(r => `
            <tr data-id="${r.id}">
              <td style="padding:8px;border-top:1px solid #e8eef2;">${r.serial_number ?? ''}</td>
              <td style="padding:8px;border-top:1px solid #e8eef2;">${r.last_name ?? ''}</td>
              <td style="padding:8px;border-top:1px solid #e8eef2;">${r.first_name ?? ''}</td>
              <td style="padding:8px;border-top:1px solid #e8eef2;">${r.class_name ?? ''}</td>
              <td style="padding:8px;border-top:1px solid #e8eef2;">${r.points ?? ''}</td>
              <td style="padding:8px;border-top:1px solid #e8eef2;">${r.private_message ?? ''}</td>
              <td style="padding:8px;border-top:1px solid #e8eef2;">${r.id_number ?? ''}</td>
              <td style="padding:8px;border-top:1px solid #e8eef2;">${r.card_number ?? ''}</td>
            </tr>`).join('');
          statusEl.textContent = `נטענו ${data.items.length} תלמידים`;

          document.querySelectorAll('tr[data-id]').forEach(tr => {
            tr.addEventListener('click', () => setSelected(tr.getAttribute('data-id')));
          });
          if (selectedId) {
            setSelected(selectedId);
          }
        }
        searchEl.addEventListener('input', () => {
          clearTimeout(timer);
          timer = setTimeout(load, 300);
        });

        btnEditPoints.addEventListener('click', async () => {
          if (!selectedId) return;
          const val = prompt('נקודות חדשות:');
          if (val === null) return;
          const n = parseInt(val, 10);
          if (Number.isNaN(n)) { alert('ערך לא תקין'); return; }
          await updateStudent({ points: n });
        });

        btnEditMsg.addEventListener('click', async () => {
          if (!selectedId) return;
          const val = prompt('הודעה פרטית (ריק למחיקה):');
          if (val === null) return;
          await updateStudent({ private_message: String(val) });
        });

        load();
      </script>
    """
    return f"""
    <!doctype html>
    <html lang="he">
    <head>
      <meta charset="utf-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      <title>SchoolPoints - ניהול</title>
      <style>
        :root {{ --navy:#2f3e4e; --bg:#eef2f4; --line:#d6dde3; --tab:#ecf0f1; --accent:#1abc9c; }}
        body {{ margin:0; font-family:"Segoe UI", Arial, sans-serif; background:var(--bg); color:#1f2d3a; direction:rtl; }}
        .wrap {{ max-width:1180px; margin:18px auto; padding:0 16px 24px; }}
        .titlebar {{ background:var(--navy); color:#fff; padding:14px 16px; border-radius:8px; display:flex; justify-content:space-between; align-items:center; }}
        .titlebar h2 {{ margin:0; font-size:20px; }}
        .tabs {{ margin:10px 0; display:flex; gap:6px; flex-wrap:wrap; }}
        .tab {{ background:var(--tab); padding:6px 10px; border-radius:4px; font-size:12px; text-decoration:none; color:#1f2d3a; border:1px solid var(--line); }}
        .actions a {{ padding:8px 12px; border:1px solid var(--line); border-radius:6px; background:#fff; text-decoration:none; color:#1f2d3a; font-weight:600; }}
        .btn-green {{ background:#2ecc71; color:#fff; border-color:#27ae60; }}
        .btn-blue {{ background:#3498db; color:#fff; border-color:#2c80ba; }}
        .btn-orange {{ background:#f39c12; color:#fff; border-color:#d68910; }}
        .btn-purple {{ background:#8e44ad; color:#fff; border-color:#7d3c98; }}
        .btn-gray {{ background:#95a5a6; color:#fff; border-color:#7f8c8d; }}
        .footerbar {{ margin-top:12px; display:flex; gap:8px; flex-wrap:wrap; justify-content:flex-end; }}
        .card {{ background:#fff; border-radius:8px; border:1px solid var(--line); box-shadow:0 6px 16px rgba(40,55,70,.08); padding:12px; }}
        table {{ width:100%; border-collapse:collapse; font-size:13px; }}
        th, td {{ padding:8px; border-bottom:1px solid #e3e9ee; text-align:right; }}
        th {{ background:#f6f8f9; }}
        tbody tr:nth-child(even) {{ background:#f3f6f8; }}
        .searchbar {{ margin:10px 0; display:flex; align-items:center; gap:8px; flex-wrap:wrap; }}
        .searchbar input, .searchbar select {{ padding:6px 8px; border:1px solid var(--line); border-radius:6px; }}
      </style>
    </head>
    <body>
      <div class="wrap">
        <div class="titlebar">
          <h2>עמדת ניהול – ווב</h2>
          <span>מערכת ניהול נקודות · <a href="/web/logout" style="color:#fff;">יציאה</a></span>
        </div>
        <div class="tabs">
          <a class="tab" href="/web/admin">תלמידים</a>
          <a class="tab" href="/web/upgrades">שדרוגים</a>
          <a class="tab" href="/web/messages">הודעות</a>
          <a class="tab" href="/web/special-bonus">בונוס מיוחד</a>
          <a class="tab" href="/web/time-bonus">בונוס זמנים</a>
          <a class="tab" href="/web/teachers">ניהול מורים</a>
          <a class="tab" href="/web/system-settings">הגדרות מערכת</a>
          <a class="tab" href="/web/display-settings">הגדרות תצוגה</a>
          <a class="tab" href="/web/bonuses">בונוסים</a>
          <a class="tab" href="/web/holidays">חגים/חופשות</a>
          <a class="tab" href="/web/logs">לוגים</a>
        </div>
        <div class="actions" style="display:flex;gap:10px;flex-wrap:wrap;margin:10px 0 14px;">
          <a class="btn-green" href="/web/students/new">➕ הוסף תלמיד</a>
          <a class="btn-blue" href="/web/students/edit">✏️ ערוך תלמיד</a>
          <a class="btn-orange" href="/web/students/delete">🗑️ מחיקת תלמיד</a>
          <a class="btn-purple" href="/web/import">⬆️ ייבוא אקסל</a>
          <a class="btn-gray" href="/web/export">⬇️ ייצוא אקסל</a>
        </div>
        <div class="searchbar">
          <label>מוסד פעיל:</label>
          <input value="" id="tenant" disabled style="min-width:160px;" />
          <input id="search" placeholder="חיפוש" />
          <span id="status" style="color:#637381;">טוען...</span>
        </div>
        <div class="actions" style="display:flex;gap:10px;flex-wrap:wrap;margin:0 0 10px;align-items:center;">
          <a class="btn-blue" id="btnEditPoints" style="opacity:.55;pointer-events:none;" href="javascript:void(0)">✏️ ערוך נקודות</a>
          <a class="btn-blue" id="btnEditMsg" style="opacity:.55;pointer-events:none;" href="javascript:void(0)">✏️ ערוך הודעה</a>
          <span id="selected" style="color:#637381;">לא נבחר תלמיד</span>
        </div>
        <div class="card">
          <div style="overflow:auto;">
            <table>
              <thead>
                <tr>
                  <th>מס'</th>
                  <th>משפחה</th>
                  <th>פרטי</th>
                  <th>כיתה</th>
                  <th>נקודות</th>
                  <th>הודעה פרטית</th>
                  <th>ת.ז</th>
                  <th>כרטיס</th>
                </tr>
              </thead>
              <tbody id="rows"></tbody>
            </table>
          </div>
        </div>
        <div class="footerbar">
          <a class="btn-green" href="/web/students/new">➕ הוסף תלמיד</a>
          <a class="btn-blue" href="/web/students/edit">✏️ ערוך</a>
          <a class="btn-orange" href="/web/students/delete">🗑️ מחיקה</a>
          <a class="btn-purple" href="/web/import">⬆️ ייבוא</a>
          <a class="btn-gray" href="/web/export">⬇️ ייצוא</a>
        </div>
      </div>
      {js}
      <script>
        try {{
          document.getElementById('tenant').value = "";
          document.getElementById('tenant').value = {tenant_json};
        }} catch(e) {{}}
      </script>
    </body>
    </html>
    """


@app.post("/admin/setup", response_class=HTMLResponse)
def admin_setup_submit(
    request: Request,
    name: str = Form(...),
    tenant_id: str = Form(...),
    institution_password: str = Form(...),
    api_key: str = Form(default=''),
    admin_key: str = ''
) -> str:
    guard = _admin_require(request, admin_key)
    if guard:
        return guard  # type: ignore[return-value]
    conn = _db()
    cur = conn.cursor()
    api_key = api_key.strip() or secrets.token_urlsafe(16)
    pw_hash = _pbkdf2_hash(institution_password.strip())
    try:
        cur.execute(
            _sql_placeholder('INSERT INTO institutions (tenant_id, name, api_key, password_hash) VALUES (?, ?, ?, ?)'),
            (tenant_id.strip(), name.strip(), api_key, pw_hash)
        )
        conn.commit()
        _ensure_tenant_db_exists(tenant_id.strip())
        return f"<h3>Institution created.</h3><p>API Key: <b>{api_key}</b></p><p>עדכן ב־config.json: sync_api_key, sync_tenant_id</p>"
    except _integrity_errors():
        return "<h3>Tenant ID already exists.</h3>"
    finally:
        conn.close()


@app.get("/view/changes", response_class=HTMLResponse)
def view_changes(tenant_id: str, api_key: str) -> str:
    conn = _db()
    cur = conn.cursor()
    cur.execute(
        _sql_placeholder('SELECT id FROM institutions WHERE tenant_id = ? AND api_key = ? LIMIT 1'),
        (tenant_id, api_key)
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        return "<h3>Unauthorized</h3>"
    cur.execute(
        _sql_placeholder(
            '''
            SELECT received_at, station_id, entity_type, action_type, entity_id, payload_json
            FROM changes
            WHERE tenant_id = ?
            ORDER BY id DESC
            LIMIT 200
            '''
        ),
        (tenant_id,)
    )
    rows = cur.fetchall() or []
    conn.close()
    items = "".join(
        f"<tr><td>{r['received_at']}</td><td>{r['station_id'] or ''}</td><td>{r['entity_type']}</td><td>{r['action_type']}</td><td>{r['entity_id'] or ''}</td><td><pre>{r['payload_json'] or ''}</pre></td></tr>"
        for r in rows
    )
    return f"""
    <html><body>
    <h2>Recent Changes</h2>
    <table border="1" cellpadding="6">
    <tr><th>Received</th><th>Station</th><th>Type</th><th>Action</th><th>Entity</th><th>Payload</th></tr>
    {items}
    </table>
    </body></html>
    """
