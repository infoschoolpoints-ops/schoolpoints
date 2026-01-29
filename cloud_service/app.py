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
import urllib.parse
import datetime

try:
    import psycopg2
    import psycopg2.extras
except Exception:
    psycopg2 = None  # type: ignore[assignment]
    psycopg2_extras = None  # type: ignore[assignment]
from fastapi import FastAPI, Header, HTTPException, Form, Query, Request
from fastapi.responses import HTMLResponse, Response, RedirectResponse, FileResponse
from pydantic import BaseModel

try:
    import boto3
except Exception:
    boto3 = None  # type: ignore[assignment]

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

SPACES_REGION = str(os.getenv('SPACES_REGION') or '').strip()
SPACES_BUCKET = str(os.getenv('SPACES_BUCKET') or '').strip()
SPACES_ENDPOINT = str(os.getenv('SPACES_ENDPOINT') or '').strip()
SPACES_CDN_BASE_URL = str(os.getenv('SPACES_CDN_BASE_URL') or '').strip()
SPACES_KEY = str(os.getenv('SPACES_KEY') or '').strip()
SPACES_SECRET = str(os.getenv('SPACES_SECRET') or '').strip()

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


def _spaces_client():
    if boto3 is None:
        return None
    if not (SPACES_BUCKET and SPACES_ENDPOINT and SPACES_KEY and SPACES_SECRET):
        return None
    try:
        return boto3.client(
            's3',
            region_name=(SPACES_REGION or 'us-east-1'),
            endpoint_url=SPACES_ENDPOINT,
            aws_access_key_id=SPACES_KEY,
            aws_secret_access_key=SPACES_SECRET,
        )
    except Exception:
        return None


def _public_base_url(request: Request) -> str:
    try:
        proto = str(request.headers.get('x-forwarded-proto') or '').strip() or str(getattr(request.url, 'scheme', '') or '').strip() or 'https'
    except Exception:
        proto = 'https'
    try:
        host = str(request.headers.get('x-forwarded-host') or '').strip() or str(request.headers.get('host') or '').strip()
    except Exception:
        host = ''
    if not host:
        try:
            host = str(request.url.netloc or '').strip()
        except Exception:
            host = ''
    host = host.strip()
    if not host:
        return str(request.base_url).rstrip('/')
    return f"{proto}://{host}".rstrip('/')


def _integrity_errors():
    errs = [sqlite3.IntegrityError]
    try:
        if psycopg2 is not None:
            errs.append(psycopg2.IntegrityError)  # type: ignore[attr-defined]
    except Exception:
        pass
    return tuple(errs)


def _random_pair_code() -> str:
    # short human-friendly code (no ambiguous chars)
    alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    try:
        return ''.join(secrets.choice(alphabet) for _ in range(8))
    except Exception:
        return secrets.token_hex(4).upper()


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


def _ensure_device_pairings_table() -> None:
    conn = _db()
    try:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute(
                '''
                CREATE TABLE IF NOT EXISTS device_pairings (
                    id BIGSERIAL PRIMARY KEY,
                    code TEXT NOT NULL UNIQUE,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP NULL,
                    approved_at TIMESTAMP NULL,
                    consumed_at TIMESTAMP NULL,
                    tenant_id TEXT NULL,
                    api_key TEXT NULL,
                    push_url TEXT NULL
                )
                '''
            )
        else:
            cur.execute(
                '''
                CREATE TABLE IF NOT EXISTS device_pairings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT NOT NULL UNIQUE,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    expires_at TEXT,
                    approved_at TEXT,
                    consumed_at TEXT,
                    tenant_id TEXT,
                    api_key TEXT,
                    push_url TEXT
                )
                '''
            )
        conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass


@app.post('/api/device/pair/start')
def api_device_pair_start(request: Request) -> Dict[str, Any]:
    _ensure_device_pairings_table()
    code = _random_pair_code()
    conn = _db()
    try:
        cur = conn.cursor()
        # best-effort retry on rare collision
        for _ in range(4):
            try:
                cur.execute(
                    _sql_placeholder(
                        'INSERT INTO device_pairings (code) VALUES (?)'
                    ),
                    (code,)
                )
                conn.commit()
                break
            except _integrity_errors():
                code = _random_pair_code()
                continue
        verify_url = _public_base_url(request) + '/web/device/pair?code=' + code
        return {'ok': True, 'code': code, 'verify_url': verify_url}
    finally:
        try:
            conn.close()
        except Exception:
            pass


@app.get('/api/device/pair/poll')
def api_device_pair_poll(code: str = Query(default='')) -> Dict[str, Any]:
    _ensure_device_pairings_table()
    code = str(code or '').strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail='missing code')

    conn = _db()
    try:
        cur = conn.cursor()
        cur.execute(
            _sql_placeholder(
                'SELECT code, approved_at, consumed_at, tenant_id, api_key, push_url FROM device_pairings WHERE code = ? LIMIT 1'
            ),
            (code,)
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='invalid code')
        r = dict(row) if isinstance(row, dict) else {k: row[k] for k in row.keys()}  # type: ignore[attr-defined]
        if r.get('consumed_at'):
            return {'ok': True, 'status': 'consumed'}
        if not r.get('approved_at'):
            return {'ok': True, 'status': 'pending'}
        tenant_id = str(r.get('tenant_id') or '').strip()
        api_key = str(r.get('api_key') or '').strip()
        push_url = str(r.get('push_url') or '').strip()
        if not (tenant_id and api_key and push_url):
            return {'ok': True, 'status': 'pending'}

        # Mark consumed so creds are one-time delivery.
        try:
            cur.execute(
                _sql_placeholder('UPDATE device_pairings SET consumed_at = ' + _now_expr() + ' WHERE code = ?'),
                (code,)
            )
            conn.commit()
        except Exception:
            pass
        return {
            'ok': True,
            'status': 'ready',
            'tenant_id': tenant_id,
            'api_key': api_key,
            'push_url': push_url,
        }
    finally:
        try:
            conn.close()
        except Exception:
            pass


@app.get('/web/device/pair', response_class=HTMLResponse)
def web_device_pair(request: Request, code: str = Query(default='')) -> str:
    guard = _web_require_teacher(request)
    if guard:
        return guard  # type: ignore[return-value]
    code = str(code or '').strip().upper()
    if not code:
        body = "<h2>חיבור עמדה</h2><p>חסר קוד.</p><div class='actionbar'><a class='gray' href='/web/admin'>חזרה</a></div>"
        return _basic_web_shell('חיבור עמדה', body)
    body = f"""
    <h2>חיבור עמדה</h2>
    <p style='font-size:16px;font-weight:800;'>האם לאשר חיבור עמדה עם האתר?</p>
    <div style='margin-top:10px; padding:12px; border:1px solid #d6dde3; border-radius:12px; background:#f8fafc;'>
      <div style='font-weight:800; color:#2f3e4e;'>קוד התאמה:</div>
      <div style='font-size:26px;font-weight:950;letter-spacing:2px;margin-top:6px;'>{code}</div>
      <div style='margin-top:8px; font-size:13px; color:#637381; line-height:1.6;'>אשר/י רק אם התחלת עכשיו חיבור מתוך התוכנה בעמדת הניהול.</div>
    </div>
    <form method='post' action='/web/device/pair' style='margin-top:14px;'>
      <input type='hidden' name='code' value='{code}' />
      <button class='green' type='submit'>אישור חיבור</button>
    </form>
    <div class='actionbar'>
      <a class='gray' href='/web/admin'>חזרה</a>
    </div>
    """
    return _basic_web_shell('חיבור עמדה', body)


@app.post('/web/device/pair', response_class=HTMLResponse)
def web_device_pair_submit(request: Request, code: str = Form(...)) -> str:
    guard = _web_require_teacher(request)
    if guard:
        return guard  # type: ignore[return-value]
    _ensure_device_pairings_table()

    tenant_id = _web_tenant_from_cookie(request)
    if not tenant_id:
        return _basic_web_shell('חיבור עמדה', "<h2>חיבור עמדה</h2><p>חסר tenant.</p>")

    code = str(code or '').strip().upper()
    if not code:
        return _basic_web_shell('חיבור עמדה', "<h2>חיבור עמדה</h2><p>חסר קוד.</p>")

    # Fetch institution api_key
    conn = _db()
    try:
        cur = conn.cursor()
        cur.execute(
            _sql_placeholder('SELECT api_key FROM institutions WHERE tenant_id = ? LIMIT 1'),
            (tenant_id,)
        )
        row = cur.fetchone()
        if not row:
            return _basic_web_shell('חיבור עמדה', "<h2>חיבור עמדה</h2><p>לא נמצא מוסד.</p>")
        api_key = (row.get('api_key') if isinstance(row, dict) else row[0])
        api_key = str(api_key or '').strip()
        push_url = _public_base_url(request) + '/sync/push'

        try:
            cur.execute(
                _sql_placeholder(
                    'UPDATE device_pairings SET approved_at = ' + _now_expr() + ', tenant_id = ?, api_key = ?, push_url = ? WHERE code = ? AND consumed_at IS NULL'
                ),
                (tenant_id, api_key, push_url, code)
            )
            conn.commit()
        except Exception:
            pass
    finally:
        try:
            conn.close()
        except Exception:
            pass

    body = "<h2>חיבור עמדה</h2><p>אושר. אפשר לחזור לתוכנה המקומית.</p><div class='actionbar'><a class='green' href='/web/admin'>המשך</a></div>"
    return _basic_web_shell('חיבור עמדה', body)


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


def _web_next_from_request(request: Request, default: str = '/web/admin') -> str:
    try:
        q = request.query_params
        nxt = str(q.get('next') or '').strip()
    except Exception:
        nxt = ''
    if not nxt:
        return default
    # basic safety
    if not nxt.startswith('/'):
        return default
    return nxt


def _web_redirect_with_next(target: str, *, request: Request) -> RedirectResponse:
    try:
        nxt = str(request.url.path)
        if str(request.url.query or '').strip():
            nxt = nxt + '?' + str(request.url.query)
    except Exception:
        nxt = '/web/admin'
    try:
        encoded = urllib.parse.quote(str(nxt), safe='')
    except Exception:
        encoded = ''
    url = str(target)
    if encoded:
        url = url + ('&' if '?' in url else '?') + 'next=' + encoded
    return RedirectResponse(url=url, status_code=302)


def _web_require_login(request: Request) -> Response | None:
    if _web_auth_ok(request):
        return None
    return _web_redirect_with_next('/web/login', request=request)


def _web_require_tenant(request: Request) -> Response | None:
    tenant_id = _web_tenant_from_cookie(request)
    if tenant_id:
        return None
    return _web_redirect_with_next('/web/signin', request=request)


def _web_require_teacher(request: Request) -> Response | None:
    tenant_guard = _web_require_tenant(request)
    if tenant_guard:
        return tenant_guard
    if _web_teacher_from_cookie(request):
        return None
    return _web_redirect_with_next('/web/teacher-login', request=request)


def _web_require_admin_teacher(request: Request) -> Response | None:
    guard = _web_require_teacher(request)
    if guard:
        return guard
    teacher = _web_current_teacher(request) or {}
    if bool(_safe_int(teacher.get('is_admin'), 0) == 1):
        return None
    return HTMLResponse('<h3>אין הרשאה</h3><p>רק מנהל יכול לנהל מורים.</p><p><a href="/web/admin">חזרה</a></p>', status_code=403)


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
      <link rel="shortcut icon" href="/web/assets/icons/public.png" />
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
    teacher_name = ''
    is_admin = False
    if tenant_id:
        try:
            inst = _get_institution(tenant_id)
            if inst:
                inst_name = str(inst.get('name') or '').strip()
        except Exception:
            inst_name = ''

        if teacher_id:
            try:
                conn = _tenant_school_db(tenant_id)
                cur = conn.cursor()
                cur.execute(_sql_placeholder('SELECT name, is_admin FROM teachers WHERE id = ? LIMIT 1'), (int(str(teacher_id).strip() or '0'),))
                row = cur.fetchone()
                try:
                    conn.close()
                except Exception:
                    pass
                if row:
                    teacher_name = str((row.get('name') if isinstance(row, dict) else row['name']) or '').strip()
                    try:
                        is_admin = bool(int((row.get('is_admin') if isinstance(row, dict) else row['is_admin']) or 0) == 1)
                    except Exception:
                        is_admin = False
            except Exception:
                teacher_name = ''
                is_admin = False
    return {
        'tenant_id': tenant_id or '',
        'institution_name': str(inst_name or '').strip(),
        'teacher_id': teacher_id or '',
        'teacher_name': teacher_name,
        'is_admin': bool(is_admin),
        'is_logged_in': bool(tenant_id),
        'is_teacher': bool(teacher_id),
    }


@app.get('/api/classes')
def api_classes(request: Request) -> Dict[str, Any]:
    guard = _web_require_teacher(request)
    if guard:
        return {'items': []}
    tenant_id = _web_tenant_from_cookie(request)
    if not tenant_id:
        return {'items': []}
    teacher = _web_current_teacher(request)
    if not teacher:
        return {'items': []}
    teacher_id = _safe_int(teacher.get('id'), 0)
    is_admin = bool(_safe_int(teacher.get('is_admin'), 0) == 1)

    if not is_admin:
        classes = _web_teacher_allowed_classes(tenant_id, teacher_id)
        classes = [str(c).strip() for c in (classes or []) if str(c).strip()]
        classes.sort()
        return {'items': classes}

    conn = _tenant_school_db(tenant_id)
    try:
        cur = conn.cursor()
        cur.execute('SELECT DISTINCT class_name FROM students')
        rows = cur.fetchall() or []
        out: List[str] = []
        for r in rows:
            try:
                cn = (r.get('class_name') if isinstance(r, dict) else r['class_name'])
            except Exception:
                try:
                    cn = r[0]
                except Exception:
                    cn = ''
            cn = str(cn or '').strip()
            if cn:
                out.append(cn)
        out = sorted(set(out))
        return {'items': out}
    finally:
        try:
            conn.close()
        except Exception:
            pass


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


def _ensure_web_settings_table(conn) -> None:
    try:
        cur = conn.cursor()
        cur.execute(
            _sql_placeholder(
                '''
                CREATE TABLE IF NOT EXISTS web_settings (
                    key TEXT PRIMARY KEY,
                    value_json TEXT,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                '''
            )
        )
        try:
            cur.execute(_sql_placeholder('CREATE INDEX IF NOT EXISTS idx_web_settings_updated_at ON web_settings(updated_at)'))
        except Exception:
            pass
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass


def _get_web_setting_json(conn, key: str, default_json: str = '{}') -> str:
    try:
        _ensure_web_settings_table(conn)
    except Exception:
        pass
    try:
        cur = conn.cursor()
        cur.execute(_sql_placeholder('SELECT value_json FROM web_settings WHERE key = ? LIMIT 1'), (str(key or '').strip(),))
        row = cur.fetchone()
        if not row:
            return default_json
        val = (row.get('value_json') if isinstance(row, dict) else row[0])
        s = str(val or '').strip()
        return s if s else default_json
    except Exception:
        return default_json


def _set_web_setting_json(conn, key: str, value_json: str) -> None:
    try:
        _ensure_web_settings_table(conn)
    except Exception:
        pass
    cur = conn.cursor()
    k = str(key or '').strip()
    v = str(value_json or '').strip()
    cur.execute(
        _sql_placeholder(
            'INSERT INTO web_settings (key, value_json, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) '
            'ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_at = CURRENT_TIMESTAMP'
        ),
        (k, v)
    )
    conn.commit()


def _web_json_editor(title: str, key: str, value_json: str, hint: str, back_href: str = '/web/admin') -> str:
    safe_key = str(key or '').strip()
    safe_hint = str(hint or '').strip()
    safe_val = str(value_json or '').strip() or '{}'
    return f"""
    <style>
      textarea {{ width:100%; min-height: 240px; padding:12px; border:1px solid var(--line); border-radius:10px; font-size:13px; font-family: Consolas, monospace; direction:ltr; }}
      .hint {{ color:#637381; font-size:13px; line-height:1.8; margin: 8px 0 10px; }}
      .row {{ display:flex; gap:12px; flex-wrap:wrap; align-items:center; justify-content:flex-end; }}
      .row a {{ text-decoration:none; }}
      .btn {{
        padding:10px 16px;
        border-radius:12px;
        border:1px solid rgba(255,255,255,.18);
        font-weight:900;
        cursor:pointer;
        color:#fff;
        box-shadow:0 10px 22px rgba(0,0,0,.12);
        transition: transform .08s ease, filter .15s ease, box-shadow .15s ease, opacity .15s ease;
        opacity: .95;
        backdrop-filter: blur(8px);
        -webkit-backdrop-filter: blur(8px);
      }}
      .btn:hover {{ filter: brightness(1.03); opacity: 1; box-shadow:0 14px 26px rgba(0,0,0,.16); }}
      .btn:active {{ transform: translateY(1px) scale(.99); box-shadow:0 8px 16px rgba(0,0,0,.12); }}
      .btn-save {{ background: linear-gradient(135deg, #22c55e, #16a34a); }}
      .btn-back {{ background: linear-gradient(135deg, #94a3b8, #64748b); }}
      .btn-link {{ display:inline-flex; align-items:center; gap:8px; }}
    </style>
    <h2>{title}</h2>
    <div class="hint">{safe_hint}</div>
    <form method="post" action="/web/settings/save">
      <input type="hidden" name="setting_key" value="{safe_key}" />
      <input type="hidden" name="redirect_to" value="{back_href}" />
      <textarea name="value_json">{safe_val}</textarea>
      <div class="actionbar" style="justify-content:flex-end; gap:12px;">
        <button class="btn btn-save" type="submit">💾 שמירה</button>
        <a class="btn btn-back btn-link" href="{back_href}">↩️ חזרה</a>
      </div>
    </form>
    """


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
                    can_edit_student_card INTEGER DEFAULT 1,
                    can_edit_student_photo INTEGER DEFAULT 1,
                    bonus_max_points_per_student INTEGER,
                    bonus_max_total_runs INTEGER,
                    bonus_runs_used INTEGER DEFAULT 0,
                    bonus_runs_reset_date DATE,
                    bonus_points_used INTEGER DEFAULT 0,
                    bonus_points_reset_date DATE,
                    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                )
                '''
            )
            cur.execute(
                f'''
                CREATE TABLE IF NOT EXISTS "{schema}".teacher_classes (
                    id BIGSERIAL PRIMARY KEY,
                    teacher_id BIGINT NOT NULL,
                    class_name TEXT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(teacher_id, class_name)
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
                    serial_number TEXT,
                    photo_number TEXT,
                    private_message TEXT,
                    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                )
                '''
            )
            try:
                cur.execute(f'ALTER TABLE "{schema}".students ALTER COLUMN serial_number TYPE TEXT')
            except Exception:
                pass
            try:
                cur.execute(f'ALTER TABLE "{schema}".students ALTER COLUMN photo_number TYPE TEXT')
            except Exception:
                pass
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
            is_admin INTEGER DEFAULT 0,
            can_edit_student_card INTEGER DEFAULT 1,
            can_edit_student_photo INTEGER DEFAULT 1,
            bonus_max_points_per_student INTEGER,
            bonus_max_total_runs INTEGER,
            bonus_runs_used INTEGER DEFAULT 0,
            bonus_runs_reset_date TEXT,
            bonus_points_used INTEGER DEFAULT 0,
            bonus_points_reset_date TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        '''
    )
    cur.execute(
        '''
        CREATE TABLE IF NOT EXISTS teacher_classes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            teacher_id INTEGER NOT NULL,
            class_name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(teacher_id, class_name)
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
            serial_number TEXT,
            photo_number TEXT,
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
        tid = str(tenant_id or '').strip()
        if not _tenant_db_ready(tid):
            _ensure_tenant_db_exists(tid)
        schema = _tenant_schema(tid)
        conn = _db()
        cur = conn.cursor()
        cur.execute(f'SET search_path TO "{schema}", public')
        return conn
    db_path = _ensure_tenant_db_exists(tenant_id)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _tenant_db_ready(tenant_id: str) -> bool:
    tenant_id = str(tenant_id or '').strip()
    if not tenant_id:
        return False
    if USE_POSTGRES:
        schema = _tenant_schema(tenant_id)
        conn = _db()
        try:
            cur = conn.cursor()
            cur.execute(
                _sql_placeholder(
                    """
                    SELECT 1
                      FROM information_schema.tables
                     WHERE table_schema = ? AND table_name = 'students'
                     LIMIT 1
                    """
                ),
                (schema,)
            )
            return bool(cur.fetchone())
        except Exception:
            return False
        finally:
            try:
                conn.close()
            except Exception:
                pass
    try:
        return os.path.isfile(_tenant_school_db_path(tenant_id))
    except Exception:
        return False


@app.on_event("startup")
def _startup() -> None:
    _init_db()
    try:
        _ensure_device_pairings_table()
    except Exception:
        pass


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


def _fetch_table_rows(conn: sqlite3.Connection, table: str) -> List[Dict[str, Any]]:
    cols = _table_columns(conn, table)
    if not cols:
        return []
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT {','.join(cols)} FROM {table}")
        rows = cur.fetchall() or []
        return [dict(r) for r in rows]
    except Exception:
        return []


class StudentUpdatePayload(BaseModel):
    student_id: int
    points: int | None = None
    private_message: str | None = None
    card_number: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    class_name: str | None = None
    id_number: str | None = None
    serial_number: str | None = None
    photo_number: str | None = None


class StudentQuickUpdatePayload(BaseModel):
    operation: str
    points: int
    mode: str
    card_number: str | None = None
    serial_from: int | None = None
    serial_to: int | None = None
    class_names: List[str] | None = None
    student_ids: List[int] | None = None


class TeacherSavePayload(BaseModel):
    teacher_id: int | None = None
    name: str | None = None
    card_number: str | None = None
    card_number2: str | None = None
    card_number3: str | None = None
    is_admin: int | None = None
    can_edit_student_card: int | None = None
    can_edit_student_photo: int | None = None
    bonus_max_points_per_student: int | None = None
    bonus_max_total_runs: int | None = None


class TeacherDeletePayload(BaseModel):
    teacher_id: int


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


def _web_current_teacher(request: Request) -> Dict[str, Any] | None:
    tenant_id = _web_tenant_from_cookie(request)
    teacher_id = _web_teacher_from_cookie(request)
    if not tenant_id or not teacher_id:
        return None
    try:
        tid = int(str(teacher_id).strip() or '0')
    except Exception:
        tid = 0
    if tid <= 0:
        return None
    conn = _tenant_school_db(tenant_id)
    try:
        cur = conn.cursor()
        cur.execute(_sql_placeholder('SELECT id, name, is_admin FROM teachers WHERE id = ? LIMIT 1'), (int(tid),))
        row = cur.fetchone()
        if not row:
            return None
        return dict(row)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _web_teacher_allowed_classes(tenant_id: str, teacher_id: int) -> List[str]:
    conn = _tenant_school_db(tenant_id)
    try:
        cur = conn.cursor()
        cur.execute(
            _sql_placeholder('SELECT class_name FROM teacher_classes WHERE teacher_id = ? ORDER BY class_name ASC'),
            (int(teacher_id),)
        )
        rows = cur.fetchall() or []
        out: List[str] = []
        for r in rows:
            try:
                cn = (r.get('class_name') if isinstance(r, dict) else r['class_name'])
            except Exception:
                try:
                    cn = r[0]
                except Exception:
                    cn = ''
            cn = str(cn or '').strip()
            if cn:
                out.append(cn)
        return out
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _make_event_id(station_id: str | None, local_id: int | None, created_at: str | None) -> str:
    sid = _safe_str(station_id).strip() or 'unknown'
    lid = _safe_int(local_id, 0)
    ca = _safe_str(created_at).strip()
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


def _record_sync_event(
    *,
    tenant_id: str,
    station_id: str,
    entity_type: str,
    entity_id: str | None,
    action_type: str,
    payload: Dict[str, Any] | None,
    created_at: str | None = None,
) -> str:
    ev_id = _make_event_id(station_id, None, created_at)
    payload_json = None
    try:
        payload_json = json.dumps(payload or {}, ensure_ascii=False)
    except Exception:
        payload_json = '{}'

    conn = _db()
    try:
        cur = conn.cursor()
        # raw change log (admin visibility)
        try:
            cur.execute(
                _sql_placeholder(
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
            _sql_placeholder(
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

    present_keys: set[str] = set()
    for r in rows:
        try:
            present_keys.update((r or {}).keys())
        except Exception:
            pass
    cols = [c for c in existing_cols if c in allowed and c in present_keys]
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


@app.get('/sync/pull')
def sync_pull(
    request: Request,
    tenant_id: str = Query(default=''),
    since_id: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=2000),
    api_key: str = Header(default=''),
) -> Dict[str, Any]:
    tenant_id = str(tenant_id or '').strip()
    if not tenant_id:
        raise HTTPException(status_code=400, detail='missing tenant_id')
    api_key = _get_api_key(request, api_key).strip()
    if not api_key:
        raise HTTPException(status_code=401, detail='missing api_key')

    conn = _db()
    try:
        cur = conn.cursor()
        cur.execute(
            _sql_placeholder('SELECT id FROM institutions WHERE tenant_id = ? AND api_key = ? LIMIT 1'),
            (tenant_id, api_key)
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=401, detail='invalid api_key')

        cur.execute(
            _sql_placeholder(
                '''
                SELECT id, event_id, station_id, entity_type, entity_id, action_type, payload_json, created_at, received_at
                  FROM sync_events
                 WHERE tenant_id = ? AND id > ?
                 ORDER BY id ASC
                 LIMIT ?
                '''
            ),
            (tenant_id, int(since_id or 0), int(limit or 0))
        )
        rows = cur.fetchall() or []
        items = [dict(r) for r in rows]
        max_id = int(since_id or 0)
        for r in items:
            try:
                max_id = max(max_id, int(r.get('id') or 0))
            except Exception:
                pass
        return {
            'ok': True,
            'tenant_id': tenant_id,
            'since_id': int(since_id or 0),
            'next_since_id': int(max_id),
            'items': items,
        }
    finally:
        try:
            conn.close()
        except Exception:
            pass


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
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"snapshot failed: teachers replace: {e}")
        try:
            students_n = _replace_rows(tconn, 'students', payload.students or [])
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"snapshot failed: students replace: {e}")
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


@app.get('/sync/snapshot')
def sync_snapshot_get(
    request: Request,
    tenant_id: str = Query(default=''),
    api_key: str = Header(default=''),
) -> Dict[str, Any]:
    tenant_id = str(tenant_id or '').strip()
    if not tenant_id:
        raise HTTPException(status_code=400, detail='missing tenant_id')
    api_key = _get_api_key(request, api_key).strip()
    if not api_key:
        raise HTTPException(status_code=401, detail='missing api_key')

    conn = _db()
    try:
        cur = conn.cursor()
        cur.execute(
            _sql_placeholder('SELECT 1 FROM institutions WHERE tenant_id = ? AND api_key = ? LIMIT 1'),
            (tenant_id, api_key)
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=401, detail='invalid api_key')
    finally:
        try:
            conn.close()
        except Exception:
            pass

    tconn = _tenant_school_db(tenant_id)
    try:
        tables = [
            'teachers',
            'students',
            'messages',
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
            'web_settings',
        ]
        data: Dict[str, Any] = {}
        for t in tables:
            try:
                data[t] = _fetch_table_rows(tconn, t)
            except Exception:
                data[t] = []
        return {'ok': True, 'tenant_id': tenant_id, 'snapshot': data}
    finally:
        try:
            tconn.close()
        except Exception:
            pass


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
    <style>
      form { display:grid; grid-template-columns: 1fr; gap:10px; max-width: 520px; }
      label { font-weight:800; font-size:13px; }
      input { width:100%; padding:12px; border:1px solid var(--line); border-radius:10px; font-size:15px; background:#fff; }
      button { padding:12px 16px; border:none; border-radius:10px; background:var(--mint); color:#fff; font-weight:900; cursor:pointer; font-size:15px; }
      .hint { color:#637381; line-height:1.9; font-size:13px; }
    </style>
    <h2>החלפת סיסמה</h2>
    <div class="hint">כדי לשנות סיסמת מוסד יש להזין את הסיסמה הנוכחית ואת הסיסמה החדשה.</div>
    <form method="post" action="/web/account/password" style="margin-top:12px;">
      <label>סיסמה נוכחית</label>
      <input name="current_password" type="password" required />
      <label>סיסמה חדשה</label>
      <input name="new_password" type="password" required />
      <label>אימות סיסמה חדשה</label>
      <input name="new_password2" type="password" required />
      <button type="submit">שמירה</button>
    </form>
    <div class="actionbar" style="justify-content:flex-start;">
      <a class="gray" href="/web/account">חזרה</a>
    </div>
    """
    return _public_web_shell("החלפת סיסמה", body)


@app.post("/web/account/password", response_class=HTMLResponse)
def web_account_password_submit(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    new_password2: str = Form(...),
) -> str:
    tenant_id = _web_tenant_from_cookie(request)
    if not tenant_id:
        return _public_web_shell("החלפת סיסמה", "<h2>החלפת סיסמה</h2><p>יש להתחבר כדי להחליף סיסמה.</p>")

    if str(new_password or '') != str(new_password2 or ''):
        body = """
        <h2>שגיאה</h2>
        <p>הסיסמה החדשה ואימות הסיסמה לא תואמים.</p>
        <div class="actionbar" style="justify-content:flex-start;">
          <a class="gray" href="/web/account/password">חזרה</a>
        </div>
        """
        return _public_web_shell("החלפת סיסמה", body)

    conn = _db()
    try:
        cur = conn.cursor()
        cur.execute(
            _sql_placeholder('SELECT password_hash FROM institutions WHERE tenant_id = ? LIMIT 1'),
            (str(tenant_id).strip(),)
        )
        row = cur.fetchone()
        pw_hash = (row.get('password_hash') if isinstance(row, dict) else (row[0] if row else None))
        if not row or not str(pw_hash or '').strip():
            body = """
            <h2>שגיאה</h2>
            <p>לא נמצאה סיסמת מוסד. פנה למנהל המערכת.</p>
            <div class="actionbar" style="justify-content:flex-start;">
              <a class="gray" href="/web/account">חזרה</a>
            </div>
            """
            return _public_web_shell("החלפת סיסמה", body)

        if not _pbkdf2_verify(str(current_password or '').strip(), str(pw_hash)):
            body = """
            <h2>שגיאה</h2>
            <p>הסיסמה הנוכחית אינה תקינה.</p>
            <div class="actionbar" style="justify-content:flex-start;">
              <a class="gray" href="/web/account/password">נסה שוב</a>
            </div>
            """
            return _public_web_shell("החלפת סיסמה", body)

        new_hash = _pbkdf2_hash(str(new_password or '').strip())
        cur.execute(
            _sql_placeholder('UPDATE institutions SET password_hash = ? WHERE tenant_id = ?'),
            (str(new_hash), str(tenant_id).strip())
        )
        conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass

    body = """
    <h2>סיסמה עודכנה</h2>
    <p>הסיסמה נשמרה בהצלחה.</p>
    <div class="actionbar" style="justify-content:flex-start;">
      <a class="blue" href="/web/account">חזרה לאזור אישי</a>
      <a class="gray" href="/web/admin">ניהול</a>
    </div>
    """
    return _public_web_shell("החלפת סיסמה", body)


@app.get("/web/account/forgot", response_class=HTMLResponse)
def web_account_forgot(request: Request) -> str:
    body = """
    <h2>שכחתי סיסמה</h2>
    <p style="line-height:1.9; color:#637381;">
      כרגע שחזור סיסמה אוטומטי אינו זמין דרך הווב.
      כדי לאפס סיסמת מוסד יש לפנות למנהל המערכת / התמיכה.
    </p>
    <div class="actionbar" style="justify-content:flex-start;">
      <a class="blue" href="/web/contact">פנייה לתמיכה</a>
      <a class="gray" href="/web/account">חזרה</a>
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
    <p style="line-height:1.9; color:#637381;">
      תשלומים/חידוש רישיון מנוהלים כרגע דרך התמיכה.
      ניתן ליצור קשר ולקבל הצעה/קישור לתשלום.
    </p>
    <div class="actionbar" style="justify-content:flex-start;">
      <a class="blue" href="/web/pricing">לתמחור</a>
      <a class="blue" href="/web/contact">צור קשר</a>
      <a class="gray" href="/web/account">חזרה</a>
    </div>
    """
    return _public_web_shell("תשלומים", body)

@app.get("/web/pricing", response_class=HTMLResponse)
def web_pricing() -> str:
    body = f"""
    <div style="text-align:center;">
      <div style="font-size:26px;font-weight:950;">תמחור</div>
      <div style="margin-top:8px; color:#637381; line-height:1.9;">רכישה חד-פעמית או השכרה חודשית. מתאים גם לעבודה עונתית: <b>2 חודשים + אפשרות הארכה</b>.</div>
    </div>
    <div class="actionbar" style="justify-content:center;">
      <a class="green" href="/web/contact">צור קשר להצעה</a>
      <a class="blue" href="/web/signin">כניסה</a>
    </div>
    <div class="small" style="text-align:center;">build: {APP_BUILD_TAG}</div>
    """
    return _public_web_shell("תמחור", body)


@app.get("/web/contact", response_class=HTMLResponse)
def web_contact() -> str:
    body = f"""
    <div style="text-align:center;">
      <div style="font-size:22px;font-weight:900;">צור קשר</div>
      <div style="margin-top:8px; color:#637381;">נשמח לעזור. ניתן להשאיר פרטים ונחזור אליך.</div>
    </div>
    <form method="post" action="/web/contact" style="margin-top:14px;">
      <label>שם</label>
      <input name="name" required />
      <label>דוא"ל</label>
      <input name="email" type="email" required />
      <label>נושא</label>
      <input name="subject" required />
      <label>הודעה</label>
      <textarea name="message" required></textarea>
      <button type="submit">שליחה</button>
    </form>
    <div class="hint">build: {APP_BUILD_TAG}</div>
    """
    return _public_web_shell("צור קשר", body)


@app.post("/web/settings/save")
def web_settings_save(
    request: Request,
    setting_key: str = Form(...),
    value_json: str = Form(...),
    redirect_to: str = Form(default='/web/admin'),
) -> Response:
    guard = _web_require_teacher(request)
    if guard:
        return guard
    tenant_id = _web_tenant_from_cookie(request)
    if not tenant_id:
        return RedirectResponse(url="/web/login", status_code=302)

    k = str(setting_key or '').strip()
    v = str(value_json or '').strip()
    if not k:
        return RedirectResponse(url=str(redirect_to or '/web/admin'), status_code=302)
    # validate json (best effort)
    try:
        json.loads(v or '{}')
    except Exception:
        body = f"""
        <h2>שגיאה</h2>
        <p>הערך אינו JSON תקין.</p>
        <div class=\"actionbar\"><a class=\"gray\" href=\"{redirect_to or '/web/admin'}\">חזרה</a></div>
        """
        return HTMLResponse(_basic_web_shell("שגיאה", body))

    conn = _tenant_school_db(tenant_id)
    try:
        _set_web_setting_json(conn, k, v)
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return RedirectResponse(url=str(redirect_to or '/web/admin'), status_code=302)


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
    <style>
      .hero {{ display:flex; gap:18px; align-items:center; justify-content:space-between; flex-wrap:wrap; margin-bottom:14px; }}
      .brand {{ display:flex; gap:12px; align-items:center; }}
      .brand img {{ width:64px; height:64px; object-fit:contain; border-radius:12px; background:#fff; border:1px solid var(--line); box-shadow:0 6px 16px rgba(40,55,70,.08); }}
      .brand .t1 {{ font-size:22px; font-weight:900; letter-spacing:.5px; }}
      .brand .t2 {{ font-size:13px; color:#637381; margin-top:2px; }}
      .panel {{ display:grid; grid-template-columns: 1fr; gap:12px; }}
      form {{ display:grid; grid-template-columns: 1fr; gap:10px; max-width: 460px; margin: 6px auto 0; }}
      label {{ font-weight:700; font-size:13px; }}
      input {{ width:100%; padding:12px; border:1px solid var(--line); border-radius:10px; font-size:15px; background:#fff; }}
      button {{ padding:12px 16px; border:none; border-radius:10px; background:var(--mint); color:#fff; font-weight:800; cursor:pointer; font-size:15px; }}
      .hint {{ text-align:center; font-size:12px; color:#637381; margin-top:8px; }}
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
        <input type="hidden" name="next" value="/web/admin" />
        <label>קוד מוסד</label>
        <input name="tenant_id" placeholder="" required />
        <label>סיסמת מוסד</label>
        <input name="institution_password" type="password" required />
        <button type="submit">התחברות</button>
      </form>
      <div class="hint">build: {APP_BUILD_TAG}</div>
    </div>
    """
    return _public_web_shell("כניסה למערכת", body)


@app.get("/web/signin", response_class=HTMLResponse)
def web_signin(request: Request) -> str:
    nxt = _web_next_from_request(request, '/web/admin')
    body = f"""
    <style>
      .panel {{ display:grid; grid-template-columns: 1fr; gap:12px; }}
      form {{ display:grid; grid-template-columns: 1fr; gap:10px; max-width: 460px; margin: 6px auto 0; }}
      label {{ font-weight:700; font-size:13px; }}
      input {{ width:100%; padding:12px; border:1px solid var(--line); border-radius:10px; font-size:15px; background:#fff; }}
      button {{ padding:12px 16px; border:none; border-radius:10px; background:var(--mint); color:#fff; font-weight:800; cursor:pointer; font-size:15px; }}
      .hint {{ text-align:center; font-size:12px; color:#637381; margin-top:8px; }}
    </style>
    <div class="panel">
      <form method="post" action="/web/institution-login">
        <input type="hidden" name="next" value="{_safe_str(nxt)}" />
        <label>קוד מוסד</label>
        <input name="tenant_id" required />
        <label>סיסמת מוסד</label>
        <input name="institution_password" type="password" required />
        <button type="submit">התחברות</button>
      </form>
      <div class="hint">build: {APP_BUILD_TAG}</div>
    </div>
    """
    return _public_web_shell("כניסה למערכת", body)


@app.post("/web/institution-login", response_class=HTMLResponse)
def web_institution_login_submit(
    request: Request,
    tenant_id: str = Form(...),
    institution_password: str = Form(...),
    next: str = Form(default='/web/teacher-login'),
) -> Response:
    tid = str(tenant_id or '').strip()
    pw = str(institution_password or '').strip()
    conn = _db()
    try:
        cur = conn.cursor()
        cur.execute(
            _sql_placeholder('SELECT password_hash FROM institutions WHERE tenant_id = ? LIMIT 1'),
            (tid,)
        )
        row = cur.fetchone()
        pw_hash = (row.get('password_hash') if isinstance(row, dict) else (row[0] if row else None))
        if (not row) or (not str(pw_hash or '').strip()) or (not _pbkdf2_verify(pw, str(pw_hash))):
            body = """
            <h2>שגיאת התחברות</h2>
            <p>קוד מוסד או סיסמת מוסד לא תקינים.</p>
            <div class="actionbar" style="justify-content:flex-start;">
              <a class="blue" href="/web/signin">נסה שוב</a>
              <a class="gray" href="/web/login">חזרה</a>
            </div>
            """
            return HTMLResponse(_public_web_shell("כניסה למערכת", body), status_code=401)
    finally:
        try:
            conn.close()
        except Exception:
            pass

    try:
        nxt = str(next or '').strip()
    except Exception:
        nxt = ''
    if not nxt.startswith('/'):
        nxt = '/web/teacher-login'

    response = RedirectResponse(url=nxt, status_code=302)
    response.set_cookie("web_tenant", tid, httponly=True)
    response.delete_cookie("web_teacher")
    return response


@app.get("/web/teacher-login", response_class=HTMLResponse)
def web_teacher_login(request: Request) -> Response:
    guard = _web_require_tenant(request)
    if guard:
        return guard
    nxt = _web_next_from_request(request, '/web/admin')
    body = f"""
    <style>
      .panel {{ display:grid; grid-template-columns: 1fr; gap:12px; }}
      form {{ display:grid; grid-template-columns: 1fr; gap:10px; max-width: 460px; margin: 6px auto 0; }}
      label {{ font-weight:700; font-size:13px; }}
      input {{ width:100%; padding:12px; border:1px solid var(--line); border-radius:10px; font-size:15px; background:#fff; }}
      button {{ padding:12px 16px; border:none; border-radius:10px; background:var(--mint); color:#fff; font-weight:800; cursor:pointer; font-size:15px; }}
      .hint {{ text-align:center; font-size:12px; color:#637381; margin-top:8px; }}
    </style>
    <div class="panel">
      <form method="post" action="/web/teacher-login">
        <input type="hidden" name="next" value="{_safe_str(nxt)}" />
        <label>קוד / כרטיס מורה (או מנהל)</label>
        <input name="card_number" type="password" required />
        <button type="submit">כניסה</button>
      </form>
    </div>
    """
    return HTMLResponse(_public_web_shell("כניסה", body))


@app.post("/web/teacher-login", response_class=HTMLResponse)
def web_teacher_login_submit(request: Request, card_number: str = Form(...), next: str = Form(default='/web/admin')) -> Response:
    guard = _web_require_tenant(request)
    if guard:
        return guard
    tenant_id = _web_tenant_from_cookie(request)
    conn = _tenant_school_db(tenant_id)
    cur = conn.cursor()
    code = (card_number or '').strip()
    cur.execute(
        _sql_placeholder(
            'SELECT id, name, is_admin FROM teachers '
            'WHERE TRIM(COALESCE(card_number, \'\')) = ? '
            'OR TRIM(COALESCE(card_number2, \'\')) = ? '
            'OR TRIM(COALESCE(card_number3, \'\')) = ? '
            'LIMIT 1'
        ),
        (code, code, code)
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
    try:
        nxt = str(next or '').strip()
    except Exception:
        nxt = ''
    if not nxt.startswith('/'):
        nxt = '/web/admin'
    response = RedirectResponse(url=nxt, status_code=302)
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
      <link rel="shortcut icon" href="/web/assets/icons/public.png" />
      <style>
        :root {{ --navy:#2f3e4e; --mint:#1abc9c; --sky:#3498db; --bg:#eef2f4; --line:#d6dde3; --tab:#ecf0f1; }}
        body {{ margin:0; font-family: "Segoe UI", Arial, sans-serif; background:var(--bg); color:#1f2d3a; direction: rtl; }}
        .wrap {{ max-width: 1180px; margin: 24px auto; padding: 0 16px; }}
        .layout {{ display:flex; gap:14px; align-items:flex-start; }}
        .sidebar {{ width: 260px; position: sticky; top: 16px; }}
        .content {{ flex: 1; min-width: 0; }}
        .card {{ background:#fff; border-radius:10px; padding:20px; border:1px solid var(--line); box-shadow:0 6px 18px rgba(40,55,70,.08); }}
        .titlebar {{ background:var(--navy); color:#fff; padding:14px 18px; border-radius:10px 10px 0 0; margin:-20px -20px 16px; }}
        .titlebar h2 {{ margin:0; font-size:20px; }}
        .tabs {{ margin:6px 0 10px; display:flex; gap:6px; flex-wrap:wrap; }}
        .tab {{ background:var(--tab); padding:6px 10px; border-radius:4px; font-size:12px; text-decoration:none; color:#1f2d3a; border:1px solid var(--line); }}
        .nav {{ display:flex; flex-direction:column; gap:10px; }}
        .navgroup {{ background:#fff; border:1px solid var(--line); border-radius:12px; padding:12px; box-shadow:0 6px 18px rgba(40,55,70,.06); }}
        .navtitle {{ font-weight:900; color:#2f3e4e; margin:2px 0 10px; font-size:14px; }}
        .navbtn {{ display:block; text-decoration:none; color:#fff; padding:12px 14px; border-radius:12px; font-weight:900; font-size:14px; box-shadow:0 10px 22px rgba(0,0,0,.10); }}
        .navbtn:active {{ transform: translateY(1px); }}
        .navbtn.green {{ background: linear-gradient(135deg, #2ecc71, #1abc9c); }}
        .navbtn.blue {{ background: linear-gradient(135deg, #3498db, #2f80ed); }}
        .navbtn.purple {{ background: linear-gradient(135deg, #8e44ad, #5b2c83); }}
        .navbtn.orange {{ background: linear-gradient(135deg, #f39c12, #e67e22); }}
        .navbtn.gray {{ background: linear-gradient(135deg, #95a5a6, #7f8c8d); }}
        .navbtn.navy {{ background: linear-gradient(135deg, #2f3e4e, #22313f); }}
        .small {{ font-size:12px; opacity:.92; font-weight:700; }}
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
        @media (max-width: 980px) {{
          .layout {{ flex-direction: column; }}
          .sidebar {{ width: 100%; position: relative; top: auto; }}
          .nav {{ flex-direction: row; overflow:auto; padding-bottom: 6px; }}
          .navgroup {{ min-width: 320px; flex: 0 0 auto; }}
        }}
      </style>
    </head>
    <body>
      <div class="wrap">
        <div class="layout">
          <div class="sidebar">
            <div class="nav">
              <div class="navgroup">
                <div class="navtitle">ניהול</div>
                <a class="navbtn navy" href="/web/admin">תלמידים</a>
                <a class="navbtn blue" href="/web/teachers">ניהול מורים</a>
                <a class="navbtn orange" href="/web/cashier">קופה</a>
                <a class="navbtn gray" href="/web/reports">דוחות</a>
              </div>
              <div class="navgroup">
                <div class="navtitle">תצוגה ותוכן</div>
                <a class="navbtn blue" href="/web/display-settings">הגדרות תצוגה <span class="small">(צבעים/צלילים/מטבעות)</span></a>
                <a class="navbtn green" href="/web/messages">הודעות</a>
                <a class="navbtn purple" href="/web/special-bonus">בונוס מיוחד</a>
                <a class="navbtn purple" href="/web/time-bonus">בונוס זמנים</a>
                <a class="navbtn orange" href="/web/bonuses">בונוסים</a>
                <a class="navbtn orange" href="/web/holidays">חגים/חופשות</a>
              </div>
              <div class="navgroup">
                <div class="navtitle">מערכת</div>
                <a class="navbtn blue" href="/web/system-settings">הגדרות מערכת</a>
                <a class="navbtn gray" href="/web/logs">לוגים</a>
                <a class="navbtn gray" href="/web/upgrades">שדרוגים</a>
                <a class="navbtn gray" href="/web/logout">יציאה</a>
              </div>
            </div>
          </div>
          <div class="content">
            <div class="card">
              <div class="titlebar"><h2>{title}</h2></div>
              <div style="font-size:12px;color:#637381;margin-bottom:8px;">
                מוסדות: {status['inst_total']} | שינויים: {status['changes_total']} | שינוי אחרון: {status['last_received']}
              </div>
              {body_html}
              <div class="links">
                <a href="/web/admin">עמדת ניהול</a>
                <a href="/web/logout">יציאה</a>
              </div>
            </div>
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
    tenant_id = _web_tenant_from_cookie(request)
    conn = _tenant_school_db(tenant_id)
    try:
        value_json = _get_web_setting_json(conn, 'cashier_settings', '{\n  "enabled": true,\n  "items": []\n}')
    finally:
        try:
            conn.close()
        except Exception:
            pass
    body = _web_json_editor(
        "עמדת קופה",
        'cashier_settings',
        value_json,
        'הגדרות קופה (JSON). בהמשך יתווסף מסך ניהול מוצרים/קטגוריות והיסטוריה.',
        back_href='/web/admin',
    )
    return _basic_web_shell("עמדת קופה", body)


@app.get("/web/ads-media", response_class=HTMLResponse)
def web_ads_media(request: Request):
    guard = _web_require_teacher(request)
    if guard:
        return guard
    tenant_id = _web_tenant_from_cookie(request)
    conn = _tenant_school_db(tenant_id)
    try:
        value_json = _get_web_setting_json(conn, 'ads_media', '{\n  "items": []\n}')
    finally:
        try:
            conn.close()
        except Exception:
            pass
    editor = _web_json_editor(
        "מדיה / פרסומות",
        'ads_media',
        value_json,
        'רשימת מדיה/פרסומות להצגה בעמדות (JSON). בהמשך יתווסף ממשק העלאה ידידותי.',
        back_href='/web/messages',
    )
    body = editor + """
    <div class=\"actionbar\">
      <a class=\"blue\" href=\"/web/messages\">↩️ למסך הודעות</a>
    </div>
    """
    return _basic_web_shell("מדיה", body)


@app.get("/web/colors", response_class=HTMLResponse)
def web_colors(request: Request):
    guard = _web_require_teacher(request)
    if guard:
        return guard
    tenant_id = _web_tenant_from_cookie(request)
    conn = _tenant_school_db(tenant_id)
    try:
        value_json = _get_web_setting_json(conn, 'color_settings', '{\n  "ranges": []\n}')
    finally:
        try:
            conn.close()
        except Exception:
            pass
    body = _web_json_editor(
        "צבעים",
        'color_settings',
        value_json,
        'טווחי נקודות/צבעים (JSON). בהמשך יתווסף מסך עריכה ידידותי.',
        back_href='/web/display-settings',
    )
    return _basic_web_shell("צבעים", body)


@app.get("/web/sounds", response_class=HTMLResponse)
def web_sounds(request: Request):
    guard = _web_require_teacher(request)
    if guard:
        return guard
    tenant_id = _web_tenant_from_cookie(request)
    conn = _tenant_school_db(tenant_id)
    try:
        value_json = _get_web_setting_json(conn, 'sound_settings', '{\n  "enabled": true,\n  "items": []\n}')
    finally:
        try:
            conn.close()
        except Exception:
            pass
    body = _web_json_editor(
        "צלילים",
        'sound_settings',
        value_json,
        'הגדרות צלילים (JSON). בהמשך יתווסף ממשק העלאה ידידותי.',
        back_href='/web/display-settings',
    )
    return _basic_web_shell("צלילים", body)


@app.get("/web/coins", response_class=HTMLResponse)
def web_coins(request: Request):
    guard = _web_require_teacher(request)
    if guard:
        return guard
    tenant_id = _web_tenant_from_cookie(request)
    conn = _tenant_school_db(tenant_id)
    try:
        value_json = _get_web_setting_json(conn, 'coins_settings', '{\n  "coins": []\n}')
    finally:
        try:
            conn.close()
        except Exception:
            pass
    body = _web_json_editor(
        "מטבעות ויעדים",
        'coins_settings',
        value_json,
        'הגדרות מטבעות/יעדים (JSON). בהמשך יתווסף מסך עריכה ידידותי.',
        back_href='/web/display-settings',
    )
    return _basic_web_shell("מטבעות", body)


@app.get("/web/reports", response_class=HTMLResponse)
def web_reports(request: Request):
    guard = _web_require_teacher(request)
    if guard:
        return guard
    tenant_id = _web_tenant_from_cookie(request)
    conn = _tenant_school_db(tenant_id)
    try:
        value_json = _get_web_setting_json(conn, 'reports_settings', '{\n  "enabled": true\n}')
    finally:
        try:
            conn.close()
        except Exception:
            pass
    editor = _web_json_editor(
        "דוחות",
        'reports_settings',
        value_json,
        'הגדרות דוחות (JSON). ייצוא תלמידים (CSV) זמין כבר עכשיו.',
        back_href='/web/admin',
    )
    body = editor + """
    <div class=\"actionbar\">
      <a class=\"blue\" href=\"/web/export/download\">⬇️ ייצוא תלמידים (CSV)</a>
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
def web_student_edit(request: Request, student_id: int | None = Query(default=None)):
    guard = _web_require_teacher(request)
    if guard:
        return guard
    sid_val = ''
    sid_ro = ''
    try:
        if student_id is not None and int(student_id) > 0:
            sid_val = str(int(student_id))
            sid_ro = 'readonly'
    except Exception:
        sid_val = ''
        sid_ro = ''
    body = """
    <h2>עריכת תלמיד</h2>
    <form method="post">
      <label>מזהה תלמיד (ID)</label>
      <input name="student_id" placeholder="ID" required value=""" + sid_val + """" """ + sid_ro + """ />
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
    try:
        cur = conn.cursor()
        old_points = 0
        try:
            cur.execute(_sql_placeholder('SELECT points FROM students WHERE id = ? LIMIT 1'), (int(student_id),))
            row = cur.fetchone()
            if row:
                old_points = _safe_int((row.get('points') if isinstance(row, dict) else row['points']), 0)
        except Exception:
            old_points = 0

        new_points = int(points or 0)
        cur.execute(
            _sql_placeholder('UPDATE students SET points = ?, private_message = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?'),
            (int(new_points), private_message.strip(), int(student_id))
        )

        # points log (best effort)
        try:
            teacher = _web_current_teacher(request) or {}
            teacher_name = _safe_str(teacher.get('name') or '').strip() or 'web'
            delta = int(new_points - int(old_points))
            cur.execute(
                _sql_placeholder(
                    '''
                    INSERT INTO points_log (student_id, old_points, new_points, delta, reason, actor_name, action_type)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    '''
                ),
                (int(student_id), int(old_points), int(new_points), int(delta), 'ווב', str(teacher_name), 'עריכת תלמיד (ווב)')
            )
        except Exception:
            teacher_name = 'web'

        conn.commit()

        # record for pull (points only)
        try:
            _record_sync_event(
                tenant_id=str(tenant_id),
                station_id='web',
                entity_type='student_points',
                entity_id=str(int(student_id)),
                action_type='update',
                payload={
                    'old_points': int(old_points),
                    'new_points': int(new_points),
                    'reason': 'ווב',
                    'added_by': str(teacher_name),
                },
                created_at=None,
            )
        except Exception:
            pass
    finally:
        try:
            conn.close()
        except Exception:
            pass
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
    tenant_id = _web_tenant_from_cookie(request)
    conn = _tenant_school_db(tenant_id)
    try:
        value_json = _get_web_setting_json(conn, 'bonus_settings', '{\n  "bonuses": []\n}')
    finally:
        try:
            conn.close()
        except Exception:
            pass
    body = _web_json_editor(
        "בונוסים",
        'bonus_settings',
        value_json,
        'הגדרות בונוסים (JSON). בהמשך יתווסף מסך עריכה ידידותי.',
        back_href='/web/admin',
    )
    return _basic_web_shell("בונוסים", body)


@app.get("/web/holidays", response_class=HTMLResponse)
def web_holidays(request: Request):
    guard = _web_require_teacher(request)
    if guard:
        return guard
    tenant_id = _web_tenant_from_cookie(request)
    conn = _tenant_school_db(tenant_id)
    try:
        value_json = _get_web_setting_json(conn, 'holidays', '{\n  "items": []\n}')
    finally:
        try:
            conn.close()
        except Exception:
            pass
    body = _web_json_editor(
        "חגים וחופשות",
        'holidays',
        value_json,
        'הגדרות חגים/חופשות (JSON). בהמשך יתווסף מסך עריכה ידידותי.',
        back_href='/web/admin',
    )
    return _basic_web_shell("חגים וחופשות", body)


@app.get("/web/upgrades", response_class=HTMLResponse)
def web_upgrades(request: Request):
    guard = _web_require_teacher(request)
    if guard:
        return guard
    tenant_id = _web_tenant_from_cookie(request)
    conn = _tenant_school_db(tenant_id)
    try:
        value_json = _get_web_setting_json(conn, 'upgrades_settings', '{\n  "auto_update": false,\n  "channel": "stable"\n}')
    finally:
        try:
            conn.close()
        except Exception:
            pass
    body = _web_json_editor(
        "שדרוגים",
        'upgrades_settings',
        value_json,
        'הגדרות שדרוגים (JSON). בהמשך יתווספו העלאת גרסה וניהול גרסאות בפועל.',
        back_href='/web/admin',
    )
    return _basic_web_shell("שדרוגים", body)


@app.get("/web/messages", response_class=HTMLResponse)
def web_messages(request: Request):
    guard = _web_require_teacher(request)
    if guard:
        return guard
    tenant_id = _web_tenant_from_cookie(request)
    conn = _tenant_school_db(tenant_id)
    try:
        value_json = _get_web_setting_json(conn, 'messages', '{\n  "items": []\n}')
    finally:
        try:
            conn.close()
        except Exception:
            pass
    editor = _web_json_editor(
        "הודעות כלליות",
        'messages',
        value_json,
        'רשימת הודעות להצגה בעמדות (JSON). בהמשך יתווסף מסך עריכה ידידותי.',
        back_href='/web/admin',
    )
    body = editor + """
    <div class=\"actionbar\">
      <a class=\"purple\" href=\"/web/ads-media\">🖼️ מדיה / פרסומות</a>
    </div>
    """
    return _basic_web_shell("הודעות", body)


@app.get("/web/special-bonus", response_class=HTMLResponse)
def web_special_bonus(request: Request):
    guard = _web_require_teacher(request)
    if guard:
        return guard
    tenant_id = _web_tenant_from_cookie(request)
    conn = _tenant_school_db(tenant_id)
    try:
        value_json = _get_web_setting_json(conn, 'special_bonus', '{\n  "items": []\n}')
    finally:
        try:
            conn.close()
        except Exception:
            pass
    editor = _web_json_editor(
        "בונוס מיוחד",
        'special_bonus',
        value_json,
        'בונוס מיוחד (JSON). בהמשך יתווסף מסך יצירה ידידותי.',
        back_href='/web/bonuses',
    )
    body = editor + """
    <div class=\"actionbar\">
      <a class=\"blue\" href=\"/web/bonuses\">↩️ למסך בונוסים</a>
    </div>
    """
    return _basic_web_shell("בונוס מיוחד", body)


@app.get("/web/time-bonus", response_class=HTMLResponse)
def web_time_bonus(request: Request):
    guard = _web_require_teacher(request)
    if guard:
        return guard
    tenant_id = _web_tenant_from_cookie(request)
    conn = _tenant_school_db(tenant_id)
    try:
        value_json = _get_web_setting_json(conn, 'time_bonus', '{\n  "rules": []\n}')
    finally:
        try:
            conn.close()
        except Exception:
            pass
    editor = _web_json_editor(
        "בונוס זמנים",
        'time_bonus',
        value_json,
        'כללי בונוס לפי זמן (JSON). בהמשך יתווסף מסך עריכה ידידותי.',
        back_href='/web/holidays',
    )
    body = editor + """
    <div class=\"actionbar\">
      <a class=\"blue\" href=\"/web/holidays\">📅 חגים/חופשות</a>
    </div>
    """
    return _basic_web_shell("בונוס זמנים", body)


@app.get("/web/teachers", response_class=HTMLResponse)
def web_teachers(request: Request):
    guard = _web_require_admin_teacher(request)
    if guard:
        return guard
    js = """
      <script>
        const rowsEl = document.getElementById('t_rows');
        const statusEl = document.getElementById('t_status');
        const searchEl = document.getElementById('t_search');
        const selectedEl = document.getElementById('t_selected');
        const btnNew = document.getElementById('t_new');
        const btnEdit = document.getElementById('t_edit');
        const btnDelete = document.getElementById('t_delete');
        let selectedId = null;
        let timer = null;

        function setSelected(id) {
          selectedId = id;
          const on = (selectedId !== null);
          btnEdit.style.opacity = on ? '1' : '.55';
          btnDelete.style.opacity = on ? '1' : '.55';
          btnEdit.style.pointerEvents = on ? 'auto' : 'none';
          btnDelete.style.pointerEvents = on ? 'auto' : 'none';
          selectedEl.textContent = on ? `נבחר מורה ID ${selectedId}` : 'לא נבחר מורה';
          document.querySelectorAll('tr[data-id]').forEach(tr => {
            tr.style.outline = (String(tr.getAttribute('data-id')) === String(selectedId)) ? '2px solid #1abc9c' : 'none';
          });
        }

        async function load() {
          statusEl.textContent = 'טוען...';
          const q = encodeURIComponent(searchEl.value || '');
          const resp = await fetch(`/api/teachers?q=${q}`);
          const data = await resp.json();
          rowsEl.innerHTML = data.items.map(r => `
            <tr data-id="${r.id}">
              <td style="padding:8px;border-top:1px solid #e8eef2;">${r.id ?? ''}</td>
              <td style="padding:8px;border-top:1px solid #e8eef2;">${r.name ?? ''}</td>
              <td style="padding:8px;border-top:1px solid #e8eef2;direction:ltr;">${r.card_number ?? ''}</td>
              <td style="padding:8px;border-top:1px solid #e8eef2;direction:ltr;">${r.card_number2 ?? ''}</td>
              <td style="padding:8px;border-top:1px solid #e8eef2;direction:ltr;">${r.card_number3 ?? ''}</td>
              <td style="padding:8px;border-top:1px solid #e8eef2;">${(r.is_admin ? 'כן' : '')}</td>
            </tr>`).join('');
          statusEl.textContent = `נטענו ${data.items.length} מורים`;
          document.querySelectorAll('tr[data-id]').forEach(tr => {
            tr.addEventListener('click', () => setSelected(tr.getAttribute('data-id')));
          });
          if (selectedId) {
            setSelected(selectedId);
          }
        }

        async function save(payload) {
          const resp = await fetch('/api/teachers/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
          });
          if (!resp.ok) {
            const txt = await resp.text();
            alert('שגיאה: ' + txt);
            return;
          }
          await load();
        }

        async function del(teacher_id) {
          const resp = await fetch('/api/teachers/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ teacher_id: teacher_id })
          });
          if (!resp.ok) {
            const txt = await resp.text();
            alert('שגיאה: ' + txt);
            return;
          }
          selectedId = null;
          await load();
        }

        btnNew.addEventListener('click', async () => {
          const name = prompt('שם מורה:');
          if (name === null) return;
          const code = prompt('כרטיס/קוד מורה (ראשי):');
          if (code === null) return;
          const isAdmin = confirm('להגדיר כמנהל?') ? 1 : 0;
          await save({ name: String(name), card_number: String(code), is_admin: isAdmin });
        });

        btnEdit.addEventListener('click', async () => {
          if (!selectedId) return;
          const name = prompt('שם מורה (השאר ריק כדי לא לשנות):');
          if (name === null) return;
          const code1 = prompt('כרטיס/קוד 1 (השאר ריק כדי לא לשנות):');
          if (code1 === null) return;
          const code2 = prompt('כרטיס/קוד 2 (ריק כדי לא לשנות):');
          if (code2 === null) return;
          const code3 = prompt('כרטיס/קוד 3 (ריק כדי לא לשנות):');
          if (code3 === null) return;
          const isAdmin = confirm('להגדיר כמנהל?') ? 1 : 0;
          await save({ teacher_id: parseInt(selectedId, 10), name: String(name), card_number: String(code1), card_number2: String(code2), card_number3: String(code3), is_admin: isAdmin });
        });

        btnDelete.addEventListener('click', async () => {
          if (!selectedId) return;
          if (!confirm('למחוק מורה?')) return;
          await del(parseInt(selectedId, 10));
        });

        searchEl.addEventListener('input', () => {
          clearTimeout(timer);
          timer = setTimeout(load, 300);
        });

        load();
      </script>
    """

    body = """
    <style>
      table { width:100%; border-collapse:collapse; font-size:13px; }
      th, td { padding:8px; border-bottom:1px solid #e3e9ee; text-align:right; }
      th { background:#f6f8f9; }
      tbody tr:nth-child(even) { background:#f3f6f8; }
      .bar { margin:10px 0; display:flex; gap:10px; flex-wrap:wrap; align-items:center; }
      .bar input { padding:6px 8px; border:1px solid var(--line); border-radius:6px; }
      .btn { padding:8px 12px; border-radius:6px; color:#fff; text-decoration:none; border:none; font-weight:600; cursor:pointer; }
      .btn-green { background:#2ecc71; }
      .btn-blue { background:#3498db; }
      .btn-red { background:#e74c3c; }
    </style>
    <div class="bar">
      <input id="t_search" placeholder="חיפוש" />
      <span id="t_status" style="color:#637381;">טוען...</span>
    </div>
    <div class="bar">
      <button class="btn btn-green" id="t_new" type="button">➕ הוסף מורה</button>
      <button class="btn btn-blue" id="t_edit" type="button" style="opacity:.55;pointer-events:none;">✏️ עריכה</button>
      <button class="btn btn-red" id="t_delete" type="button" style="opacity:.55;pointer-events:none;">🗑️ מחיקה</button>
      <span id="t_selected" style="color:#637381;">לא נבחר מורה</span>
    </div>
    <div style="overflow:auto;">
      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>שם</th>
            <th>כרטיס 1</th>
            <th>כרטיס 2</th>
            <th>כרטיס 3</th>
            <th>מנהל</th>
          </tr>
        </thead>
        <tbody id="t_rows"></tbody>
      </table>
    </div>
    """
    return HTMLResponse(_basic_web_shell("ניהול מורים", body + js))


@app.get("/api/teachers")
def api_teachers(
    request: Request,
    q: str = Query(default='', description="search"),
    limit: int = Query(default=500, ge=1, le=2000),
    offset: int = Query(default=0, ge=0)
) -> Dict[str, Any]:
    guard = _web_require_admin_teacher(request)
    if guard:
        return {"items": [], "limit": limit, "offset": offset, "query": q}
    tenant_id = _web_tenant_from_cookie(request)
    conn = _tenant_school_db(tenant_id)
    cur = conn.cursor()
    query = """
        SELECT id, name, card_number, card_number2, card_number3, is_admin
        FROM teachers
    """
    params: List[Any] = []
    if q:
        like = f"%{q.strip()}%"
        query += " WHERE name LIKE ? OR card_number LIKE ? OR card_number2 LIKE ? OR card_number3 LIKE ?"
        params.extend([like, like, like, like])
    query += " ORDER BY id ASC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    cur.execute(_sql_placeholder(query), params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return {"items": rows, "limit": limit, "offset": offset, "query": q}


@app.post("/api/teachers/save")
def api_teachers_save(request: Request, payload: TeacherSavePayload) -> Dict[str, Any]:
    guard = _web_require_admin_teacher(request)
    if guard:
        raise HTTPException(status_code=401, detail='not authorized')
    tenant_id = _web_tenant_from_cookie(request)
    if not tenant_id:
        raise HTTPException(status_code=401, detail='missing tenant')
    conn = _tenant_school_db(tenant_id)
    try:
        cur = conn.cursor()
        tid = payload.teacher_id
        if tid is None or int(tid or 0) <= 0:
            cur.execute('SELECT COALESCE(MAX(id), 0) AS m FROM teachers')
            r = cur.fetchone() or {}
            max_id = int((r.get('m') if isinstance(r, dict) else r[0]) or 0)
            tid = max_id + 1
            cur.execute(
                _sql_placeholder(
                    'INSERT INTO teachers (id, name, card_number, card_number2, card_number3, is_admin) VALUES (?, ?, ?, ?, ?, ?)'
                ),
                (
                    int(tid),
                    str(payload.name or '').strip(),
                    str(payload.card_number or '').strip(),
                    str(payload.card_number2 or '').strip(),
                    str(payload.card_number3 or '').strip(),
                    int(payload.is_admin or 0),
                )
            )
            conn.commit()
            return {'ok': True, 'created': True, 'teacher_id': int(tid)}

        sets = []
        params: List[Any] = []
        if payload.name is not None:
            sets.append('name = ?')
            params.append(str(payload.name).strip())
        if payload.card_number is not None:
            sets.append('card_number = ?')
            params.append(str(payload.card_number).strip())
        if payload.card_number2 is not None:
            sets.append('card_number2 = ?')
            params.append(str(payload.card_number2).strip())
        if payload.card_number3 is not None:
            sets.append('card_number3 = ?')
            params.append(str(payload.card_number3).strip())
        if payload.is_admin is not None:
            sets.append('is_admin = ?')
            params.append(int(payload.is_admin))
        if not sets:
            return {'ok': True, 'updated': False, 'teacher_id': int(tid)}
        sets.append('updated_at = CURRENT_TIMESTAMP')
        sql = 'UPDATE teachers SET ' + ', '.join(sets) + ' WHERE id = ?'
        params.append(int(tid))
        cur.execute(_sql_placeholder(sql), params)
        conn.commit()
        return {'ok': True, 'updated': True, 'teacher_id': int(tid)}
    finally:
        try:
            conn.close()
        except Exception:
            pass


@app.post("/api/teachers/delete")
def api_teachers_delete(request: Request, payload: TeacherDeletePayload) -> Dict[str, Any]:
    guard = _web_require_admin_teacher(request)
    if guard:
        raise HTTPException(status_code=401, detail='not authorized')
    tenant_id = _web_tenant_from_cookie(request)
    if not tenant_id:
        raise HTTPException(status_code=401, detail='missing tenant')
    conn = _tenant_school_db(tenant_id)
    try:
        cur = conn.cursor()
        cur.execute(_sql_placeholder('DELETE FROM teachers WHERE id = ?'), (int(payload.teacher_id),))
        conn.commit()
        return {'ok': True}
    finally:
        try:
            conn.close()
        except Exception:
            pass


@app.get("/web/system-settings", response_class=HTMLResponse)
def web_system_settings(request: Request):
    guard = _web_require_teacher(request)
    if guard:
        return guard
    tenant_id = _web_tenant_from_cookie(request)
    conn = _tenant_school_db(tenant_id)
    try:
        value_json = _get_web_setting_json(conn, 'system_settings', '{\n  "deployment_mode": "hybrid",\n  "shared_folder": "",\n  "logo_path": ""\n}')
    finally:
        try:
            conn.close()
        except Exception:
            pass
    body = _web_json_editor(
        "הגדרות מערכת",
        'system_settings',
        value_json,
        'הגדרות מערכת כלליות (JSON). בהמשך יתווספו מסכים ייעודיים לתיקייה משותפת/לוגו/נתיבים.',
        back_href='/web/admin',
    )
    return _basic_web_shell("הגדרות מערכת", body)


@app.get("/web/display-settings", response_class=HTMLResponse)
def web_display_settings(request: Request):
    guard = _web_require_teacher(request)
    if guard:
        return guard
    tenant_id = _web_tenant_from_cookie(request)
    conn = _tenant_school_db(tenant_id)
    try:
        value_json = _get_web_setting_json(conn, 'display_settings', '{\n  "enabled": true\n}')
    finally:
        try:
            conn.close()
        except Exception:
            pass
    editor = _web_json_editor(
        "הגדרות תצוגה",
        'display_settings',
        value_json,
        'הגדרות תצוגה כלליות (JSON). לעריכה של צבעים/צלילים/מטבעות/חגים השתמש בכפתורים למטה.',
        back_href='/web/admin',
    )
    body = editor + """
    <div class=\"actionbar\">
      <a class=\"blue\" href=\"/web/colors\">🎨 צבעים</a>
      <a class=\"blue\" href=\"/web/sounds\">🔊 צלילים</a>
      <a class=\"blue\" href=\"/web/coins\">🪙 מטבעות</a>
      <a class=\"blue\" href=\"/web/holidays\">📅 חגים/חופשות</a>
    </div>
    """
    return _basic_web_shell("הגדרות תצוגה", body)


@app.get("/web/logs", response_class=HTMLResponse)
def web_logs(request: Request):
    guard = _web_require_teacher(request)
    if guard:
        return guard
    tenant_id = _web_tenant_from_cookie(request)
    conn = _tenant_school_db(tenant_id)
    try:
        value_json = _get_web_setting_json(conn, 'log_settings', '{\n  "retention_days": 30\n}')
    finally:
        try:
            conn.close()
        except Exception:
            pass
    body = _web_json_editor(
        "לוגים",
        'log_settings',
        value_json,
        'הגדרות לוגים (JSON). בהמשך יתווספו הורדה/ניקוי בפועל.',
        back_href='/web/admin',
    )
    return _basic_web_shell("לוגים", body)


@app.get("/web/settings", response_class=HTMLResponse)
def web_settings(request: Request):
    guard = _web_require_teacher(request)
    if guard:
        return guard
    tenant_id = _web_tenant_from_cookie(request)
    conn = _tenant_school_db(tenant_id)
    try:
        value_json = _get_web_setting_json(conn, 'settings', '{\n  "notes": ""\n}')
    finally:
        try:
            conn.close()
        except Exception:
            pass
    body = _web_json_editor(
        "הגדרות",
        'settings',
        value_json,
        'הגדרות כלליות (JSON). עמוד זה מחליף placeholder ונותן מקום לשמור הגדרות נוספות בווב.',
        back_href='/web/admin',
    )
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
    if USE_POSTGRES:
        query += (
            " ORDER BY "
            "(serial_number IS NULL OR BTRIM(serial_number) = '' OR serial_number = '0'), "
            "(CASE WHEN serial_number ~ '^[0-9]+$' THEN serial_number::BIGINT ELSE 9223372036854775807 END), "
            "class_name, last_name, first_name"
        )
    else:
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
    card_number = payload.card_number
    first_name = payload.first_name
    last_name = payload.last_name
    class_name = payload.class_name
    id_number = payload.id_number
    serial_number = payload.serial_number
    photo_number = payload.photo_number

    conn = _tenant_school_db(tenant_id)
    try:
        cur = conn.cursor()
        old_points: int | None = None
        if points is not None:
            try:
                cur.execute(_sql_placeholder('SELECT points FROM students WHERE id = ? LIMIT 1'), (int(sid),))
                row = cur.fetchone()
                if row:
                    old_points = _safe_int((row.get('points') if isinstance(row, dict) else row['points']), 0)
            except Exception:
                old_points = None
        sets = []
        params: List[Any] = []
        if points is not None:
            sets.append('points = ?')
            params.append(int(points))
        if private_message is not None:
            sets.append('private_message = ?')
            params.append(str(private_message))
        if card_number is not None:
            sets.append('card_number = ?')
            params.append(str(card_number).strip())
        if first_name is not None:
            sets.append('first_name = ?')
            params.append(str(first_name).strip())
        if last_name is not None:
            sets.append('last_name = ?')
            params.append(str(last_name).strip())
        if class_name is not None:
            sets.append('class_name = ?')
            params.append(str(class_name).strip())
        if id_number is not None:
            sets.append('id_number = ?')
            params.append(str(id_number).strip())
        if serial_number is not None:
            sets.append('serial_number = ?')
            params.append(str(serial_number).strip())
        if photo_number is not None:
            sets.append('photo_number = ?')
            params.append(str(photo_number).strip())
        if not sets:
            return {'ok': True, 'updated': False}
        sets.append('updated_at = CURRENT_TIMESTAMP')
        sql = 'UPDATE students SET ' + ', '.join(sets) + ' WHERE id = ?'
        params.append(int(sid))
        cur.execute(_sql_placeholder(sql), params)
        conn.commit()

        # record event for pull (points only for now)
        if points is not None:
            try:
                teacher = _web_current_teacher(request) or {}
                teacher_name = _safe_str(teacher.get('name') or '').strip() or 'web'
                old_p = int(old_points or 0)
                new_p = int(points)
                _record_sync_event(
                    tenant_id=str(tenant_id),
                    station_id='web',
                    entity_type='student_points',
                    entity_id=str(int(sid)),
                    action_type='update',
                    payload={
                        'old_points': int(old_p),
                        'new_points': int(new_p),
                        'reason': 'ווב',
                        'added_by': str(teacher_name),
                    },
                    created_at=None,
                )
            except Exception:
                pass
        return {'ok': True, 'updated': True}
    finally:
        try:
            conn.close()
        except Exception:
            pass


class StudentPointsDeltaPayload(BaseModel):
    student_id: int
    delta: int
    reason: str | None = None


@app.post('/api/students/points-delta')
def api_students_points_delta(request: Request, payload: StudentPointsDeltaPayload) -> Dict[str, Any]:
    guard = _web_require_teacher(request)
    if guard:
        raise HTTPException(status_code=401, detail='not authorized')
    tenant_id = _web_tenant_from_cookie(request)
    if not tenant_id:
        raise HTTPException(status_code=401, detail='missing tenant')
    sid = int(payload.student_id or 0)
    delta = int(payload.delta or 0)
    if sid <= 0 or delta == 0:
        raise HTTPException(status_code=400, detail='invalid payload')

    conn = _tenant_school_db(tenant_id)
    try:
        cur = conn.cursor()
        cur.execute(_sql_placeholder('SELECT points FROM students WHERE id = ? LIMIT 1'), (sid,))
        row = cur.fetchone()
        old_p = _safe_int((row.get('points') if isinstance(row, dict) else (row['points'] if row else 0)), 0) if row else 0
        new_p = int(old_p) + int(delta)
        cur.execute(_sql_placeholder('UPDATE students SET points = ? WHERE id = ?'), (int(new_p), int(sid)))
        conn.commit()

        try:
            teacher = _web_current_teacher(request) or {}
            teacher_name = _safe_str(teacher.get('name') or '').strip() or 'web'
            _record_sync_event(
                tenant_id=str(tenant_id),
                station_id='web',
                entity_type='student_points',
                entity_id=str(int(sid)),
                action_type='update',
                payload={
                    'old_points': int(old_p),
                    'new_points': int(new_p),
                    'reason': str(payload.reason or '').strip() or 'ווב',
                    'added_by': str(teacher_name),
                },
                created_at=None,
            )
        except Exception:
            pass

        return {'ok': True, 'student_id': int(sid), 'old_points': int(old_p), 'new_points': int(new_p)}
    finally:
        try:
            conn.close()
        except Exception:
            pass


@app.post('/api/students/quick-update')
def api_students_quick_update(request: Request, payload: StudentQuickUpdatePayload) -> Dict[str, Any]:
    guard = _web_require_teacher(request)
    if guard:
        raise HTTPException(status_code=401, detail='not authorized')
    tenant_id = _web_tenant_from_cookie(request)
    if not tenant_id:
        raise HTTPException(status_code=401, detail='missing tenant')

    teacher = _web_current_teacher(request)
    if not teacher:
        raise HTTPException(status_code=401, detail='missing teacher')
    teacher_id = _safe_int(teacher.get('id'), 0)
    teacher_name = _safe_str(teacher.get('name') or '').strip() or 'מורה'
    is_admin = bool(_safe_int(teacher.get('is_admin'), 0) == 1)

    operation = str(payload.operation or '').strip().lower()
    if operation not in ('add', 'subtract', 'set'):
        operation = 'add'
    try:
        points = int(payload.points)
    except Exception:
        points = 0
    if operation in ('add', 'subtract') and points <= 0:
        raise HTTPException(status_code=400, detail='invalid points')
    if operation == 'set' and points < 0:
        raise HTTPException(status_code=400, detail='invalid points')

    mode = str(payload.mode or '').strip().lower()
    if mode not in ('card', 'serial_range', 'class', 'students', 'all_school'):
        raise HTTPException(status_code=400, detail='invalid mode')
    if mode == 'all_school' and not is_admin:
        raise HTTPException(status_code=403, detail='admin only')

    allowed_classes: List[str] | None = None
    if not is_admin:
        allowed_classes = _web_teacher_allowed_classes(tenant_id, teacher_id)
        allowed_classes = [str(c).strip() for c in (allowed_classes or []) if str(c).strip()]

    def _compute_new_points(old_points: int) -> int:
        if operation == 'add':
            return int(old_points + int(points))
        if operation == 'subtract':
            return int(max(0, int(old_points) - abs(int(points))))
        return int(max(0, int(points)))

    def _reason_label() -> str:
        try:
            if operation == 'add':
                return f"עדכון מהיר +{int(points)}"
            if operation == 'subtract':
                return f"עדכון מהיר -{abs(int(points))}"
            return f"עדכון מהיר = {max(0, int(points))}"
        except Exception:
            return 'עדכון מהיר'

    reason = _reason_label()

    conn = _tenant_school_db(tenant_id)
    try:
        cur = conn.cursor()

        student_ids: List[int] = []
        if mode == 'card':
            cn = str(payload.card_number or '').strip()
            if not cn:
                raise HTTPException(status_code=400, detail='missing card_number')
            cur.execute(_sql_placeholder('SELECT id, class_name FROM students WHERE TRIM(COALESCE(card_number, \'\')) = ? LIMIT 1'), (cn,))
            row = cur.fetchone()
            if not row:
                return {'ok': True, 'updated': 0, 'not_found': True}
            sid = _safe_int((row.get('id') if isinstance(row, dict) else row['id']), 0)
            scls = _safe_str((row.get('class_name') if isinstance(row, dict) else row['class_name']) or '').strip()
            if sid <= 0:
                return {'ok': True, 'updated': 0, 'not_found': True}
            if allowed_classes is not None:
                if not allowed_classes or (scls not in set(allowed_classes)):
                    raise HTTPException(status_code=403, detail='not allowed')
            student_ids = [int(sid)]

        elif mode == 'serial_range':
            x = _safe_int(payload.serial_from, 0)
            y = _safe_int(payload.serial_to, 0)
            if x <= 0 or y <= 0 or x > y:
                raise HTTPException(status_code=400, detail='invalid serial range')
            if allowed_classes is not None:
                if not allowed_classes:
                    student_ids = []
                else:
                    placeholders = ','.join(['?'] * len(allowed_classes))
                    cur.execute(
                        _sql_placeholder(f'SELECT id, serial_number FROM students WHERE class_name IN ({placeholders})'),
                        tuple(allowed_classes)
                    )
                    rows = cur.fetchall() or []
            else:
                cur.execute(_sql_placeholder('SELECT id, serial_number FROM students'))
                rows = cur.fetchall() or []
            for r in rows:
                try:
                    sid = _safe_int((r.get('id') if isinstance(r, dict) else r['id']), 0)
                    sn = (r.get('serial_number') if isinstance(r, dict) else r['serial_number'])
                except Exception:
                    sid = 0
                    sn = None
                if sid <= 0:
                    continue
                try:
                    sn_i = int(str(sn or '').strip())
                except Exception:
                    continue
                if sn_i >= x and sn_i <= y:
                    student_ids.append(int(sid))

        elif mode == 'class':
            raw = payload.class_names
            cls_list = [str(c).strip() for c in (raw or []) if str(c).strip()]
            if not cls_list:
                raise HTTPException(status_code=400, detail='missing class_names')
            if allowed_classes is not None:
                allowed_set = set(allowed_classes or [])
                bad = [c for c in cls_list if c not in allowed_set]
                if bad:
                    raise HTTPException(status_code=403, detail='not allowed')
            placeholders = ','.join(['?'] * len(cls_list))
            cur.execute(_sql_placeholder(f'SELECT id FROM students WHERE class_name IN ({placeholders})'), tuple(cls_list))
            rows = cur.fetchall() or []
            for r in rows:
                try:
                    sid = _safe_int((r.get('id') if isinstance(r, dict) else r['id']), 0)
                except Exception:
                    sid = 0
                if sid > 0:
                    student_ids.append(int(sid))

        elif mode == 'students':
            raw_ids = payload.student_ids
            if not isinstance(raw_ids, list) or not raw_ids:
                raise HTTPException(status_code=400, detail='missing student_ids')
            try:
                sid_list = [int(x) for x in raw_ids if int(x) > 0]
            except Exception:
                sid_list = []
            if not sid_list:
                raise HTTPException(status_code=400, detail='missing student_ids')

            placeholders = ','.join(['?'] * len(sid_list))
            cur.execute(_sql_placeholder(f'SELECT id, class_name FROM students WHERE id IN ({placeholders})'), tuple(sid_list))
            rows = cur.fetchall() or []
            found_ids: List[int] = []
            for r in rows:
                try:
                    sid = _safe_int((r.get('id') if isinstance(r, dict) else r['id']), 0)
                    scls = _safe_str((r.get('class_name') if isinstance(r, dict) else r['class_name']) or '').strip()
                except Exception:
                    sid = 0
                    scls = ''
                if sid <= 0:
                    continue
                if allowed_classes is not None:
                    if not allowed_classes or (scls not in set(allowed_classes)):
                        raise HTTPException(status_code=403, detail='not allowed')
                found_ids.append(int(sid))
            if len(set(found_ids)) != len(set(sid_list)):
                raise HTTPException(status_code=400, detail='student not found')
            student_ids = found_ids

        elif mode == 'all_school':
            cur.execute(_sql_placeholder('SELECT id FROM students'))
            rows = cur.fetchall() or []
            for r in rows:
                try:
                    sid = _safe_int((r.get('id') if isinstance(r, dict) else r['id']), 0)
                except Exception:
                    sid = 0
                if sid > 0:
                    student_ids.append(int(sid))

        updated = 0
        for sid in student_ids:
            try:
                cur.execute(_sql_placeholder('SELECT points FROM students WHERE id = ? LIMIT 1'), (int(sid),))
                row = cur.fetchone()
                if not row:
                    continue
                old_points = _safe_int((row.get('points') if isinstance(row, dict) else row['points']), 0)
                new_points = _compute_new_points(old_points)
                delta = int(new_points - int(old_points))
                cur.execute(
                    _sql_placeholder('UPDATE students SET points = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?'),
                    (int(new_points), int(sid))
                )
                try:
                    cur.execute(
                        _sql_placeholder(
                            '''
                            INSERT INTO points_log (student_id, old_points, new_points, delta, reason, actor_name, action_type)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                            '''
                        ),
                        (int(sid), int(old_points), int(new_points), int(delta), str(reason), str(teacher_name), 'עדכון מהיר')
                    )
                except Exception:
                    pass
                updated += 1

                # record for pull
                try:
                    _record_sync_event(
                        tenant_id=str(tenant_id),
                        station_id='web',
                        entity_type='student_points',
                        entity_id=str(int(sid)),
                        action_type='update',
                        payload={
                            'old_points': int(old_points),
                            'new_points': int(new_points),
                            'reason': str(reason),
                            'added_by': str(teacher_name),
                        },
                        created_at=None,
                    )
                except Exception:
                    pass
            except Exception:
                pass

        conn.commit()
        return {'ok': True, 'updated': int(updated)}
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
        const btnQuickDelta = document.getElementById('btnQuickDelta');
        const btnEditMsg = document.getElementById('btnEditMsg');
        const btnEditStudent = document.getElementById('btnEditStudent');
        let selectedId = null;
        let timer = null;

        function setSelected(id) {
          selectedId = id;
          const on = (selectedId !== null);
          btnEditPoints.style.opacity = on ? '1' : '.55';
          btnQuickDelta.style.opacity = on ? '1' : '.55';
          btnEditMsg.style.opacity = on ? '1' : '.55';
          btnEditStudent.style.opacity = on ? '1' : '.55';
          btnEditPoints.style.pointerEvents = on ? 'auto' : 'none';
          btnQuickDelta.style.pointerEvents = on ? 'auto' : 'none';
          btnEditMsg.style.pointerEvents = on ? 'auto' : 'none';
          btnEditStudent.style.pointerEvents = on ? 'auto' : 'none';
          selectedEl.textContent = on ? `נבחר תלמיד ID ${selectedId}` : 'לא נבחר תלמיד';
          document.querySelectorAll('tr[data-id]').forEach(tr => {
            tr.style.outline = (String(tr.getAttribute('data-id')) === String(selectedId)) ? '2px solid #1abc9c' : 'none';
          });
        }

        async function updateStudentFor(studentId, patch) {
          if (!studentId) return;
          const resp = await fetch('/api/students/update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ student_id: parseInt(String(studentId), 10), ...patch })
          });
          if (!resp.ok) {
            const txt = await resp.text();
            alert('שגיאה בעדכון: ' + txt);
            return;
          }
          await load();
        }

        async function updateStudent(patch) {
          if (!selectedId) return;
          await updateStudentFor(selectedId, patch);
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
              <td style="padding:8px;border-top:1px solid #e8eef2;" data-field="points" contenteditable="true">${r.points ?? ''}</td>
              <td style="padding:8px;border-top:1px solid #e8eef2;" data-field="private_message" contenteditable="true">${r.private_message ?? ''}</td>
              <td style="padding:8px;border-top:1px solid #e8eef2;">${r.card_number ?? ''}</td>
            </tr>`).join('');
          statusEl.textContent = `נטענו ${data.items.length} תלמידים`;

          document.querySelectorAll('tr[data-id]').forEach(tr => {
            tr.addEventListener('click', () => setSelected(tr.getAttribute('data-id')));
          });

          document.querySelectorAll('td[contenteditable][data-field]').forEach(td => {
            td.addEventListener('click', (ev) => {
              try { ev.stopPropagation(); } catch (e) {}
              const tr = td.closest('tr[data-id]');
              if (tr) setSelected(tr.getAttribute('data-id'));
            });

            td.addEventListener('keydown', (ev) => {
              if (ev.key === 'Enter') {
                ev.preventDefault();
                try { td.blur(); } catch (e) {}
              }
            });

            td.addEventListener('blur', async () => {
              const tr = td.closest('tr[data-id]');
              const sid = tr ? tr.getAttribute('data-id') : null;
              if (!sid) return;
              const field = td.getAttribute('data-field');
              const raw = (td.textContent ?? '').trim();

              if (field === 'points') {
                const n = parseInt(raw || '0', 10);
                if (Number.isNaN(n)) { alert('ערך לא תקין'); await load(); return; }
                await updateStudentFor(sid, { points: n });
              } else if (field === 'private_message') {
                await updateStudentFor(sid, { private_message: String(raw) });
              }
            });
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

        btnQuickDelta.addEventListener('click', async () => {
          if (!selectedId) return;
          const deltaS = prompt('כמה נקודות להוסיף/להוריד? (לדוגמה: 5 או -3)');
          if (deltaS === null) return;
          const delta = parseInt(deltaS, 10);
          if (Number.isNaN(delta) || delta === 0) { alert('ערך לא תקין'); return; }
          const reason = prompt('סיבה (אופציונלי):') ?? '';
          const resp = await fetch('/api/students/points-delta', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ student_id: parseInt(String(selectedId), 10), delta: delta, reason: String(reason || '') })
          });
          if (!resp.ok) {
            const txt = await resp.text();
            alert('שגיאה: ' + txt);
            return;
          }
          await load();
        });

        btnEditMsg.addEventListener('click', async () => {
          if (!selectedId) return;
          const val = prompt('הודעה פרטית (ריק למחיקה):');
          if (val === null) return;
          await updateStudent({ private_message: String(val) });
        });

        btnEditStudent.addEventListener('click', async () => {
          if (!selectedId) return;
          window.location.href = `/web/students/edit?student_id=${encodeURIComponent(String(selectedId))}`;
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
          <a class="tab" href="/web/spaces-test">בדיקת אחסון</a>
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
          <a class="btn-blue" id="btnQuickDelta" style="opacity:.55;pointer-events:none;" href="javascript:void(0)">⚡ עדכון מהיר</a>
          <a class="btn-blue" id="btnEditMsg" style="opacity:.55;pointer-events:none;" href="javascript:void(0)">✏️ ערוך הודעה</a>
          <a class="btn-blue" id="btnEditStudent" style="opacity:.55;pointer-events:none;" href="javascript:void(0)">✏️ ערוך תלמיד</a>
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
                  <th>כרטיס</th>
                </tr>
              </thead>
              <tbody id="rows"></tbody>
            </table>
          </div>
        </div>
        <div class="footerbar">
          <a class="btn-green" href="/web/students/new">➕ הוסף תלמיד</a>
          <a class="btn-blue" href="/web/students/edit">✏️ ערוך תלמיד</a>
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


@app.get('/web/spaces-test', response_class=HTMLResponse)
def web_spaces_test(request: Request) -> Response:
    guard = _web_require_teacher(request)
    if guard:
        return guard

    tenant_id = _web_tenant_from_cookie(request)
    teacher = _web_current_teacher(request) or {}

    has_boto = bool(boto3 is not None)
    has_cfg = bool(SPACES_BUCKET and SPACES_ENDPOINT and SPACES_KEY and SPACES_SECRET)

    return HTMLResponse(
        f"""
        <!doctype html>
        <html lang=\"he\">
        <head>
          <meta charset=\"utf-8\" />
          <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
          <title>SchoolPoints - בדיקת אחסון</title>
          <style>
            :root {{ --navy:#2f3e4e; --bg:#eef2f4; --line:#d6dde3; --tab:#ecf0f1; }}
            body {{ margin:0; font-family:\"Segoe UI\", Arial, sans-serif; background:var(--bg); color:#1f2d3a; direction:rtl; }}
            .wrap {{ max-width:980px; margin:18px auto; padding:0 16px 24px; }}
            .titlebar {{ background:var(--navy); color:#fff; padding:14px 16px; border-radius:8px; display:flex; justify-content:space-between; align-items:center; }}
            .titlebar h2 {{ margin:0; font-size:20px; }}
            .tabs {{ margin:10px 0; display:flex; gap:6px; flex-wrap:wrap; }}
            .tab {{ background:var(--tab); padding:6px 10px; border-radius:4px; font-size:12px; text-decoration:none; color:#1f2d3a; border:1px solid var(--line); }}
            .card {{ background:#fff; border-radius:10px; border:1px solid var(--line); box-shadow:0 6px 16px rgba(40,55,70,.08); padding:14px; }}
            .hint {{ color:#637381; font-size:13px; line-height:1.8; margin:8px 0; }}
            .kv {{ display:grid; grid-template-columns: 200px 1fr; gap:8px; font-size:13px; }}
            .kv div {{ padding:6px 0; border-bottom:1px dashed #e3e9ee; }}
            .btn {{ padding:10px 14px; border-radius:10px; border:1px solid rgba(0,0,0,.08); background:#fff; cursor:pointer; font-weight:800; }}
            .btn-primary {{ background: linear-gradient(135deg, #22c55e, #16a34a); color:#fff; border-color:transparent; }}
          </style>
        </head>
        <body>
          <div class=\"wrap\">
            <div class=\"titlebar\">
              <h2>בדיקת אחסון (Spaces/CDN)</h2>
              <span>שלום {str(teacher.get('name') or '').strip() or 'מורה'} · <a href=\"/web/logout\" style=\"color:#fff;\">יציאה</a></span>
            </div>
            <div class=\"tabs\">
              <a class=\"tab\" href=\"/web/admin\">תלמידים</a>
              <a class=\"tab\" href=\"/web/spaces-test\">בדיקת אחסון</a>
            </div>
            <div class=\"card\">
              <div class=\"hint\">הדף הזה מעלה קובץ בדיקה קטן ל־Spaces תחת tenant שלך ומציג קישורי בדיקה.</div>
              <div class=\"kv\">
                <div><b>Tenant</b></div><div>{str(tenant_id or '')}</div>
                <div><b>Bucket</b></div><div>{str(SPACES_BUCKET or '')}</div>
                <div><b>Endpoint</b></div><div>{str(SPACES_ENDPOINT or '')}</div>
                <div><b>CDN Base</b></div><div>{str(SPACES_CDN_BASE_URL or '')}</div>
                <div><b>boto3</b></div><div>{'OK' if has_boto else 'MISSING'}</div>
                <div><b>Config</b></div><div>{'OK' if has_cfg else 'MISSING (ENV vars)'} </div>
              </div>
              <form method=\"post\" action=\"/web/spaces-test\" style=\"margin-top:12px;\">
                <button class=\"btn btn-primary\" type=\"submit\">בדוק עכשיו</button>
                <a class=\"btn\" href=\"/web/admin\" style=\"text-decoration:none;\">חזרה</a>
              </form>
            </div>
          </div>
        </body>
        </html>
        """
    )


@app.post('/web/spaces-test', response_class=HTMLResponse)
def web_spaces_test_submit(request: Request) -> Response:
    guard = _web_require_teacher(request)
    if guard:
        return guard

    tenant_id = str(_web_tenant_from_cookie(request) or '').strip()
    if not tenant_id:
        return RedirectResponse(url='/web/spaces-test?msg=missing_tenant', status_code=302)

    s3 = _spaces_client()
    if s3 is None:
        return RedirectResponse(url='/web/spaces-test?msg=missing_boto_or_env', status_code=302)

    probe_id = secrets.token_hex(6)
    key = f"tenants/{tenant_id}/__probe__/probe-{probe_id}.txt"
    body = f"ok {datetime.datetime.utcnow().isoformat()}Z tenant={tenant_id}"
    try:
        s3.put_object(Bucket=SPACES_BUCKET, Key=key, Body=body.encode('utf-8'), ContentType='text/plain')
    except Exception:
        return RedirectResponse(url='/web/spaces-test?msg=put_failed', status_code=302)

    presigned = ''
    try:
        presigned = s3.generate_presigned_url(
            'get_object',
            Params={'Bucket': SPACES_BUCKET, 'Key': key},
            ExpiresIn=60 * 10,
        )
    except Exception:
        presigned = ''

    cdn_url = ''
    try:
        base = str(SPACES_CDN_BASE_URL or '').strip().rstrip('/')
        if base:
            cdn_url = base + '/' + urllib.parse.quote(key)
    except Exception:
        cdn_url = ''

    return HTMLResponse(
        f"""
        <!doctype html>
        <html lang=\"he\">
        <head>
          <meta charset=\"utf-8\" />
          <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
          <title>SchoolPoints - בדיקת אחסון</title>
          <style>
            body {{ margin:0; font-family:\"Segoe UI\", Arial, sans-serif; background:#eef2f4; color:#1f2d3a; direction:rtl; }}
            .wrap {{ max-width:980px; margin:18px auto; padding:0 16px 24px; }}
            .card {{ background:#fff; border-radius:10px; border:1px solid #d6dde3; box-shadow:0 6px 16px rgba(40,55,70,.08); padding:14px; }}
            .btn {{ padding:10px 14px; border-radius:10px; border:1px solid rgba(0,0,0,.08); background:#fff; cursor:pointer; font-weight:800; text-decoration:none; display:inline-block; }}
            .btn-primary {{ background: linear-gradient(135deg, #22c55e, #16a34a); color:#fff; border-color:transparent; }}
            code {{ background:#f6f8f9; padding:2px 6px; border-radius:6px; }}
            .hint {{ color:#637381; font-size:13px; line-height:1.8; margin:8px 0; }}
          </style>
        </head>
        <body>
          <div class=\"wrap\">
            <div class=\"card\">
              <h2 style=\"margin-top:0;\">בדיקה הצליחה ✅</h2>
              <div class=\"hint\">נוצר קובץ בדיקה תחת: <code>{key}</code></div>
              <div style=\"margin-top:10px;\">
                <div style=\"margin-bottom:6px;\"><b>CDN URL</b></div>
                <div><a href=\"{cdn_url}\" target=\"_blank\">{cdn_url or 'N/A'}</a></div>
              </div>
              <div style=\"margin-top:10px;\">
                <div style=\"margin-bottom:6px;\"><b>Presigned URL (10 דקות)</b></div>
                <div><a href=\"{presigned}\" target=\"_blank\">{presigned or 'N/A'}</a></div>
              </div>
              <div style=\"margin-top:14px;display:flex;gap:10px;flex-wrap:wrap;\">
                <form method=\"post\" action=\"/web/spaces-test\">
                  <button class=\"btn btn-primary\" type=\"submit\">בדיקה נוספת</button>
                </form>
                <a class=\"btn\" href=\"/web/admin\">חזרה לניהול</a>
              </div>
            </div>
          </div>
        </body>
        </html>
        """
    )


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
