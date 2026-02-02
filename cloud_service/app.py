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
import re
import json
import html
import secrets
import hashlib
import hmac
import shutil
import urllib.parse
import datetime
import traceback
import uuid

try:
    import psycopg2
    import psycopg2.extras
except Exception:
    psycopg2 = None  # type: ignore[assignment]
    psycopg2_extras = None  # type: ignore[assignment]
from fastapi import FastAPI, Header, HTTPException, Form, Query, Request, UploadFile, File
from fastapi.responses import HTMLResponse, Response, RedirectResponse, FileResponse
from pydantic import BaseModel

try:
    import boto3
except Exception:
    boto3 = None  # type: ignore[assignment]

app = FastAPI(title="SchoolPoints Sync")


@app.get("/", include_in_schema=False)
def root() -> Response:
    return RedirectResponse(url="/web", status_code=302)

APP_BUILD_TAG = "2026-01-31-web-ui-a25e6b4"


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


def _ensure_teacher_columns(conn) -> None:
    cols: set[str] = set()
    try:
        if USE_POSTGRES:
            cols = set([c.lower() for c in _table_columns_postgres(conn, 'teachers')])
        else:
            cols = set([c.lower() for c in _table_columns(conn, 'teachers')])
    except Exception:
        cols = set()
    cur = conn.cursor()
    if USE_POSTGRES:
        for ddl in (
            'card_number2 TEXT',
            'card_number3 TEXT',
            'can_edit_student_card INTEGER DEFAULT 1',
            'can_edit_student_photo INTEGER DEFAULT 1',
            'bonus_max_points_per_student INTEGER',
            'bonus_max_total_runs INTEGER',
            'bonus_runs_used INTEGER DEFAULT 0',
            'bonus_runs_reset_date DATE',
            'bonus_points_used INTEGER DEFAULT 0',
            'bonus_points_reset_date DATE',
        ):
            try:
                cur.execute(f'ALTER TABLE teachers ADD COLUMN IF NOT EXISTS {ddl}')
            except Exception:
                pass
        try:
            conn.commit()
        except Exception:
            pass
        return

    def _add_if_missing(col: str, ddl: str) -> None:
        if col in cols:
            return
        try:
            cur.execute(f'ALTER TABLE teachers ADD COLUMN {ddl}')
        except Exception:
            pass

    _add_if_missing('card_number2', 'card_number2 TEXT')
    _add_if_missing('card_number3', 'card_number3 TEXT')
    _add_if_missing('can_edit_student_card', 'can_edit_student_card INTEGER DEFAULT 1')
    _add_if_missing('can_edit_student_photo', 'can_edit_student_photo INTEGER DEFAULT 1')
    _add_if_missing('bonus_max_points_per_student', 'bonus_max_points_per_student INTEGER')
    _add_if_missing('bonus_max_total_runs', 'bonus_max_total_runs INTEGER')
    _add_if_missing('bonus_runs_used', 'bonus_runs_used INTEGER DEFAULT 0')
    _add_if_missing('bonus_runs_reset_date', 'bonus_runs_reset_date TEXT')
    _add_if_missing('bonus_points_used', 'bonus_points_used INTEGER DEFAULT 0')
    _add_if_missing('bonus_points_reset_date', 'bonus_points_reset_date TEXT')
    try:
        conn.commit()
    except Exception:
        pass


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


def _get_institution(tenant_id: str) -> Dict[str, Any] | None:
    tenant_id = str(tenant_id or '').strip()
    if not tenant_id:
        return None
    conn = _db()
    try:
        cur = conn.cursor()
        cur.execute(
            _sql_placeholder('SELECT tenant_id, name, api_key, password_hash, created_at FROM institutions WHERE tenant_id = ? LIMIT 1'),
            (tenant_id,)
        )
        row = cur.fetchone()
        if not row:
            return None
        if isinstance(row, dict):
            return dict(row)
        try:
            return dict(row)
        except Exception:
            return {
                'tenant_id': row[0],
                'name': row[1],
                'api_key': row[2],
                'password_hash': row[3] if len(row) > 3 else None,
                'created_at': row[4] if len(row) > 4 else None,
            }
    finally:
        try:
            conn.close()
        except Exception:
            pass


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
    return (
        f"<div style=\"font-size:12px;color:#637381;margin:0 0 10px;\">"
        f"עדכון אחרון: {status['last_received']}"
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


def _ensure_pending_registrations_table() -> None:
    conn = _db()
    try:
        cur = conn.cursor()
        if USE_POSTGRES:
            cur.execute(
                '''
                CREATE TABLE IF NOT EXISTS pending_registrations (
                    id BIGSERIAL PRIMARY KEY,
                    institution_name TEXT NOT NULL,
                    contact_name TEXT,
                    email TEXT NOT NULL,
                    phone TEXT,
                    password_hash TEXT,
                    plan TEXT,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    payment_status TEXT DEFAULT 'pending',
                    payment_id TEXT
                )
                '''
            )
        else:
            cur.execute(
                '''
                CREATE TABLE IF NOT EXISTS pending_registrations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    institution_name TEXT NOT NULL,
                    contact_name TEXT,
                    email TEXT NOT NULL,
                    phone TEXT,
                    password_hash TEXT,
                    plan TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    payment_status TEXT DEFAULT 'pending',
                    payment_id TEXT
                )
                '''
            )
        conn.commit()
    finally:
        try: conn.close()
        except: pass

@app.post('/api/register')
def api_register(request: Request, payload: Dict[str, Any]) -> Dict[str, Any]:
    _ensure_pending_registrations_table()
    
    inst_name = str(payload.get('institution_name') or '').strip()
    contact = str(payload.get('contact_name') or '').strip()
    email = str(payload.get('email') or '').strip()
    phone = str(payload.get('phone') or '').strip()
    password = str(payload.get('password') or '').strip()
    plan = str(payload.get('plan') or 'basic').strip()
    
    if not inst_name or not email or not password:
        raise HTTPException(status_code=400, detail="Missing required fields")
        
    # Basic password hashing (mock for now, should use bcrypt/argon2 in prod)
    # Using SHA256 for simplicity in this dev phase, switch to passlib later
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    
    conn = _db()
    try:
        cur = conn.cursor()
        cur.execute(
            _sql_placeholder(
                '''
                INSERT INTO pending_registrations 
                (institution_name, contact_name, email, phone, password_hash, plan)
                VALUES (?, ?, ?, ?, ?, ?)
                '''
            ),
            (inst_name, contact, email, phone, password_hash, plan)
        )
        conn.commit()
        reg_id = cur.lastrowid if not USE_POSTGRES else None # Postgres needs RETURNING
        
        # Mock payment URL generation
        # In real flow, we'd call Stripe/Provider API here to get a checkout URL
        payment_url = f"/web/payment/mock?reg_email={urllib.parse.quote(email)}&plan={plan}"
        
        return {
            'ok': True,
            'payment_url': payment_url,
            'reg_id': reg_id
        }
    except Exception as e:
        print(f"Registration error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error during registration")
    finally:
        try: conn.close()
        except: pass

@app.get('/web/payment/mock', response_class=HTMLResponse)
def web_payment_mock(request: Request, reg_email: str = Query(...), plan: str = Query(...)) -> str:
    # Mock payment page to simulate successful payment
    body = f"""
    <div style="max-width:500px; margin:40px auto; text-align:center; background:#fff; padding:30px; border-radius:15px; box-shadow:0 10px 30px rgba(0,0,0,0.1);">
      <h2 style="color:#2c3e50;">תשלום מאובטח (סימולציה)</h2>
      <div style="font-size:18px; margin:20px 0;">
        <div><b>לקוח:</b> {reg_email}</div>
        <div><b>מסלול:</b> {plan.upper()}</div>
        <div style="font-size:24px; font-weight:bold; color:#27ae60; margin-top:10px;">סכום לתשלום: ₪{(50 if plan=='basic' else (100 if plan=='extended' else 200))}</div>
      </div>
      
      <div style="background:#f8f9fa; padding:15px; border-radius:8px; margin-bottom:20px; text-align:left; direction:ltr;">
        <div>💳 Card Number: 4242 4242 4242 4242</div>
        <div>📅 Expiry: 12/30</div>
        <div>🔒 CVC: 123</div>
      </div>
      
      <button onclick="processPayment()" style="width:100%; padding:15px; background:#2ecc71; color:white; border:none; border-radius:8px; font-size:18px; font-weight:bold; cursor:pointer;">שלם עכשיו</button>
      
      <script>
        async function processPayment() {{
            const btn = document.querySelector('button');
            btn.disabled = true;
            btn.textContent = 'מעבד תשלום...';
            
            await new Promise(r => setTimeout(r, 1500));
            
            // Call webhook simulation
            try {{
                const resp = await fetch('/api/payment/webhook/mock', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ email: '{reg_email}', status: 'success' }})
                }});
                const data = await resp.json();
                if (data.ok) {{
                    document.body.innerHTML = '<h2 style="color:#27ae60">התשלום עבר בהצלחה!</h2><p>פרטי ההתחברות נשלחו למייל שלך.</p><a href="/web/signin" style="display:inline-block; margin-top:20px; padding:10px 20px; background:#3498db; color:white; text-decoration:none; border-radius:6px;">מעבר להתחברות</a>';
                }} else {{
                    alert('שגיאה: ' + (data.detail || 'unknown'));
                    btn.disabled = false;
                    btn.textContent = 'שלם עכשיו';
                }}
            }} catch (e) {{
                alert('שגיאה בתקשורת');
                btn.disabled = false;
                btn.textContent = 'שלם עכשיו';
            }}
        }}
      </script>
    </div>
    """
    return _public_web_shell("תשלום", body, request=request)


def _send_email(to_email: str, subject: str, body_html: str) -> bool:
    """Send an email using configured SMTP server."""
    smtp_server = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
    smtp_port = int(os.getenv('SMTP_PORT', '587'))
    smtp_user = os.getenv('SMTP_USER', '')
    smtp_pass = os.getenv('SMTP_PASS', '')
    
    if not smtp_user or not smtp_pass:
        print(f"[_send_email] SKIP: No SMTP config. To={to_email}, Subject={subject}")
        return False
        
    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        
        msg = MIMEMultipart()
        msg['From'] = smtp_user
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body_html, 'html'))
        
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        return True
    except Exception as e:
        print(f"[_send_email] ERROR: {e}")
        return False

def _generate_cloud_license_key(school_name: str, system_code: str, plan: str) -> str:
    """Generate a license key (adapted from license_manager logic)."""
    # Using SP5 (Payload) logic or simple profile logic
    # For cloud, we will use SP5 logic with 1 year validity or Monthly
    # Let's use SP5 style with Payload for flexibility
    
    # 1. Normalize
    school_name = (school_name or '').strip()
    sys_norm = ''.join(ch for ch in (system_code or "").upper() if ch.isalnum())
    if not school_name or not sys_norm:
        return "ERROR-KEY-GEN"

    # 2. Determine params
    plan = plan.lower()
    max_stations = 2
    if 'extended' in plan: max_stations = 5
    if 'unlimited' in plan: max_stations = 999
    
    # Cloud licenses are valid for 35 days (monthly + buffer) usually, 
    # but here we might give a year if they paid for it.
    # For now, let's give 35 days (Monthly subscription model).
    days_valid = 35 
    allow_cashier = True

    # 3. Construct Payload
    payload = {
        'v': 'SP5',
        'school': school_name,
        'sys': sys_norm,
        'days': int(days_valid),
        'max': int(max_stations),
        'cashier': bool(allow_cashier),
    }

    # 4. Sign and Encrypt (Simplified version of license_manager to avoid import hell)
    # We must match the SECRET from license_manager.py
    _HMAC_SECRET = b"SchoolPoints-Offline-License-Key-2024-11-Strong-Secret"
    
    raw = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    sig = hmac.new(_HMAC_SECRET, raw, hashlib.sha256).digest()[:10]
    
    key_stream = hashlib.sha256(_HMAC_SECRET + sys_norm.encode('utf-8')).digest()
    blob = raw + sig
    
    # XOR
    out = bytearray(len(blob))
    klen = len(key_stream)
    for i, b in enumerate(blob):
        out[i] = b ^ key_stream[i % klen]
    enc = bytes(out)
    
    # Base32
    token = base64.b32encode(enc).decode('ascii').replace('=', '').upper()
    
    # Format groups
    core = 'SP5' + token
    groups = [core[i : i + 5] for i in range(0, len(core), 5)]
    return "-".join(groups)

@app.post('/api/payment/webhook/mock')
def api_payment_webhook_mock(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Mock webhook for payment success."""
    email = str(payload.get('email') or '').strip()
    status = str(payload.get('status') or '').strip()
    
    if status != 'success':
         return {'ok': False, 'detail': 'Status not success'}
         
    _ensure_pending_registrations_table()
    conn = _db()
    try:
        cur = conn.cursor()
        # Find pending registration
        cur.execute(
            _sql_placeholder("SELECT id, institution_name, contact_name, plan, password_hash, payment_status FROM pending_registrations WHERE email = ? AND payment_status != 'completed' ORDER BY id DESC LIMIT 1"),
            (email,)
        )
        row = cur.fetchone()
        
        if not row:
             # Maybe already processed?
             return {'ok': True, 'processed': False, 'detail': 'No pending registration found'}
             
        if isinstance(row, dict):
             reg_id = row['id']
             inst_name = row['institution_name']
             contact = row['contact_name']
             plan = row['plan']
             pwd_hash = row['password_hash']
        else:
             reg_id, inst_name, contact, plan, pwd_hash, _ = row
             
        # 1. Generate Tenant ID
        # Simple slugify
        slug = ''.join(c for c in inst_name.lower() if c.isalnum() or c==' ')
        slug = slug.replace(' ', '_')
        if not slug: slug = 'school'
        # Append random suffix to ensure uniqueness
        tenant_id = f"{slug[:20]}_{secrets.token_hex(3)}"
        
        # 2. Create Institution
        # We need an API Key
        api_key = secrets.token_urlsafe(24)
        
        # Insert into institutions
        # Note: 'institutions' table schema might vary (sqlite vs postgres in this codebase). 
        # Checking schema from previous reads: (tenant_id, name, api_key, password_hash, created_at)
        # We need to make sure password_hash column exists in institutions. 
        # Based on _get_institution it seems it does.
        
        cur.execute(
            _sql_placeholder("INSERT INTO institutions (tenant_id, name, api_key, password_hash) VALUES (?, ?, ?, ?)"),
            (tenant_id, inst_name, api_key, pwd_hash)
        )
        
        # 3. Update pending registration
        cur.execute(
            _sql_placeholder("UPDATE pending_registrations SET payment_status = 'completed' WHERE id = ?"),
            (reg_id,)
        )
        
        conn.commit()
        
        # 4. Generate License Key (Cloud License)
        # We use the Tenant ID as the "System Code" for cloud-managed licenses, 
        # OR we generate a generic key. 
        # Actually, standard license keys are bound to a Machine ID.
        # For a new cloud registration, we don't know the user's Machine ID yet!
        # SOLUTION: We will send them a "Temporary License Key" or "Activation Code" 
        # or simply tell them to log in to the software with their Tenant ID.
        #
        # Better: We send them the Tenant ID + API Key. The client software will fetch license status online.
        # BUT, for the sake of the 'classic' flow, let's generate a key bound to a placeholder, 
        # and they might need to re-generate it later or we instruct them to use the Online Cloud feature.
        #
        # Let's send the Tenant ID & API Key primarily.
        
        # 5. Send Email
        login_url = "https://schoolpoints.co.il/web/login" # Placeholder
        download_url = "https://schoolpoints.co.il/web/download"
        
        body = f"""
        <div dir="rtl" style="font-family:Arial, sans-serif; line-height:1.6; color:#333;">
            <h2 style="color:#2ecc71;">ברוכים הבאים ל-SchoolPoints!</h2>
            <p>שלום {contact},</p>
            <p>תודה שנרשמת למערכת SchoolPoints. ההרשמה עברה בהצלחה והחשבון שלך מוכן.</p>
            
            <div style="background:#f9f9f9; padding:15px; border-radius:10px; border:1px solid #ddd; margin:20px 0;">
                <h3 style="margin-top:0;">פרטי המוסד שלך:</h3>
                <div><b>שם המוסד:</b> {inst_name}</div>
                <div><b>מזהה מוסד (Tenant ID):</b> <span style="font-family:monospace; background:#eee; padding:2px 5px;">{tenant_id}</span></div>
                <div><b>סיסמת ניהול:</b> (כפי שבחרת בהרשמה)</div>
            </div>
            
            <p>
                <b>להורדת התוכנה והתקנה ראשונית:</b><br/>
                <a href="{download_url}">לחץ כאן להורדה</a>
            </p>
            
            <p>
                במסך ההגדרות בתוכנה, הזן את מזהה המוסד שלך ({tenant_id}) כדי להתחבר לענן.
            </p>
            
            <hr style="border:0; border-top:1px solid #eee; margin:20px 0;">
            <div style="font-size:12px; color:#888;">
                הודעה זו נשלחה אוטומטית ממערכת SchoolPoints Cloud.
            </div>
        </div>
        """
        
        email_sent = _send_email(email, "ברוכים הבאים ל-SchoolPoints - פרטי התחברות", body)
        
        return {
            'ok': True,
            'tenant_id': tenant_id,
            'email_sent': email_sent
        }
        
    except Exception as e:
        print(f"Webhook error: {e}")
        return {'ok': False, 'detail': str(e)}
    finally:
        try: conn.close()
        except: pass


def _approve_pending_registration(reg_id: int) -> Dict[str, Any]:
    """Approve a pending registration: create tenant, send email, mark completed."""
    conn = _db()
    try:
        cur = conn.cursor()
        cur.execute(
            _sql_placeholder("SELECT id, institution_name, contact_name, plan, password_hash, email, payment_status FROM pending_registrations WHERE id = ? LIMIT 1"),
            (reg_id,)
        )
        row = cur.fetchone()
        if not row:
            return {'ok': False, 'detail': 'Registration not found'}
        
        if isinstance(row, dict):
             r = row
        else:
             r = {
                 'id': row[0], 'institution_name': row[1], 'contact_name': row[2], 
                 'plan': row[3], 'password_hash': row[4], 'email': row[5], 'payment_status': row[6]
             }
             
        if r['payment_status'] == 'completed':
            return {'ok': True, 'already_completed': True}

        inst_name = r['institution_name']
        contact = r['contact_name']
        email = r['email']
        pwd_hash = r['password_hash']
        
        # 1. Generate Tenant ID
        slug = ''.join(c for c in inst_name.lower() if c.isalnum() or c==' ')
        slug = slug.replace(' ', '_')
        if not slug: slug = 'school'
        tenant_id = f"{slug[:20]}_{secrets.token_hex(3)}"
        
        # 2. Create Institution
        api_key = secrets.token_urlsafe(24)
        
        cur.execute(
            _sql_placeholder("INSERT INTO institutions (tenant_id, name, api_key, password_hash) VALUES (?, ?, ?, ?)"),
            (tenant_id, inst_name, api_key, pwd_hash)
        )
        
        # 3. Update pending registration
        cur.execute(
            _sql_placeholder("UPDATE pending_registrations SET payment_status = 'completed', payment_id = ? WHERE id = ?"),
            (f"MANUAL_{secrets.token_hex(4)}", reg_id)
        )
        conn.commit()
        
        # 4. Send Email
        download_url = "https://schoolpoints.co.il/web/download"
        
        body = f"""
        <div dir="rtl" style="font-family:Arial, sans-serif; line-height:1.6; color:#333;">
            <h2 style="color:#2ecc71;">ברוכים הבאים ל-SchoolPoints!</h2>
            <p>שלום {contact},</p>
            <p>תודה שנרשמת למערכת SchoolPoints. ההרשמה עברה בהצלחה והחשבון שלך מוכן.</p>
            
            <div style="background:#f9f9f9; padding:15px; border-radius:10px; border:1px solid #ddd; margin:20px 0;">
                <h3 style="margin-top:0;">פרטי המוסד שלך:</h3>
                <div><b>שם המוסד:</b> {inst_name}</div>
                <div><b>מזהה מוסד (Tenant ID):</b> <span style="font-family:monospace; background:#eee; padding:2px 5px;">{tenant_id}</span></div>
                <div><b>סיסמת ניהול:</b> (כפי שבחרת בהרשמה)</div>
            </div>
            
            <p>
                <b>להורדת התוכנה והתקנה ראשונית:</b><br/>
                <a href="{download_url}">לחץ כאן להורדה</a>
            </p>
            
            <p>
                במסך ההגדרות בתוכנה, הזן את מזהה המוסד שלך ({tenant_id}) כדי להתחבר לענן.
            </p>
            
            <hr style="border:0; border-top:1px solid #eee; margin:20px 0;">
            <div style="font-size:12px; color:#888;">
                הודעה זו נשלחה אוטומטית ממערכת SchoolPoints Cloud.
            </div>
        </div>
        """
        
        email_sent = _send_email(email, "ברוכים הבאים ל-SchoolPoints - פרטי התחברות", body)
        
        return {
            'ok': True,
            'tenant_id': tenant_id,
            'email_sent': email_sent
        }
    except Exception as e:
        print(f"Approve error: {e}")
        return {'ok': False, 'detail': str(e)}
    finally:
        try: conn.close()
        except: pass


@app.post('/api/payment/webhook/mock')
def api_payment_webhook_mock(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Mock webhook for payment success."""
    email = str(payload.get('email') or '').strip()
    status = str(payload.get('status') or '').strip()
    
    if status != 'success':
         return {'ok': False, 'detail': 'Status not success'}
         
    _ensure_pending_registrations_table()
    conn = _db()
    try:
        cur = conn.cursor()
        cur.execute(
            _sql_placeholder("SELECT id FROM pending_registrations WHERE email = ? AND payment_status != 'completed' ORDER BY id DESC LIMIT 1"),
            (email,)
        )
        row = cur.fetchone()
        if not row:
             return {'ok': True, 'processed': False, 'detail': 'No pending registration found'}
             
        reg_id = row[0] if not isinstance(row, dict) else row['id']
    finally:
        try: conn.close()
        except: pass

    # Delegate to core logic
    return _approve_pending_registration(reg_id)


@app.get("/admin/registrations", response_class=HTMLResponse)
def admin_registrations(request: Request, admin_key: str = '') -> str:
    guard = _admin_require(request, admin_key)
    if guard: return guard
    
    _ensure_pending_registrations_table()
    conn = _db()
    cur = conn.cursor()
    cur.execute('SELECT id, institution_name, contact_name, email, phone, plan, created_at, payment_status FROM pending_registrations ORDER BY id DESC')
    rows = cur.fetchall() or []
    conn.close()
    
    items = ""
    for r in rows:
        d = dict(r) if isinstance(r, dict) else {
            'id': r[0], 'institution_name': r[1], 'contact_name': r[2], 'email': r[3], 
            'phone': r[4], 'plan': r[5], 'created_at': r[6], 'payment_status': r[7]
        }
        
        status_color = "#f39c12" # pending
        if d['payment_status'] == 'completed': status_color = "#2ecc71"
        if d['payment_status'] == 'failed': status_color = "#e74c3c"
        
        actions = ""
        if d['payment_status'] != 'completed':
            actions = f"""
            <form method="post" action="/admin/registrations/approve" style="display:inline;" onsubmit="return confirm('האם לאשר ידנית? פעולה זו תיצור מוסד ותשלח מייל.');">
                <input type="hidden" name="reg_id" value="{d['id']}" />
                <button style="background:#3498db; font-size:12px; padding:5px 10px;">אשר ידנית</button>
            </form>
            """
        
        items += f"""
        <tr>
          <td>{d['id']}</td>
          <td>{d['created_at']}</td>
          <td style="font-weight:600;">{d['institution_name']}</td>
          <td>
            <div>{d['contact_name']}</div>
            <div style="font-size:12px; opacity:0.7;">{d['email']}</div>
            <div style="font-size:12px; opacity:0.7;">{d['phone']}</div>
          </td>
          <td>{d['plan']}</td>
          <td><span style="background:{status_color}; color:#fff; padding:2px 6px; border-radius:4px; font-size:12px;">{d['payment_status']}</span></td>
          <td>{actions}</td>
        </tr>
        """
        
    body = f"""
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px;">
      <h2>בקשות הרשמה ({len(rows)})</h2>
      <a href="/admin/institutions"><button class="btn-gray">חזרה למוסדות</button></a>
    </div>
    <div class="card" style="padding:0; overflow:hidden;">
      <table style="width:100%; border-collapse:collapse;">
        <thead style="background:#f8f9fa;">
          <tr>
            <th>ID</th>
            <th>תאריך</th>
            <th>מוסד</th>
            <th>איש קשר</th>
            <th>מסלול</th>
            <th>סטטוס</th>
            <th>פעולות</th>
          </tr>
        </thead>
        <tbody>
          {items}
        </tbody>
      </table>
    </div>
    """
    return _super_admin_shell("בקשות הרשמה", body, request)

@app.post("/admin/registrations/approve", response_class=HTMLResponse)
def admin_registrations_approve(request: Request, reg_id: int = Form(...), admin_key: str = '') -> str:
    guard = _admin_require(request, admin_key)
    if guard: return guard
    
    res = _approve_pending_registration(reg_id)
    if res.get('ok'):
        msg = f"ההרשמה אושרה בהצלחה! נוצר Tenant: {res.get('tenant_id')}"
    else:
        msg = f"שגיאה באישור: {res.get('detail')}"
        
    body = f"""
    <div class="card">
        <h2>תוצאת אישור</h2>
        <p>{msg}</p>
        <a href="/admin/registrations"><button>חזרה לרשימה</button></a>
    </div>
    """
    return _super_admin_shell("תוצאה", body, request)

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
def web_device_pair(request: Request, code: str = '') -> str:
    guard = _web_require_teacher(request)
    if guard:
        return guard  # type: ignore[return-value]
    code = str(code or '').strip().upper()
    if not code:
        body = "<h2>חיבור עמדה</h2><p>חסר קוד.</p><div class='actionbar'><a class='gray' href='/web/admin'>חזרה</a></div>"
        return _basic_web_shell('חיבור עמדה', body, request=request)
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
    return _basic_web_shell('חיבור עמדה', body, request=request)


@app.post('/web/device/pair', response_class=HTMLResponse)
def web_device_pair_submit(request: Request, code: str = Form(default='')) -> str:
    guard = _web_require_teacher(request)
    if guard:
        return guard  # type: ignore[return-value]
    _ensure_device_pairings_table()

    tenant_id = _web_tenant_from_cookie(request)
    if not tenant_id:
        return _basic_web_shell('חיבור עמדה', "<h2>חיבור עמדה</h2><p>חסר tenant.</p>", request=request)

    code = str(code or '').strip().upper()
    if not code:
        return _basic_web_shell('חיבור עמדה', "<h2>חיבור עמדה</h2><p>חסר קוד.</p>", request=request)

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
            return _basic_web_shell('חיבור עמדה', "<h2>חיבור עמדה</h2><p>לא נמצא מוסד.</p>", request=request)
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
    return _basic_web_shell('חיבור עמדה', body, request=request)


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
    return _web_redirect_with_next('/web/signin', request=request)


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


@app.get('/web', response_class=HTMLResponse)
@app.get('/web/', response_class=HTMLResponse)
def web_home() -> str:
    body = f"""
    <div style=\"text-align:center;\">
      <div style=\"font-size:28px;font-weight:950; letter-spacing:.2px;\">תוכנת נקודות</div>
      <div style=\"margin-top:10px;line-height:1.9; opacity:.90; max-width:780px; margin-left:auto; margin-right:auto;\">
        מערכת לניהול נקודות בבתי ספר: עמדת תלמידים, עמדת קופה ועמדת ניהול.
        כולל סינכרון ושדרוגים, עם ממשק מהיר ונוח.
      </div>
      <div class=\"actionbar\" style=\"justify-content:center; margin-top:16px;\">
        <a class=\"green\" href=\"/web/signin\">כניסה</a>
        <a class=\"blue\" href=\"/web/download\">הורדה</a>
        <a class=\"gray\" href=\"/web/guide\">מדריך</a>
        <a class=\"gray\" href=\"/web/contact\">צור קשר</a>
      </div>
      <div class=\"small\" style=\"margin-top:14px;\">build: {APP_BUILD_TAG}</div>
    </div>
    """
    return _public_web_shell('דף הבית', body)


@app.get('/web/login', include_in_schema=False)
def web_login(request: Request) -> Response:
    # Do not use _web_redirect_with_next here: it would set next=/web/login
    # and create a redirect loop after successful signin.
    return RedirectResponse(url='/web/signin', status_code=302)


@app.get('/web/logout', include_in_schema=False)
def web_logout() -> Response:
    resp = RedirectResponse(url='/web', status_code=302)
    resp.delete_cookie('web_teacher')
    resp.delete_cookie('web_tenant')
    resp.delete_cookie('web_user')
    return resp


@app.get('/web/signin', response_class=HTMLResponse, response_model=None)
def web_signin(request: Request):
    tenant_id = _web_tenant_from_cookie(request)
    teacher_id = _web_teacher_from_cookie(request)
    if tenant_id and teacher_id:
        return RedirectResponse(url='/web/admin', status_code=302)
    if tenant_id:
        return RedirectResponse(url='/web/teacher-login', status_code=302)

    nxt = _web_next_from_request(request, '/web/teacher-login')
    body = f"""
    <h2>כניסת מוסד</h2>
    <div style=\"color:#637381; margin-top:-6px;\">יש להזין קוד מוסד וסיסמת מוסד.</div>
    <form method=\"post\" action=\"/web/signin?next={urllib.parse.quote(nxt, safe='')}\" style=\"margin-top:12px; max-width:520px;\">
      <label style=\"display:block;margin:10px 0 6px;font-weight:800;\">קוד מוסד</label>
      <input name=\"tenant_id\" autocomplete=\"username\" style=\"width:100%;padding:12px;border:1px solid var(--line);border-radius:10px;font-size:15px;\" required />
      <label style=\"display:block;margin:10px 0 6px;font-weight:800;\">סיסמה</label>
      <input name=\"password\" type=\"password\" autocomplete=\"current-password\" style=\"width:100%;padding:12px;border:1px solid var(--line);border-radius:10px;font-size:15px;\" required />
      <div class=\"actionbar\" style=\"justify-content:flex-start;\">
        <button class=\"green\" type=\"submit\" style=\"padding:10px 14px;border-radius:8px;border:none;background:#2ecc71;color:#fff;font-weight:900;cursor:pointer;\">כניסה</button>
        <a class=\"gray\" href=\"/web/download\" style=\"padding:10px 14px;border-radius:8px;background:#95a5a6;color:#fff;text-decoration:none;font-weight:900;\">הורדה</a>
      </div>
    </form>
    <div class=\"small\">build: {APP_BUILD_TAG}</div>
    """
    return _public_web_shell('כניסת מוסד', body)


@app.post('/web/signin', response_class=HTMLResponse)
def web_signin_submit(
    request: Request,
    tenant_id: str = Form(default=''),
    password: str = Form(default=''),
) -> Response:
    tenant_id = str(tenant_id or '').strip()
    password = str(password or '').strip()
    if not tenant_id or not password:
        return _public_web_shell('כניסת מוסד', '<h2>שגיאה</h2><p>חסרים פרטים.</p>')

    inst = _get_institution(tenant_id)
    if not inst:
        return _public_web_shell('כניסת מוסד', '<h2>שגיאה</h2><p>מוסד לא נמצא.</p>')
    pw_hash = str(inst.get('password_hash') or '').strip()
    if not pw_hash:
        return _public_web_shell('כניסת מוסד', '<h2>שגיאה</h2><p>לא הוגדרה סיסמת מוסד. פנה למנהל.</p>')
    if not _pbkdf2_verify(password, pw_hash):
        return _public_web_shell('כניסת מוסד', '<h2>שגיאה</h2><p>סיסמה שגויה.</p>')

    nxt = _web_next_from_request(request, '/web/teacher-login')
    if nxt in ('/web/login', '/web/signin'):
        nxt = '/web/teacher-login'
    resp = RedirectResponse(url=nxt, status_code=302)
    resp.set_cookie('web_tenant', tenant_id, httponly=True, samesite='lax', max_age=60 * 60 * 24 * 30)
    return resp


@app.get('/web/teacher-login', response_class=HTMLResponse)
def web_teacher_login(request: Request) -> Response:
    guard = _web_require_tenant(request)
    if guard:
        return guard
    nxt = _web_next_from_request(request, '/web/admin')
    body = f"""
    <h2>כניסת מורה</h2>
    <div style=\"color:#637381; margin-top:-6px;\">יש להעביר כרטיס מורה או להזין מספר כרטיס.</div>
    <form method=\"post\" action=\"/web/teacher-login?next={urllib.parse.quote(nxt, safe='')}\" style=\"margin-top:12px; max-width:520px;\">
      <label style=\"display:block;margin:10px 0 6px;font-weight:800;\">כרטיס מורה</label>
      <input name=\"card_number\" type=\"password\" autofocus style=\"width:100%;padding:12px;border:1px solid var(--line);border-radius:10px;font-size:15px;\" required />
      <div class=\"actionbar\" style=\"justify-content:flex-start;\">
        <button class=\"green\" type=\"submit\" style=\"padding:10px 14px;border-radius:8px;border:none;background:#2ecc71;color:#fff;font-weight:900;cursor:pointer;\">כניסה</button>
        <a class=\"gray\" href=\"/web/logout\" style=\"padding:10px 14px;border-radius:8px;background:#95a5a6;color:#fff;text-decoration:none;font-weight:900;\">החלפת מוסד</a>
      </div>
    </form>
    """
    return _public_web_shell('כניסת מורה', body)


@app.post('/web/teacher-login', response_class=HTMLResponse)
def web_teacher_login_submit(
    request: Request,
    card_number: str = Form(default=''),
) -> Response:
    guard = _web_require_tenant(request)
    if guard:
        return guard
    tenant_id = _web_tenant_from_cookie(request)
    card_number = str(card_number or '').strip()
    if not card_number:
        return _public_web_shell('כניסת מורה', '<h2>שגיאה</h2><p>חסר כרטיס.</p>')

    conn = _tenant_school_db(tenant_id)
    try:
        _ensure_teacher_columns(conn)
        cur = conn.cursor()
        cur.execute(
            _sql_placeholder(
                'SELECT id, name, is_admin FROM teachers WHERE card_number = ? OR card_number2 = ? OR card_number3 = ? LIMIT 1'
            ),
            (card_number, card_number, card_number)
        )
        row = cur.fetchone()
        if not row:
            return _public_web_shell('כניסת מורה', '<h2>שגיאה</h2><p>כרטיס מורה לא נמצא.</p>')
        teacher_id = (row.get('id') if isinstance(row, dict) else row['id'])
        teacher_id = str(teacher_id or '').strip()
        if not teacher_id:
            return _public_web_shell('כניסת מורה', '<h2>שגיאה</h2><p>מזהה מורה לא תקין.</p>')
    finally:
        try:
            conn.close()
        except Exception:
            pass

    nxt = _web_next_from_request(request, '/web/admin')
    resp = RedirectResponse(url=nxt, status_code=302)
    resp.set_cookie('web_teacher', str(teacher_id), httponly=True, samesite='lax', max_age=60 * 60 * 24 * 7)
    return resp


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


def _guide_image_sort_key(name: str) -> tuple:
    stem = os.path.splitext(name)[0]
    if stem.isdigit():
        return (0, int(stem))
    return (1, stem.lower())


def _replace_guide_base64_images(html_text: str) -> str:
    images_dir = os.path.join(ROOT_DIR, 'תמונות', 'להוראות')
    if not os.path.isdir(images_dir):
        return html_text

    icon_names = ['admin.png', 'public.png', 'cashier.png', 'installer.png']
    replacements: List[str] = []
    for icon in icon_names:
        icon_path = os.path.join(images_dir, icon)
        if os.path.isfile(icon_path):
            replacements.append(f'/web/assets/guide_images/{icon}')
        else:
            fallback = os.path.join(ROOT_DIR, 'icons', icon)
            if os.path.isfile(fallback):
                replacements.append(f'/web/assets/icons/{icon}')

    other_files: List[str] = []
    for name in os.listdir(images_dir):
        if name in icon_names:
            continue
        ext = os.path.splitext(name)[1].lower()
        if ext in ('.png', '.jpg', '.jpeg', '.gif', '.webp'):
            other_files.append(name)
    other_files.sort(key=_guide_image_sort_key)
    replacements.extend(f'/web/assets/guide_images/{name}' for name in other_files)
    if not replacements:
        return html_text

    pattern = re.compile(r'(<img[^>]+src=["\"])(data:image[^"\"]+)(["\"][^>]*>)', re.IGNORECASE)
    index = 0

    def repl(match: re.Match) -> str:
        nonlocal index
        if index >= len(replacements):
            return match.group(0)
        new_src = replacements[index]
        index += 1
        return f"{match.group(1)}{new_src}{match.group(3)}"

    return pattern.sub(repl, html_text)


@app.get('/web/assets/{asset_path:path}', include_in_schema=False)
def web_assets(asset_path: str) -> Response:
    rel = str(asset_path or '').replace('\\', '/').lstrip('/')
    if not rel or '..' in rel:
        raise HTTPException(status_code=404, detail='Not found')

    rel_l = rel.lower()
    base = ROOT_DIR
    if rel_l.startswith('icons/'):
        base = os.path.join(ROOT_DIR, 'icons')
        rel = rel[len('icons/'):]
    elif rel_l.startswith('guide_images/'):
        base = os.path.join(ROOT_DIR, 'תמונות', 'להוראות')
        rel = rel[len('guide_images/'):]
    elif rel_l.startswith('equipment_required_files/'):
        base = os.path.join(ROOT_DIR, 'equipment_required_files')
        rel = rel[len('equipment_required_files/'):]
    
    full_path = os.path.join(base, rel)
    if not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail='Not found')
    return FileResponse(full_path)


def _public_web_shell(title: str, body_html: str) -> str:
    style_block = """
      <style>
        :root {
          --navy: #1a2639;
          --navy-light: #2c3e50;
          --accent-green: #00b894;
          --accent-blue: #0984e3;
          --accent-purple: #6c5ce7;
          --accent-orange: #fdcb6e;
          --accent-red: #d63031;
          
          --glass-bg: rgba(255, 255, 255, 0.08);
          --glass-bg-hover: rgba(255, 255, 255, 0.12);
          --glass-border: rgba(255, 255, 255, 0.15);
          --glass-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.3);
          
          --text-main: rgba(255, 255, 255, 0.95);
          --text-dim: rgba(255, 255, 255, 0.75);
        }

        * { box-sizing: border-box; }

        html, body { height: 100%; margin: 0; }
        
        body {
          font-family: 'Heebo', 'Segoe UI', Arial, sans-serif;
          color: var(--text-main);
          direction: rtl;
          background: linear-gradient(135deg, #0f2027 0%, #203a43 50%, #2c5364 100%);
          background-attachment: fixed;
          overflow-x: hidden;
        }

        a { text-decoration: none; color: inherit; transition: all 0.2s ease; }

        /* Glassmorphism Utilities */
        .glass {
          background: var(--glass-bg);
          backdrop-filter: blur(16px);
          -webkit-backdrop-filter: blur(16px);
          border: 1px solid var(--glass-border);
          box-shadow: var(--glass-shadow);
        }

        /* Scrollbar */
        ::-webkit-scrollbar { width: 8px; height: 8px; }
        ::-webkit-scrollbar-track { background: rgba(0,0,0,0.1); }
        ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.2); border-radius: 4px; }
        ::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.3); }

        /* Topbar */
        .topbar {
          position: sticky;
          top: 0;
          z-index: 100;
          background: rgba(15, 32, 39, 0.75);
          backdrop-filter: blur(20px);
          -webkit-backdrop-filter: blur(20px);
          border-bottom: 1px solid var(--glass-border);
        }

        .topbar-inner {
          max-width: 1400px;
          margin: 0 auto;
          padding: 10px 20px;
          display: flex;
          align-items: center;
          justify-content: space-between;
          height: 64px;
        }

        .brand { display: flex; align-items: center; gap: 12px; }
        .brand img { width: 40px; height: 40px; border-radius: 10px; box-shadow: 0 4px 12px rgba(0,0,0,0.2); }
        .brand-text { display: flex; flex-direction: column; }
        .brand-title { font-weight: 900; font-size: 18px; letter-spacing: 0.5px; line-height: 1; }
        .brand-sub { font-size: 11px; color: var(--text-dim); letter-spacing: 1px; margin-top: 4px; text-transform: uppercase; }

        .top-nav { display: flex; align-items: center; gap: 12px; }
        
        .btn-glass {
          display: inline-flex;
          align-items: center;
          gap: 8px;
          padding: 8px 16px;
          border-radius: 12px;
          font-weight: 700;
          font-size: 14px;
          background: rgba(255,255,255,0.1);
          border: 1px solid rgba(255,255,255,0.2);
          transition: all 0.2s;
        }
        .btn-glass:hover { background: rgba(255,255,255,0.2); transform: translateY(-1px); }
        .btn-glass.primary { background: linear-gradient(135deg, var(--accent-blue), #00cec9); border: none; box-shadow: 0 4px 15px rgba(9, 132, 227, 0.4); }
        .btn-glass.primary:hover { filter: brightness(1.1); box-shadow: 0 6px 20px rgba(9, 132, 227, 0.5); }

        /* Layout */
        .layout-container {
          max-width: 1400px;
          margin: 24px auto;
          padding: 0 20px;
          display: flex;
          gap: 24px;
          align-items: flex-start;
          justify-content: center;
        }

        /* Main Content */
        .main-content { flex: 1; min-width: 0; max-width: 800px; }
        
        .page-card {
          background: var(--glass-bg);
          backdrop-filter: blur(24px);
          -webkit-backdrop-filter: blur(24px);
          border: 1px solid var(--glass-border);
          border-radius: 20px;
          padding: 24px;
          box-shadow: var(--glass-shadow);
          min-height: 400px;
        }

        .page-header {
          display: flex;
          justify-content: center;
          align-items: center;
          margin-bottom: 24px;
          padding-bottom: 16px;
          border-bottom: 1px solid rgba(255,255,255,0.1);
        }
        .page-title { margin: 0; font-size: 24px; font-weight: 900; background: linear-gradient(135deg, #fff, #b2bec3); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        
        .footerbar {
          margin-top: 16px;
          padding-top: 14px;
          border-top: 1px solid rgba(255,255,255,0.18);
          display: flex;
          gap: 12px;
          flex-wrap: wrap;
          justify-content: space-between;
          align-items: center;
        }
        .footer-title { font-weight: 950; opacity: .96; }
        .whoami { margin-top: 6px; font-weight: 800; }
        .whoami a { text-decoration: none; font-weight: 900; }
        .whoami-row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
        .whoami-name { font-weight: 950; }
        .footer-actions { display: flex; gap: 10px; flex-wrap: wrap; justify-content: flex-end; }

        /* Responsive */
        @media (max-width: 900px) {
            .layout-container { flex-direction: column; }
        }
      </style>
    """

    footer = """
      <div class="footerbar">
        <div class="footer-left">
          <div class="footer-title">אזור אישי</div>
          <div id="whoami" class="whoami">
            <a href="/web/signin">התחברות</a>
          </div>
        </div>
        <div class="footer-actions">
          <a class="btn-glass" href="/web">דף הבית</a>
          <a class="btn-glass" href="javascript:history.back()">אחורה</a>
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
              <div class="whoami-row">
                <span class="whoami-name">${name}</span>
                <a href="/web/account">תפריט מוסד</a>
                <a href="/web/logout">יציאה</a>
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
      <link href="https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;700;900&display=swap" rel="stylesheet">
      {style_block}
    </head>
    <body>
      <!-- Topbar -->
      <nav class="topbar">
        <div class="topbar-inner">
          <div class="brand">
            <img src="/web/assets/icons/public.png" alt="Logo">
            <div class="brand-text">
                <div class="brand-title">SchoolPoints</div>
                <div class="brand-sub">עמדת ניהול מתקדמת</div>
            </div>
          </div>
          <div class="top-nav">
             <a href="/web/signin" class="btn-glass primary">
                <span>🔑</span>
                <span>כניסה</span>
             </a>
             <a href="/web/download" class="btn-glass">
                <span>⬇️</span>
                <span>הורדה</span>
             </a>
          </div>
        </div>
      </nav>

      <!-- Layout -->
      <div class="layout-container">
        <!-- Main Content -->
        <main class="main-content">
            <div class="page-card">
                <div class="page-header">
                    <h2 class="page-title">{title}</h2>
                </div>
                
                <div class="content-body">
                    {body_html}
                    {footer}
                </div>
            </div>
        </main>
      </div>
    </body>
    </html>
    """

def _basic_web_shell(title: str, body_html: str, request: Request = None) -> str:
    style_block = """
      <style>
        :root {
          --navy: #1a2639;
          --navy-light: #2c3e50;
          --accent-green: #00b894;
          --accent-blue: #0984e3;
          --accent-purple: #6c5ce7;
          --accent-orange: #fdcb6e;
          --accent-red: #d63031;
          
          --glass-bg: rgba(255, 255, 255, 0.08);
          --glass-bg-hover: rgba(255, 255, 255, 0.12);
          --glass-border: rgba(255, 255, 255, 0.15);
          --glass-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.3);
          
          --text-main: rgba(255, 255, 255, 0.95);
          --text-dim: rgba(255, 255, 255, 0.75);
        }

        * { box-sizing: border-box; }

        html, body { height: 100%; margin: 0; }
        
        body {
          font-family: 'Heebo', 'Segoe UI', Arial, sans-serif;
          color: var(--text-main);
          direction: rtl;
          background: linear-gradient(135deg, #0f2027 0%, #203a43 50%, #2c5364 100%);
          background-attachment: fixed;
          overflow-x: hidden;
        }

        a { text-decoration: none; color: inherit; transition: all 0.2s ease; }

        /* Glassmorphism Utilities */
        .glass {
          background: var(--glass-bg);
          backdrop-filter: blur(16px);
          -webkit-backdrop-filter: blur(16px);
          border: 1px solid var(--glass-border);
          box-shadow: var(--glass-shadow);
        }

        /* Scrollbar */
        ::-webkit-scrollbar { width: 8px; height: 8px; }
        ::-webkit-scrollbar-track { background: rgba(0,0,0,0.1); }
        ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.2); border-radius: 4px; }
        ::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.3); }

        /* Topbar */
        .topbar {
          position: sticky;
          top: 0;
          z-index: 100;
          background: rgba(15, 32, 39, 0.75);
          backdrop-filter: blur(20px);
          -webkit-backdrop-filter: blur(20px);
          border-bottom: 1px solid var(--glass-border);
        }

        .topbar-inner {
          max-width: 1400px;
          margin: 0 auto;
          padding: 10px 20px;
          display: flex;
          align-items: center;
          justify-content: space-between;
          height: 64px;
        }

        .brand { display: flex; align-items: center; gap: 12px; }
        .brand img { width: 40px; height: 40px; border-radius: 10px; box-shadow: 0 4px 12px rgba(0,0,0,0.2); }
        .brand-text { display: flex; flex-direction: column; }
        .brand-title { font-weight: 900; font-size: 18px; letter-spacing: 0.5px; line-height: 1; }
        .brand-sub { font-size: 11px; color: var(--text-dim); letter-spacing: 1px; margin-top: 4px; text-transform: uppercase; }

        .top-nav { display: flex; align-items: center; gap: 12px; }
        
        .btn-glass {
          display: inline-flex;
          align-items: center;
          gap: 8px;
          padding: 8px 16px;
          border-radius: 12px;
          font-weight: 700;
          font-size: 14px;
          background: rgba(255,255,255,0.1);
          border: 1px solid rgba(255,255,255,0.2);
          transition: all 0.2s;
        }
        .btn-glass:hover { background: rgba(255,255,255,0.2); transform: translateY(-1px); }
        .btn-glass.primary { background: linear-gradient(135deg, var(--accent-blue), #00cec9); border: none; box-shadow: 0 4px 15px rgba(9, 132, 227, 0.4); }
        .btn-glass.primary:hover { filter: brightness(1.1); box-shadow: 0 6px 20px rgba(9, 132, 227, 0.5); }

        /* Layout */
        .layout-container {
          max-width: 1400px;
          margin: 24px auto;
          padding: 0 20px;
          display: flex;
          gap: 24px;
          align-items: flex-start;
          justify-content: center;
        }

        /* Main Content */
        .main-content { flex: 1; min-width: 0; max-width: 800px; }
        
        .page-card {
          background: var(--glass-bg);
          backdrop-filter: blur(24px);
          -webkit-backdrop-filter: blur(24px);
          border: 1px solid var(--glass-border);
          border-radius: 20px;
          padding: 24px;
          box-shadow: var(--glass-shadow);
          min-height: 400px;
        }

        .page-header {
          display: flex;
          justify-content: center;
          align-items: center;
          margin-bottom: 24px;
          padding-bottom: 16px;
          border-bottom: 1px solid rgba(255,255,255,0.1);
        }
        .page-title { margin: 0; font-size: 24px; font-weight: 900; background: linear-gradient(135deg, #fff, #b2bec3); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        
        .footerbar {
          margin-top: 16px;
          padding-top: 14px;
          border-top: 1px solid rgba(255,255,255,0.18);
          display: flex;
          gap: 12px;
          flex-wrap: wrap;
          justify-content: space-between;
          align-items: center;
        }
        .footer-title { font-weight: 950; opacity: .96; }
        .whoami { margin-top: 6px; font-weight: 800; }
        .whoami a { text-decoration: none; font-weight: 900; }
        .whoami-row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
        .whoami-name { font-weight: 950; }
        .footer-actions { display: flex; gap: 10px; flex-wrap: wrap; justify-content: flex-end; }

        /* Responsive */
        @media (max-width: 900px) {
            .layout-container { flex-direction: column; }
        }
      </style>
    """

    footer = """
      <div class="footerbar">
        <div class="footer-left">
          <div class="footer-title">אזור אישי</div>
          <div id="whoami" class="whoami">
            <a href="/web/signin">התחברות</a>
          </div>
        </div>
        <div class="footer-actions">
          <a class="btn-glass" href="/web/admin">לוח בקרה</a>
          <a class="btn-glass" href="javascript:history.back()">אחורה</a>
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
              <div class="whoami-row">
                <span class="whoami-name">${name}</span>
                <a href="/web/account">תפריט מוסד</a>
                <a href="/web/logout">יציאה</a>
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
      <link href="https://fonts.googleapis.com/css2?family=Heebo:wght@300;400;700;900&display=swap" rel="stylesheet">
      {style_block}
    </head>
    <body>
      <!-- Topbar -->
      <nav class="topbar">
        <div class="topbar-inner">
          <div class="brand">
            <img src="/web/assets/icons/public.png" alt="Logo">
            <div class="brand-text">
                <div class="brand-title">SchoolPoints</div>
                <div class="brand-sub">עמדת ניהול מתקדמת</div>
            </div>
          </div>
          <div class="top-nav">
             <a href="/web/admin" class="btn-glass primary">
                <span>🏠</span>
                <span>לוח בקרה</span>
             </a>
             <a href="/web/logout" class="btn-glass">
                <span>🚪</span>
                <span>יציאה</span>
             </a>
          </div>
        </div>
      </nav>

      <!-- Layout -->
      <div class="layout-container">
        <!-- Main Content -->
        <main class="main-content">
            <div class="page-card">
                <div class="page-header">
                    <h2 class="page-title">{title}</h2>
                </div>
                
                <div class="content-body">
                    {body_html}
                    {footer}
                </div>
            </div>
        </main>
      </div>
    </body>
    </html>
    """

def _init_db():
    conn = _db()
    try:
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
    finally:
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
            cur.execute(
                f'''
                CREATE TABLE IF NOT EXISTS "{schema}".static_messages (
                    id BIGSERIAL PRIMARY KEY,
                    message TEXT NOT NULL,
                    show_always INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                )
                '''
            )
            cur.execute(
                f'''
                CREATE TABLE IF NOT EXISTS "{schema}".threshold_messages (
                    id BIGSERIAL PRIMARY KEY,
                    min_points INTEGER NOT NULL,
                    max_points INTEGER NOT NULL,
                    message TEXT NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                )
                '''
            )
            cur.execute(
                f'''
                CREATE TABLE IF NOT EXISTS "{schema}".news_items (
                    id BIGSERIAL PRIMARY KEY,
                    text TEXT NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    sort_order INTEGER,
                    start_date TEXT,
                    end_date TEXT,
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                )
                '''
            )
            cur.execute(
                f'''
                CREATE TABLE IF NOT EXISTS "{schema}".ads_items (
                    id BIGSERIAL PRIMARY KEY,
                    text TEXT NOT NULL,
                    image_path TEXT,
                    is_active INTEGER DEFAULT 1,
                    sort_order INTEGER,
                    start_date TEXT,
                    end_date TEXT,
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                )
                '''
            )
            cur.execute(
                f'''
                CREATE TABLE IF NOT EXISTS "{schema}".student_messages (
                    id BIGSERIAL PRIMARY KEY,
                    student_id BIGINT NOT NULL,
                    message TEXT NOT NULL,
                    is_active INTEGER DEFAULT 1,
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
    cur.execute(
        '''
        CREATE TABLE IF NOT EXISTS static_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message TEXT NOT NULL,
            show_always INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        '''
    )
    cur.execute(
        '''
        CREATE TABLE IF NOT EXISTS threshold_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            min_points INTEGER NOT NULL,
            max_points INTEGER NOT NULL,
            message TEXT NOT NULL,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        '''
    )
    cur.execute(
        '''
        CREATE TABLE IF NOT EXISTS news_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            is_active INTEGER DEFAULT 1,
            sort_order INTEGER,
            start_date TEXT,
            end_date TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        '''
    )
    cur.execute(
        '''
        CREATE TABLE IF NOT EXISTS ads_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            image_path TEXT,
            is_active INTEGER DEFAULT 1,
            sort_order INTEGER,
            start_date TEXT,
            end_date TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        '''
    )
    cur.execute(
        '''
        CREATE TABLE IF NOT EXISTS student_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            message TEXT NOT NULL,
            is_active INTEGER DEFAULT 1,
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
    static_messages: List[Dict[str, Any]] = []
    threshold_messages: List[Dict[str, Any]] = []
    news_items: List[Dict[str, Any]] = []
    ads_items: List[Dict[str, Any]] = []
    student_messages: List[Dict[str, Any]] = []


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


class StudentSavePayload(BaseModel):
    student_id: int | None = None
    last_name: str | None = None
    first_name: str | None = None
    id_number: str | None = None
    class_name: str | None = None
    card_number: str | None = None
    photo_number: str | None = None
    serial_number: str | None = None
    points: int | None = None
    private_message: str | None = None


class StudentDeletePayload(BaseModel):
    student_id: int


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


class TeacherClassesPayload(BaseModel):
    teacher_id: int
    classes: List[str] = []


class StaticMessagePayload(BaseModel):
    message_id: int | None = None
    message: str | None = None
    show_always: int | None = None


class StaticMessageTogglePayload(BaseModel):
    message_id: int


class ThresholdMessagePayload(BaseModel):
    message_id: int | None = None
    min_points: int | None = None
    max_points: int | None = None
    message: str | None = None


class ThresholdMessageTogglePayload(BaseModel):
    message_id: int


class NewsItemPayload(BaseModel):
    news_id: int | None = None
    text: str | None = None
    start_date: str | None = None
    end_date: str | None = None


class NewsItemTogglePayload(BaseModel):
    news_id: int


class NewsReorderPayload(BaseModel):
    news_id: int
    direction: str


class AdsItemPayload(BaseModel):
    ads_id: int | None = None
    text: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    image_path: str | None = None


class AdsItemTogglePayload(BaseModel):
    ads_id: int


class AdsReorderPayload(BaseModel):
    ads_id: int
    direction: str


class StudentMessagePayload(BaseModel):
    message_id: int | None = None
    student_id: int | None = None
    message: str | None = None


class StudentMessageTogglePayload(BaseModel):
    message_id: int


class NewsSettingsPayload(BaseModel):
    show_weekday: int | None = None
    show_hebrew_date: int | None = None
    show_parsha: int | None = None
    show_holidays: int | None = None
    ticker_speed: str | None = None


class AdsSettingsPayload(BaseModel):
    popup_enabled: int | None = None
    popup_idle_sec: int | None = None
    popup_show_sec: float | None = None
    popup_gap_sec: float | None = None
    popup_border: int | None = None


class GenericSettingPayload(BaseModel):
    key: str
    value: Dict[str, Any]


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


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def _bool_int(v: Any, default: int = 0) -> int:
    if v is None:
        return int(default)
    if isinstance(v, bool):
        return 1 if v else 0
    if isinstance(v, (int, float)):
        return 1 if int(v) != 0 else 0
    s = str(v).strip().lower()
    if s in ('1', 'true', 'yes', 'on'):
        return 1
    if s in ('0', 'false', 'no', 'off'):
        return 0
    return int(default)


def _normalize_date(value: Any) -> str | None:
    s = _safe_str(value).strip()
    if not s:
        return None
    if '.' in s:
        parts = s.split('.')
        if len(parts) == 3:
            return f"{parts[2].zfill(4)}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"
    if len(s) >= 10 and s[4:5] == '-' and s[7:8] == '-':
        return s[:10]
    return s


def _row_value(row: Any, key: str, index: int = 0) -> Any:
    try:
        return row[key]
    except Exception:
        try:
            return row.get(key)
        except Exception:
            try:
                return row[index]
            except Exception:
                return None


def _get_setting_value(conn, key: str, default: str = '') -> str:
    cur = conn.cursor()
    cur.execute(_sql_placeholder('SELECT value FROM settings WHERE "key" = ? LIMIT 1'), (str(key or '').strip(),))
    row = cur.fetchone()
    if not row:
        return default
    val = _row_value(row, 'value', 0)
    s = str(val) if val is not None else ''
    return s if s else default


def _set_setting_value(conn, key: str, value: Any) -> None:
    cur = conn.cursor()
    cur.execute(
        _sql_placeholder(
            'INSERT INTO settings ("key", value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) '
            'ON CONFLICT("key") DO UPDATE SET value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP'
        ),
        (str(key or '').strip(), str(value if value is not None else '').strip())
    )


def _get_system_settings(tenant_id: str) -> Dict[str, Any]:
    if not tenant_id:
        return {}
    conn = _tenant_school_db(tenant_id)
    try:
        value_json = _get_web_setting_json(conn, 'system_settings', '{}')
    finally:
        try:
            conn.close()
        except Exception:
            pass
    try:
        return json.loads(value_json) if value_json else {}
    except Exception:
        return {}


def _get_shared_folder_for_tenant(tenant_id: str) -> str:
    cfg = _get_system_settings(tenant_id)
    try:
        shared = str(cfg.get('shared_folder') or cfg.get('network_root') or '').strip()
    except Exception:
        shared = ''
    if not shared:
        return ''
    try:
        if os.path.isdir(shared):
            return shared
    except Exception:
        return ''
    return ''


def _reset_sort_order(conn, table: str) -> None:
    cur = conn.cursor()
    cur.execute(f'SELECT id FROM {table} ORDER BY created_at DESC')
    rows = cur.fetchall() or []
    order = 1
    for row in rows:
        rid = _safe_int(_row_value(row, 'id', 0), 0)
        if rid <= 0:
            continue
        cur.execute(_sql_placeholder(f'UPDATE {table} SET sort_order = ? WHERE id = ?'), (order, rid))
        order += 1


def _swap_sort_order(conn, table: str, first_id: int, second_id: int) -> bool:
    if first_id == second_id:
        return False
    cur = conn.cursor()
    cur.execute(_sql_placeholder(f'SELECT id, sort_order FROM {table} WHERE id IN (?, ?)'), (int(first_id), int(second_id)))
    rows = cur.fetchall() or []
    if len(rows) != 2:
        return False
    orders: Dict[int, Any] = {}
    for row in rows:
        rid = _safe_int(_row_value(row, 'id', 0), 0)
        orders[rid] = _row_value(row, 'sort_order', 1)
    order1 = orders.get(int(first_id))
    order2 = orders.get(int(second_id))
    if order1 is None or order2 is None:
        _reset_sort_order(conn, table)
        cur.execute(_sql_placeholder(f'SELECT id, sort_order FROM {table} WHERE id IN (?, ?)'), (int(first_id), int(second_id)))
        rows = cur.fetchall() or []
        orders = {}
        for row in rows:
            rid = _safe_int(_row_value(row, 'id', 0), 0)
            orders[rid] = _row_value(row, 'sort_order', 1)
        order1 = orders.get(int(first_id))
        order2 = orders.get(int(second_id))
    if order1 is None or order2 is None:
        return False
    cur.execute(_sql_placeholder(f'UPDATE {table} SET sort_order = ? WHERE id = ?'), (order2, int(first_id)))
    cur.execute(_sql_placeholder(f'UPDATE {table} SET sort_order = ? WHERE id = ?'), (order1, int(second_id)))
    conn.commit()
    return True


def _record_tenant_change(tenant_id: str, entity_type: str, entity_id: str | int, action_type: str, payload: Dict[str, Any] | None) -> None:
    if not tenant_id:
        return
    conn = _db()
    try:
        cur = conn.cursor()
        cur.execute(
            _sql_placeholder(
                '''
                INSERT INTO changes (tenant_id, station_id, entity_type, entity_id, action_type, payload_json, created_at)
                VALUES (?, 'web', ?, ?, ?, ?, CURRENT_TIMESTAMP)
                '''
            ),
            (
                str(tenant_id),
                str(entity_type),
                str(entity_id),
                str(action_type),
                json.dumps(payload or {}, ensure_ascii=False)
            )
        )
        conn.commit()
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _persist_ads_media(request: Request, tenant_id: str, upload: UploadFile) -> str:
    if not upload:
        return ''
    ext = ''
    try:
        ext = os.path.splitext(str(upload.filename or ''))[1].lower()
    except Exception:
        ext = ''
    if ext not in ('.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp'):
        ext = '.png'
    data = upload.file.read()
    if not data:
        return ''

    media_rel = os.path.join('ads_media', f"{uuid.uuid4().hex}{ext}")
    shared_folder = _get_shared_folder_for_tenant(tenant_id)
    if shared_folder:
        try:
            dst_abs = os.path.join(shared_folder, media_rel)
            os.makedirs(os.path.dirname(dst_abs), exist_ok=True)
            with open(dst_abs, 'wb') as f:
                f.write(data)
            return media_rel
        except Exception:
            return ''

    s3 = _spaces_client()
    if s3 is None:
        # Local fallback if no S3 and no shared folder
        assets_dir = os.path.join(DATA_DIR, 'tenants_assets', tenant_id)
        os.makedirs(assets_dir, exist_ok=True)
        # Use simple name
        name = os.path.basename(media_rel)
        path = os.path.join(assets_dir, name)
        with open(path, 'wb') as f:
            f.write(data)
        return name

    key = f"tenants/{tenant_id}/{media_rel.replace('\\', '/')}"
    try:
        s3.put_object(Bucket=SPACES_BUCKET, Key=key, Body=data, ContentType=upload.content_type or 'application/octet-stream')
    except Exception:
        return ''
    base = str(SPACES_CDN_BASE_URL or '').strip().rstrip('/')
    if base:
        return base + '/' + urllib.parse.quote(key)
    return key


@app.get("/assets/{tenant_id}/{filename}")
def get_tenant_asset(tenant_id: str, filename: str):
    # Serve tenant assets (if local)
    # This covers both 'ads_media' from legacy and new assets
    # check legacy ads_media first if needed or just shared folder
    shared = _get_shared_folder_for_tenant(tenant_id)
    if shared:
        path = os.path.join(shared, 'ads_media', filename)
        if os.path.isfile(path):
            return FileResponse(path)
    
    # check local data dir tenants_assets
    assets_dir = os.path.join(DATA_DIR, 'tenants_assets', tenant_id)
    path = os.path.join(assets_dir, filename)
    if os.path.isfile(path):
        return FileResponse(path)
        
    return Response(status_code=404)


def _ads_media_url(request: Request, tenant_id: str, image_path: str) -> str:
    p = str(image_path or '').strip()
    if not p:
        return ''
    lower = p.lower()
    if lower.startswith('http://') or lower.startswith('https://'):
        return p
    if p.startswith('tenants/') and SPACES_CDN_BASE_URL:
        base = str(SPACES_CDN_BASE_URL or '').strip().rstrip('/')
        return base + '/' + urllib.parse.quote(p)
    if p.startswith('tenants/') and SPACES_ENDPOINT and SPACES_BUCKET:
        base = str(SPACES_ENDPOINT or '').strip().rstrip('/')
        return f"{base}/{SPACES_BUCKET}/" + urllib.parse.quote(p)
    rel = p.replace('\\', '/').lstrip('/')
    base = _public_base_url(request)
    try:
        quoted = urllib.parse.quote(rel)
        return f"{base}/assets/{tenant_id}/{quoted}"
    except Exception:
        return p


# --- MESSAGES API ---

@app.get('/api/messages/static')
def api_messages_static(request: Request) -> Dict[str, Any]:
    guard = _web_require_admin_teacher(request)
    if guard:
        return {'items': []}
    tenant_id = _web_tenant_from_cookie(request)
    conn = _tenant_school_db(tenant_id)
    try:
        items = _fetch_table_rows(conn, 'static_messages')
        # Sort: ID desc
        items.sort(key=lambda x: _safe_int(x.get('id'), 0), reverse=True)
        return {'items': items}
    finally:
        try: conn.close()
        except: pass

@app.post('/api/messages/static/save')
def api_messages_static_save(request: Request, payload: StaticMessagePayload) -> Dict[str, Any]:
    guard = _web_require_admin_teacher(request)
    if guard:
        raise HTTPException(status_code=401)
    tenant_id = _web_tenant_from_cookie(request)
    conn = _tenant_school_db(tenant_id)
    try:
        cur = conn.cursor()
        mid = payload.message_id
        msg = str(payload.message or '').strip()
        if not msg:
            raise HTTPException(status_code=400, detail="Empty message")
        show_always = 1 if payload.show_always else 0
        
        if mid and int(mid) > 0:
            cur.execute(
                _sql_placeholder('UPDATE static_messages SET message=?, show_always=? WHERE id=?'),
                (msg, show_always, int(mid))
            )
            act = 'update'
            rid = int(mid)
        else:
            cur.execute(
                _sql_placeholder('INSERT INTO static_messages (message, show_always, is_active) VALUES (?, ?, 1)'),
                (msg, show_always)
            )
            rid = cur.lastrowid
            act = 'create'
            
        conn.commit()
        _record_tenant_change(tenant_id, 'static_message', rid, act, payload.dict())
        return {'ok': True, 'id': rid}
    finally:
        try: conn.close()
        except: pass

@app.post('/api/messages/static/delete')
def api_messages_static_delete(request: Request, payload: StaticMessageTogglePayload) -> Dict[str, Any]:
    guard = _web_require_admin_teacher(request)
    if guard:
        raise HTTPException(status_code=401)
    tenant_id = _web_tenant_from_cookie(request)
    conn = _tenant_school_db(tenant_id)
    try:
        cur = conn.cursor()
        cur.execute(_sql_placeholder('DELETE FROM static_messages WHERE id=?'), (int(payload.message_id),))
        conn.commit()
        _record_tenant_change(tenant_id, 'static_message', payload.message_id, 'delete', None)
        return {'ok': True}
    finally:
        try: conn.close()
        except: pass

@app.post('/api/messages/static/toggle')
def api_messages_static_toggle(request: Request, payload: StaticMessageTogglePayload) -> Dict[str, Any]:
    guard = _web_require_admin_teacher(request)
    if guard:
        raise HTTPException(status_code=401)
    tenant_id = _web_tenant_from_cookie(request)
    conn = _tenant_school_db(tenant_id)
    try:
        cur = conn.cursor()
        cur.execute(_sql_placeholder('SELECT is_active FROM static_messages WHERE id=?'), (int(payload.message_id),))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404)
        curr = _safe_int(_row_value(row, 'is_active'), 1)
        new_val = 0 if curr == 1 else 1
        cur.execute(_sql_placeholder('UPDATE static_messages SET is_active=? WHERE id=?'), (new_val, int(payload.message_id)))
        conn.commit()
        _record_tenant_change(tenant_id, 'static_message', payload.message_id, 'update', {'is_active': new_val})
        return {'ok': True, 'is_active': new_val}
    finally:
        try: conn.close()
        except: pass

@app.get('/api/messages/threshold')
def api_messages_threshold(request: Request) -> Dict[str, Any]:
    guard = _web_require_admin_teacher(request)
    if guard:
        return {'items': []}
    tenant_id = _web_tenant_from_cookie(request)
    conn = _tenant_school_db(tenant_id)
    try:
        items = _fetch_table_rows(conn, 'threshold_messages')
        # Sort by min_points desc
        items.sort(key=lambda x: _safe_int(x.get('min_points'), 0), reverse=True)
        return {'items': items}
    finally:
        try: conn.close()
        except: pass

@app.post('/api/messages/threshold/save')
def api_messages_threshold_save(request: Request, payload: ThresholdMessagePayload) -> Dict[str, Any]:
    guard = _web_require_admin_teacher(request)
    if guard:
        raise HTTPException(status_code=401)
    tenant_id = _web_tenant_from_cookie(request)
    conn = _tenant_school_db(tenant_id)
    try:
        cur = conn.cursor()
        mid = payload.message_id
        msg = str(payload.message or '').strip()
        min_p = int(payload.min_points or 0)
        max_p = int(payload.max_points or 0)
        if not msg:
            raise HTTPException(status_code=400, detail="Empty message")
        
        if mid and int(mid) > 0:
            cur.execute(
                _sql_placeholder('UPDATE threshold_messages SET message=?, min_points=?, max_points=? WHERE id=?'),
                (msg, min_p, max_p, int(mid))
            )
            act = 'update'
            rid = int(mid)
        else:
            cur.execute(
                _sql_placeholder('INSERT INTO threshold_messages (message, min_points, max_points, is_active) VALUES (?, ?, ?, 1)'),
                (msg, min_p, max_p)
            )
            rid = cur.lastrowid
            act = 'create'
            
        conn.commit()
        _record_tenant_change(tenant_id, 'threshold_message', rid, act, payload.dict())
        return {'ok': True, 'id': rid}
    finally:
        try: conn.close()
        except: pass

@app.post('/api/messages/threshold/delete')
def api_messages_threshold_delete(request: Request, payload: ThresholdMessageTogglePayload) -> Dict[str, Any]:
    guard = _web_require_admin_teacher(request)
    if guard:
        raise HTTPException(status_code=401)
    tenant_id = _web_tenant_from_cookie(request)
    conn = _tenant_school_db(tenant_id)
    try:
        cur = conn.cursor()
        cur.execute(_sql_placeholder('DELETE FROM threshold_messages WHERE id=?'), (int(payload.message_id),))
        conn.commit()
        _record_tenant_change(tenant_id, 'threshold_message', payload.message_id, 'delete', None)
        return {'ok': True}
    finally:
        try: conn.close()
        except: pass

@app.post('/api/messages/threshold/toggle')
def api_messages_threshold_toggle(request: Request, payload: ThresholdMessageTogglePayload) -> Dict[str, Any]:
    guard = _web_require_admin_teacher(request)
    if guard:
        raise HTTPException(status_code=401)
    tenant_id = _web_tenant_from_cookie(request)
    conn = _tenant_school_db(tenant_id)
    try:
        cur = conn.cursor()
        cur.execute(_sql_placeholder('SELECT is_active FROM threshold_messages WHERE id=?'), (int(payload.message_id),))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404)
        curr = _safe_int(_row_value(row, 'is_active'), 1)
        new_val = 0 if curr == 1 else 1
        cur.execute(_sql_placeholder('UPDATE threshold_messages SET is_active=? WHERE id=?'), (new_val, int(payload.message_id)))
        conn.commit()
        _record_tenant_change(tenant_id, 'threshold_message', payload.message_id, 'update', {'is_active': new_val})
        return {'ok': True, 'is_active': new_val}
    finally:
        try: conn.close()
        except: pass

@app.get('/api/messages/news')
def api_messages_news(request: Request) -> Dict[str, Any]:
    guard = _web_require_admin_teacher(request)
    if guard:
        return {'items': []}
    tenant_id = _web_tenant_from_cookie(request)
    conn = _tenant_school_db(tenant_id)
    try:
        items = _fetch_table_rows(conn, 'news_items')
        # Sort by sort_order
        items.sort(key=lambda x: _safe_int(x.get('sort_order'), 9999))
        return {'items': items}
    finally:
        try: conn.close()
        except: pass

@app.post('/api/messages/news/save')
def api_messages_news_save(request: Request, payload: NewsItemPayload) -> Dict[str, Any]:
    guard = _web_require_admin_teacher(request)
    if guard:
        raise HTTPException(status_code=401)
    tenant_id = _web_tenant_from_cookie(request)
    conn = _tenant_school_db(tenant_id)
    try:
        cur = conn.cursor()
        nid = payload.news_id
        txt = str(payload.text or '').strip()
        if not txt:
            raise HTTPException(status_code=400, detail="Empty text")
        start_dt = _normalize_date(payload.start_date)
        end_dt = _normalize_date(payload.end_date)
        
        if nid and int(nid) > 0:
            cur.execute(
                _sql_placeholder('UPDATE news_items SET text=?, start_date=?, end_date=? WHERE id=?'),
                (txt, start_dt, end_dt, int(nid))
            )
            act = 'update'
            rid = int(nid)
        else:
            # Get max sort order
            cur.execute('SELECT MAX(sort_order) FROM news_items')
            row = cur.fetchone()
            max_so = 0
            if row:
                max_so = _safe_int(row[0] if not isinstance(row, dict) else row.get('MAX(sort_order)'), 0)
            
            cur.execute(
                _sql_placeholder('INSERT INTO news_items (text, start_date, end_date, is_active, sort_order) VALUES (?, ?, ?, 1, ?)'),
                (txt, start_dt, end_dt, max_so + 1)
            )
            rid = cur.lastrowid
            act = 'create'
            
        conn.commit()
        _record_tenant_change(tenant_id, 'news_item', rid, act, payload.dict())
        return {'ok': True, 'id': rid}
    finally:
        try: conn.close()
        except: pass

@app.post('/api/messages/news/delete')
def api_messages_news_delete(request: Request, payload: NewsItemTogglePayload) -> Dict[str, Any]:
    guard = _web_require_admin_teacher(request)
    if guard:
        raise HTTPException(status_code=401)
    tenant_id = _web_tenant_from_cookie(request)
    conn = _tenant_school_db(tenant_id)
    try:
        cur = conn.cursor()
        cur.execute(_sql_placeholder('DELETE FROM news_items WHERE id=?'), (int(payload.news_id),))
        conn.commit()
        _record_tenant_change(tenant_id, 'news_item', payload.news_id, 'delete', None)
        return {'ok': True}
    finally:
        try: conn.close()
        except: pass

@app.post('/api/messages/news/toggle')
def api_messages_news_toggle(request: Request, payload: NewsItemTogglePayload) -> Dict[str, Any]:
    guard = _web_require_admin_teacher(request)
    if guard:
        raise HTTPException(status_code=401)
    tenant_id = _web_tenant_from_cookie(request)
    conn = _tenant_school_db(tenant_id)
    try:
        cur = conn.cursor()
        cur.execute(_sql_placeholder('SELECT is_active FROM news_items WHERE id=?'), (int(payload.news_id),))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404)
        curr = _safe_int(_row_value(row, 'is_active'), 1)
        new_val = 0 if curr == 1 else 1
        cur.execute(_sql_placeholder('UPDATE news_items SET is_active=? WHERE id=?'), (new_val, int(payload.news_id)))
        conn.commit()
        _record_tenant_change(tenant_id, 'news_item', payload.news_id, 'update', {'is_active': new_val})
        return {'ok': True, 'is_active': new_val}
    finally:
        try: conn.close()
        except: pass

@app.post('/api/messages/news/reorder')
def api_messages_news_reorder(request: Request, payload: NewsReorderPayload) -> Dict[str, Any]:
    guard = _web_require_admin_teacher(request)
    if guard:
        raise HTTPException(status_code=401)
    tenant_id = _web_tenant_from_cookie(request)
    conn = _tenant_school_db(tenant_id)
    try:
        items = _fetch_table_rows(conn, 'news_items')
        items.sort(key=lambda x: _safe_int(x.get('sort_order'), 9999))
        
        # find current index
        idx = -1
        for i, item in enumerate(items):
            if _safe_int(item.get('id')) == int(payload.news_id):
                idx = i
                break
        
        if idx == -1:
            return {'ok': False}
            
        swap_idx = -1
        if payload.direction == 'up' and idx > 0:
            swap_idx = idx - 1
        elif payload.direction == 'down' and idx < len(items) - 1:
            swap_idx = idx + 1
            
        if swap_idx != -1:
            other_id = _safe_int(items[swap_idx].get('id'))
            if _swap_sort_order(conn, 'news_items', int(payload.news_id), other_id):
                _record_tenant_change(tenant_id, 'news_item', payload.news_id, 'update', {'reorder': True})
                _record_tenant_change(tenant_id, 'news_item', other_id, 'update', {'reorder': True})
                return {'ok': True}
        
        return {'ok': False}
    finally:
        try: conn.close()
        except: pass

@app.get('/api/messages/news/settings')
def api_messages_news_settings(request: Request) -> Dict[str, Any]:
    guard = _web_require_admin_teacher(request)
    if guard:
        return {}
    tenant_id = _web_tenant_from_cookie(request)
    conn = _tenant_school_db(tenant_id)
    try:
        val = _get_setting_value(conn, 'news_settings', '{}')
        try:
            return json.loads(val)
        except:
            return {}
    finally:
        try: conn.close()
        except: pass

@app.post('/api/messages/news/settings')
def api_messages_news_settings_save(request: Request, payload: NewsSettingsPayload) -> Dict[str, Any]:
    guard = _web_require_admin_teacher(request)
    if guard:
        raise HTTPException(status_code=401)
    tenant_id = _web_tenant_from_cookie(request)
    conn = _tenant_school_db(tenant_id)
    try:
        current_raw = _get_setting_value(conn, 'news_settings', '{}')
        try:
            current = json.loads(current_raw)
        except:
            current = {}
        
        updates = payload.dict(exclude_unset=True)
        current.update(updates)
        
        _set_setting_value(conn, 'news_settings', json.dumps(current))
        conn.commit()
        _record_tenant_change(tenant_id, 'settings', 'news_settings', 'update', current)
        return {'ok': True}
    finally:
        try: conn.close()
        except: pass

@app.get('/api/messages/ads')
def api_messages_ads(request: Request) -> Dict[str, Any]:
    guard = _web_require_admin_teacher(request)
    if guard:
        return {'items': []}
    tenant_id = _web_tenant_from_cookie(request)
    conn = _tenant_school_db(tenant_id)
    try:
        items = _fetch_table_rows(conn, 'ads_items')
        items.sort(key=lambda x: _safe_int(x.get('sort_order'), 9999))
        return {'items': items}
    finally:
        try: conn.close()
        except: pass

@app.post('/api/messages/ads/save')
async def api_messages_ads_save(
    request: Request,
    ads_id: str = Form(default=''),
    text: str = Form(default=''),
    start_date: str = Form(default=''),
    end_date: str = Form(default=''),
    image: UploadFile | None = File(None)
) -> Dict[str, Any]:
    guard = _web_require_admin_teacher(request)
    if guard:
        raise HTTPException(status_code=401)
    tenant_id = _web_tenant_from_cookie(request)
    if not tenant_id:
        raise HTTPException(status_code=401)
        
    conn = _tenant_school_db(tenant_id)
    try:
        cur = conn.cursor()
        aid = int(ads_id) if ads_id and ads_id.isdigit() else 0
        txt = str(text or '').strip()
        s_dt = _normalize_date(start_date)
        e_dt = _normalize_date(end_date)
        
        image_path = None
        if image and image.filename:
            file_bytes = await image.read()
            if file_bytes:
                image_path = _save_uploaded_file(tenant_id, file_bytes, image.filename)
        
        if aid > 0:
            if image_path:
                cur.execute(
                    _sql_placeholder('UPDATE ads_items SET text=?, start_date=?, end_date=?, image_path=? WHERE id=?'),
                    (txt, s_dt, e_dt, image_path, aid)
                )
            else:
                cur.execute(
                    _sql_placeholder('UPDATE ads_items SET text=?, start_date=?, end_date=? WHERE id=?'),
                    (txt, s_dt, e_dt, aid)
                )
            act = 'update'
            rid = aid
        else:
            # Max sort order
            cur.execute('SELECT MAX(sort_order) FROM ads_items')
            row = cur.fetchone()
            max_so = 0
            if row:
                max_so = _safe_int(row[0] if not isinstance(row, dict) else row.get('MAX(sort_order)'), 0)
            
            cur.execute(
                _sql_placeholder('INSERT INTO ads_items (text, image_path, start_date, end_date, is_active, sort_order) VALUES (?, ?, ?, ?, 1, ?)'),
                (txt, image_path, s_dt, e_dt, max_so + 1)
            )
            rid = cur.lastrowid
            act = 'create'
            
        conn.commit()
        _record_tenant_change(tenant_id, 'ads_item', rid, act, {'text': txt, 'image_path': image_path})
        return {'ok': True, 'id': rid, 'image_path': image_path}
    finally:
        try: conn.close()
        except: pass

@app.post('/api/messages/ads/delete')
def api_messages_ads_delete(request: Request, payload: AdsItemTogglePayload) -> Dict[str, Any]:
    guard = _web_require_admin_teacher(request)
    if guard:
        raise HTTPException(status_code=401)
    tenant_id = _web_tenant_from_cookie(request)
    conn = _tenant_school_db(tenant_id)
    try:
        cur = conn.cursor()
        cur.execute(_sql_placeholder('DELETE FROM ads_items WHERE id=?'), (int(payload.ads_id),))
        conn.commit()
        _record_tenant_change(tenant_id, 'ads_item', payload.ads_id, 'delete', None)
        return {'ok': True}
    finally:
        try: conn.close()
        except: pass

@app.post('/api/messages/ads/toggle')
def api_messages_ads_toggle(request: Request, payload: AdsItemTogglePayload) -> Dict[str, Any]:
    guard = _web_require_admin_teacher(request)
    if guard:
        raise HTTPException(status_code=401)
    tenant_id = _web_tenant_from_cookie(request)
    conn = _tenant_school_db(tenant_id)
    try:
        cur = conn.cursor()
        cur.execute(_sql_placeholder('SELECT is_active FROM ads_items WHERE id=?'), (int(payload.ads_id),))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404)
        curr = _safe_int(_row_value(row, 'is_active'), 1)
        new_val = 0 if curr == 1 else 1
        cur.execute(_sql_placeholder('UPDATE ads_items SET is_active=? WHERE id=?'), (new_val, int(payload.ads_id)))
        conn.commit()
        _record_tenant_change(tenant_id, 'ads_item', payload.ads_id, 'update', {'is_active': new_val})
        return {'ok': True, 'is_active': new_val}
    finally:
        try: conn.close()
        except: pass

@app.post('/api/messages/ads/reorder')
def api_messages_ads_reorder(request: Request, payload: AdsReorderPayload) -> Dict[str, Any]:
    guard = _web_require_admin_teacher(request)
    if guard:
        raise HTTPException(status_code=401)
    tenant_id = _web_tenant_from_cookie(request)
    conn = _tenant_school_db(tenant_id)
    try:
        items = _fetch_table_rows(conn, 'ads_items')
        items.sort(key=lambda x: _safe_int(x.get('sort_order'), 9999))
        
        idx = -1
        for i, item in enumerate(items):
            if _safe_int(item.get('id')) == int(payload.ads_id):
                idx = i
                break
        
        if idx == -1:
            return {'ok': False}
            
        swap_idx = -1
        if payload.direction == 'up' and idx > 0:
            swap_idx = idx - 1
        elif payload.direction == 'down' and idx < len(items) - 1:
            swap_idx = idx + 1
            
        if swap_idx != -1:
            other_id = _safe_int(items[swap_idx].get('id'))
            if _swap_sort_order(conn, 'ads_items', int(payload.ads_id), other_id):
                _record_tenant_change(tenant_id, 'ads_item', payload.ads_id, 'update', {'reorder': True})
                _record_tenant_change(tenant_id, 'ads_item', other_id, 'update', {'reorder': True})
                return {'ok': True}
        
        return {'ok': False}
    finally:
        try: conn.close()
        except: pass

@app.get('/api/messages/student')
def api_messages_student(request: Request) -> Dict[str, Any]:
    # Returns all student messages, enriched with student name/class
    guard = _web_require_admin_teacher(request)
    if guard:
        return {'items': []}
    tenant_id = _web_tenant_from_cookie(request)
    conn = _tenant_school_db(tenant_id)
    try:
        # Need to join with students to get names
        cur = conn.cursor()
        query = """
            SELECT m.id, m.student_id, m.message, m.is_active, m.created_at,
                   s.first_name, s.last_name, s.class_name, s.card_number
            FROM student_messages m
            LEFT JOIN students s ON m.student_id = s.id
            ORDER BY m.id DESC
            LIMIT 1000
        """
        cur.execute(_sql_placeholder(query))
        rows = cur.fetchall() or []
        items = []
        for r in rows:
            items.append({
                'id': _row_value(r, 'id'),
                'student_id': _row_value(r, 'student_id'),
                'message': _row_value(r, 'message'),
                'is_active': _row_value(r, 'is_active'),
                'created_at': _row_value(r, 'created_at'),
                'first_name': _row_value(r, 'first_name'),
                'last_name': _row_value(r, 'last_name'),
                'class_name': _row_value(r, 'class_name'),
                'card_number': _row_value(r, 'card_number'),
            })
        return {'items': items}
    finally:
        try: conn.close()
        except: pass

@app.post('/api/messages/student/save')
def api_messages_student_save(request: Request, payload: StudentMessagePayload) -> Dict[str, Any]:
    guard = _web_require_admin_teacher(request)
    if guard:
        raise HTTPException(status_code=401)
    tenant_id = _web_tenant_from_cookie(request)
    conn = _tenant_school_db(tenant_id)
    try:
        cur = conn.cursor()
        mid = payload.message_id
        sid = payload.student_id
        msg = str(payload.message or '').strip()
        if not msg:
            raise HTTPException(status_code=400, detail="Empty message")
        
        if mid and int(mid) > 0:
            cur.execute(
                _sql_placeholder('UPDATE student_messages SET message=? WHERE id=?'),
                (msg, int(mid))
            )
            act = 'update'
            rid = int(mid)
            # fetch student_id if not provided
            if not sid:
                cur.execute(_sql_placeholder('SELECT student_id FROM student_messages WHERE id=?'), (rid,))
                row = cur.fetchone()
                if row:
                    sid = _safe_int(_row_value(row, 'student_id'))
        else:
            if not sid or int(sid) <= 0:
                 raise HTTPException(status_code=400, detail="Missing student_id")
            cur.execute(
                _sql_placeholder('INSERT INTO student_messages (student_id, message, is_active) VALUES (?, ?, 1)'),
                (int(sid), msg)
            )
            rid = cur.lastrowid
            act = 'create'
            
        conn.commit()
        _record_tenant_change(tenant_id, 'student_message', rid, act, payload.dict())
        return {'ok': True, 'id': rid}
    finally:
        try: conn.close()
        except: pass

@app.post('/api/messages/student/delete')
def api_messages_student_delete(request: Request, payload: StudentMessageTogglePayload) -> Dict[str, Any]:
    guard = _web_require_admin_teacher(request)
    if guard:
        raise HTTPException(status_code=401)
    tenant_id = _web_tenant_from_cookie(request)
    conn = _tenant_school_db(tenant_id)
    try:
        cur = conn.cursor()
        cur.execute(_sql_placeholder('DELETE FROM student_messages WHERE id=?'), (int(payload.message_id),))
        conn.commit()
        _record_tenant_change(tenant_id, 'student_message', payload.message_id, 'delete', None)
        return {'ok': True}
    finally:
        try: conn.close()
        except: pass

@app.post('/api/messages/student/toggle')
def api_messages_student_toggle(request: Request, payload: StudentMessageTogglePayload) -> Dict[str, Any]:
    guard = _web_require_admin_teacher(request)
    if guard:
        raise HTTPException(status_code=401)
    tenant_id = _web_tenant_from_cookie(request)
    conn = _tenant_school_db(tenant_id)
    try:
        cur = conn.cursor()
        cur.execute(_sql_placeholder('SELECT is_active FROM student_messages WHERE id=?'), (int(payload.message_id),))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404)
        curr = _safe_int(_row_value(row, 'is_active'), 1)
        new_val = 0 if curr == 1 else 1
        cur.execute(_sql_placeholder('UPDATE student_messages SET is_active=? WHERE id=?'), (new_val, int(payload.message_id)))
        conn.commit()
        _record_tenant_change(tenant_id, 'student_message', payload.message_id, 'update', {'is_active': new_val})
        return {'ok': True, 'is_active': new_val}
    finally:
        try: conn.close()
        except: pass


def _record_message_event(
    *,
    tenant_id: str,
    entity_type: str,
    action_type: str,
    payload: Dict[str, Any] | None,
    entity_id: Any = None,
) -> None:
    try:
        pid = entity_id
        if pid is None and isinstance(payload, dict):
            pid = payload.get('id')
        created_at = None
        if isinstance(payload, dict):
            created_at = payload.get('created_at')
        _record_sync_event(
            tenant_id=str(tenant_id or ''),
            station_id='web',
            entity_type=str(entity_type or '').strip(),
            entity_id=(str(pid) if pid is not None else None),
            action_type=str(action_type or '').strip(),
            payload=(payload or {}),
            created_at=(str(created_at) if created_at else None),
        )
    except Exception:
        pass


def _fetch_message_row(conn, table: str, row_id: int) -> Dict[str, Any] | None:
    cur = conn.cursor()
    cur.execute(_sql_placeholder(f'SELECT * FROM {table} WHERE id = ? LIMIT 1'), (int(row_id),))
    row = cur.fetchone()
    if not row:
        return None
    if isinstance(row, dict):
        return dict(row)
    try:
        return {k: row[k] for k in row.keys()}  # type: ignore[attr-defined]
    except Exception:
        return None


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


def _web_current_teacher_permissions(request: Request) -> Dict[str, Any]:
    tenant_id = _web_tenant_from_cookie(request)
    teacher_id = _web_teacher_from_cookie(request)
    if not tenant_id or not teacher_id:
        return {
            'id': 0,
            'name': '',
            'is_admin': 0,
            'can_edit_student_card': 0,
            'can_edit_student_photo': 0,
        }
    try:
        tid = int(str(teacher_id).strip() or '0')
    except Exception:
        tid = 0
    if tid <= 0:
        return {
            'id': 0,
            'name': '',
            'is_admin': 0,
            'can_edit_student_card': 0,
            'can_edit_student_photo': 0,
        }

    conn = _tenant_school_db(str(tenant_id))
    try:
        try:
            if USE_POSTGRES:
                cols = set([c.lower() for c in _table_columns_postgres(conn, 'teachers')])
                cur = conn.cursor()
                if 'can_edit_student_card' not in cols:
                    cur.execute('ALTER TABLE teachers ADD COLUMN can_edit_student_card INTEGER DEFAULT 1')
                if 'can_edit_student_photo' not in cols:
                    cur.execute('ALTER TABLE teachers ADD COLUMN can_edit_student_photo INTEGER DEFAULT 1')
                conn.commit()
            else:
                cols = set([c.lower() for c in _table_columns(conn, 'teachers')])
                if 'can_edit_student_card' not in cols:
                    conn.execute('ALTER TABLE teachers ADD COLUMN can_edit_student_card INTEGER DEFAULT 1')
                if 'can_edit_student_photo' not in cols:
                    conn.execute('ALTER TABLE teachers ADD COLUMN can_edit_student_photo INTEGER DEFAULT 1')
                conn.commit()
        except Exception:
            cols = set()
        if not cols:
            try:
                cols = set([c.lower() for c in (_table_columns_postgres(conn, 'teachers') if USE_POSTGRES else _table_columns(conn, 'teachers'))])
            except Exception:
                cols = set()
        select_fields = [
            'id',
            'name',
            'is_admin',
            'can_edit_student_card' if 'can_edit_student_card' in cols else '0 as can_edit_student_card',
            'can_edit_student_photo' if 'can_edit_student_photo' in cols else '0 as can_edit_student_photo',
        ]
        cur = conn.cursor()
        cur.execute(
            _sql_placeholder(
                'SELECT ' + ', '.join(select_fields) + ' FROM teachers WHERE id = ? LIMIT 1'
            ),
            (int(tid),)
        )
        row = cur.fetchone()
        if not row:
            return {
                'id': 0,
                'name': '',
                'is_admin': 0,
                'can_edit_student_card': 0,
                'can_edit_student_photo': 0,
            }
        r = dict(row) if isinstance(row, dict) else {k: row[k] for k in row.keys()}  # type: ignore[attr-defined]
        return {
            'id': _safe_int(r.get('id'), 0),
            'name': _safe_str(r.get('name') or ''),
            'is_admin': _safe_int(r.get('is_admin'), 0),
            'can_edit_student_card': _safe_int(r.get('can_edit_student_card'), 0),
            'can_edit_student_photo': _safe_int(r.get('can_edit_student_photo'), 0),
        }
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



# --- FILE SYNC API ---

def _get_tenant_storage_path(tenant_id: str, rel_path: str) -> str:
    """Returns absolute path for a tenant file in local storage."""
    # rel_path should be like 'images/foo.png' or 'sounds/bar.wav'
    safe_rel = rel_path.replace('..', '').strip('/\\')
    if not safe_rel:
        return ''
    
    # Priority 1: Shared Folder (if configured)
    shared = _get_shared_folder_for_tenant(tenant_id)
    if shared:
        return os.path.join(shared, safe_rel)
    
    # Priority 2: Local Data Dir
    return os.path.join(DATA_DIR, 'tenants_assets', tenant_id, safe_rel)

def _calc_file_hash(path: str) -> str:
    if not os.path.isfile(path):
        return ""
    hash_md5 = hashlib.md5()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    except Exception:
        return ""

def _get_server_manifest(tenant_id: str) -> Dict[str, str]:
    manifest = {}
    # We only scan specific directories
    dirs_to_scan = ['images', 'sounds', 'ads_media']
    
    # Determine root for scanning
    # If shared folder exists, scan that. Else scan local assets.
    
    shared = _get_shared_folder_for_tenant(tenant_id)
    roots = []
    if shared:
        roots.append(shared)
    
    local_assets = os.path.join(DATA_DIR, 'tenants_assets', tenant_id)
    if os.path.isdir(local_assets):
        roots.append(local_assets)
        
    # Scan
    seen_paths = set()
    
    for root_dir in roots:
        for subdir in dirs_to_scan:
            abs_base = os.path.join(root_dir, subdir)
            if not os.path.isdir(abs_base):
                continue
            for root, _, files in os.walk(abs_base):
                for name in files:
                    if name.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp', '.wav', '.mp3', '.ogg')):
                        full_path = os.path.join(root, name)
                        # Rel path relative to tenant root
                        rel_path = os.path.relpath(full_path, root_dir).replace('\\', '/')
                        if rel_path in seen_paths:
                            continue
                        manifest[rel_path] = _calc_file_hash(full_path)
                        seen_paths.add(rel_path)
    return manifest

def _verify_sync_auth(api_key: str | None, tenant_id: str | None) -> bool:
    if not api_key or not tenant_id:
        return False
    conn = _db()
    try:
        cur = conn.cursor()
        cur.execute(
            _sql_placeholder('SELECT id FROM institutions WHERE tenant_id = ? AND api_key = ? LIMIT 1'),
            (tenant_id, api_key)
        )
        return bool(cur.fetchone())
    finally:
        try: conn.close()
        except: pass

@app.post('/sync/files/manifest')
def sync_files_manifest(request: Request, payload: Dict[str, Any]) -> Dict[str, Any]:
    api_key = request.headers.get('api-key')
    tenant_id = request.headers.get('x-tenant-id')
    
    if not _verify_sync_auth(api_key, tenant_id):
        raise HTTPException(status_code=401, detail='Invalid auth')

    client_manifest = payload.get('manifest', {})
    server_manifest = _get_server_manifest(tenant_id)
    
    missing = []
    for rel_path, client_hash in client_manifest.items():
        # Check if we need this file
        # We need it if we don't have it, or if hash is different
        # (Assuming client is source of truth for PUSH)
        srv_hash = server_manifest.get(rel_path)
        if srv_hash != client_hash:
            missing.append(rel_path)
            
    return {'missing': missing}

@app.post('/sync/files/upload')
async def sync_files_upload(
    request: Request,
    file: UploadFile = File(...),
    rel_path: str = Form(...)
):
    api_key = request.headers.get('api-key')
    tenant_id = request.headers.get('x-tenant-id')
    
    if not _verify_sync_auth(api_key, tenant_id):
        raise HTTPException(status_code=401, detail='Invalid auth')
        
    if not file or not rel_path:
        return {'ok': False, 'error': 'missing data'}

    # Security check on rel_path
    if '..' in rel_path or rel_path.startswith('/') or '\\' in rel_path:
         pass

    dest_path = _get_tenant_storage_path(tenant_id, rel_path)
    if not dest_path:
        return {'ok': False, 'error': 'invalid path'}
        
    try:
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        content = await file.read()
        with open(dest_path, 'wb') as f:
            f.write(content)
        return {'ok': True}
    except Exception as e:
        print(f"Upload error: {e}")
        return {'ok': False, 'error': str(e)}

@app.get('/sync/files/list')
def sync_files_list(request: Request) -> Dict[str, Any]:
    api_key = request.headers.get('api-key')
    tenant_id = request.headers.get('x-tenant-id')
    
    if not _verify_sync_auth(api_key, tenant_id):
        raise HTTPException(status_code=401, detail='Invalid auth')
        
    return {'manifest': _get_server_manifest(tenant_id)}

@app.get('/sync/files/download')
def sync_files_download(request: Request, path: str = Query(...)):
    api_key = request.headers.get('api-key')
    tenant_id = request.headers.get('x-tenant-id')
    
    if not _verify_sync_auth(api_key, tenant_id):
        raise HTTPException(status_code=401, detail='Invalid auth')
        
    file_path = _get_tenant_storage_path(tenant_id, path)
    if not file_path or not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail='File not found')
        
    return FileResponse(file_path)

# --- END FILE SYNC API ---

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
        'static_messages': static_n,
        'threshold_messages': threshold_n,
        'news_items': news_n,
        'ads_items': ads_n,
        'student_messages': student_msg_n,
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
        
        # Get last change ID for sync continuity
        cur.execute('SELECT MAX(id) FROM changes')
        row = cur.fetchone()
        last_change_id = 0
        if row:
            val = row[0] if not isinstance(row, dict) else list(row.values())[0]
            last_change_id = _safe_int(val, 0)
            
    finally:
        try:
            conn.close()
        except Exception:
            pass

    tconn = _tenant_school_db(tenant_id)
    try:
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
        ]
        data: Dict[str, Any] = {}
        for t in tables:
            try:
                data[t] = _fetch_table_rows(tconn, t)
            except Exception:
                data[t] = []
        return {
            'ok': True, 
            'tenant_id': tenant_id, 
            'snapshot': data,
            'last_change_id': last_change_id
        }
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
        return guard
    
    body = """
    <h2>הקמת מוסד חדש</h2>
    <div class="card" style="max-width:600px;">
      <form method="post">
        <div class="form-group">
          <label>שם מוסד</label>
          <input name="name" required placeholder="לדוגמה: ישיבת אור החיים" />
        </div>
        <div class="form-group">
          <label>Tenant ID (מזהה ייחודי באנגלית)</label>
          <input name="tenant_id" required placeholder="לדוגמה: or_hachaim" pattern="[a-zA-Z0-9_-]+" />
        </div>
        <div class="form-group">
          <label>סיסמת מוסד (לכניסת מנהל)</label>
          <input name="institution_password" type="password" required />
        </div>
        <div class="form-group">
          <label>API Key (אופציונלי - יווצר אוטומטית אם ריק)</label>
          <input name="api_key" placeholder="השאר ריק ליצירה אוטומטית" />
        </div>
        <div style="margin-top:24px;">
          <button type="submit" class="btn-green">צור מוסד</button>
          <a href="/admin/institutions" style="margin-right:10px; color:#7f8c8d; text-decoration:none;">ביטול</a>
        </div>
      </form>
    </div>
    """
    return _super_admin_shell("הקמת מוסד", body, request)


@app.get("/__version")
def app_version() -> Dict[str, Any]:
    return {
        "build": APP_BUILD_TAG,
        "has_web_login": True,
        "template_version": "web-ui-a25e6b4",
    }


@app.get("/web/equipment-required", response_class=HTMLResponse)
def web_equipment_required() -> str:
    path = os.path.join(ROOT_DIR, 'equipment_required.html')
    html_content = _read_text_file(path)
    if not html_content:
        body = "<h2>רשימת ציוד נדרש</h2><p>העמוד עדיין לא זמין.</p>"
        return _public_web_shell("רשימת ציוד נדרש", body)
    
    # Extract body content
    body_content = html_content
    m = re.search(r'<body[^>]*>(.*?)</body>', html_content, re.DOTALL | re.IGNORECASE)
    if m:
        body_content = m.group(1)
        
    # Fix relative paths
    body_content = body_content.replace('src="equipment_required_files/', 'src="/web/assets/equipment_required_files/')
    body_content = body_content.replace("src='equipment_required_files/", "src='/web/assets/equipment_required_files/")
    
    return _public_web_shell("רשימת ציוד נדרש", body_content)


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


@app.get('/web/guide', response_class=HTMLResponse)
def web_guide() -> str:
    path = os.path.join(ROOT_DIR, 'guide_user_embedded.html')
    html_content = _read_text_file(path)
    if not html_content:
        path = os.path.join(ROOT_DIR, 'guide_index.html')
        html_content = _read_text_file(path)
    if not html_content:
        body = "<h2>מדריך</h2><p>המדריך עדיין לא זמין.</p><div class=\"actionbar\"><a class=\"gray\" href=\"/web\">חזרה</a></div>"
        return _public_web_shell('מדריך', body)
    
    html_content = str(html_content)
    html_content = html_content.replace('file:///C:/ProgramData/SchoolPoints/equipment_required.html', '/web/equipment-required')
    html_content = html_content.replace('file:///C:/%D7%9E%D7%99%D7%A6%D7%93/SchoolPoints/equipment_required.html', '/web/equipment-required')
    html_content = html_content.replace('equipment_required.html', '/web/equipment-required')
    html_content = _replace_guide_base64_images(html_content)
    
    # Extract body
    body_content = html_content
    m = re.search(r'<body[^>]*>(.*?)</body>', html_content, re.DOTALL | re.IGNORECASE)
    if m:
        body_content = m.group(1)
        
    return _public_web_shell('מדריך', body_content)


@app.get('/web/register', response_class=HTMLResponse)
def web_register(request: Request) -> Response:
    body = """
    <style>
      .reg-container { max-width: 600px; margin: 0 auto; background: rgba(255,255,255,0.05); padding: 30px; border-radius: 20px; border: 1px solid rgba(255,255,255,0.1); box-shadow: 0 20px 50px rgba(0,0,0,0.3); }
      .reg-row { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px; }
      .reg-group { margin-bottom: 20px; }
      .reg-label { display: block; margin-bottom: 8px; font-weight: 700; color: #cbd5e1; }
      .reg-input { width: 100%; padding: 12px; background: rgba(0,0,0,0.2); border: 1px solid rgba(255,255,255,0.1); border-radius: 10px; color: #fff; font-size: 16px; outline: none; transition: border-color 0.2s; box-sizing: border-box; }
      .reg-input:focus { border-color: #3498db; background: rgba(0,0,0,0.3); }
      .reg-select { width: 100%; padding: 12px; background: #1e293b; border: 1px solid rgba(255,255,255,0.1); border-radius: 10px; color: #fff; font-size: 16px; outline: none; box-sizing: border-box; }
      .reg-btn { width: 100%; padding: 15px; background: linear-gradient(135deg, #2ecc71, #27ae60); border: none; border-radius: 12px; color: #fff; font-weight: 800; font-size: 18px; cursor: pointer; transition: transform 0.2s, box-shadow 0.2s; margin-top: 10px; }
      .reg-btn:hover { transform: translateY(-2px); box-shadow: 0 10px 20px rgba(46, 204, 113, 0.3); }
      .plan-card { background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); border-radius: 10px; padding: 15px; text-align: center; cursor: pointer; transition: all 0.2s; position: relative; }
      .plan-card:hover { background: rgba(255,255,255,0.1); }
      .plan-card.selected { border-color: #2ecc71; background: rgba(46, 204, 113, 0.1); box-shadow: 0 0 0 2px #2ecc71; }
      .plan-name { font-weight: 800; font-size: 18px; margin-bottom: 5px; }
      .plan-price { font-size: 24px; font-weight: 700; color: #2ecc71; }
      .plan-desc { font-size: 13px; opacity: 0.7; margin-top: 5px; }
      .login-link { text-align: center; margin-top: 20px; font-size: 14px; opacity: 0.8; }
      .login-link a { color: #3498db; text-decoration: none; font-weight: 700; }
      
      /* Hidden radio inputs for plans */
      input[type="radio"].plan-radio { display: none; }
    </style>

    <div class="reg-container">
      <h2 style="text-align:center; margin-bottom:10px;">הרשמה ל-SchoolPoints</h2>
      <p style="text-align:center; opacity:0.7; margin-bottom:30px;">הצטרפו למאות מוסדות שכבר נהנים מניהול נקודות מתקדם.</p>
      
      <form id="regForm" onsubmit="event.preventDefault(); submitRegistration();">
        <div class="reg-row">
          <div class="reg-group">
            <label class="reg-label">שם המוסד</label>
            <input type="text" name="institution_name" class="reg-input" placeholder="לדוגמה: ישיבת אור החיים" required />
          </div>
          <div class="reg-group">
            <label class="reg-label">שם איש קשר</label>
            <input type="text" name="contact_name" class="reg-input" placeholder="ישראל ישראלי" required />
          </div>
        </div>
        
        <div class="reg-row">
          <div class="reg-group">
            <label class="reg-label">אימייל (שם משתמש)</label>
            <input type="email" name="email" class="reg-input" placeholder="admin@yeshiva.co.il" required />
          </div>
          <div class="reg-group">
            <label class="reg-label">טלפון</label>
            <input type="tel" name="phone" class="reg-input" placeholder="050-1234567" required />
          </div>
        </div>
        
        <div class="reg-group">
            <label class="reg-label">סיסמה לאזור אישי</label>
            <input type="password" name="password" class="reg-input" placeholder="******" required minlength="6" />
        </div>

        <div class="reg-group">
          <label class="reg-label">בחירת מסלול</label>
          <div class="reg-row" style="grid-template-columns: 1fr 1fr 1fr; gap: 10px;">
            <label class="plan-card" onclick="selectPlan('basic')">
              <input type="radio" name="plan" value="basic" class="plan-radio" required />
              <div class="plan-name">Basic</div>
              <div class="plan-price">₪50<span style="font-size:14px">/חודש</span></div>
              <div class="plan-desc">עד 2 עמדות</div>
            </label>
            <label class="plan-card selected" onclick="selectPlan('extended')">
              <input type="radio" name="plan" value="extended" class="plan-radio" checked />
              <div class="plan-name">Extended</div>
              <div class="plan-price">₪100<span style="font-size:14px">/חודש</span></div>
              <div class="plan-desc">עד 5 עמדות</div>
            </label>
            <label class="plan-card" onclick="selectPlan('unlimited')">
              <input type="radio" name="plan" value="unlimited" class="plan-radio" />
              <div class="plan-name">Unlimited</div>
              <div class="plan-price">₪200<span style="font-size:14px">/חודש</span></div>
              <div class="plan-desc">ללא הגבלה</div>
            </label>
          </div>
        </div>
        
        <div class="reg-group">
            <label class="reg-label" style="display:flex; align-items:center; gap:10px; cursor:pointer;">
                <input type="checkbox" name="terms" required style="width:20px; height:20px;" />
                <span>קראתי ואני מסכים <a href="#" style="color:#3498db;">לתקנון ולתנאי השימוש</a></span>
            </label>
        </div>

        <button type="submit" id="btnSubmit" class="reg-btn">המשך לתשלום &gt;</button>
        
        <div id="regError" style="color:#e74c3c; text-align:center; margin-top:15px; display:none; font-weight:700;"></div>
      </form>
      
      <div class="login-link">
        כבר רשום? <a href="/web/signin">התחבר כאן</a>
      </div>
    </div>
    
    <script>
      function selectPlan(plan) {
        document.querySelectorAll('.plan-card').forEach(el => el.classList.remove('selected'));
        const input = document.querySelector('input[name="plan"][value="' + plan + '"]');
        if (input) {
            input.checked = true;
            input.parentElement.classList.add('selected');
        }
      }
      
      async function submitRegistration() {
        const form = document.getElementById('regForm');
        const btn = document.getElementById('btnSubmit');
        const err = document.getElementById('regError');
        
        if (!form.checkValidity()) {
            form.reportValidity();
            return;
        }
        
        const formData = new FormData(form);
        const payload = Object.fromEntries(formData.entries());
        
        // Basic logic for now
        btn.disabled = true;
        btn.style.opacity = '0.7';
        btn.textContent = 'מעבד נתונים...';
        err.style.display = 'none';
        
        try {
            const resp = await fetch('/api/register', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            
            const data = await resp.json();
            
            if (!resp.ok) {
                throw new Error(data.detail || 'שגיאה בהרשמה');
            }
            
            // Redirect to payment or success page
            if (data.payment_url) {
                window.location.href = data.payment_url;
            } else {
                alert('הרשמה נקלטה בהצלחה! (מצב פיתוח: אין תשלום עדיין)');
                window.location.href = '/web/login'; // Or wherever
            }
            
        } catch (e) {
            err.textContent = e.message;
            err.style.display = 'block';
            btn.disabled = false;
            btn.style.opacity = '1';
            btn.textContent = 'המשך לתשלום >';
        }
      }
    </script>
    """
    return _public_web_shell("הרשמה", body, request=request)


@app.get('/web/contact', response_class=HTMLResponse)
def web_contact() -> str:
    body = f"""
    <h2>צור קשר</h2>
    <div style=\"opacity:.86; margin-top:-6px;\">נחזור אליך בהקדם.</div>
    <form method=\"post\" action=\"/web/contact\" style=\"margin-top:12px; max-width:680px;\">
      <label style=\"display:block;margin:10px 0 6px;font-weight:800;\">שם</label>
      <input name=\"name\" style=\"width:100%;padding:12px;border:1px solid var(--line);border-radius:10px;font-size:15px;\" required />
      <label style=\"display:block;margin:10px 0 6px;font-weight:800;\">אימייל</label>
      <input name=\"email\" type=\"email\" style=\"width:100%;padding:12px;border:1px solid var(--line);border-radius:10px;font-size:15px;\" required />
      <label style=\"display:block;margin:10px 0 6px;font-weight:800;\">נושא</label>
      <input name=\"subject\" style=\"width:100%;padding:12px;border:1px solid var(--line);border-radius:10px;font-size:15px;\" />
      <label style=\"display:block;margin:10px 0 6px;font-weight:800;\">הודעה</label>
      <textarea name=\"message\" style=\"width:100%;padding:12px;border:1px solid var(--line);border-radius:10px;font-size:15px; min-height:120px;\" required></textarea>
      <div class=\"actionbar\" style=\"justify-content:flex-start;\">
        <button class=\"green\" type=\"submit\" style=\"padding:10px 14px;border-radius:8px;border:none;background:#2ecc71;color:#fff;font-weight:900;cursor:pointer;\">שליחה</button>
        <a class=\"gray\" href=\"/web\" style=\"padding:10px 14px;border-radius:8px;background:#95a5a6;color:#fff;text-decoration:none;font-weight:900;\">חזרה</a>
      </div>
      <div class=\"small\">build: {APP_BUILD_TAG}</div>
    </form>
    """
    return _public_web_shell('צור קשר', body)


import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

def _send_contact_email(name: str, email: str, subject: str, message: str) -> bool:
    smtp_host = os.getenv('SMTP_HOST')
    smtp_port = _safe_int(os.getenv('SMTP_PORT'), 587)
    smtp_user = os.getenv('SMTP_USER')
    smtp_pass = os.getenv('SMTP_PASSWORD')
    smtp_from = os.getenv('SMTP_FROM') or smtp_user
    smtp_to = os.getenv('CONTACT_EMAIL_TO') or smtp_user

    if not smtp_host or not smtp_user or not smtp_pass or not smtp_to:
        print("[EMAIL] Missing SMTP configuration")
        return False

    try:
        msg = MIMEMultipart()
        msg['From'] = smtp_from
        msg['To'] = smtp_to
        msg['Subject'] = f"Contact Form: {subject} (from {name})"
        msg['Reply-To'] = email

        body = f"""
        Name: {name}
        Email: {email}
        Subject: {subject}
        
        Message:
        {message}
        """
        msg.attach(MIMEText(body, 'plain', 'utf-8'))

        server = smtplib.SMTP(smtp_host, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_from, [smtp_to], msg.as_string())
        server.quit()
        return True
    except Exception as e:
        print(f"[EMAIL] Failed to send email: {e}")
        return False


@app.post('/web/contact', response_class=HTMLResponse)
def web_contact_submit(
    name: str = Form(default=''),
    email: str = Form(default=''),
    subject: str = Form(default=''),
    message: str = Form(default=''),
) -> Response:
    name = str(name or '').strip()
    email = str(email or '').strip()
    subject = str(subject or '').strip()
    message = str(message or '').strip()
    if not name or not email or not message:
        body = "<h2>צור קשר</h2><p>חסרים פרטים.</p><div class=\"actionbar\"><a class=\"gray\" href=\"/web/contact\">חזרה</a></div>"
        return HTMLResponse(_public_web_shell('צור קשר', body), status_code=400)
    
    # Save to DB
    try:
        _save_contact_message(name=name, email=email, subject=subject, message=message)
    except Exception:
        pass
        
    # Send Email
    email_sent = _send_contact_email(name, email, subject, message)
    
    if not email_sent:
        # If email failed (e.g. no config), we still show success if saved to DB, but maybe log it.
        # Ideally we might want to tell the user, but for now we'll assume DB is backup.
        pass

    body = "<h2>תודה!</h2><p>ההודעה נשלחה בהצלחה.</p><div class=\"actionbar\"><a class=\"blue\" href=\"/web\">דף הבית</a><a class=\"gray\" href=\"/web/guide\">מדריך</a></div>"
    return HTMLResponse(_public_web_shell('צור קשר', body), status_code=200)


@app.get('/web/equipment-required', response_class=HTMLResponse)
def web_equipment_required(request: Request) -> str:
    path = os.path.join(ROOT_DIR, 'equipment_required.html')
    content = _read_text_file(path)
    if not content:
        body = "<h2>ציוד נדרש</h2><p>הדף לא נמצא.</p><div class='actionbar'><a class='gray' href='/web/guide'>חזרה</a></div>"
        return _public_web_shell('ציוד נדרש', body)
    
    # Extract body content if full HTML
    m = re.search(r'<body[^>]*>(.*?)</body>', content, re.DOTALL | re.IGNORECASE)
    if m:
        content = m.group(1)
        
    return _public_web_shell('ציוד נדרש', content, request=request)


@app.get('/web/download', response_class=HTMLResponse)
def web_download() -> str:
    download_url = "https://drive.google.com/drive/folders/1jM8CpSPbO0avrmNLA3MBcCPXpdC0JGxc?usp=sharing"
    body = f"""
    <div style="text-align:center;">
      <div style="font-size:22px;font-weight:900;">הורדת התוכנה</div>
      <div style="margin-top:10px;line-height:1.8;">ההתקנה נמצאת בתיקיית Google Drive.</div>
      <div class="actionbar" style="justify-content:center;">
        <a class="green" href="{download_url}" target="_blank" rel="noopener">להורדה</a>
        <a class="blue" href="/web/guide">מדריך</a>
        <a class="gray" href="/web">חזרה</a>
      </div>
      <div class="small">build: {APP_BUILD_TAG}</div>
    </div>
    """
    return _public_web_shell("הורדה", body)


@app.get('/web/pricing', response_class=HTMLResponse)
def web_pricing() -> str:
    body = """
    <style>
      .pricing-container { display: flex; flex-wrap: wrap; justify-content: center; gap: 20px; margin-top: 30px; }
      .pricing-card { flex: 1; min-width: 280px; max-width: 320px; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); border-radius: 16px; padding: 24px; text-align: center; transition: transform 0.3s, box-shadow 0.3s; position: relative; overflow: hidden; }
      .pricing-card:hover { transform: translateY(-5px); box-shadow: 0 10px 30px rgba(0,0,0,0.3); border-color: rgba(255,255,255,0.2); }
      .pricing-card.featured { background: linear-gradient(145deg, rgba(46, 204, 113, 0.1), rgba(39, 174, 96, 0.15)); border: 1px solid rgba(46, 204, 113, 0.4); transform: scale(1.05); z-index: 1; }
      .pricing-card.featured:hover { transform: scale(1.05) translateY(-5px); }
      .pricing-title { font-size: 24px; font-weight: 900; margin-bottom: 10px; color: #fff; }
      .pricing-price { font-size: 36px; font-weight: 800; margin-bottom: 20px; color: #2ecc71; }
      .pricing-price span { font-size: 16px; font-weight: 400; opacity: 0.7; }
      .pricing-features { list-style: none; padding: 0; margin: 0 0 24px 0; text-align: right; }
      .pricing-features li { padding: 10px 0; border-bottom: 1px solid rgba(255,255,255,0.05); color: rgba(255,255,255,0.9); }
      .pricing-features li:last-child { border-bottom: none; }
      .pricing-features li::before { content: "✓"; color: #2ecc71; margin-left: 8px; font-weight: bold; }
      .pricing-features li.disabled { opacity: 0.5; text-decoration: line-through; }
      .pricing-features li.disabled::before { content: "✕"; color: #e74c3c; }
      .btn-pricing { display: inline-block; width: 100%; padding: 12px 0; background: rgba(255,255,255,0.1); color: #fff; font-weight: 800; text-decoration: none; border-radius: 8px; transition: background 0.2s; }
      .btn-pricing:hover { background: rgba(255,255,255,0.2); }
      .btn-pricing.primary { background: #2ecc71; box-shadow: 0 4px 15px rgba(46, 204, 113, 0.3); }
      .btn-pricing.primary:hover { background: #27ae60; }
      .ribbon { position: absolute; top: 12px; right: -30px; transform: rotate(45deg); background: #f1c40f; color: #000; font-weight: 900; font-size: 12px; padding: 4px 40px; box-shadow: 0 2px 5px rgba(0,0,0,0.2); }
    </style>

    <div style="text-align: center; max-width: 700px; margin: 0 auto;">
      <h2>מחירון וחבילות</h2>
      <p style="opacity: 0.8; font-size: 16px;">בחר את החבילה המתאימה ביותר למוסד שלך. כל החבילות כוללות את כל הפיצ'רים הבסיסיים.</p>
    </div>

    <div class="pricing-container">
      <!-- Basic Plan -->
      <div class="pricing-card">
        <div class="pricing-title">בסיסי (Basic)</div>
        <div class="pricing-price">₪50 <span>/חודש</span></div>
        <ul class="pricing-features">
          <li>עד 2 עמדות פעילות</li>
          <li>ניהול תלמידים מלא</li>
          <li>ממשק מורים</li>
          <li>חנות הטבות בסיסית</li>
          <li class="disabled">גיבוי אוטומטי לענן</li>
          <li class="disabled">תמיכה טכנית מועדפת</li>
        </ul>
        <a href="/web/contact?plan=basic" class="btn-pricing">בחר חבילה</a>
      </div>

      <!-- Extended Plan -->
      <div class="pricing-card featured">
        <div class="ribbon">מומלץ</div>
        <div class="pricing-title">מורחב (Extended)</div>
        <div class="pricing-price">₪100 <span>/חודש</span></div>
        <ul class="pricing-features">
          <li>עד 5 עמדות פעילות</li>
          <li>כל מה שבחבילה הבסיסית</li>
          <li>ניהול שדרוגים מתקדם</li>
          <li>הודעות רצות וחדשות</li>
          <li>גיבוי אוטומטי לענן</li>
          <li class="disabled">תמיכה טכנית מועדפת</li>
        </ul>
        <a href="/web/contact?plan=extended" class="btn-pricing primary">בחר חבילה</a>
      </div>

      <!-- Unlimited Plan -->
      <div class="pricing-card">
        <div class="pricing-title">ללא הגבלה (Unlimited)</div>
        <div class="pricing-price">₪200 <span>/חודש</span></div>
        <ul class="pricing-features">
          <li>מספר עמדות ללא הגבלה</li>
          <li>כל הפיצ'רים פתוחים</li>
          <li>ניהול רשת מוסדות</li>
          <li>התאמה אישית של עיצוב</li>
          <li>גיבוי וסנכרון מלא</li>
          <li>תמיכה טכנית מועדפת</li>
        </ul>
        <a href="/web/contact?plan=unlimited" class="btn-pricing">בחר חבילה</a>
      </div>
    </div>

    <div style="text-align: center; margin-top: 40px;">
        <p style="opacity: 0.7; font-size: 14px;">* המחירים כוללים מע"מ. ט.ל.ח.</p>
        <a class="btn-glass" href="/web" style="margin-top: 10px;">חזרה לדף הבית</a>
    </div>
    """
    return _public_web_shell("מחירון", body)


@app.get('/api/settings/{key}')
def api_settings_get(request: Request, key: str) -> Dict[str, Any]:
    guard = _web_require_admin_teacher(request)
    if guard:
        return {}
    tenant_id = _web_tenant_from_cookie(request)
    conn = _tenant_school_db(tenant_id)
    try:
        val = _get_setting_value(conn, key, '{}')
        try:
            return json.loads(val)
        except:
            return {}
    finally:
        try: conn.close()
        except: pass


@app.post('/api/settings/save')
def api_settings_save(request: Request, payload: GenericSettingPayload) -> Dict[str, Any]:
    guard = _web_require_admin_teacher(request)
    if guard:
        raise HTTPException(status_code=401)
    tenant_id = _web_tenant_from_cookie(request)
    conn = _tenant_school_db(tenant_id)
    try:
        # validate key to prevent overwriting critical non-settings
        if not payload.key or not re.match(r'^[a-z0-9_]+$', payload.key):
             raise HTTPException(status_code=400, detail="Invalid key")
             
        val_str = json.dumps(payload.value, ensure_ascii=False)
        _set_setting_value(conn, payload.key, val_str)
        conn.commit()
        _record_tenant_change(tenant_id, 'settings', payload.key, 'update', payload.value)
        return {'ok': True}
    finally:
        try: conn.close()
        except: pass


@app.get('/web/account', response_class=HTMLResponse)
def web_account(request: Request):
    guard = _web_require_tenant(request)
    if guard: return guard
    tenant_id = _web_tenant_from_cookie(request)
    inst = _get_institution(tenant_id)
    name = inst.get('name') or tenant_id
    body = f"""
    <h2>אזור אישי / פרטי מוסד</h2>
    <div class="card" style="max-width:600px; margin:0 auto; padding:24px; background:rgba(255,255,255,0.05); border-radius:16px;">
      <div style="margin-bottom:16px;">
        <div style="font-size:14px; opacity:0.7;">שם המוסד</div>
        <div style="font-size:20px; font-weight:bold;">{name}</div>
      </div>
      <div style="margin-bottom:24px;">
        <div style="font-size:14px; opacity:0.7;">מזהה מערכת (Tenant ID)</div>
        <div style="font-size:18px; font-family:monospace;">{tenant_id}</div>
      </div>
      <div class="actionbar">
        <a class="btn-glass" href="/web/logout" style="background:rgba(231,76,60,0.2);">יציאה</a>
        <a class="btn-glass" href="/web/admin">חזרה ללוח בקרה</a>
      </div>
    </div>
    """
    return _basic_web_shell("חשבון", body, request=request)


@app.get("/web/settings", response_class=HTMLResponse)
def web_settings(request: Request):
    guard = _web_require_admin_teacher(request)
    if guard:
        return guard
    tenant_id = _web_tenant_from_cookie(request)
    conn = _tenant_school_db(tenant_id)
    try:
        value_json = _get_web_setting_json(conn, 'admin_settings', '{\n  "enabled": true\n}')
    finally:
        try: conn.close()
        except: pass
    
    import json
    try:
        data = json.loads(value_json)
    except:
        data = {}

    def _v(k, default=''):
        return html.escape(str(data.get(k, default)))

    html_content = f"""
    <div style="max-width:800px; margin:0 auto;">
      <h2>הגדרות עמדת ניהול</h2>
      <div class="card" style="padding:24px;">
        <div class="form-group">
            <label>שם העמדה (לזיהוי)</label>
            <input id="as_name" class="form-control" value="{_v('station_name', 'Admin Station')}" />
        </div>
        
        <div style="margin-top:20px;">
            <label class="ck"><input type="checkbox" id="as_enabled" {'checked' if data.get('enabled', True) else ''}> עמדה פעילה</label>
        </div>

        <div style="margin-top:30px; border-top:1px solid #eee; padding-top:20px; text-align:left;">
            <button class="green" onclick="saveAdminSettings()">💾 שמור הגדרות</button>
            <a class="gray btn" href="/web/admin">חזרה</a>
        </div>
      </div>
    </div>

    <script>
      async function saveAdminSettings() {{
        const payload = {{
            station_name: document.getElementById('as_name').value,
            enabled: document.getElementById('as_enabled').checked
        }};

        try {{
            const res = await fetch('/api/settings/save', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{ key: 'admin_settings', value: payload }})
            }});
            if (res.ok) {{
                alert('נשמר בהצלחה');
            }} else {{
                alert('שגיאה בשמירה');
            }}
        }} catch (e) {{
            alert('שגיאה: ' + e);
        }}
      }}
    </script>
    <style>
        .form-group {{ margin-bottom:15px; }}
        .form-group label {{ display:block; font-weight:600; margin-bottom:5px; }}
        .form-control {{ width:100%; padding:10px; border:1px solid #ddd; border-radius:8px; box-sizing:border-box; }}
        .ck {{ display:flex; align-items:center; gap:8px; cursor:pointer; font-weight:600; user-select:none; background:#f8f9fa; padding:8px 12px; border-radius:20px; border:1px solid #eee; }}
        .ck:hover {{ background:#e9ecef; }}
        .btn {{ padding:10px 20px; border-radius:8px; text-decoration:none; font-weight:bold; border:none; cursor:pointer; font-size:14px; display:inline-block; }}
        .green {{ background:#2ecc71; color:white; }}
        .gray {{ background:#95a5a6; color:white; }}
    </style>
    """
    return _basic_web_shell("הגדרות עמדת ניהול", html_content, request=request)


@app.post("/web/settings/save")
def web_settings_save(
    request: Request,
    setting_key: str = Form(...),
    value_json: str = Form(...),
    redirect_to: str = Form(default='/web/admin'),
) -> Response:
    guard = _web_require_admin_teacher(request)
    if guard:
        return guard
    tenant_id = _web_tenant_from_cookie(request)
    if not tenant_id:
        return RedirectResponse(url="/web/signin", status_code=302)

    k = str(setting_key or '').strip()
    v = str(value_json or '').strip()
    if not k:
        return RedirectResponse(url=str(redirect_to or '/web/admin'), status_code=302)
    # validate json (best effort)
    try:
        val = json.loads(v or '{}')
    except Exception:
        body = f"""
        <h2>שגיאה</h2>
        <p>הערך אינו JSON תקין.</p>
        <div class=\"actionbar\"><a class=\"gray\" href=\"{redirect_to or '/web/admin'}\">חזרה</a></div>
        """
        return HTMLResponse(_public_web_shell("שגיאה", body), status_code=400)
    
    conn = _tenant_school_db(tenant_id)
    try:
        _set_setting_value(conn, k, v)
        conn.commit()
        _record_tenant_change(tenant_id, 'settings', k, 'update', val)
    finally:
        try:
            conn.close()
        except Exception:
            pass
    
    return RedirectResponse(url=str(redirect_to or '/web/admin'), status_code=302)


@app.get('/web/students/edit', response_class=HTMLResponse)
def web_students_edit(request: Request, student_id: int = Query(default=0)):
    guard = _web_require_teacher(request)
    if guard:
        return guard
    tenant_id = _web_tenant_from_cookie(request)
    if not tenant_id:
        return RedirectResponse(url='/web/signin', status_code=302)
    if int(student_id or 0) <= 0:
        body = "<h2>עריכת תלמיד</h2><p>בחר/י תלמיד מהטבלה ואז לחץ/י 'ערוך תלמיד'.</p><div class='actionbar'><a class='gray' href='/web/admin'>חזרה</a></div>"
        return _basic_web_shell('עריכת תלמיד', body, request=request)

    teacher = _web_current_teacher(request) or {}
    teacher_id = _safe_int(teacher.get('id'), 0)
    is_admin = bool(_safe_int(teacher.get('is_admin'), 0) == 1)
    allowed_classes: List[str] | None = None
    if not is_admin:
        allowed_classes = _web_teacher_allowed_classes(tenant_id, teacher_id)
        allowed_classes = [str(c).strip() for c in (allowed_classes or []) if str(c).strip()]

    conn = _tenant_school_db(tenant_id)
    try:
        cur = conn.cursor()
        cur.execute(
            _sql_placeholder(
                'SELECT id, first_name, last_name, class_name, points, card_number, serial_number, photo_number, private_message '
                'FROM students WHERE id = ? LIMIT 1'
            ),
            (int(student_id),)
        )
        row = cur.fetchone()
        if not row:
            body = "<h2>עריכת תלמיד</h2><p>תלמיד לא נמצא.</p><div class='actionbar'><a class='gray' href='/web/admin'>חזרה</a></div>"
            return _basic_web_shell('עריכת תלמיד', body, request=request)
        r = dict(row) if isinstance(row, dict) else {k: row[k] for k in row.keys()}  # type: ignore[attr-defined]

        if allowed_classes is not None:
            cn = str(r.get('class_name') or '').strip()
            if cn and cn not in allowed_classes:
                return HTMLResponse('<h3>אין הרשאה</h3><p>אין הרשאה לערוך תלמיד מכיתה זו.</p><p><a href="/web/admin">חזרה</a></p>', status_code=403)
    finally:
        try:
            conn.close()
        except Exception:
            pass

    def _esc(v: Any) -> str:
        try:
            return html.escape(str(v or ''))
        except Exception:
            return ''

    body = f"""
    <h2>עריכת תלמיד</h2>
    <form method="post" action="/web/students/edit" style="max-width:640px; display:grid; grid-template-columns:1fr; gap:10px;">
      <input type="hidden" name="student_id" value="{int(student_id)}" />
      <label style="font-weight:900;">מס' סידורי</label>
      <input name="serial_number" value="{_esc(r.get('serial_number'))}" style="padding:12px;border:1px solid var(--line);border-radius:10px;" />
      <label style="font-weight:900;">שם משפחה</label>
      <input name="last_name" value="{_esc(r.get('last_name'))}" style="padding:12px;border:1px solid var(--line);border-radius:10px;" />
      <label style="font-weight:900;">שם פרטי</label>
      <input name="first_name" value="{_esc(r.get('first_name'))}" style="padding:12px;border:1px solid var(--line);border-radius:10px;" />
      <label style="font-weight:900;">כיתה</label>
      <input name="class_name" value="{_esc(r.get('class_name'))}" style="padding:12px;border:1px solid var(--line);border-radius:10px;" />
      <label style="font-weight:900;">כרטיס</label>
      <input name="card_number" value="{_esc(r.get('card_number'))}" style="padding:12px;border:1px solid var(--line);border-radius:10px;" />
      <label style="font-weight:900;">תמונה (מספר)</label>
      <input name="photo_number" value="{_esc(r.get('photo_number'))}" style="padding:12px;border:1px solid var(--line);border-radius:10px;" />
      <label style="font-weight:900;">נקודות</label>
      <input name="points" value="{_esc(r.get('points'))}" style="padding:12px;border:1px solid var(--line);border-radius:10px;" />
      <label style="font-weight:900;">הודעה פרטית</label>
      <textarea name="private_message" style="padding:12px;border:1px solid var(--line);border-radius:10px; min-height:90px;">{_esc(r.get('private_message'))}</textarea>
      <div class="actionbar" style="justify-content:flex-start;">
        <button class="green" type="submit" style="padding:10px 14px;border-radius:8px;border:none;background:#2ecc71;color:#fff;font-weight:900;cursor:pointer;">שמירה</button>
        <a class="gray" href="/web/admin" style="padding:10px 14px;border-radius:8px;background:#95a5a6;color:#fff;text-decoration:none;font-weight:900;">חזרה</a>
      </div>
    </form>
    """
    return _basic_web_shell('עריכת תלמיד', body, request=request)


@app.post('/web/students/edit', response_class=HTMLResponse)
def web_students_edit_submit(
    request: Request,
    student_id: int = Form(default=0),
    serial_number: str = Form(default=''),
    last_name: str = Form(default=''),
    first_name: str = Form(default=''),
    class_name: str = Form(default=''),
    card_number: str = Form(default=''),
    photo_number: str = Form(default=''),
    points: str = Form(default=''),
    private_message: str = Form(default=''),
) -> Response:
    guard = _web_require_teacher(request)
    if guard:
        return guard
    tenant_id = _web_tenant_from_cookie(request)
    if not tenant_id:
        return RedirectResponse(url='/web/signin', status_code=302)
    sid = int(student_id or 0)
    if sid <= 0:
        return RedirectResponse(url='/web/admin', status_code=302)

    teacher = _web_current_teacher(request) or {}
    teacher_id = _safe_int(teacher.get('id'), 0)
    is_admin = bool(_safe_int(teacher.get('is_admin'), 0) == 1)
    allowed_classes: List[str] | None = None
    if not is_admin:
        allowed_classes = _web_teacher_allowed_classes(tenant_id, teacher_id)
        allowed_classes = [str(c).strip() for c in (allowed_classes or []) if str(c).strip()]

    conn = _tenant_school_db(tenant_id)
    try:
        cur = conn.cursor()
        cur.execute(_sql_placeholder('SELECT class_name FROM students WHERE id = ? LIMIT 1'), (sid,))
        row = cur.fetchone()
        if not row:
            return _basic_web_shell('עריכת תלמיד', "<h2>שגיאה</h2><p>תלמיד לא נמצא.</p><div class='actionbar'><a class='gray' href='/web/admin'>חזרה</a></div>", request=request)
        current_class = str((row.get('class_name') if isinstance(row, dict) else row['class_name']) or '').strip()
        if allowed_classes is not None and current_class and current_class not in allowed_classes:
            return HTMLResponse('<h3>אין הרשאה</h3><p>אין הרשאה לערוך תלמיד מכיתה זו.</p><p><a href="/web/admin">חזרה</a></p>', status_code=403)
        if allowed_classes is not None:
            new_class = str(class_name or '').strip()
            if new_class and new_class not in allowed_classes:
                return HTMLResponse('<h3>אין הרשאה</h3><p>אין הרשאה להעביר תלמיד לכיתה זו.</p><p><a href="/web/admin">חזרה</a></p>', status_code=403)

        try:
            pts = int(str(points or '').strip() or '0')
        except Exception:
            pts = 0

        cur.execute(
            _sql_placeholder(
                'UPDATE students SET serial_number = ?, last_name = ?, first_name = ?, class_name = ?, card_number = ?, photo_number = ?, points = ?, private_message = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?'
            ),
            (
                str(serial_number or '').strip(),
                str(last_name or '').strip(),
                str(first_name or '').strip(),
                str(class_name or '').strip(),
                str(card_number or '').strip(),
                str(photo_number or '').strip(),
                int(pts),
                str(private_message or ''),
                int(sid),
            )
        )
        conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return RedirectResponse(url='/web/admin', status_code=302)


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
        const modal = document.getElementById('t_modal');
        const modalTitle = document.getElementById('t_modal_title');
        const mId = document.getElementById('m_teacher_id');
        const mName = document.getElementById('m_name');
        const mCard1 = document.getElementById('m_card1');
        const mCard2 = document.getElementById('m_card2');
        const mCard3 = document.getElementById('m_card3');
        const mIsAdmin = document.getElementById('m_is_admin');
        const mCanEditCard = document.getElementById('m_can_edit_student_card');
        const mCanEditPhoto = document.getElementById('m_can_edit_student_photo');
        const mMaxPoints = document.getElementById('m_bonus_max_points_per_student');
        const mMaxRuns = document.getElementById('m_bonus_max_total_runs');
        const classesBox = document.getElementById('m_classes_box');
        const btnSave = document.getElementById('m_save');
        const btnCancel = document.getElementById('m_cancel');
        const btnSelectAll = document.getElementById('m_select_all');
        const btnClearAll = document.getElementById('m_clear_all');

        let selectedId = null;
        let timer = null;

        function esc(s) {
          return String(s ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
        }

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

        function openModal() {
          modal.style.display = 'flex';
        }

        function closeModal() {
          modal.style.display = 'none';
        }

        function setAdminMode(isAdmin) {
          const on = !!isAdmin;
          classesBox.style.opacity = on ? '.55' : '1';
          classesBox.style.pointerEvents = on ? 'none' : 'auto';
        }

        async function loadAllClasses() {
          try {
            const resp = await fetch('/api/classes');
            const data = await resp.json();
            const items = Array.isArray(data.items) ? data.items : [];
            return items.map(x => String(x)).filter(x => x.trim()).sort();
          } catch (e) {
            return [];
          }
        }

        function renderClasses(allClasses, selected) {
          const sel = new Set((selected || []).map(x => String(x)));
          if (!allClasses || allClasses.length === 0) {
            classesBox.innerHTML = '<div style="opacity:.86;">אין כיתות במערכת</div>';
            return;
          }
          classesBox.innerHTML = allClasses.map(cls => {
            const checked = sel.has(String(cls)) ? 'checked' : '';
            return `<label class="ck"><input type="checkbox" value="${esc(cls)}" ${checked}/> ${esc(cls)}</label>`;
          }).join('');
        }

        function getSelectedClassesFromUI() {
          const out = [];
          classesBox.querySelectorAll('input[type="checkbox"]').forEach(cb => {
            if (cb.checked) out.push(String(cb.value));
          });
          return out;
        }

        function normalizeIntOrNull(v) {
          const s = String(v ?? '').trim();
          if (!s) return null;
          const n = parseInt(s, 10);
          if (Number.isNaN(n) || n <= 0) return null;
          return n;
        }

        async function load() {
          statusEl.textContent = 'טוען...';
          const q = encodeURIComponent(searchEl.value || '');
          const resp = await fetch(`/api/teachers?q=${q}`);
          const data = await resp.json();
          rowsEl.innerHTML = data.items.map(r => `
            <tr data-id="${r.id}">
              <td class="cell">${esc(r.name)}</td>
              <td class="cell ltr">${esc(r.masked_card)}</td>
              <td class="cell">${esc(r.role)}</td>
              <td class="cell">${esc(r.classes_str)}</td>
              <td class="cell">${esc(r.bonus_max_points_per_student ?? '')}</td>
              <td class="cell">${esc(r.bonus_max_total_runs ?? '')}</td>
              <td class="cell">${esc(r.bonus_runs_used_today_str ?? '')}</td>
              <td class="cell">${esc(r.bonus_points_today ?? '')}</td>
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
            return null;
          }
          return await resp.json();
        }

        async function saveClasses(teacherId, classes) {
          const resp = await fetch('/api/teacher-classes/set', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ teacher_id: parseInt(String(teacherId), 10), classes: classes })
          });
          if (!resp.ok) {
            const txt = await resp.text();
            alert('שגיאה בשמירת כיתות: ' + txt);
            return false;
          }
          return true;
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

        async function openAdd() {
          modalTitle.textContent = 'הוספת מורה';
          mId.value = '';
          mName.value = '';
          mCard1.value = '';
          mCard2.value = '';
          mCard3.value = '';
          mIsAdmin.checked = false;
          mCanEditCard.checked = true;
          mCanEditPhoto.checked = true;
          mMaxPoints.value = '';
          mMaxRuns.value = '';
          const allClasses = await loadAllClasses();
          renderClasses(allClasses, []);
          setAdminMode(false);
          openModal();
          try { mName.focus(); } catch(e) {}
        }

        async function openEdit() {
          if (!selectedId) return;
          modalTitle.textContent = 'עריכת מורה';
          const resp = await fetch(`/api/teachers/${encodeURIComponent(String(selectedId))}`);
          if (!resp.ok) {
            const txt = await resp.text();
            alert('שגיאה בטעינת מורה: ' + txt);
            return;
          }
          const t = await resp.json();
          mId.value = String(t.id ?? selectedId);
          mName.value = String(t.name ?? '');
          mCard1.value = String(t.card_number ?? '');
          mCard2.value = String(t.card_number2 ?? '');
          mCard3.value = String(t.card_number3 ?? '');
          mIsAdmin.checked = (parseInt(String(t.is_admin ?? 0), 10) === 1);
          mCanEditCard.checked = (parseInt(String(t.can_edit_student_card ?? 1), 10) === 1);
          mCanEditPhoto.checked = (parseInt(String(t.can_edit_student_photo ?? 1), 10) === 1);
          mMaxPoints.value = (t.bonus_max_points_per_student ?? '') === null ? '' : String(t.bonus_max_points_per_student ?? '');
          mMaxRuns.value = (t.bonus_max_total_runs ?? '') === null ? '' : String(t.bonus_max_total_runs ?? '');
          const allClasses = await loadAllClasses();
          renderClasses(allClasses, Array.isArray(t.classes) ? t.classes : []);
          setAdminMode(mIsAdmin.checked);
          openModal();
        }

        async function submitModal() {
          const name = String(mName.value || '').trim();
          const card1 = String(mCard1.value || '').trim();
          const card2 = String(mCard2.value || '').trim();
          const card3 = String(mCard3.value || '').trim();
          if (!name) { alert('יש להזין שם מורה'); return; }
          if (!(card1 || card2 || card3)) { alert('יש להזין לפחות מספר כרטיס אחד'); return; }
          const isAdmin = mIsAdmin.checked ? 1 : 0;

          const payload = {
            teacher_id: mId.value ? parseInt(String(mId.value), 10) : null,
            name: name,
            card_number: card1,
            card_number2: card2,
            card_number3: card3,
            is_admin: isAdmin,
            can_edit_student_card: (mCanEditCard.checked ? 1 : 0),
            can_edit_student_photo: (mCanEditPhoto.checked ? 1 : 0),
            bonus_max_points_per_student: normalizeIntOrNull(mMaxPoints.value),
            bonus_max_total_runs: normalizeIntOrNull(mMaxRuns.value)
          };

          btnSave.disabled = true;
          try {
            const res = await save(payload);
            if (!res || !res.ok) return;
            const teacherId = res.teacher_id || payload.teacher_id;
            const classes = isAdmin ? [] : getSelectedClassesFromUI();
            await saveClasses(teacherId, classes);
            closeModal();
            selectedId = null;
            await load();
          } finally {
            btnSave.disabled = false;
          }
        }

        btnNew.addEventListener('click', openAdd);
        btnEdit.addEventListener('click', openEdit);

        btnDelete.addEventListener('click', async () => {
          if (!selectedId) return;
          if (!confirm('למחוק מורה?')) return;
          await del(parseInt(selectedId, 10));
        });

        btnSave.addEventListener('click', submitModal);
        btnCancel.addEventListener('click', closeModal);
        modal.addEventListener('click', (ev) => {
          if (ev.target === modal) closeModal();
        });
        mIsAdmin.addEventListener('change', () => setAdminMode(mIsAdmin.checked));
        btnSelectAll.addEventListener('click', () => {
          classesBox.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.checked = true);
        });
        btnClearAll.addEventListener('click', () => {
          classesBox.querySelectorAll('input[type="checkbox"]').forEach(cb => cb.checked = false);
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
      table { width:100%; border-collapse:separate; border-spacing:0; font-size:13px; overflow:hidden; border-radius:14px; }
      thead th {
        position: sticky;
        top: 0;
        background: rgba(255,255,255,.12);
        color: rgba(255,255,255,.92);
        border-bottom: 1px solid rgba(255,255,255,.16);
        padding: 10px 10px;
        text-align: right;
        font-weight: 950;
        white-space: nowrap;
      }
      tbody tr { background: rgba(0,0,0,.08); }
      tbody tr:nth-child(even) { background: rgba(255,255,255,.06); }
      tbody tr:hover { background: rgba(26,188,156,.18); }
      .cell {
        padding: 10px 10px;
        border-bottom: 1px solid rgba(255,255,255,.12);
        color: rgba(255,255,255,.92);
        white-space: nowrap;
      }
      .cell.ltr { direction:ltr; text-align:left; }
      .bar { margin:10px 0; display:flex; gap:10px; flex-wrap:wrap; align-items:center; }
      .bar input { padding:10px 12px; border:1px solid rgba(255,255,255,.18); border-radius:12px; background: rgba(0,0,0,.18); color: rgba(255,255,255,.92); }
      .bar input::placeholder { color: rgba(255,255,255,.62); }
      .btn { padding:10px 14px; border-radius:14px; color:#fff; text-decoration:none; border:1px solid rgba(255,255,255,.16); font-weight:900; cursor:pointer; box-shadow: 0 14px 28px rgba(0,0,0,.22); }
      .btn-green { background: linear-gradient(135deg, #2ecc71, #1abc9c); }
      .btn-blue { background: linear-gradient(135deg, #3498db, #2f80ed); }
      .btn-red { background: linear-gradient(135deg, #e74c3c, #c0392b); }
      .modal-backdrop { display:none; position:fixed; inset:0; background: rgba(0,0,0,.55); z-index: 50; align-items:center; justify-content:center; padding: 16px; }
      .modal { width: min(860px, 96vw); background: linear-gradient(180deg, rgba(255,255,255,.18), rgba(255,255,255,.10)); border:1px solid rgba(255,255,255,.18); border-radius: 18px; box-shadow: 0 24px 60px rgba(0,0,0,.35); backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px); padding: 16px; }
      .modal h3 { margin: 0 0 10px; font-size: 18px; font-weight: 950; }
      .grid { display:grid; grid-template-columns: 1fr 1fr; gap: 10px 12px; }
      .grid label { font-weight: 900; font-size: 13px; opacity:.92; display:block; margin-bottom:6px; }
      .grid input[type="text"], .grid input[type="password"], .grid input[type="number"] { width:100%; padding:10px 12px; border:1px solid rgba(255,255,255,.18); border-radius:12px; background: rgba(0,0,0,.18); color: rgba(255,255,255,.92); }
      .grid input::placeholder { color: rgba(255,255,255,.62); }
      .row { display:flex; gap:10px; flex-wrap:wrap; align-items:center; margin-top: 10px; }
      .ck { display:inline-flex; align-items:center; gap:8px; padding:6px 10px; border-radius: 999px; border:1px solid rgba(255,255,255,.16); background: rgba(0,0,0,.14); font-weight: 800; }
      .classes { max-height: 220px; overflow:auto; padding: 10px; border-radius: 14px; border: 1px solid rgba(255,255,255,.16); background: rgba(0,0,0,.12); display:flex; flex-wrap:wrap; gap:8px; }
    </style>
    <div class="bar">
      <input id="t_search" placeholder="חיפוש" />
      <span id="t_status" style="opacity:.86;">טוען...</span>
    </div>
    <div class="bar">
      <button class="btn btn-green" id="t_new" type="button">➕ הוסף מורה</button>
      <button class="btn btn-blue" id="t_edit" type="button" style="opacity:.55;pointer-events:none;">✏️ עריכה</button>
      <button class="btn btn-red" id="t_delete" type="button" style="opacity:.55;pointer-events:none;">🗑️ מחיקה</button>
      <span id="t_selected" style="opacity:.86;">לא נבחר מורה</span>
    </div>
    <div style="overflow:auto;">
      <table>
        <thead>
          <tr>
            <th>שם</th>
            <th>מס׳ כרטיס / סיסמה</th>
            <th>תפקיד</th>
            <th>כיתות</th>
            <th>מקס׳ נק׳<br/>בונוס לתלמיד</th>
            <th>מקס׳ הפעלות<br/>בונוס ליום</th>
            <th>הפעלות<br/>בונוס היום</th>
            <th>סה"כ נק׳<br/>שהמורה חילק היום</th>
          </tr>
        </thead>
        <tbody id="t_rows"></tbody>
      </table>
    </div>

    <div id="t_modal" class="modal-backdrop">
      <div class="modal">
        <h3 id="t_modal_title">עריכת מורה</h3>
        <input id="m_teacher_id" type="hidden" />
        <div class="grid">
          <div>
            <label>שם המורה</label>
            <input id="m_name" type="text" placeholder="שם" />
          </div>
          <div>
            <label>מנהל</label>
            <label class="ck"><input id="m_is_admin" type="checkbox" /> מנהל (הרשאות מלאות)</label>
          </div>

          <div>
            <label>מספר כרטיס 1</label>
            <input id="m_card1" type="password" placeholder="••••••" />
          </div>
          <div>
            <label>מספר כרטיס 2</label>
            <input id="m_card2" type="password" placeholder="••••••" />
          </div>
          <div>
            <label>מספר כרטיס 3</label>
            <input id="m_card3" type="password" placeholder="••••••" />
          </div>
          <div>
            <label>הרשאות מורה</label>
            <div class="row">
              <label class="ck"><input id="m_can_edit_student_card" type="checkbox" checked /> מורה יכול לשנות מס' כרטיס לתלמיד</label>
              <label class="ck"><input id="m_can_edit_student_photo" type="checkbox" checked /> מורה יכול לשנות תמונת תלמיד</label>
            </div>
          </div>
          <div>
            <label>מקסימום נקודות לבונוס מורה (לכל תלמיד)</label>
            <input id="m_bonus_max_points_per_student" type="number" min="1" placeholder="ריק = ללא הגבלה" />
          </div>
          <div>
            <label>מקסימום הפעלות בונוס ליום</label>
            <input id="m_bonus_max_total_runs" type="number" min="1" placeholder="ריק = ללא הגבלה" />
          </div>
        </div>

        <div style="margin-top:12px;">
          <div style="font-weight:950; margin-bottom:8px;">כיתות</div>
          <div class="row" style="margin-top:0;">
            <button id="m_select_all" class="btn btn-blue" type="button">בחר הכל</button>
            <button id="m_clear_all" class="btn btn-red" type="button">נקה הכל</button>
          </div>
          <div id="m_classes_box" class="classes" style="margin-top:10px;"></div>
        </div>

        <div class="row" style="justify-content:flex-end; margin-top:14px;">
          <button id="m_cancel" class="btn btn-red" type="button">ביטול</button>
          <button id="m_save" class="btn btn-green" type="button">שמירה</button>
        </div>
      </div>
    </div>
    """
    return HTMLResponse(_basic_web_shell("ניהול מורים", body + js, request=request))


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
    try:
        _ensure_teacher_columns(conn)
        cur = conn.cursor()
        query = """
            SELECT
              id, name, card_number, card_number2, card_number3, is_admin,
              can_edit_student_card, can_edit_student_photo,
              bonus_max_points_per_student, bonus_max_total_runs,
              bonus_runs_used, bonus_runs_reset_date,
              bonus_points_used, bonus_points_reset_date
            FROM teachers
        """
        params: List[Any] = []
        if q:
            like = f"%{q.strip()}%"
            query += " WHERE name LIKE ? OR card_number LIKE ? OR card_number2 LIKE ? OR card_number3 LIKE ?"
            params.extend([like, like, like, like])
        query += " ORDER BY name ASC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        cur.execute(_sql_placeholder(query), params)
        rows = [dict(r) for r in (cur.fetchall() or [])]

        today_iso = datetime.date.today().isoformat()
        out: List[Dict[str, Any]] = []
        for r in rows:
            rid = _safe_int(r.get('id'), 0)
            name = str(r.get('name') or '').strip()
            is_admin = bool(_safe_int(r.get('is_admin'), 0) == 1)

            c1 = str(r.get('card_number') or '').strip()
            c2 = str(r.get('card_number2') or '').strip()
            c3 = str(r.get('card_number3') or '').strip()
            has_any_card = bool(c1 or c2 or c3)
            masked_card = '••••••' if has_any_card else '(ללא כרטיס)'

            max_points = r.get('bonus_max_points_per_student')
            max_runs = r.get('bonus_max_total_runs')

            runs_used = _safe_int(r.get('bonus_runs_used'), 0)
            runs_reset = str(r.get('bonus_runs_reset_date') or '').strip()
            if runs_reset:
                runs_reset = runs_reset[:10]
            if not runs_reset or runs_reset != today_iso:
                runs_used = 0

            points_used = _safe_int(r.get('bonus_points_used'), 0)
            points_reset = str(r.get('bonus_points_reset_date') or '').strip()
            if points_reset:
                points_reset = points_reset[:10]
            if not points_reset or points_reset != today_iso:
                points_used = 0

            max_runs_i = None
            try:
                if max_runs is not None and str(max_runs).strip() != '':
                    max_runs_i = int(max_runs)
            except Exception:
                max_runs_i = None

            if max_runs_i is not None and max_runs_i > 0:
                runs_used_str = f"{int(runs_used)}/{int(max_runs_i)}"
            else:
                runs_used_str = str(int(runs_used))

            try:
                classes = _web_teacher_allowed_classes(tenant_id, rid)
            except Exception:
                classes = []
            classes_str = ', '.join(classes) if classes else '(אין כיתות)'

            out.append({
                'id': rid,
                'name': name,
                'masked_card': masked_card,
                'role': ('מנהל' if is_admin else 'מורה'),
                'classes': classes,
                'classes_str': classes_str,
                'bonus_max_points_per_student': max_points,
                'bonus_max_total_runs': max_runs,
                'bonus_runs_used_today': int(runs_used),
                'bonus_runs_used_today_str': runs_used_str,
                'bonus_points_today': int(points_used),
                'can_edit_student_card': _safe_int(r.get('can_edit_student_card'), 1),
                'can_edit_student_photo': _safe_int(r.get('can_edit_student_photo'), 1),
            })

        return {"items": out, "limit": limit, "offset": offset, "query": q}
    finally:
        try:
            conn.close()
        except Exception:
            pass


@app.get('/api/teachers/{teacher_id}')
def api_teacher_get(request: Request, teacher_id: int) -> Dict[str, Any]:
    guard = _web_require_admin_teacher(request)
    if guard:
        raise HTTPException(status_code=401, detail='not authorized')
    tenant_id = _web_tenant_from_cookie(request)
    conn = _tenant_school_db(tenant_id)
    try:
        _ensure_teacher_columns(conn)
        cur = conn.cursor()
        cur.execute(
            _sql_placeholder(
                'SELECT id, name, card_number, card_number2, card_number3, is_admin, '
                'can_edit_student_card, can_edit_student_photo, '
                'bonus_max_points_per_student, bonus_max_total_runs '
                'FROM teachers WHERE id = ? LIMIT 1'
            ),
            (int(teacher_id),)
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='not found')
        r = dict(row) if isinstance(row, dict) else {k: row[k] for k in row.keys()}  # type: ignore[attr-defined]
        try:
            classes = _web_teacher_allowed_classes(tenant_id, int(teacher_id))
        except Exception:
            classes = []
        r['classes'] = classes
        return r
    finally:
        try:
            conn.close()
        except Exception:
            pass


@app.post('/api/teacher-classes/set')
def api_teacher_classes_set(request: Request, payload: TeacherClassesPayload) -> Dict[str, Any]:
    guard = _web_require_admin_teacher(request)
    if guard:
        raise HTTPException(status_code=401, detail='not authorized')
    tenant_id = _web_tenant_from_cookie(request)
    tid = int(payload.teacher_id or 0)
    if tid <= 0:
        raise HTTPException(status_code=400, detail='invalid teacher_id')
    classes = [str(c).strip() for c in (payload.classes or []) if str(c).strip()]
    classes = sorted(set(classes))

    conn = _tenant_school_db(tenant_id)
    try:
        cur = conn.cursor()
        cur.execute(_sql_placeholder('DELETE FROM teacher_classes WHERE teacher_id = ?'), (int(tid),))
        for cn in classes:
            cur.execute(
                _sql_placeholder('INSERT INTO teacher_classes (teacher_id, class_name) VALUES (?, ?)'),
                (int(tid), str(cn))
            )
        conn.commit()
        return {'ok': True, 'teacher_id': int(tid), 'classes': classes}
    finally:
        try:
            conn.close()
        except Exception:
            pass


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
        _ensure_teacher_columns(conn)
        cur = conn.cursor()
        tid = payload.teacher_id
        if tid is None or int(tid or 0) <= 0:
            cur.execute('SELECT COALESCE(MAX(id), 0) AS m FROM teachers')
            r = cur.fetchone() or {}
            max_id = int((r.get('m') if isinstance(r, dict) else r[0]) or 0)
            tid = max_id + 1
            cur.execute(
                _sql_placeholder(
                    'INSERT INTO teachers '
                    '(id, name, card_number, card_number2, card_number3, is_admin, '
                    'can_edit_student_card, can_edit_student_photo, '
                    'bonus_max_points_per_student, bonus_max_total_runs) '
                    'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)'
                ),
                (
                    int(tid),
                    str(payload.name or '').strip(),
                    str(payload.card_number or '').strip(),
                    str(payload.card_number2 or '').strip(),
                    str(payload.card_number3 or '').strip(),
                    int(payload.is_admin or 0),
                    int(1 if _safe_int(payload.can_edit_student_card, 1) == 1 else 0),
                    int(1 if _safe_int(payload.can_edit_student_photo, 1) == 1 else 0),
                    (int(payload.bonus_max_points_per_student) if payload.bonus_max_points_per_student is not None else None),
                    (int(payload.bonus_max_total_runs) if payload.bonus_max_total_runs is not None else None),
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
        if payload.can_edit_student_card is not None:
            sets.append('can_edit_student_card = ?')
            params.append(int(1 if _safe_int(payload.can_edit_student_card, 1) == 1 else 0))
        if payload.can_edit_student_photo is not None:
            sets.append('can_edit_student_photo = ?')
            params.append(int(1 if _safe_int(payload.can_edit_student_photo, 1) == 1 else 0))
        if payload.bonus_max_points_per_student is not None:
            sets.append('bonus_max_points_per_student = ?')
            params.append(int(payload.bonus_max_points_per_student))
        if payload.bonus_max_total_runs is not None:
            sets.append('bonus_max_total_runs = ?')
            params.append(int(payload.bonus_max_total_runs))
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
    guard = _web_require_admin_teacher(request)
    if guard:
        return guard
    
    html_content = """
    <h2>הגדרות מערכת</h2>
    
    <div class="card" style="padding:20px; background:#fff; border-radius:10px; border:1px solid #eee;">
      <div class="form-group" style="margin-bottom:15px;">
        <label style="display:block; margin-bottom:5px; font-weight:600;">מצב פריסה</label>
        <select id="sys-mode" style="width:100%; padding:10px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box;">
          <option value="local">מקומי (Local)</option>
          <option value="cloud">ענן (Cloud)</option>
          <option value="hybrid">משולב (Hybrid)</option>
        </select>
      </div>
      <div class="form-group" style="margin-bottom:15px;">
        <label style="display:block; margin-bottom:5px; font-weight:600;">תיקייה משותפת (נתיב)</label>
        <input id="sys-shared" style="width:100%; padding:10px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box; direction:ltr; text-align:left;">
      </div>
      <div class="form-group" style="margin-bottom:15px;">
        <label style="display:block; margin-bottom:5px; font-weight:600;">נתיב לוגו (אופציונלי)</label>
        <input id="sys-logo" style="width:100%; padding:10px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box; direction:ltr; text-align:left;">
      </div>
      <div>
        <button class="green" onclick="saveSystem()" style="padding:10px 20px; border-radius:6px; border:none; background:#2ecc71; color:white; font-weight:bold; cursor:pointer;">שמירה</button>
      </div>
    </div>

    <script>
      async function loadSystem() {
        try {
          const res = await fetch('/api/settings/system_settings');
          const data = await res.json();
          document.getElementById('sys-mode').value = data.deployment_mode || 'hybrid';
          document.getElementById('sys-shared').value = data.shared_folder || '';
          document.getElementById('sys-logo').value = data.logo_path || '';
        } catch(e) {}
      }

      async function saveSystem() {
        const payload = {
            deployment_mode: document.getElementById('sys-mode').value,
            shared_folder: document.getElementById('sys-shared').value,
            logo_path: document.getElementById('sys-logo').value
        };
        await fetch('/api/settings/save', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ key: 'system_settings', value: payload })
        });
        alert('נשמר בהצלחה');
      }

      loadSystem();
    </script>
    """
    return _basic_web_shell("הגדרות מערכת", html_content, request=request)


@app.get("/web/display-settings", response_class=HTMLResponse)
def web_display_settings(request: Request):
    guard = _web_require_admin_teacher(request)
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

    import json
    try:
        data = json.loads(value_json)
    except:
        data = {}

    def _v(k, default=''):
        return html.escape(str(data.get(k, default)))

    style_block = """
    <style>
        .form-group { margin-bottom:15px; }
        .form-group label { display:block; font-weight:600; margin-bottom:5px; }
        .form-control { width:100%; padding:10px; border:1px solid #ddd; border-radius:8px; box-sizing:border-box; }
        .ck { display:flex; align-items:center; gap:8px; cursor:pointer; font-weight:600; user-select:none; background:#f8f9fa; padding:8px 12px; border-radius:20px; border:1px solid #eee; }
        .ck:hover { background:#e9ecef; }
        .btn { padding:10px 20px; border-radius:8px; text-decoration:none; font-weight:bold; border:none; cursor:pointer; font-size:14px; display:inline-block; }
        .green { background:#2ecc71; color:white; }
        .gray { background:#95a5a6; color:white; }
        .actionbar { display:flex; gap:10px; }
    </style>
    """

    script_block = """
    <script>
      async function saveSettings() {
        const payload = {
            title_text: document.getElementById('p_title').value,
            subtitle_text: document.getElementById('p_subtitle').value,
            logo_url: document.getElementById('p_logo').value,
            background_url: document.getElementById('p_bg').value,
            refresh_interval: parseInt(document.getElementById('p_refresh').value) || 60,
            font_size: parseInt(document.getElementById('p_fontsize').value) || 16,
            enabled: document.getElementById('p_enabled').checked,
            dark_mode: document.getElementById('p_dark').checked,
            show_clock: document.getElementById('p_clock').checked,
            show_qr: document.getElementById('p_qr').checked
        };

        try {
            const res = await fetch('/api/settings/save', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ key: 'display_settings', value: payload })
            });
            if (res.ok) {
                alert('נשמר בהצלחה');
            } else {
                alert('שגיאה בשמירה');
            }
        } catch (e) {
            alert('שגיאה: ' + e);
        }
      }
    </script>
    """

    html_content = f"""
    <div style="max-width:800px; margin:0 auto;">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px;">
        <h2>הגדרות תצוגה</h2>
        <div class="actionbar">
          <a class="blue" href="/web/colors">🎨 צבעים</a>
          <a class="blue" href="/web/sounds">🔊 צלילים</a>
          <a class="blue" href="/web/coins">🪙 מטבעות</a>
          <a class="blue" href="/web/holidays">📅 חגים</a>
        </div>
      </div>

      <div class="card" style="padding:24px;">
        <div class="form-group">
            <label>כותרת ראשית (שם המוסד)</label>
            <input id="p_title" class="form-control" value="{_v('title_text', 'ברוכים הבאים')}" />
        </div>
        <div class="form-group">
            <label>כותרת משנית</label>
            <input id="p_subtitle" class="form-control" value="{_v('subtitle_text', '')}" />
        </div>
        <div class="form-group">
            <label>קישור ללוגו (URL)</label>
            <input id="p_logo" class="form-control" value="{_v('logo_url', '')}" dir="ltr" />
        </div>
        <div class="form-group">
            <label>תמונת רקע (URL)</label>
            <input id="p_bg" class="form-control" value="{_v('background_url', '')}" dir="ltr" />
        </div>
        
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:20px; margin-top:15px;">
            <div class="form-group">
                <label>זמן רענון (שניות)</label>
                <input id="p_refresh" type="number" class="form-control" value="{data.get('refresh_interval', 60)}" />
            </div>
            <div class="form-group">
                <label>גודל גופן בסיסי (px)</label>
                <input id="p_fontsize" type="number" class="form-control" value="{data.get('font_size', 16)}" />
            </div>
        </div>

        <div style="margin-top:20px; display:flex; gap:20px; flex-wrap:wrap;">
            <label class="ck"><input type="checkbox" id="p_enabled" {'checked' if data.get('enabled', True) else ''}> פעיל</label>
            <label class="ck"><input type="checkbox" id="p_dark" {'checked' if data.get('dark_mode', False) else ''}> מצב כהה</label>
            <label class="ck"><input type="checkbox" id="p_clock" {'checked' if data.get('show_clock', True) else ''}> הצג שעון</label>
            <label class="ck"><input type="checkbox" id="p_qr" {'checked' if data.get('show_qr', False) else ''}> הצג QR לסריקה</label>
        </div>

        <div style="margin-top:30px; border-top:1px solid #eee; padding-top:20px; text-align:left;">
            <button class="green" onclick="saveSettings()">💾 שמור הגדרות</button>
            <a class="gray btn" href="/web/admin">חזרה</a>
        </div>
      </div>
    </div>
    {script_block}
    {style_block}
    """
    return _basic_web_shell("הגדרות תצוגה", html_content, request=request)


@app.get("/web/colors", response_class=HTMLResponse)
def web_colors(request: Request):
    guard = _web_require_admin_teacher(request)
    if guard:
        return guard
    
    html_content = """
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px;">
      <h2>צבעים לפי ניקוד</h2>
      <button class="green" onclick="openRangeModal()">+ טווח חדש</button>
    </div>
    
    <div class="card" style="padding:0; overflow:hidden;">
      <table style="width:100%; border-collapse:collapse;">
        <thead>
          <tr style="background:#f8f9fa; border-bottom:1px solid #eee;">
            <th style="padding:12px; text-align:right;">מינימום נקודות</th>
            <th style="padding:12px; text-align:right;">צבע</th>
            <th style="padding:12px; text-align:right;">פעולות</th>
          </tr>
        </thead>
        <tbody id="ranges-list"></tbody>
      </table>
    </div>

    <!-- Modal -->
    <div id="modal-range" class="modal-overlay" style="display:none; position:fixed; top:0; left:0; right:0; bottom:0; background:rgba(0,0,0,0.5); align-items:center; justify-content:center; z-index:1000;">
      <div class="modal" style="background:#fff; padding:24px; border-radius:12px; width:90%; max-width:400px; box-shadow:0 4px 20px rgba(0,0,0,0.2);">
        <h3 id="modal-title" style="margin-top:0;">טווח צבע</h3>
        <input type="hidden" id="range-index">
        <div class="form-group" style="margin-bottom:15px;">
          <label style="display:block; margin-bottom:5px; font-weight:600;">מינימום נקודות</label>
          <input type="number" id="range-min" style="width:100%; padding:8px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box;">
        </div>
        <div class="form-group" style="margin-bottom:15px;">
          <label style="display:block; margin-bottom:5px; font-weight:600;">צבע</label>
          <input type="color" id="range-color" style="width:100%; height:40px; padding:2px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box;">
        </div>
        <div style="display:flex; justify-content:flex-end; gap:10px; margin-top:20px;">
          <button class="gray" onclick="closeRangeModal()" style="padding:8px 16px; border:none; border-radius:6px; cursor:pointer;">ביטול</button>
          <button class="green" onclick="saveRange()" style="padding:8px 16px; background:#2ecc71; color:white; border:none; border-radius:6px; font-weight:600; cursor:pointer;">שמירה</button>
        </div>
      </div>
    </div>

    <script>
      let ranges = [];

      async function loadRanges() {
        try {
          const res = await fetch('/api/settings/color_settings');
          const data = await res.json();
          ranges = Array.isArray(data.ranges) ? data.ranges : [];
          ranges.sort((a, b) => (a.min || 0) - (b.min || 0));
          renderRanges();
        } catch(e) {}
      }

      function renderRanges() {
        const tbody = document.getElementById('ranges-list');
        if (ranges.length === 0) {
            tbody.innerHTML = '<tr><td colspan="3" style="padding:20px; text-align:center; color:#888;">אין טווחים מוגדרים</td></tr>';
            return;
        }
        tbody.innerHTML = ranges.map((r, idx) => `
          <tr style="border-bottom:1px solid #eee; hover:background:#fdfdfd;">
            <td style="padding:12px;">${r.min || 0}</td>
            <td style="padding:12px;"><span style="display:inline-block; width:20px; height:20px; background:${r.color}; vertical-align:middle; border:1px solid #ccc; border-radius:4px;"></span> ${r.color}</td>
            <td style="padding:12px;">
              <button onclick="editRange(${idx})" style="background:none; border:none; cursor:pointer; font-size:16px;">✏️</button>
              <button onclick="deleteRange(${idx})" style="background:none; border:none; cursor:pointer; font-size:16px;">🗑️</button>
            </td>
          </tr>
        `).join('');
      }

      function openRangeModal() {
        document.getElementById('range-index').value = '-1';
        document.getElementById('range-min').value = '0';
        document.getElementById('range-color').value = '#000000';
        document.getElementById('modal-title').textContent = 'הוספת טווח';
        document.getElementById('modal-range').style.display = 'flex';
      }

      function closeRangeModal() {
        document.getElementById('modal-range').style.display = 'none';
      }

      function editRange(idx) {
        const r = ranges[idx];
        document.getElementById('range-index').value = idx;
        document.getElementById('range-min').value = r.min || 0;
        document.getElementById('range-color').value = r.color || '#000000';
        document.getElementById('modal-title').textContent = 'עריכת טווח';
        document.getElementById('modal-range').style.display = 'flex';
      }

      async function saveRange() {
        const idx = parseInt(document.getElementById('range-index').value);
        const min = parseInt(document.getElementById('range-min').value) || 0;
        const color = document.getElementById('range-color').value;
        
        const newRange = { min, color };
        
        if (idx >= 0) {
            ranges[idx] = newRange;
        } else {
            ranges.push(newRange);
        }
        
        ranges.sort((a, b) => (a.min || 0) - (b.min || 0));
        
        await saveToServer();
        closeRangeModal();
        renderRanges();
      }

      async function deleteRange(idx) {
        if (!confirm('למחוק?')) return;
        ranges.splice(idx, 1);
        await saveToServer();
        renderRanges();
      }

      async function saveToServer() {
        await fetch('/api/settings/save', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ key: 'color_settings', value: { ranges: ranges } })
        });
      }

      loadRanges();
    </script>
    """
    return _basic_web_shell("צבעים", html_content, request=request)


@app.get("/web/sounds", response_class=HTMLResponse)
def web_sounds(request: Request):
    guard = _web_require_admin_teacher(request)
    if guard:
        return guard
    
    html_content = """
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px;">
      <h2>הגדרות צלילים</h2>
      <button class="green" onclick="openSoundModal()">+ צליל חדש</button>
    </div>
    
    <div class="card" style="padding:0; overflow:hidden;">
      <table style="width:100%; border-collapse:collapse;">
        <thead>
          <tr style="background:#f8f9fa; border-bottom:1px solid #eee;">
            <th style="padding:12px; text-align:right;">אירוע</th>
            <th style="padding:12px; text-align:right;">קובץ / URL</th>
            <th style="padding:12px; text-align:right;">פעולות</th>
          </tr>
        </thead>
        <tbody id="sounds-list"></tbody>
      </table>
    </div>

    <!-- Modal -->
    <div id="modal-sound" class="modal-overlay" style="display:none; position:fixed; top:0; left:0; right:0; bottom:0; background:rgba(0,0,0,0.5); align-items:center; justify-content:center; z-index:1000;">
      <div class="modal" style="background:#fff; padding:24px; border-radius:12px; width:90%; max-width:400px; box-shadow:0 4px 20px rgba(0,0,0,0.2);">
        <h3 id="modal-title" style="margin-top:0;">הגדרת צליל</h3>
        <input type="hidden" id="sound-index">
        <div class="form-group" style="margin-bottom:15px;">
          <label style="display:block; margin-bottom:5px; font-weight:600;">אירוע</label>
          <select id="sound-event" style="width:100%; padding:10px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box;">
            <option value="scan_success">סריקה מוצלחת (scan_success)</option>
            <option value="scan_error">שגיאת סריקה (scan_error)</option>
            <option value="bonus_success">קבלת בונוס (bonus_success)</option>
            <option value="shop_purchase">רכישה בקופה (shop_purchase)</option>
            <option value="level_up">עליית רמה (level_up)</option>
            <option value="custom">אחר (מותאם אישית)</option>
          </select>
          <input id="sound-event-custom" placeholder="שם אירוע..." style="width:100%; padding:8px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box; margin-top:5px; display:none;">
        </div>
        <div class="form-group" style="margin-bottom:15px;">
          <label style="display:block; margin-bottom:5px; font-weight:600;">קובץ / URL</label>
          <input id="sound-file" style="width:100%; padding:8px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box; direction:ltr; text-align:left;">
        </div>
        <div style="display:flex; justify-content:flex-end; gap:10px; margin-top:20px;">
          <button class="gray" onclick="closeSoundModal()" style="padding:8px 16px; border:none; border-radius:6px; cursor:pointer;">ביטול</button>
          <button class="green" onclick="saveSound()" style="padding:8px 16px; background:#2ecc71; color:white; border:none; border-radius:6px; font-weight:600; cursor:pointer;">שמירה</button>
        </div>
      </div>
    </div>

    <script>
      let sounds = [];

      async function loadSounds() {
        try {
          const res = await fetch('/api/settings/sound_settings');
          const data = await res.json();
          sounds = Array.isArray(data.sounds) ? data.sounds : [];
          renderSounds();
        } catch(e) {}
      }

      function renderSounds() {
        const tbody = document.getElementById('sounds-list');
        if (sounds.length === 0) {
            tbody.innerHTML = '<tr><td colspan="3" style="padding:20px; text-align:center; color:#888;">אין צלילים מוגדרים</td></tr>';
            return;
        }
        tbody.innerHTML = sounds.map((s, idx) => `
          <tr style="border-bottom:1px solid #eee; hover:background:#fdfdfd;">
            <td style="padding:12px;">${esc(s.event)}</td>
            <td style="padding:12px; direction:ltr; text-align:left;">${esc(s.file)}</td>
            <td style="padding:12px;">
              <button onclick="editSound(${idx})" style="background:none; border:none; cursor:pointer; font-size:16px;">✏️</button>
              <button onclick="deleteSound(${idx})" style="background:none; border:none; cursor:pointer; font-size:16px;">🗑️</button>
            </td>
          </tr>
        `).join('');
      }

      const evtSelect = document.getElementById('sound-event');
      const evtCustom = document.getElementById('sound-event-custom');
      
      evtSelect.addEventListener('change', () => {
        evtCustom.style.display = evtSelect.value === 'custom' ? 'block' : 'none';
      });

      function openSoundModal() {
        document.getElementById('sound-index').value = '-1';
        evtSelect.value = 'scan_success';
        evtCustom.style.display = 'none';
        evtCustom.value = '';
        document.getElementById('sound-file').value = '';
        document.getElementById('modal-title').textContent = 'הוספת צליל';
        document.getElementById('modal-sound').style.display = 'flex';
      }

      function closeSoundModal() {
        document.getElementById('modal-sound').style.display = 'none';
      }

      function editSound(idx) {
        const s = sounds[idx];
        document.getElementById('sound-index').value = idx;
        const standard = ['scan_success','scan_error','bonus_success','shop_purchase','level_up'].includes(s.event);
        evtSelect.value = standard ? s.event : 'custom';
        evtCustom.style.display = standard ? 'none' : 'block';
        evtCustom.value = standard ? '' : s.event;
        document.getElementById('sound-file').value = s.file || '';
        document.getElementById('modal-title').textContent = 'עריכת צליל';
        document.getElementById('modal-sound').style.display = 'flex';
      }

      async function saveSound() {
        const idx = parseInt(document.getElementById('sound-index').value);
        let event = evtSelect.value;
        if (event === 'custom') event = evtCustom.value.trim();
        const file = document.getElementById('sound-file').value.trim();
        
        if (!event || !file) return alert('נא להזין אירוע וקובץ');

        const newSound = { event, file };
        
        if (idx >= 0) {
            sounds[idx] = newSound;
        } else {
            sounds.push(newSound);
        }
        
        await saveToServer();
        closeSoundModal();
        renderSounds();
      }

      async function deleteSound(idx) {
        if (!confirm('למחוק?')) return;
        sounds.splice(idx, 1);
        await saveToServer();
        renderSounds();
      }

      async function saveToServer() {
        await fetch('/api/settings/save', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ key: 'sound_settings', value: { sounds: sounds } })
        });
      }

      function esc(s) {
        return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
      }

      loadSounds();
    </script>
    """
    return _basic_web_shell("צלילים", html_content, request=request)


@app.get("/web/bonuses", response_class=HTMLResponse)
def web_bonuses(request: Request):
    guard = _web_require_admin_teacher(request)
    if guard:
        return guard
    
    html_content = """
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px;">
      <h2>בונוסים</h2>
      <button class="green" onclick="openBonusModal()">+ בונוס חדש</button>
    </div>
    
    <div class="card" style="padding:0; overflow:hidden;">
      <table style="width:100%; border-collapse:collapse;">
        <thead>
          <tr style="background:#f8f9fa; border-bottom:1px solid #eee;">
            <th style="padding:12px; text-align:right;">שם</th>
            <th style="padding:12px; text-align:right;">ניקוד</th>
            <th style="padding:12px; text-align:right;">פעולות</th>
          </tr>
        </thead>
        <tbody id="bonuses-list"></tbody>
      </table>
    </div>

    <!-- Modal -->
    <div id="modal-bonus" class="modal-overlay" style="display:none; position:fixed; top:0; left:0; right:0; bottom:0; background:rgba(0,0,0,0.5); align-items:center; justify-content:center; z-index:1000;">
      <div class="modal" style="background:#fff; padding:24px; border-radius:12px; width:90%; max-width:400px; box-shadow:0 4px 20px rgba(0,0,0,0.2);">
        <h3 id="modal-title" style="margin-top:0;">בונוס</h3>
        <input type="hidden" id="bonus-index">
        <div class="form-group" style="margin-bottom:15px;">
          <label style="display:block; margin-bottom:5px; font-weight:600;">שם הבונוס</label>
          <input id="bonus-name" style="width:100%; padding:8px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box;">
        </div>
        <div class="form-group" style="margin-bottom:15px;">
          <label style="display:block; margin-bottom:5px; font-weight:600;">ניקוד</label>
          <input type="number" id="bonus-points" style="width:100%; padding:8px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box;">
        </div>
        <div style="display:flex; justify-content:flex-end; gap:10px; margin-top:20px;">
          <button class="gray" onclick="closeBonusModal()" style="padding:8px 16px; border:none; border-radius:6px; cursor:pointer;">ביטול</button>
          <button class="green" onclick="saveBonus()" style="padding:8px 16px; background:#2ecc71; color:white; border:none; border-radius:6px; font-weight:600; cursor:pointer;">שמירה</button>
        </div>
      </div>
    </div>

    <script>
      let bonuses = [];

      async function loadBonuses() {
        try {
          const res = await fetch('/api/settings/bonuses_settings');
          const data = await res.json();
          bonuses = Array.isArray(data.items) ? data.items : [];
          renderBonuses();
        } catch(e) {}
      }

      function renderBonuses() {
        const tbody = document.getElementById('bonuses-list');
        if (bonuses.length === 0) {
            tbody.innerHTML = '<tr><td colspan="3" style="padding:20px; text-align:center; color:#888;">אין בונוסים מוגדרים</td></tr>';
            return;
        }
        tbody.innerHTML = bonuses.map((b, idx) => `
          <tr style="border-bottom:1px solid #eee; hover:background:#fdfdfd;">
            <td style="padding:12px;">${esc(b.name)}</td>
            <td style="padding:12px;">${b.points}</td>
            <td style="padding:12px;">
              <button onclick="editBonus(${idx})" style="background:none; border:none; cursor:pointer; font-size:16px;">✏️</button>
              <button onclick="deleteBonus(${idx})" style="background:none; border:none; cursor:pointer; font-size:16px;">🗑️</button>
            </td>
          </tr>
        `).join('');
      }

      function openBonusModal() {
        document.getElementById('bonus-index').value = '-1';
        document.getElementById('bonus-name').value = '';
        document.getElementById('bonus-points').value = '';
        document.getElementById('modal-title').textContent = 'הוספת בונוס';
        document.getElementById('modal-bonus').style.display = 'flex';
      }

      function closeBonusModal() {
        document.getElementById('modal-bonus').style.display = 'none';
      }

      function editBonus(idx) {
        const b = bonuses[idx];
        document.getElementById('bonus-index').value = idx;
        document.getElementById('bonus-name').value = b.name || '';
        document.getElementById('bonus-points').value = b.points || 0;
        document.getElementById('modal-title').textContent = 'עריכת בונוס';
        document.getElementById('modal-bonus').style.display = 'flex';
      }

      async function saveBonus() {
        const idx = parseInt(document.getElementById('bonus-index').value);
        const name = document.getElementById('bonus-name').value.trim();
        const points = parseInt(document.getElementById('bonus-points').value) || 0;
        
        if (!name) return alert('נא להזין שם');

        const newBonus = { name, points };
        
        if (idx >= 0) {
            bonuses[idx] = newBonus;
        } else {
            bonuses.push(newBonus);
        }
        
        await saveToServer();
        closeBonusModal();
        renderBonuses();
      }

      async function deleteBonus(idx) {
        if (!confirm('למחוק?')) return;
        bonuses.splice(idx, 1);
        await saveToServer();
        renderBonuses();
      }

      async function saveToServer() {
        await fetch('/api/settings/save', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ key: 'bonuses_settings', value: { items: bonuses } })
        });
      }

      function esc(s) {
        return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
      }

      loadBonuses();
    </script>
    """
    return _basic_web_shell("בונוסים", html_content, request=request)
    if guard:
        return guard
    
    html_content = """
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px;">
      <h2>מטבעות ויעדים</h2>
      <button class="green" onclick="openCoinModal()">+ מטבע/יעד חדש</button>
    </div>
    
    <div class="card" style="padding:0; overflow:hidden;">
      <table style="width:100%; border-collapse:collapse;">
        <thead>
          <tr style="background:#f8f9fa; border-bottom:1px solid #eee;">
            <th style="padding:12px; text-align:right;">שם</th>
            <th style="padding:12px; text-align:right;">שווי (נקודות)</th>
            <th style="padding:12px; text-align:right;">פעולות</th>
          </tr>
        </thead>
        <tbody id="coins-list"></tbody>
      </table>
    </div>

    <!-- Modal -->
    <div id="modal-coin" class="modal-overlay" style="display:none; position:fixed; top:0; left:0; right:0; bottom:0; background:rgba(0,0,0,0.5); align-items:center; justify-content:center; z-index:1000;">
      <div class="modal" style="background:#fff; padding:24px; border-radius:12px; width:90%; max-width:400px; box-shadow:0 4px 20px rgba(0,0,0,0.2);">
        <h3 id="modal-title" style="margin-top:0;">מטבע / יעד</h3>
        <input type="hidden" id="coin-index">
        <div class="form-group" style="margin-bottom:15px;">
          <label style="display:block; margin-bottom:5px; font-weight:600;">שם המטבע/יעד</label>
          <input id="coin-name" style="width:100%; padding:8px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box;">
        </div>
        <div class="form-group" style="margin-bottom:15px;">
          <label style="display:block; margin-bottom:5px; font-weight:600;">שווי בנקודות</label>
          <input type="number" id="coin-value" style="width:100%; padding:8px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box;">
        </div>
        <div style="display:flex; justify-content:flex-end; gap:10px; margin-top:20px;">
          <button class="gray" onclick="closeCoinModal()" style="padding:8px 16px; border:none; border-radius:6px; cursor:pointer;">ביטול</button>
          <button class="green" onclick="saveCoin()" style="padding:8px 16px; background:#2ecc71; color:white; border:none; border-radius:6px; font-weight:600; cursor:pointer;">שמירה</button>
        </div>
      </div>
    </div>

    <script>
      let coins = [];

      async function loadCoins() {
        try {
          const res = await fetch('/api/settings/coins_settings');
          const data = await res.json();
          coins = Array.isArray(data.coins) ? data.coins : [];
          renderCoins();
        } catch(e) {}
      }

      function renderCoins() {
        const tbody = document.getElementById('coins-list');
        if (coins.length === 0) {
            tbody.innerHTML = '<tr><td colspan="3" style="padding:20px; text-align:center; color:#888;">אין מטבעות מוגדרים</td></tr>';
            return;
        }
        tbody.innerHTML = coins.map((c, idx) => `
          <tr style="border-bottom:1px solid #eee; hover:background:#fdfdfd;">
            <td style="padding:12px;">${esc(c.name)}</td>
            <td style="padding:12px;">${c.value || 0}</td>
            <td style="padding:12px;">
              <button onclick="editCoin(${idx})" style="background:none; border:none; cursor:pointer; font-size:16px;">✏️</button>
              <button onclick="deleteCoin(${idx})" style="background:none; border:none; cursor:pointer; font-size:16px;">🗑️</button>
            </td>
          </tr>
        `).join('');
      }

      function openCoinModal() {
        document.getElementById('coin-index').value = '-1';
        document.getElementById('coin-name').value = '';
        document.getElementById('coin-value').value = '';
        document.getElementById('modal-title').textContent = 'הוספת מטבע';
        document.getElementById('modal-coin').style.display = 'flex';
      }

      function closeCoinModal() {
        document.getElementById('modal-coin').style.display = 'none';
      }

      function editCoin(idx) {
        const c = coins[idx];
        document.getElementById('coin-index').value = idx;
        document.getElementById('coin-name').value = c.name || '';
        document.getElementById('coin-value').value = c.value || 0;
        document.getElementById('modal-title').textContent = 'עריכת מטבע';
        document.getElementById('modal-coin').style.display = 'flex';
      }

      async function saveCoin() {
        const idx = parseInt(document.getElementById('coin-index').value);
        const name = document.getElementById('coin-name').value.trim();
        const value = parseInt(document.getElementById('coin-value').value) || 0;
        
        if (!name) return alert('נא להזין שם');

        const newCoin = { name, value };
        
        if (idx >= 0) {
            coins[idx] = newCoin;
        } else {
            coins.push(newCoin);
        }
        
        await saveToServer();
        closeCoinModal();
        renderCoins();
      }

      async function deleteCoin(idx) {
        if (!confirm('למחוק?')) return;
        coins.splice(idx, 1);
        await saveToServer();
        renderCoins();
      }

      async function saveToServer() {
        await fetch('/api/settings/save', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ key: 'coins_settings', value: { coins: coins } })
        });
      }

      function esc(s) {
        return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
      }

      loadCoins();
    </script>
    """
    return _basic_web_shell("מטבעות", html_content, request=request)


@app.get("/web/messages", response_class=HTMLResponse)
def web_messages(request: Request):
    guard = _web_require_admin_teacher(request)
    if guard:
        return guard
    
    html_content = """
    <style>
      .tabs { display: flex; border-bottom: 1px solid var(--line); margin-bottom: 20px; }
      .tab { padding: 10px 20px; cursor: pointer; border-bottom: 3px solid transparent; font-weight: 600; color: var(--text-sub); }
      .tab.active { border-bottom-color: var(--primary); color: var(--text-main); }
      .tab:hover { background: rgba(0,0,0,0.02); }
      .tab-content { display: none; }
      .tab-content.active { display: block; }
      .toolbar { display: flex; gap: 10px; margin-bottom: 10px; }
      .data-table { width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
      .data-table th, .data-table td { padding: 12px; text-align: right; border-bottom: 1px solid #eee; }
      .data-table th { background: #f8f9fa; font-weight: 700; color: #555; }
      .data-table tr:hover { background: #fdfdfd; }
      .status-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-left: 5px; }
      .status-active { background: #2ecc71; }
      .status-inactive { background: #e74c3c; }
      .btn-icon { cursor: pointer; padding: 4px; border-radius: 4px; border: none; background: transparent; }
      .btn-icon:hover { background: #eee; }
      /* Modal styles */
      .modal-overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); display: none; align-items: center; justify-content: center; z-index: 1000; }
      .modal { background: #fff; padding: 20px; border-radius: 12px; width: 90%; max-width: 500px; box-shadow: 0 4px 20px rgba(0,0,0,0.2); }
      .modal h3 { margin-top: 0; }
      .form-group { margin-bottom: 15px; }
      .form-group label { display: block; margin-bottom: 5px; font-weight: 600; }
      .form-group input, .form-group textarea, .form-group select { width: 100%; padding: 8px; border: 1px solid #ddd; border-radius: 6px; box-sizing: border-box; }
      .modal-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 20px; }
    </style>

    <div class="tabs">
      <div class="tab active" onclick="switchTab('static')">הודעות רצות</div>
      <div class="tab" onclick="switchTab('threshold')">הודעות סף</div>
      <div class="tab" onclick="switchTab('news')">חדשות</div>
      <div class="tab" onclick="switchTab('ads')">פרסומות</div>
      <div class="tab" onclick="switchTab('student')">הודעות אישיות</div>
    </div>

    <!-- Static Messages -->
    <div id="tab-static" class="tab-content active">
      <div class="toolbar">
        <button class="green" onclick="openStaticModal()">+ חדש</button>
        <button class="gray" onclick="loadStatic()">רענן</button>
      </div>
      <table class="data-table">
        <thead><tr><th>הודעה</th><th>הצג תמיד</th><th>פעיל</th><th>פעולות</th></tr></thead>
        <tbody id="tbody-static"></tbody>
      </table>
    </div>

    <!-- Threshold Messages -->
    <div id="tab-threshold" class="tab-content">
      <div class="toolbar">
        <button class="green" onclick="openThresholdModal()">+ חדש</button>
        <button class="gray" onclick="loadThreshold()">רענן</button>
      </div>
      <table class="data-table">
        <thead><tr><th>הודעה</th><th>טווח ניקוד</th><th>פעיל</th><th>פעולות</th></tr></thead>
        <tbody id="tbody-threshold"></tbody>
      </table>
    </div>

    <!-- News Items -->
    <div id="tab-news" class="tab-content">
      <div class="toolbar">
        <button class="green" onclick="openNewsModal()">+ חדש</button>
        <button class="blue" onclick="openNewsSettings()">הגדרות</button>
        <button class="gray" onclick="loadNews()">רענן</button>
      </div>
      <table class="data-table">
        <thead><tr><th>טקסט</th><th>תאריכים</th><th>סדר</th><th>פעיל</th><th>פעולות</th></tr></thead>
        <tbody id="tbody-news"></tbody>
      </table>
    </div>

    <!-- Ads Items -->
    <div id="tab-ads" class="tab-content">
      <div class="toolbar">
        <button class="green" onclick="openAdsModal()">+ חדש</button>
        <button class="blue" onclick="openAdsSettings()">הגדרות</button>
        <button class="gray" onclick="loadAds()">רענן</button>
      </div>
      <table class="data-table">
        <thead><tr><th>תמונה</th><th>טקסט</th><th>תאריכים</th><th>סדר</th><th>פעיל</th><th>פעולות</th></tr></thead>
        <tbody id="tbody-ads"></tbody>
      </table>
    </div>

    <!-- Student Messages -->
    <div id="tab-student" class="tab-content">
      <div class="toolbar">
        <button class="green" onclick="openStudentMsgModal()">+ חדש</button>
        <button class="gray" onclick="loadStudentMsg()">רענן</button>
        <div style="flex-grow:1;"></div>
        <input id="search-student-msg" placeholder="חיפוש..." onkeyup="filterStudentMsg()" style="padding:6px;border-radius:6px;border:1px solid #ddd;">
      </div>
      <table class="data-table">
        <thead><tr><th>תלמיד</th><th>הודעה</th><th>נוצר</th><th>פעיל</th><th>פעולות</th></tr></thead>
        <tbody id="tbody-student"></tbody>
      </table>
    </div>

    <!-- Modals -->
    <!-- Static Modal -->
    <div id="modal-static" class="modal-overlay">
      <div class="modal">
        <h3 id="title-static">הודעה רצה</h3>
        <input type="hidden" id="static-id">
        <div class="form-group">
          <label>תוכן ההודעה</label>
          <textarea id="static-message" rows="3"></textarea>
        </div>
        <div class="form-group">
          <label><input type="checkbox" id="static-always"> הצג גם כשיש הודעות אחרות (דחיפות)</label>
        </div>
        <div class="modal-actions">
          <button class="gray" onclick="closeModal('modal-static')">ביטול</button>
          <button class="green" onclick="saveStatic()">שמירה</button>
        </div>
      </div>
    </div>

    <!-- Threshold Modal -->
    <div id="modal-threshold" class="modal-overlay">
      <div class="modal">
        <h3 id="title-threshold">הודעת סף</h3>
        <input type="hidden" id="threshold-id">
        <div class="form-group">
          <label>תוכן ההודעה</label>
          <textarea id="threshold-message" rows="3"></textarea>
        </div>
        <div class="form-group" style="display:flex; gap:10px;">
          <div style="flex:1;">
            <label>מינימום נקודות</label>
            <input type="number" id="threshold-min">
          </div>
          <div style="flex:1;">
            <label>מקסימום נקודות</label>
            <input type="number" id="threshold-max">
          </div>
        </div>
        <div class="modal-actions">
          <button class="gray" onclick="closeModal('modal-threshold')">ביטול</button>
          <button class="green" onclick="saveThreshold()">שמירה</button>
        </div>
      </div>
    </div>

    <!-- News Modal -->
    <div id="modal-news" class="modal-overlay">
      <div class="modal">
        <h3 id="title-news">ידיעה חדשותית</h3>
        <input type="hidden" id="news-id">
        <div class="form-group">
          <label>תוכן הידיעה</label>
          <textarea id="news-text" rows="3"></textarea>
        </div>
        <div class="form-group" style="display:flex; gap:10px;">
          <div style="flex:1;">
            <label>תאריך התחלה</label>
            <input type="date" id="news-start">
          </div>
          <div style="flex:1;">
            <label>תאריך סיום</label>
            <input type="date" id="news-end">
          </div>
        </div>
        <div class="modal-actions">
          <button class="gray" onclick="closeModal('modal-news')">ביטול</button>
          <button class="green" onclick="saveNews()">שמירה</button>
        </div>
      </div>
    </div>

    <!-- News Settings Modal -->
    <div id="modal-news-settings" class="modal-overlay">
      <div class="modal">
        <h3>הגדרות חדשות</h3>
        <div class="form-group">
          <label><input type="checkbox" id="ns-weekday"> הצג יום בשבוע</label>
          <label><input type="checkbox" id="ns-hebrew"> הצג תאריך עברי</label>
          <label><input type="checkbox" id="ns-parsha"> הצג פרשת שבוע</label>
          <label><input type="checkbox" id="ns-holidays"> הצג חגים ומועדים</label>
        </div>
        <div class="form-group">
          <label>מהירות גלילה</label>
          <select id="ns-speed">
            <option value="slow">איטית</option>
            <option value="normal">רגילה</option>
            <option value="fast">מהירה</option>
          </select>
        </div>
        <div class="modal-actions">
          <button class="gray" onclick="closeModal('modal-news-settings')">ביטול</button>
          <button class="green" onclick="saveNewsSettings()">שמירה</button>
        </div>
      </div>
    </div>

    <!-- Ads Modal -->
    <div id="modal-ads" class="modal-overlay">
      <div class="modal">
        <h3 id="title-ads">פרסומת / תמונה</h3>
        <input type="hidden" id="ads-id">
        <div class="form-group">
          <label>כיתוב (אופציונלי)</label>
          <input type="text" id="ads-text">
        </div>
        <div class="form-group">
          <label>תמונה</label>
          <input type="file" id="ads-file" accept="image/*">
          <div id="ads-preview" style="margin-top:5px; max-height:100px; overflow:hidden;"></div>
        </div>
        <div class="form-group" style="display:flex; gap:10px;">
          <div style="flex:1;">
            <label>תאריך התחלה</label>
            <input type="date" id="ads-start">
          </div>
          <div style="flex:1;">
            <label>תאריך סיום</label>
            <input type="date" id="ads-end">
          </div>
        </div>
        <div class="modal-actions">
          <button class="gray" onclick="closeModal('modal-ads')">ביטול</button>
          <button class="green" onclick="saveAds()">שמירה</button>
        </div>
      </div>
    </div>

    <!-- Ads Settings Modal -->
    <div id="modal-ads-settings" class="modal-overlay">
      <div class="modal">
        <h3>הגדרות פרסומות</h3>
        <div class="form-group">
          <label><input type="checkbox" id="as-enabled"> אפשר קפיצת פרסומות (Popups)</label>
        </div>
        <div class="form-group">
          <label>זמן המתנה ללא פעילות (שניות)</label>
          <input type="number" id="as-idle" min="5">
        </div>
        <div class="form-group">
          <label>משך זמן הצגת פרסומת (שניות)</label>
          <input type="number" id="as-show" step="0.5">
        </div>
        <div class="form-group">
          <label>מרווח בין פרסומות (שניות)</label>
          <input type="number" id="as-gap" step="0.5">
        </div>
        <div class="modal-actions">
          <button class="gray" onclick="closeModal('modal-ads-settings')">ביטול</button>
          <button class="green" onclick="saveAdsSettings()">שמירה</button>
        </div>
      </div>
    </div>

    <!-- Student Msg Modal -->
    <div id="modal-student" class="modal-overlay">
      <div class="modal">
        <h3 id="title-student">הודעה אישית לתלמיד</h3>
        <input type="hidden" id="student-msg-id">
        <div class="form-group" id="student-select-group">
          <label>בחר תלמיד (חפש לפי שם או ת.ז.)</label>
          <div style="display:flex; gap:5px;">
             <input id="student-search-input" placeholder="הקלד שם/ת.ז..." oninput="searchStudentsDebounced()">
             <input type="hidden" id="selected-student-id">
          </div>
          <div id="student-search-results" style="border:1px solid #ddd; max-height:150px; overflow-y:auto; display:none; position:absolute; background:#fff; width:80%; z-index:100;"></div>
          <div id="selected-student-display" style="margin-top:5px; font-weight:bold; color:var(--primary);"></div>
        </div>
        <div class="form-group">
          <label>תוכן ההודעה</label>
          <textarea id="student-message-text" rows="3"></textarea>
        </div>
        <div class="modal-actions">
          <button class="gray" onclick="closeModal('modal-student')">ביטול</button>
          <button class="green" onclick="saveStudentMsg()">שמירה</button>
        </div>
      </div>
    </div>

    <script>
      let currentTab = 'static';
      let studentSearchTimer = null;

      function switchTab(tab) {
        currentTab = tab;
        document.querySelectorAll('.tab').forEach(el => el.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
        document.querySelector(`.tab[onclick="switchTab('${tab}')"]`).classList.add('active');
        document.getElementById(`tab-${tab}`).classList.add('active');
        
        if (tab === 'static') loadStatic();
        else if (tab === 'threshold') loadThreshold();
        else if (tab === 'news') loadNews();
        else if (tab === 'ads') loadAds();
        else if (tab === 'student') loadStudentMsg();
      }

      function closeModal(id) {
        document.getElementById(id).style.display = 'none';
      }

      function esc(s) {
        return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
      }

      function formatDate(d) {
        if (!d) return '';
        try {
            return d.split('T')[0].split('-').reverse().join('.');
        } catch(e) { return d; }
      }

      // --- Static ---
      async function loadStatic() {
        const res = await fetch('/api/messages/static');
        const data = await res.json();
        const tbody = document.getElementById('tbody-static');
        tbody.innerHTML = (data.items || []).map(item => `
          <tr>
            <td>${esc(item.message)}</td>
            <td>${item.show_always ? 'V' : ''}</td>
            <td><span class="status-dot ${item.is_active ? 'status-active' : 'status-inactive'}"></span></td>
            <td>
              <button class="btn-icon" onclick='editStatic(${JSON.stringify(item)})'>✏️</button>
              <button class="btn-icon" onclick="toggleStatic(${item.id})">🔄</button>
              <button class="btn-icon" onclick="deleteStatic(${item.id})">🗑️</button>
            </td>
          </tr>
        `).join('');
      }

      function openStaticModal() {
        document.getElementById('static-id').value = '';
        document.getElementById('static-message').value = '';
        document.getElementById('static-always').checked = false;
        document.getElementById('title-static').textContent = 'הוספת הודעה רצה';
        document.getElementById('modal-static').style.display = 'flex';
      }

      function editStatic(item) {
        document.getElementById('static-id').value = item.id;
        document.getElementById('static-message').value = item.message;
        document.getElementById('static-always').checked = !!item.show_always;
        document.getElementById('title-static').textContent = 'עריכת הודעה רצה';
        document.getElementById('modal-static').style.display = 'flex';
      }

      async function saveStatic() {
        const id = document.getElementById('static-id').value;
        const msg = document.getElementById('static-message').value;
        const always = document.getElementById('static-always').checked ? 1 : 0;
        
        await fetch('/api/messages/static/save', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ message_id: id ? parseInt(id) : null, message: msg, show_always: always })
        });
        closeModal('modal-static');
        loadStatic();
      }

      async function deleteStatic(id) {
        if(!confirm('למחוק?')) return;
        await fetch('/api/messages/static/delete', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ message_id: id })
        });
        loadStatic();
      }

      async function toggleStatic(id) {
        await fetch('/api/messages/static/toggle', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ message_id: id })
        });
        loadStatic();
      }

      // --- Threshold ---
      async function loadThreshold() {
        const res = await fetch('/api/messages/threshold');
        const data = await res.json();
        document.getElementById('tbody-threshold').innerHTML = (data.items || []).map(item => `
          <tr>
            <td>${esc(item.message)}</td>
            <td>${item.min_points} - ${item.max_points}</td>
            <td><span class="status-dot ${item.is_active ? 'status-active' : 'status-inactive'}"></span></td>
            <td>
              <button class="btn-icon" onclick='editThreshold(${JSON.stringify(item)})'>✏️</button>
              <button class="btn-icon" onclick="toggleThreshold(${item.id})">🔄</button>
              <button class="btn-icon" onclick="deleteThreshold(${item.id})">🗑️</button>
            </td>
          </tr>
        `).join('');
      }

      function openThresholdModal() {
        document.getElementById('threshold-id').value = '';
        document.getElementById('threshold-message').value = '';
        document.getElementById('threshold-min').value = '0';
        document.getElementById('threshold-max').value = '1000';
        document.getElementById('title-threshold').textContent = 'הוספת הודעת סף';
        document.getElementById('modal-threshold').style.display = 'flex';
      }

      function editThreshold(item) {
        document.getElementById('threshold-id').value = item.id;
        document.getElementById('threshold-message').value = item.message;
        document.getElementById('threshold-min').value = item.min_points;
        document.getElementById('threshold-max').value = item.max_points;
        document.getElementById('title-threshold').textContent = 'עריכת הודעת סף';
        document.getElementById('modal-threshold').style.display = 'flex';
      }

      async function saveThreshold() {
        const id = document.getElementById('threshold-id').value;
        const msg = document.getElementById('threshold-message').value;
        const min = document.getElementById('threshold-min').value;
        const max = document.getElementById('threshold-max').value;
        
        await fetch('/api/messages/threshold/save', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ message_id: id ? parseInt(id) : null, message: msg, min_points: parseInt(min), max_points: parseInt(max) })
        });
        closeModal('modal-threshold');
        loadThreshold();
      }

      async function deleteThreshold(id) {
        if(!confirm('למחוק?')) return;
        await fetch('/api/messages/threshold/delete', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ message_id: id })
        });
        loadThreshold();
      }

      async function toggleThreshold(id) {
        await fetch('/api/messages/threshold/toggle', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ message_id: id })
        });
        loadThreshold();
      }

      // --- News ---
      async function loadNews() {
        const res = await fetch('/api/messages/news');
        const data = await res.json();
        const items = data.items || [];
        document.getElementById('tbody-news').innerHTML = items.map((item, idx) => `
          <tr>
            <td>${esc(item.text)}</td>
            <td>${formatDate(item.start_date)} - ${formatDate(item.end_date)}</td>
            <td>
               ${idx > 0 ? `<button class="btn-icon" onclick="reorderNews(${item.id}, 'up')">⬆️</button>` : ''}
               ${idx < items.length-1 ? `<button class="btn-icon" onclick="reorderNews(${item.id}, 'down')">⬇️</button>` : ''}
            </td>
            <td><span class="status-dot ${item.is_active ? 'status-active' : 'status-inactive'}"></span></td>
            <td>
              <button class="btn-icon" onclick='editNews(${JSON.stringify(item)})'>✏️</button>
              <button class="btn-icon" onclick="toggleNews(${item.id})">🔄</button>
              <button class="btn-icon" onclick="deleteNews(${item.id})">🗑️</button>
            </td>
          </tr>
        `).join('');
      }

      function openNewsModal() {
        document.getElementById('news-id').value = '';
        document.getElementById('news-text').value = '';
        document.getElementById('news-start').value = '';
        document.getElementById('news-end').value = '';
        document.getElementById('title-news').textContent = 'הוספת ידיעה';
        document.getElementById('modal-news').style.display = 'flex';
      }

      function editNews(item) {
        document.getElementById('news-id').value = item.id;
        document.getElementById('news-text').value = item.text;
        document.getElementById('news-start').value = item.start_date;
        document.getElementById('news-end').value = item.end_date;
        document.getElementById('title-news').textContent = 'עריכת ידיעה';
        document.getElementById('modal-news').style.display = 'flex';
      }

      async function saveNews() {
        const id = document.getElementById('news-id').value;
        const text = document.getElementById('news-text').value;
        const start = document.getElementById('news-start').value;
        const end = document.getElementById('news-end').value;
        
        await fetch('/api/messages/news/save', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ news_id: id ? parseInt(id) : null, text: text, start_date: start, end_date: end })
        });
        closeModal('modal-news');
        loadNews();
      }

      async function deleteNews(id) {
        if(!confirm('למחוק?')) return;
        await fetch('/api/messages/news/delete', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ news_id: id })
        });
        loadNews();
      }

      async function toggleNews(id) {
        await fetch('/api/messages/news/toggle', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ news_id: id })
        });
        loadNews();
      }

      async function reorderNews(id, direction) {
        await fetch('/api/messages/news/reorder', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ news_id: id, direction: direction })
        });
        loadNews();
      }

      async function openNewsSettings() {
        const res = await fetch('/api/messages/news/settings');
        const s = await res.json();
        document.getElementById('ns-weekday').checked = !!s.show_weekday;
        document.getElementById('ns-hebrew').checked = !!s.show_hebrew_date;
        document.getElementById('ns-parsha').checked = !!s.show_parsha;
        document.getElementById('ns-holidays').checked = !!s.show_holidays;
        document.getElementById('ns-speed').value = s.ticker_speed || 'normal';
        document.getElementById('modal-news-settings').style.display = 'flex';
      }

      async function saveNewsSettings() {
        const payload = {
            show_weekday: document.getElementById('ns-weekday').checked ? 1 : 0,
            show_hebrew_date: document.getElementById('ns-hebrew').checked ? 1 : 0,
            show_parsha: document.getElementById('ns-parsha').checked ? 1 : 0,
            show_holidays: document.getElementById('ns-holidays').checked ? 1 : 0,
            ticker_speed: document.getElementById('ns-speed').value
        };
        await fetch('/api/messages/news/settings', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        });
        closeModal('modal-news-settings');
      }

      // --- Ads ---
      async function loadAds() {
        const res = await fetch('/api/messages/ads');
        const data = await res.json();
        const items = data.items || [];
        document.getElementById('tbody-ads').innerHTML = items.map((item, idx) => `
          <tr>
            <td>${item.image_url ? `<img src="${item.image_url}" style="height:40px;">` : '-'}</td>
            <td>${esc(item.text)}</td>
            <td>${formatDate(item.start_date)} - ${formatDate(item.end_date)}</td>
            <td>
               ${idx > 0 ? `<button class="btn-icon" onclick="reorderAds(${item.id}, 'up')">⬆️</button>` : ''}
               ${idx < items.length-1 ? `<button class="btn-icon" onclick="reorderAds(${item.id}, 'down')">⬇️</button>` : ''}
            </td>
            <td><span class="status-dot ${item.is_active ? 'status-active' : 'status-inactive'}"></span></td>
            <td>
              <button class="btn-icon" onclick='editAds(${JSON.stringify(item).replace(/'/g, "&apos;")})'>✏️</button>
              <button class="btn-icon" onclick="toggleAds(${item.id})">🔄</button>
              <button class="btn-icon" onclick="deleteAds(${item.id})">🗑️</button>
            </td>
          </tr>
        `).join('');
      }

      function openAdsModal() {
        document.getElementById('ads-id').value = '';
        document.getElementById('ads-text').value = '';
        document.getElementById('ads-start').value = '';
        document.getElementById('ads-end').value = '';
        document.getElementById('ads-file').value = '';
        document.getElementById('ads-preview').innerHTML = '';
        document.getElementById('title-ads').textContent = 'הוספת פרסומת';
        document.getElementById('modal-ads').style.display = 'flex';
      }

      function editAds(item) {
        document.getElementById('ads-id').value = item.id;
        document.getElementById('ads-text').value = item.text;
        document.getElementById('ads-start').value = item.start_date;
        document.getElementById('ads-end').value = item.end_date;
        document.getElementById('ads-file').value = '';
        document.getElementById('ads-preview').innerHTML = item.image_url ? `<img src="${item.image_url}" style="height:100px;">` : '';
        document.getElementById('title-ads').textContent = 'עריכת פרסומת';
        document.getElementById('modal-ads').style.display = 'flex';
      }

      async function saveAds() {
        const id = document.getElementById('ads-id').value;
        const text = document.getElementById('ads-text').value;
        const start = document.getElementById('ads-start').value;
        const end = document.getElementById('ads-end').value;
        const fileInput = document.getElementById('ads-file');
        
        const formData = new FormData();
        if (id) formData.append('ads_id', id);
        formData.append('text', text);
        formData.append('start_date', start);
        formData.append('end_date', end);
        if (fileInput.files[0]) {
            formData.append('image', fileInput.files[0]);
        }

        await fetch('/api/messages/ads/save', {
            method: 'POST',
            body: formData
        });
        closeModal('modal-ads');
        loadAds();
      }

      async function deleteAds(id) {
        if(!confirm('למחוק?')) return;
        await fetch('/api/messages/ads/delete', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ ads_id: id })
        });
        loadAds();
      }

      async function toggleAds(id) {
        await fetch('/api/messages/ads/toggle', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ ads_id: id })
        });
        loadAds();
      }

      async function reorderAds(id, direction) {
        await fetch('/api/messages/ads/reorder', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ ads_id: id, direction: direction })
        });
        loadAds();
      }

      async function openAdsSettings() {
        const res = await fetch('/api/messages/ads/settings');
        const s = await res.json();
        document.getElementById('as-enabled').checked = !!s.popup_enabled;
        document.getElementById('as-idle').value = s.popup_idle_sec || 60;
        document.getElementById('as-show').value = s.popup_show_sec || 10;
        document.getElementById('as-gap').value = s.popup_gap_sec || 30;
        document.getElementById('modal-ads-settings').style.display = 'flex';
      }

      async function saveAdsSettings() {
        const payload = {
            popup_enabled: document.getElementById('as-enabled').checked ? 1 : 0,
            popup_idle_sec: parseInt(document.getElementById('as-idle').value),
            popup_show_sec: parseFloat(document.getElementById('as-show').value),
            popup_gap_sec: parseFloat(document.getElementById('as-gap').value)
        };
        await fetch('/api/messages/ads/settings', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        });
        closeModal('modal-ads-settings');
      }

      // --- Student Msg ---
      async function loadStudentMsg() {
        const res = await fetch('/api/messages/student');
        const data = await res.json();
        const items = data.items || [];
        document.getElementById('tbody-student').innerHTML = items.map(item => `
          <tr>
            <td>${esc(item.first_name)} ${esc(item.last_name)} (${esc(item.class_name)})</td>
            <td>${esc(item.message)}</td>
            <td>${formatDate(item.created_at)}</td>
            <td><span class="status-dot ${item.is_active ? 'status-active' : 'status-inactive'}"></span></td>
            <td>
              <button class="btn-icon" onclick='editStudentMsg(${JSON.stringify(item)})'>✏️</button>
              <button class="btn-icon" onclick="toggleStudentMsg(${item.id})">🔄</button>
              <button class="btn-icon" onclick="deleteStudentMsg(${item.id})">🗑️</button>
            </td>
          </tr>
        `).join('');
      }

      function searchStudentsDebounced() {
        clearTimeout(studentSearchTimer);
        studentSearchTimer = setTimeout(searchStudents, 300);
      }

      async function searchStudents() {
        const q = document.getElementById('student-search-input').value;
        if (q.length < 2) {
            document.getElementById('student-search-results').style.display = 'none';
            return;
        }
        const res = await fetch(`/api/students?q=${encodeURIComponent(q)}&limit=10&offset=0`);
        const data = await res.json();
        const results = document.getElementById('student-search-results');
        results.innerHTML = (data.items || []).map(s => `
            <div onclick="selectStudent(${s.id}, '${esc(s.first_name)} ${esc(s.last_name)}')" style="padding:8px; border-bottom:1px solid #eee; cursor:pointer;">
                ${esc(s.first_name)} ${esc(s.last_name)} - ${esc(s.class_name)} (ת.ז. ${esc(s.id_number)})
            </div>
        `).join('');
        results.style.display = 'block';
      }

      function selectStudent(id, name) {
        document.getElementById('selected-student-id').value = id;
        document.getElementById('selected-student-display').textContent = 'נבחר: ' + name;
        document.getElementById('student-search-results').style.display = 'none';
        document.getElementById('student-search-input').value = '';
      }

      function openStudentMsgModal() {
        document.getElementById('student-msg-id').value = '';
        document.getElementById('selected-student-id').value = '';
        document.getElementById('selected-student-display').textContent = '';
        document.getElementById('student-message-text').value = '';
        document.getElementById('student-select-group').style.display = 'block'; // Show student selector
        document.getElementById('title-student').textContent = 'הודעה חדשה לתלמיד';
        document.getElementById('modal-student').style.display = 'flex';
      }

      function editStudentMsg(item) {
        document.getElementById('student-msg-id').value = item.id;
        document.getElementById('selected-student-id').value = item.student_id;
        document.getElementById('selected-student-display').textContent = `נבחר: ${item.first_name} ${item.last_name}`;
        document.getElementById('student-message-text').value = item.message;
        // Hide student selector on edit? Or allow changing? Usually msg is specific to student.
        // Let's allow changing but show current.
        document.getElementById('title-student').textContent = 'עריכת הודעה';
        document.getElementById('modal-student').style.display = 'flex';
      }

      async function saveStudentMsg() {
        const id = document.getElementById('student-msg-id').value;
        const sid = document.getElementById('selected-student-id').value;
        const msg = document.getElementById('student-message-text').value;
        
        if (!sid && !id) {
            alert('אנא בחר תלמיד');
            return;
        }

        await fetch('/api/messages/student/save', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ message_id: id ? parseInt(id) : null, student_id: parseInt(sid), message: msg })
        });
        closeModal('modal-student');
        loadStudentMsg();
      }

      async function deleteStudentMsg(id) {
        if(!confirm('למחוק?')) return;
        await fetch('/api/messages/student/delete', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ message_id: id })
        });
        loadStudentMsg();
      }

      async function toggleStudentMsg(id) {
        await fetch('/api/messages/student/toggle', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ message_id: id })
        });
        loadStudentMsg();
      }

      // Initial load
      switchTab('static');
    </script>
    """
    return _basic_web_shell("ניהול הודעות", html_content, request=request)


@app.get("/web/holidays", response_class=HTMLResponse)
def web_holidays(request: Request):
    guard = _web_require_admin_teacher(request)
    if guard:
        return guard
    
    html_content = """
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px;">
      <h2>חגים וחופשות</h2>
      <button class="green" onclick="openHolidayModal()">+ חג חדש</button>
    </div>
    
    <div class="card" style="padding:0; overflow:hidden;">
      <table style="width:100%; border-collapse:collapse;">
        <thead>
          <tr style="background:#f8f9fa; border-bottom:1px solid #eee;">
            <th style="padding:12px; text-align:right;">שם החג</th>
            <th style="padding:12px; text-align:right;">תאריך התחלה</th>
            <th style="padding:12px; text-align:right;">תאריך סיום</th>
            <th style="padding:12px; text-align:right;">פעולות</th>
          </tr>
        </thead>
        <tbody id="holidays-list"></tbody>
      </table>
    </div>

    <!-- Modal -->
    <div id="modal-holiday" class="modal-overlay" style="display:none; position:fixed; top:0; left:0; right:0; bottom:0; background:rgba(0,0,0,0.5); align-items:center; justify-content:center; z-index:1000;">
      <div class="modal" style="background:#fff; padding:24px; border-radius:12px; width:90%; max-width:400px; box-shadow:0 4px 20px rgba(0,0,0,0.2);">
        <h3 id="modal-title" style="margin-top:0;">חג / חופשה</h3>
        <input type="hidden" id="holiday-index">
        <div class="form-group" style="margin-bottom:15px;">
          <label style="display:block; margin-bottom:5px; font-weight:600;">שם החג</label>
          <input id="holiday-name" style="width:100%; padding:8px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box;">
        </div>
        <div class="form-group" style="margin-bottom:15px;">
          <label style="display:block; margin-bottom:5px; font-weight:600;">תאריך התחלה</label>
          <input type="date" id="holiday-start" style="width:100%; padding:8px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box;">
        </div>
        <div class="form-group" style="margin-bottom:15px;">
          <label style="display:block; margin-bottom:5px; font-weight:600;">תאריך סיום</label>
          <input type="date" id="holiday-end" style="width:100%; padding:8px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box;">
        </div>
        <div style="display:flex; justify-content:flex-end; gap:10px; margin-top:20px;">
          <button class="gray" onclick="closeHolidayModal()" style="padding:8px 16px; border:none; border-radius:6px; cursor:pointer;">ביטול</button>
          <button class="green" onclick="saveHoliday()" style="padding:8px 16px; background:#2ecc71; color:white; border:none; border-radius:6px; font-weight:600; cursor:pointer;">שמירה</button>
        </div>
      </div>
    </div>

    <script>
      let holidays = [];

      async function loadHolidays() {
        try {
          const res = await fetch('/api/settings/holidays');
          const data = await res.json();
          holidays = Array.isArray(data.items) ? data.items : [];
          renderHolidays();
        } catch(e) {
          console.error(e);
        }
      }

      function renderHolidays() {
        const tbody = document.getElementById('holidays-list');
        if (holidays.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" style="padding:20px; text-align:center; color:#888;">אין חגים מוגדרים</td></tr>';
            return;
        }
        tbody.innerHTML = holidays.map((h, idx) => `
          <tr style="border-bottom:1px solid #eee; hover:background:#fdfdfd;">
            <td style="padding:12px;">${esc(h.name)}</td>
            <td style="padding:12px;">${formatDate(h.start_date)}</td>
            <td style="padding:12px;">${formatDate(h.end_date)}</td>
            <td style="padding:12px;">
              <button onclick="editHoliday(${idx})" style="background:none; border:none; cursor:pointer; font-size:16px;">✏️</button>
              <button onclick="deleteHoliday(${idx})" style="background:none; border:none; cursor:pointer; font-size:16px;">🗑️</button>
            </td>
          </tr>
        `).join('');
      }

      function formatDate(d) {
        if (!d) return '';
        try { return d.split('T')[0].split('-').reverse().join('.'); } catch(e) { return d; }
      }

      function openHolidayModal() {
        document.getElementById('holiday-index').value = '-1';
        document.getElementById('holiday-name').value = '';
        document.getElementById('holiday-start').value = '';
        document.getElementById('holiday-end').value = '';
        document.getElementById('modal-title').textContent = 'הוספת חג';
        document.getElementById('modal-holiday').style.display = 'flex';
      }

      function closeHolidayModal() {
        document.getElementById('modal-holiday').style.display = 'none';
      }

      function editHoliday(idx) {
        const h = holidays[idx];
        document.getElementById('holiday-index').value = idx;
        document.getElementById('holiday-name').value = h.name || '';
        document.getElementById('holiday-start').value = h.start_date || '';
        document.getElementById('holiday-end').value = h.end_date || '';
        document.getElementById('modal-title').textContent = 'עריכת חג';
        document.getElementById('modal-holiday').style.display = 'flex';
      }

      async function saveHoliday() {
        const idx = parseInt(document.getElementById('holiday-index').value);
        const name = document.getElementById('holiday-name').value.trim();
        const start = document.getElementById('holiday-start').value;
        const end = document.getElementById('holiday-end').value;
        
        if (!name) return alert('נא להזין שם');

        const newHoliday = { name, start_date: start, end_date: end };
        
        if (idx >= 0) {
            holidays[idx] = newHoliday;
        } else {
            holidays.push(newHoliday);
        }
        
        await saveToServer();
        closeHolidayModal();
        renderHolidays();
      }

      async function deleteHoliday(idx) {
        if (!confirm('למחוק חג זה?')) return;
        holidays.splice(idx, 1);
        await saveToServer();
        renderHolidays();
      }

      async function saveToServer() {
        await fetch('/api/settings/save', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ key: 'holidays', value: { items: holidays } })
        });
      }

      function esc(s) {
        return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
      }

      loadHolidays();
    </script>
    """
    return _basic_web_shell("חגים וחופשות", html_content, request=request)


@app.get("/web/upgrades", response_class=HTMLResponse)
def web_upgrades(request: Request):
    guard = _web_require_admin_teacher(request)
    if guard:
        return guard
    
    html_content = """
    <h2>הגדרות שדרוגים</h2>
    
    <div class="card" style="padding:20px; background:#fff; border-radius:10px; border:1px solid #eee;">
      <div class="form-group" style="margin-bottom:15px;">
        <label class="ck" style="display:flex; align-items:center; gap:8px; font-weight:600;">
          <input type="checkbox" id="upg-auto" style="width:18px; height:18px;"> עדכון אוטומטי
        </label>
      </div>
      <div class="form-group" style="margin-bottom:15px;">
        <label style="display:block; margin-bottom:5px; font-weight:600;">ערוץ עדכון</label>
        <select id="upg-channel" style="width:100%; padding:10px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box;">
          <option value="stable">יציב (Stable)</option>
          <option value="beta">בטא (Beta)</option>
          <option value="dev">פיתוח (Dev)</option>
        </select>
      </div>
      <div>
        <button class="green" onclick="saveUpgrades()" style="padding:10px 20px; border-radius:6px; border:none; background:#2ecc71; color:white; font-weight:bold; cursor:pointer;">שמירה</button>
      </div>
    </div>

    <script>
      async function loadUpgrades() {
        try {
          const res = await fetch('/api/settings/upgrades_settings');
          const data = await res.json();
          document.getElementById('upg-auto').checked = !!data.auto_update;
          document.getElementById('upg-channel').value = data.channel || 'stable';
        } catch(e) {}
      }

      async function saveUpgrades() {
        const payload = {
            auto_update: document.getElementById('upg-auto').checked,
            channel: document.getElementById('upg-channel').value
        };
        await fetch('/api/settings/save', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ key: 'upgrades_settings', value: payload })
        });
        alert('נשמר בהצלחה');
      }

      loadUpgrades();
    </script>
    """
    return _basic_web_shell("שדרוגים", html_content, request=request)


@app.get("/web/special-bonus", response_class=HTMLResponse)
def web_special_bonus(request: Request):
    guard = _web_require_admin_teacher(request)
    if guard:
        return guard
    
    html_content = """
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px;">
      <h2>בונוס מיוחד</h2>
      <button class="green" onclick="openItemModal()">+ פריט חדש</button>
    </div>
    
    <div class="card" style="padding:0; overflow:hidden;">
      <table style="width:100%; border-collapse:collapse;">
        <thead>
          <tr style="background:#f8f9fa; border-bottom:1px solid #eee;">
            <th style="padding:12px; text-align:right;">תיאור</th>
            <th style="padding:12px; text-align:right;">ניקוד</th>
            <th style="padding:12px; text-align:right;">פעולות</th>
          </tr>
        </thead>
        <tbody id="items-list"></tbody>
      </table>
    </div>

    <!-- Modal -->
    <div id="modal-item" class="modal-overlay" style="display:none; position:fixed; top:0; left:0; right:0; bottom:0; background:rgba(0,0,0,0.5); align-items:center; justify-content:center; z-index:1000;">
      <div class="modal" style="background:#fff; padding:24px; border-radius:12px; width:90%; max-width:400px; box-shadow:0 4px 20px rgba(0,0,0,0.2);">
        <h3 id="modal-title" style="margin-top:0;">פריט בונוס</h3>
        <input type="hidden" id="item-index">
        <div class="form-group" style="margin-bottom:15px;">
          <label style="display:block; margin-bottom:5px; font-weight:600;">תיאור</label>
          <input id="item-name" style="width:100%; padding:8px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box;">
        </div>
        <div class="form-group" style="margin-bottom:15px;">
          <label style="display:block; margin-bottom:5px; font-weight:600;">ניקוד</label>
          <input type="number" id="item-points" style="width:100%; padding:8px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box;">
        </div>
        <div style="display:flex; justify-content:flex-end; gap:10px; margin-top:20px;">
          <button class="gray" onclick="closeItemModal()" style="padding:8px 16px; border:none; border-radius:6px; cursor:pointer;">ביטול</button>
          <button class="green" onclick="saveItem()" style="padding:8px 16px; background:#2ecc71; color:white; border:none; border-radius:6px; font-weight:600; cursor:pointer;">שמירה</button>
        </div>
      </div>
    </div>

    <script>
      let items = [];

      async function loadItems() {
        try {
          const res = await fetch('/api/settings/special_bonus');
          const data = await res.json();
          items = Array.isArray(data.items) ? data.items : [];
          renderItems();
        } catch(e) {}
      }

      function renderItems() {
        const tbody = document.getElementById('items-list');
        if (items.length === 0) {
            tbody.innerHTML = '<tr><td colspan="3" style="padding:20px; text-align:center; color:#888;">אין פריטים</td></tr>';
            return;
        }
        tbody.innerHTML = items.map((b, idx) => `
          <tr style="border-bottom:1px solid #eee; hover:background:#fdfdfd;">
            <td style="padding:12px;">${esc(b.name)}</td>
            <td style="padding:12px;">${b.points}</td>
            <td style="padding:12px;">
              <button onclick="editItem(${idx})" style="background:none; border:none; cursor:pointer; font-size:16px;">✏️</button>
              <button onclick="deleteItem(${idx})" style="background:none; border:none; cursor:pointer; font-size:16px;">🗑️</button>
            </td>
          </tr>
        `).join('');
      }

      function openItemModal() {
        document.getElementById('item-index').value = '-1';
        document.getElementById('item-name').value = '';
        document.getElementById('item-points').value = '';
        document.getElementById('modal-title').textContent = 'הוספת פריט';
        document.getElementById('modal-item').style.display = 'flex';
      }

      function closeItemModal() {
        document.getElementById('modal-item').style.display = 'none';
      }

      function editItem(idx) {
        const b = items[idx];
        document.getElementById('item-index').value = idx;
        document.getElementById('item-name').value = b.name || '';
        document.getElementById('item-points').value = b.points || 0;
        document.getElementById('modal-title').textContent = 'עריכת פריט';
        document.getElementById('modal-item').style.display = 'flex';
      }

      async function saveItem() {
        const idx = parseInt(document.getElementById('item-index').value);
        const name = document.getElementById('item-name').value.trim();
        const points = parseInt(document.getElementById('item-points').value) || 0;
        
        if (!name) return alert('נא להזין שם');

        const newItem = { name, points };
        
        if (idx >= 0) {
            items[idx] = newItem;
        } else {
            items.push(newItem);
        }
        
        await saveToServer();
        closeItemModal();
        renderItems();
      }

      async function deleteItem(idx) {
        if (!confirm('למחוק?')) return;
        items.splice(idx, 1);
        await saveToServer();
        renderItems();
      }

      async function saveToServer() {
        await fetch('/api/settings/save', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ key: 'special_bonus', value: { items: items } })
        });
      }

      function esc(s) {
        return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
      }

      loadItems();
    </script>
    """
    return _basic_web_shell("בונוס מיוחד", html_content, request=request)


@app.get("/web/time-bonus", response_class=HTMLResponse)
def web_time_bonus(request: Request):
    guard = _web_require_admin_teacher(request)
    if guard:
        return guard
    
    html_content = """
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px;">
      <h2>בונוס זמנים</h2>
      <button class="green" onclick="openRuleModal()">+ כלל חדש</button>
    </div>
    
    <div class="card" style="padding:0; overflow:hidden;">
      <table style="width:100%; border-collapse:collapse;">
        <thead>
          <tr style="background:#f8f9fa; border-bottom:1px solid #eee;">
            <th style="padding:12px; text-align:right;">שם הכלל</th>
            <th style="padding:12px; text-align:right;">שעות</th>
            <th style="padding:12px; text-align:right;">בונוס (נקודות)</th>
            <th style="padding:12px; text-align:right;">פעולות</th>
          </tr>
        </thead>
        <tbody id="rules-list"></tbody>
      </table>
    </div>

    <!-- Modal -->
    <div id="modal-rule" class="modal-overlay" style="display:none; position:fixed; top:0; left:0; right:0; bottom:0; background:rgba(0,0,0,0.5); align-items:center; justify-content:center; z-index:1000;">
      <div class="modal" style="background:#fff; padding:24px; border-radius:12px; width:90%; max-width:450px; box-shadow:0 4px 20px rgba(0,0,0,0.2);">
        <h3 id="modal-title" style="margin-top:0;">כלל בונוס זמן</h3>
        <input type="hidden" id="rule-index">
        <div class="form-group" style="margin-bottom:15px;">
          <label style="display:block; margin-bottom:5px; font-weight:600;">שם הכלל (לדוגמה: שחרית)</label>
          <input id="rule-name" style="width:100%; padding:8px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box;">
        </div>
        <div style="display:flex; gap:10px; margin-bottom:15px;">
            <div style="flex:1;">
                <label style="display:block; margin-bottom:5px; font-weight:600;">התחלה</label>
                <input type="time" id="rule-start" style="width:100%; padding:8px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box;">
            </div>
            <div style="flex:1;">
                <label style="display:block; margin-bottom:5px; font-weight:600;">סיום</label>
                <input type="time" id="rule-end" style="width:100%; padding:8px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box;">
            </div>
        </div>
        <div class="form-group" style="margin-bottom:15px;">
          <label style="display:block; margin-bottom:5px; font-weight:600;">תוספת נקודות</label>
          <input type="number" id="rule-points" style="width:100%; padding:8px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box;">
        </div>
        <div style="display:flex; justify-content:flex-end; gap:10px; margin-top:20px;">
          <button class="gray" onclick="closeRuleModal()" style="padding:8px 16px; border:none; border-radius:6px; cursor:pointer;">ביטול</button>
          <button class="green" onclick="saveRule()" style="padding:8px 16px; background:#2ecc71; color:white; border:none; border-radius:6px; font-weight:600; cursor:pointer;">שמירה</button>
        </div>
      </div>
    </div>

    <script>
      let rules = [];

      async function loadRules() {
        try {
          const res = await fetch('/api/settings/time_bonus');
          const data = await res.json();
          rules = Array.isArray(data.rules) ? data.rules : [];
          renderRules();
        } catch(e) {}
      }

      function renderRules() {
        const tbody = document.getElementById('rules-list');
        if (rules.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" style="padding:20px; text-align:center; color:#888;">אין כללים מוגדרים</td></tr>';
            return;
        }
        tbody.innerHTML = rules.map((r, idx) => `
          <tr style="border-bottom:1px solid #eee; hover:background:#fdfdfd;">
            <td style="padding:12px;">${esc(r.name)}</td>
            <td style="padding:12px; direction:ltr; text-align:right;">${r.start_time} - ${r.end_time}</td>
            <td style="padding:12px;">${r.points}</td>
            <td style="padding:12px;">
              <button onclick="editRule(${idx})" style="background:none; border:none; cursor:pointer; font-size:16px;">✏️</button>
              <button onclick="deleteRule(${idx})" style="background:none; border:none; cursor:pointer; font-size:16px;">🗑️</button>
            </td>
          </tr>
        `).join('');
      }

      function openRuleModal() {
        document.getElementById('rule-index').value = '-1';
        document.getElementById('rule-name').value = '';
        document.getElementById('rule-start').value = '';
        document.getElementById('rule-end').value = '';
        document.getElementById('rule-points').value = '';
        document.getElementById('modal-title').textContent = 'הוספת כלל';
        document.getElementById('modal-rule').style.display = 'flex';
      }

      function closeRuleModal() {
        document.getElementById('modal-rule').style.display = 'none';
      }

      function editRule(idx) {
        const r = rules[idx];
        document.getElementById('rule-index').value = idx;
        document.getElementById('rule-name').value = r.name || '';
        document.getElementById('rule-start').value = r.start_time || '';
        document.getElementById('rule-end').value = r.end_time || '';
        document.getElementById('rule-points').value = r.points || 0;
        document.getElementById('modal-title').textContent = 'עריכת כלל';
        document.getElementById('modal-rule').style.display = 'flex';
      }

      async function saveRule() {
        const idx = parseInt(document.getElementById('rule-index').value);
        const name = document.getElementById('rule-name').value.trim();
        const start = document.getElementById('rule-start').value;
        const end = document.getElementById('rule-end').value;
        const points = parseInt(document.getElementById('rule-points').value) || 0;
        
        if (!name) return alert('נא להזין שם');

        const newRule = { name, start_time: start, end_time: end, points };
        
        if (idx >= 0) {
            rules[idx] = newRule;
        } else {
            rules.push(newRule);
        }
        
        await saveToServer();
        closeRuleModal();
        renderRules();
      }

      async function deleteRule(idx) {
        if (!confirm('למחוק?')) return;
        rules.splice(idx, 1);
        await saveToServer();
        renderRules();
      }

      async function saveToServer() {
        await fetch('/api/settings/save', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ key: 'time_bonus', value: { rules: rules } })
        });
      }

      function esc(s) {
        return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
      }

      loadRules();
    </script>
    """
    return _basic_web_shell("בונוס זמנים", html_content, request=request)


@app.get("/web/cashier", response_class=HTMLResponse)
def web_cashier(request: Request):
    guard = _web_require_admin_teacher(request)
    if guard:
        return guard
    
    html_content = """
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px;">
      <h2>עמדת קופה</h2>
      <button class="green" onclick="openItemModal()">+ פריט קופה חדש</button>
    </div>
    
    <div class="card" style="padding:20px; background:#fff; border-radius:10px; border:1px solid #eee; margin-bottom:20px;">
      <label class="ck" style="display:flex; align-items:center; gap:8px; font-weight:600;">
        <input type="checkbox" id="cashier-enabled" style="width:18px; height:18px;" onchange="saveToServer()"> קופה פעילה
      </label>
    </div>

    <div class="card" style="padding:0; overflow:hidden;">
      <table style="width:100%; border-collapse:collapse;">
        <thead>
          <tr style="background:#f8f9fa; border-bottom:1px solid #eee;">
            <th style="padding:12px; text-align:right;">שם הפריט</th>
            <th style="padding:12px; text-align:right;">מחיר (נקודות)</th>
            <th style="padding:12px; text-align:right;">פעולות</th>
          </tr>
        </thead>
        <tbody id="items-list"></tbody>
      </table>
    </div>

    <!-- Modal -->
    <div id="modal-item" class="modal-overlay" style="display:none; position:fixed; top:0; left:0; right:0; bottom:0; background:rgba(0,0,0,0.5); align-items:center; justify-content:center; z-index:1000;">
      <div class="modal" style="background:#fff; padding:24px; border-radius:12px; width:90%; max-width:400px; box-shadow:0 4px 20px rgba(0,0,0,0.2);">
        <h3 id="modal-title" style="margin-top:0;">פריט קופה</h3>
        <input type="hidden" id="item-index">
        <div class="form-group" style="margin-bottom:15px;">
          <label style="display:block; margin-bottom:5px; font-weight:600;">שם הפריט</label>
          <input id="item-name" style="width:100%; padding:8px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box;">
        </div>
        <div class="form-group" style="margin-bottom:15px;">
          <label style="display:block; margin-bottom:5px; font-weight:600;">מחיר בנקודות</label>
          <input type="number" id="item-price" style="width:100%; padding:8px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box;">
        </div>
        <div style="display:flex; justify-content:flex-end; gap:10px; margin-top:20px;">
          <button class="gray" onclick="closeItemModal()" style="padding:8px 16px; border:none; border-radius:6px; cursor:pointer;">ביטול</button>
          <button class="green" onclick="saveItem()" style="padding:8px 16px; background:#2ecc71; color:white; border:none; border-radius:6px; font-weight:600; cursor:pointer;">שמירה</button>
        </div>
      </div>
    </div>

    <script>
      let items = [];
      let enabled = true;

      async function loadItems() {
        try {
          const res = await fetch('/api/settings/cashier_settings');
          const data = await res.json();
          items = Array.isArray(data.items) ? data.items : [];
          enabled = !!data.enabled;
          document.getElementById('cashier-enabled').checked = enabled;
          renderItems();
        } catch(e) {}
      }

      function renderItems() {
        const tbody = document.getElementById('items-list');
        if (items.length === 0) {
            tbody.innerHTML = '<tr><td colspan="3" style="padding:20px; text-align:center; color:#888;">אין פריטים</td></tr>';
            return;
        }
        tbody.innerHTML = items.map((b, idx) => `
          <tr style="border-bottom:1px solid #eee; hover:background:#fdfdfd;">
            <td style="padding:12px;">${esc(b.name)}</td>
            <td style="padding:12px;">${b.price || 0}</td>
            <td style="padding:12px;">
              <button onclick="editItem(${idx})" style="background:none; border:none; cursor:pointer; font-size:16px;">✏️</button>
              <button onclick="deleteItem(${idx})" style="background:none; border:none; cursor:pointer; font-size:16px;">🗑️</button>
            </td>
          </tr>
        `).join('');
      }

      function openItemModal() {
        document.getElementById('item-index').value = '-1';
        document.getElementById('item-name').value = '';
        document.getElementById('item-price').value = '';
        document.getElementById('modal-title').textContent = 'הוספת פריט';
        document.getElementById('modal-item').style.display = 'flex';
      }

      function closeItemModal() {
        document.getElementById('modal-item').style.display = 'none';
      }

      function editItem(idx) {
        const b = items[idx];
        document.getElementById('item-index').value = idx;
        document.getElementById('item-name').value = b.name || '';
        document.getElementById('item-price').value = b.price || 0;
        document.getElementById('modal-title').textContent = 'עריכת פריט';
        document.getElementById('modal-item').style.display = 'flex';
      }

      async function saveItem() {
        const idx = parseInt(document.getElementById('item-index').value);
        const name = document.getElementById('item-name').value.trim();
        const price = parseInt(document.getElementById('item-price').value) || 0;
        
        if (!name) return alert('נא להזין שם');

        const newItem = { name, price };
        
        if (idx >= 0) {
            items[idx] = newItem;
        } else {
            items.push(newItem);
        }
        
        await saveToServer();
        closeItemModal();
        renderItems();
      }

      async function deleteItem(idx) {
        if (!confirm('למחוק?')) return;
        items.splice(idx, 1);
        await saveToServer();
        renderItems();
      }

      async function saveToServer() {
        const en = document.getElementById('cashier-enabled').checked;
        await fetch('/api/settings/save', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ key: 'cashier_settings', value: { enabled: en, items: items } })
        });
      }

      function esc(s) {
        return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
      }

      loadItems();
    </script>
    """
    return _basic_web_shell("עמדת קופה", html_content, request=request)


@app.get("/web/reports", response_class=HTMLResponse)
def web_reports(request: Request):
    guard = _web_require_admin_teacher(request)
    if guard:
        return guard
    
    html_content = """
    <h2>דוחות</h2>
    
    <div class="card" style="padding:20px; background:#fff; border-radius:10px; border:1px solid #eee; margin-bottom:20px;">
      <h3 style="margin-top:0;">ייצוא נתונים</h3>
      <p style="color:#666;">הורדת רשימת התלמידים והניקוד שלהם לקובץ CSV (אקסל).</p>
      <a href="/web/export/download" target="_blank" style="text-decoration:none;">
        <button class="blue" style="padding:10px 20px; border-radius:6px; border:none; background:#3498db; color:white; font-weight:bold; cursor:pointer;">⬇️ ייצוא תלמידים (CSV)</button>
      </a>
    </div>

    <div class="card" style="padding:20px; background:#fff; border-radius:10px; border:1px solid #eee;">
      <h3 style="margin-top:0;">הגדרות דוחות</h3>
      <div style="margin-bottom:15px;">
        <label class="ck" style="display:flex; align-items:center; gap:8px; font-weight:600;">
          <input type="checkbox" id="rep-enabled" style="width:18px; height:18px;"> אפשר דוחות
        </label>
      </div>
      <div>
        <button class="green" onclick="saveReports()" style="padding:10px 20px; border-radius:6px; border:none; background:#2ecc71; color:white; font-weight:bold; cursor:pointer;">שמירה</button>
      </div>
    </div>

    <script>
      async function loadReports() {
        try {
          const res = await fetch('/api/settings/reports_settings');
          const data = await res.json();
          document.getElementById('rep-enabled').checked = !!data.enabled;
        } catch(e) {}
      }

      async function saveReports() {
        const enabled = document.getElementById('rep-enabled').checked;
        await fetch('/api/settings/save', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ key: 'reports_settings', value: { enabled: enabled } })
        });
        alert('נשמר בהצלחה');
      }

      loadReports();
    </script>
    """
    return _basic_web_shell("דוחות", html_content, request=request)


@app.get("/web/logs", response_class=HTMLResponse)
def web_logs(request: Request):
    guard = _web_require_admin_teacher(request)
    if guard:
        return guard
    
    html_content = """
    <h2>הגדרות לוגים</h2>
    
    <div class="card" style="padding:20px; background:#fff; border-radius:10px; border:1px solid #eee;">
      <h3 style="margin-top:0;">שמירת היסטוריה</h3>
      <div style="margin-bottom:15px;">
        <label style="display:block; margin-bottom:5px; font-weight:600;">מספר ימים לשמירת לוגים</label>
        <input type="number" id="log-retention" style="width:100%; max-width:200px; padding:10px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box;">
      </div>
      <div>
        <button class="green" onclick="saveLogs()" style="padding:10px 20px; border-radius:6px; border:none; background:#2ecc71; color:white; font-weight:bold; cursor:pointer;">שמירה</button>
      </div>
    </div>

    <script>
      async function loadLogs() {
        try {
          const res = await fetch('/api/settings/log_settings');
          const data = await res.json();
          document.getElementById('log-retention').value = data.retention_days || 30;
        } catch(e) {}
      }

      async function saveLogs() {
        const days = parseInt(document.getElementById('log-retention').value) || 30;
        await fetch('/api/settings/save', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ key: 'log_settings', value: { retention_days: days } })
        });
        alert('נשמר בהצלחה');
      }

      loadLogs();
    </script>
    """
    return _basic_web_shell("לוגים", html_content, request=request)


@app.get("/admin", response_class=HTMLResponse)
def admin_index(request: Request, admin_key: str = '') -> str:
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
            <a href="/admin/registrations" style="color:#e67e22; font-weight:bold;">בקשות הרשמה</a>
            <a href="/admin/logout">יציאה</a>
            <a href="/web/admin">עמדת ניהול ווב</a>
          </div>
        </div>
      </div>
    </body>
    </html>
    """


def _super_admin_shell(title: str, body: str, request: Request = None) -> str:
    nav_links = [
        {"href": "/admin/dashboard", "label": "דשבורד"},
        {"href": "/admin/institutions", "label": "ניהול מוסדות"},
        {"href": "/admin/setup", "label": "הקמת מוסד"},
        {"href": "/admin/global-settings", "label": "הגדרות שרת"},
        {"href": "/admin/logout", "label": "יציאה", "class": "red"},
    ]
    
    nav_html = ""
    for link in nav_links:
        cls = link.get("class", "")
        style = "color:#e74c3c;" if cls == "red" else ""
        nav_html += f'<a href="{link["href"]}" class="{cls}" style="{style}">{link["label"]}</a>'

    return f"""
    <!doctype html>
    <html lang="he" dir="rtl">
    <head>
      <meta charset="utf-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      <title>{title} - ניהול על</title>
      <style>
        :root {{ --primary: #2c3e50; --secondary: #34495e; --accent: #3498db; --bg: #f8f9fa; --card: #ffffff; --text: #2c3e50; --border: #dfe6e9; }}
        body {{ margin: 0; font-family: 'Segoe UI', system-ui, sans-serif; background: var(--bg); color: var(--text); }}
        .layout {{ display: flex; min-height: 100vh; }}
        .sidebar {{ width: 240px; background: var(--primary); color: white; display: flex; flex-direction: column; padding: 20px 0; }}
        .sidebar-header {{ padding: 0 20px 20px; border-bottom: 1px solid rgba(255,255,255,0.1); margin-bottom: 10px; }}
        .sidebar-header h1 {{ margin: 0; font-size: 20px; font-weight: 600; }}
        .nav {{ display: flex; flex-direction: column; }}
        .nav a {{ padding: 12px 20px; color: rgba(255,255,255,0.8); text-decoration: none; transition: 0.2s; border-right: 3px solid transparent; }}
        .nav a:hover, .nav a.active {{ background: rgba(255,255,255,0.05); color: white; border-right-color: var(--accent); }}
        .main {{ flex: 1; padding: 30px; overflow-y: auto; }}
        .card {{ background: var(--card); border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,0.04); padding: 24px; margin-bottom: 24px; border: 1px solid var(--border); }}
        h2 {{ margin-top: 0; margin-bottom: 20px; font-size: 24px; color: var(--primary); }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ padding: 12px 16px; text-align: right; border-bottom: 1px solid var(--border); }}
        th {{ font-weight: 600; color: var(--secondary); background: rgba(0,0,0,0.02); }}
        tr:hover {{ background: rgba(0,0,0,0.01); }}
        input, select, textarea {{ padding: 10px; border: 1px solid var(--border); border-radius: 6px; font-family: inherit; width: 100%; box-sizing: border-box; }}
        button {{ padding: 10px 20px; background: var(--accent); color: white; border: none; border-radius: 6px; cursor: pointer; font-weight: 600; transition: 0.2s; }}
        button:hover {{ filter: brightness(1.1); }}
        .btn-red {{ background: #e74c3c; }}
        .btn-green {{ background: #2ecc71; }}
        .form-group {{ margin-bottom: 16px; }}
        .form-group label {{ display: block; margin-bottom: 6px; font-weight: 500; }}
        .stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 24px; }}
        .stat-card {{ background: white; padding: 20px; border-radius: 10px; border: 1px solid var(--border); text-align: center; }}
        .stat-val {{ font-size: 32px; font-weight: 700; color: var(--accent); }}
        .stat-label {{ color: var(--secondary); font-size: 14px; margin-top: 5px; }}
      </style>
    </head>
    <body>
      <div class="layout">
        <div class="sidebar">
          <div class="sidebar-header">
            <h1>ניהול מערכת</h1>
            <div style="font-size:12px; opacity:0.6; margin-top:4px;">SchoolPoints Cloud</div>
          </div>
          <div class="nav">
            {nav_html}
          </div>
        </div>
        <div class="main">
          {body}
        </div>
      </div>
    </body>
    </html>
    """

@app.get("/admin/dashboard", response_class=HTMLResponse)
def admin_dashboard(request: Request, admin_key: str = '') -> str:
    guard = _admin_require(request, admin_key)
    if guard:
        return guard
    
    conn = _db()
    cur = conn.cursor()
    
    # Stats
    cur.execute('SELECT COUNT(*) FROM institutions')
    inst_count = cur.fetchone()[0]
    
    cur.execute('SELECT COUNT(*) FROM changes')
    changes_count = cur.fetchone()[0]
    
    cur.execute('SELECT COUNT(*) FROM device_pairings WHERE consumed_at IS NULL')
    pending_pairs = cur.fetchone()[0]
    
    conn.close()
    
    body = f"""
    <h2>דשבורד</h2>
    <div class="stats-grid">
      <div class="stat-card">
        <div class="stat-val">{inst_count}</div>
        <div class="stat-label">מוסדות פעילים</div>
      </div>
      <div class="stat-card">
        <div class="stat-val">{changes_count}</div>
        <div class="stat-label">אירועי סנכרון</div>
      </div>
      <div class="stat-card">
        <div class="stat-val">{pending_pairs}</div>
        <div class="stat-label">צימודים בהמתנה</div>
      </div>
    </div>
    
    <div class="card">
      <h3>קיצורי דרך</h3>
      <div style="display:flex; gap:10px;">
        <a href="/admin/setup"><button class="btn-green">+ הקמת מוסד חדש</button></a>
        <a href="/admin/institutions"><button>ניהול מוסדות</button></a>
      </div>
    </div>
    """
    return _super_admin_shell("דשבורד", body, request)

@app.get("/admin/institutions", response_class=HTMLResponse)
def admin_institutions(request: Request, admin_key: str = '') -> str:
    guard = _admin_require(request, admin_key)
    if guard:
        return guard
    
    conn = _db()
    cur = conn.cursor()
    cur.execute('SELECT tenant_id, name, api_key, password_hash, created_at FROM institutions ORDER BY id DESC')
    rows = cur.fetchall() or []
    conn.close()
    
    items = ""
    for r in rows:
        has_pw = "כן" if (r['password_hash'] or '').strip() else '<span style="color:#e74c3c">לא</span>'
        created = str(r['created_at'])[:16]
        items += f"""
        <tr>
          <td style="font-weight:600;">{r['name']}</td>
          <td><code>{r['tenant_id']}</code></td>
          <td style="font-family:monospace;font-size:12px;">{r['api_key']}</td>
          <td>{has_pw}</td>
          <td>{created}</td>
          <td>
            <a href='/admin/institutions/login?tenant_id={r['tenant_id']}' style="text-decoration:none; margin-left:5px;">
              <button style="padding:6px 12px; font-size:12px; background:#3498db; color:white; border:none; border-radius:4px; cursor:pointer;">🚀 כניסה</button>
            </a>
            <a href='/admin/institutions/password?tenant_id={r['tenant_id']}' style="text-decoration:none;">
              <button style="padding:6px 12px; font-size:12px;">🔑 סיסמה</button>
            </a>
          </td>
        </tr>
        """
        
    body = f"""
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px;">
      <h2>מוסדות ({len(rows)})</h2>
      <div>
        <a href="/admin/registrations" style="margin-left:10px;"><button class="btn-gray">בקשות הרשמה</button></a>
        <a href="/admin/setup"><button class="btn-green">+ חדש</button></a>
      </div>
    </div>
    <div class="card" style="padding:0; overflow:hidden;">
      <table>
        <thead>
          <tr>
            <th>שם מוסד</th>
            <th>Tenant ID</th>
            <th>API Key</th>
            <th>סיסמה?</th>
            <th>נוצר</th>
            <th>פעולות</th>
          </tr>
        </thead>
        <tbody>
          {items}
        </tbody>
      </table>
    </div>
    """
    return _super_admin_shell("מוסדות", body, request)



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
        return guard
        
    conn = _db()
    cur = conn.cursor()
    pw_hash = _pbkdf2_hash(institution_password.strip())
    cur.execute(_sql_placeholder('UPDATE institutions SET password_hash = ? WHERE tenant_id = ?'), (pw_hash, tenant_id.strip()))
    conn.commit()
    conn.close()
    
    body = f"""
    <h2>הסיסמה עודכנה בהצלחה</h2>
    <p>הסיסמה עבור מוסד <code>{tenant_id}</code> עודכנה.</p>
    <div style="margin-top:20px;">
      <a href='/admin/institutions'><button>חזרה לרשימת מוסדות</button></a>
    </div>
    """
    return _super_admin_shell("עדכון בוצע", body, request)


@app.get("/admin/institutions/login")
def admin_institution_login(request: Request, tenant_id: str, admin_key: str = '') -> Response:
    guard = _admin_require(request, admin_key)
    if guard:
        return guard  # type: ignore[return-value]
    
    conn = _db()
    try:
        cur = conn.cursor()
        cur.execute(_sql_placeholder('SELECT 1 FROM institutions WHERE tenant_id = ? LIMIT 1'), (tenant_id.strip(),))
        row = cur.fetchone()
    finally:
        conn.close()

    if not row:
        return HTMLResponse("<h3>Tenant not found</h3>", status_code=404)
        
    resp = RedirectResponse(url='/web/teacher-login', status_code=302)
    resp.set_cookie('web_tenant', tenant_id.strip(), httponly=True, samesite='lax', max_age=60 * 60 * 24 * 30)
    # Clear teacher cookie to ensure fresh login state
    resp.delete_cookie('web_teacher')
    return resp


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

    teacher = _web_current_teacher(request) or {}
    teacher_id = _safe_int(teacher.get('id'), 0)
    is_admin = bool(_safe_int(teacher.get('is_admin'), 0) == 1)
    allowed_classes: List[str] | None = None
    if not is_admin and teacher_id > 0:
        try:
            allowed_classes = _web_teacher_allowed_classes(active_tenant, teacher_id)
            allowed_classes = [str(c).strip() for c in (allowed_classes or []) if str(c).strip()]
        except Exception:
            allowed_classes = []

    conn = _tenant_school_db(active_tenant)
    cur = conn.cursor()
    query = """
        SELECT id, serial_number, last_name, first_name, class_name, points, private_message,
               card_number, id_number, photo_number
        FROM students
    """
    params: List[Any] = []

    wheres: List[str] = []
    if allowed_classes is not None:
        if not allowed_classes:
            try:
                conn.close()
            except Exception:
                pass
            return {"items": [], "limit": limit, "offset": offset, "query": q}
        placeholders = ','.join(['?'] * len(allowed_classes))
        wheres.append(f"class_name IN ({placeholders})")
        params.extend(list(allowed_classes))

    if q:
        wheres.append("(first_name LIKE ? OR last_name LIKE ? OR class_name LIKE ? OR id_number LIKE ?)")
        like = f"%{q.strip()}%"
        params.extend([like, like, like, like])

    if wheres:
        query += " WHERE " + " AND ".join(wheres)

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


@app.post('/api/students/save')
def api_students_save(request: Request, payload: StudentSavePayload) -> Dict[str, Any]:
    guard = _web_require_teacher(request)
    if guard:
        raise HTTPException(status_code=401, detail='not authorized')
    tenant_id = _web_tenant_from_cookie(request)
    if not tenant_id:
        raise HTTPException(status_code=401, detail='missing tenant')

    teacher = _web_current_teacher_permissions(request)
    teacher_id = _safe_int(teacher.get('id'), 0)
    if teacher_id <= 0:
        raise HTTPException(status_code=401, detail='missing teacher')
    is_admin = bool(_safe_int(teacher.get('is_admin'), 0) == 1)
    can_edit_card = bool(_safe_int(teacher.get('can_edit_student_card'), 0) == 1)
    can_edit_photo = bool(_safe_int(teacher.get('can_edit_student_photo'), 0) == 1)

    allowed_classes: List[str] | None = None
    if not is_admin:
        allowed_classes = _web_teacher_allowed_classes(str(tenant_id), int(teacher_id))
        allowed_classes = [str(c).strip() for c in (allowed_classes or []) if str(c).strip()]

    sid = int(payload.student_id or 0)
    last_name = _safe_str(payload.last_name or '').strip()
    first_name = _safe_str(payload.first_name or '').strip()
    id_number = _safe_str(payload.id_number or '').strip()
    class_name = _safe_str(payload.class_name or '').strip()
    serial_number = _safe_str(payload.serial_number or '').strip()
    card_number = _safe_str(payload.card_number or '').strip()
    photo_number = _safe_str(payload.photo_number or '').strip()
    private_message = _safe_str(payload.private_message or '')
    points = payload.points

    if not last_name or not first_name:
        raise HTTPException(status_code=400, detail='missing name')
    if points is not None:
        try:
            points = int(points)
        except Exception:
            raise HTTPException(status_code=400, detail='invalid points')

    if allowed_classes is not None:
        if not allowed_classes:
            raise HTTPException(status_code=403, detail='not allowed')
        if class_name and class_name not in set(allowed_classes):
            raise HTTPException(status_code=403, detail='not allowed')

    conn = _tenant_school_db(str(tenant_id))
    try:
        cur = conn.cursor()
        if sid > 0:
            cur.execute(_sql_placeholder('SELECT class_name, card_number, photo_number FROM students WHERE id = ? LIMIT 1'), (int(sid),))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail='student not found')
            current_class = _safe_str((row.get('class_name') if isinstance(row, dict) else row['class_name']) or '').strip()
            if allowed_classes is not None and current_class and current_class not in set(allowed_classes):
                raise HTTPException(status_code=403, detail='not allowed')

            sets: List[str] = ['last_name = ?', 'first_name = ?', 'id_number = ?', 'class_name = ?', 'serial_number = ?', 'private_message = ?']
            params: List[Any] = [last_name, first_name, id_number, class_name, serial_number, private_message]
            if points is not None:
                sets.append('points = ?')
                params.append(int(points))
            if can_edit_card:
                sets.append('card_number = ?')
                params.append(card_number)
            if can_edit_photo:
                sets.append('photo_number = ?')
                params.append(photo_number)
            sets.append('updated_at = CURRENT_TIMESTAMP')
            sql = 'UPDATE students SET ' + ', '.join(sets) + ' WHERE id = ?'
            params.append(int(sid))
            cur.execute(_sql_placeholder(sql), params)
            conn.commit()
            return {'ok': True, 'student_id': int(sid), 'created': False}

        if not can_edit_card:
            card_number = ''
        if not can_edit_photo:
            photo_number = ''
        pts = int(points) if points is not None else 0
        cur.execute(
            _sql_placeholder(
                'INSERT INTO students (serial_number, last_name, first_name, class_name, points, private_message, card_number, id_number, photo_number) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)'
            ),
            (serial_number, last_name, first_name, class_name, int(pts), private_message, card_number, id_number, photo_number)
        )
        new_id = int(cur.lastrowid or 0)
        conn.commit()
        return {'ok': True, 'student_id': int(new_id), 'created': True}
    finally:
        try:
            conn.close()
        except Exception:
            pass


@app.post('/api/students/delete')
def api_students_delete(request: Request, payload: StudentDeletePayload) -> Dict[str, Any]:
    guard = _web_require_teacher(request)
    if guard:
        raise HTTPException(status_code=401, detail='not authorized')
    tenant_id = _web_tenant_from_cookie(request)
    if not tenant_id:
        raise HTTPException(status_code=401, detail='missing tenant')

    teacher = _web_current_teacher_permissions(request)
    is_admin = bool(_safe_int(teacher.get('is_admin'), 0) == 1)
    if not is_admin:
        raise HTTPException(status_code=403, detail='admin only')

    sid = int(payload.student_id or 0)
    if sid <= 0:
        raise HTTPException(status_code=400, detail='invalid student_id')

    conn = _tenant_school_db(str(tenant_id))
    try:
        cur = conn.cursor()
        cur.execute(_sql_placeholder('DELETE FROM points_history WHERE student_id = ?'), (int(sid),))
        try:
            cur.execute(_sql_placeholder('DELETE FROM points_log WHERE student_id = ?'), (int(sid),))
        except Exception:
            pass
        cur.execute(_sql_placeholder('DELETE FROM students WHERE id = ?'), (int(sid),))
        conn.commit()
        return {'ok': True}
    finally:
        try:
            conn.close()
        except Exception:
            pass


@app.get("/web/personal", response_class=HTMLResponse)
def web_personal(request: Request):
    guard = _web_require_teacher(request)
    if guard:
        return guard
    
    teacher = _web_current_teacher_permissions(request)
    if not teacher:
        return RedirectResponse(url="/web/teacher-login", status_code=302)

    name = teacher.get('name') or 'מורה'
    card = teacher.get('card_number') or ''
    is_admin = bool(_safe_int(teacher.get('is_admin'), 0) == 1)
    
    # Permissions
    can_edit_card = bool(_safe_int(teacher.get('can_edit_student_card'), 0) == 1)
    can_edit_photo = bool(_safe_int(teacher.get('can_edit_student_photo'), 0) == 1)
    bonus_cap_student = teacher.get('bonus_max_points_per_student')
    bonus_cap_total = teacher.get('bonus_max_total_runs')
    
    perm_html = "<ul style='list-style-type:none; padding:0;'>"
    if is_admin: perm_html += "<li style='margin-bottom:5px;'>👮 מנהל מערכת</li>"
    perm_html += f"<li style='margin-bottom:5px;'>💳 עריכת כרטיס תלמיד: {'כן' if can_edit_card else 'לא'}</li>"
    perm_html += f"<li style='margin-bottom:5px;'>📷 עריכת תמונת תלמיד: {'כן' if can_edit_photo else 'לא'}</li>"
    if bonus_cap_student:
        perm_html += f"<li style='margin-bottom:5px;'>🎁 מגבלת בונוס לתלמיד: {bonus_cap_student}</li>"
    if bonus_cap_total:
        perm_html += f"<li style='margin-bottom:5px;'>🔢 מגבלת שימוש בבונוס: {bonus_cap_total}</li>"
    perm_html += "</ul>"

    html_content = f"""
    <h2>אזור אישי</h2>
    <div class="card" style="padding:20px; background:#fff; border-radius:10px; border:1px solid #eee;">
      <h3 style="margin-top:0;">שלום, {name}</h3>
      <div style="margin-bottom:10px;"><b>מספר כרטיס:</b> {card}</div>
      <div style="margin-bottom:10px;"><b>הרשאות:</b></div>
      {perm_html}
      <div style="margin-top:20px;">
        <a href="/web/logout"><button class="red" style="padding:10px 20px; border-radius:6px; border:none; background:#e74c3c; color:white; font-weight:bold; cursor:pointer;">יציאה</button></a>
      </div>
    </div>
    """
    return _basic_web_shell("אזור אישי", html_content, request=request)


@app.get("/web/admin", response_class=HTMLResponse)
def web_admin(request: Request):
    guard = _web_require_teacher(request)
    if guard:
        return guard
    
    teacher = _web_current_teacher(request)
    if not teacher:
        return RedirectResponse(url="/web/teacher-login", status_code=302)
        
    is_admin = bool(_safe_int(teacher.get('is_admin'), 0) == 1)
    
    tiles_html = ""
    
    # Students (Everyone)
    tiles_html += """
    <a href="/web/students" class="tile blue">
      <div class="icon">🎓</div>
      <div class="label">תלמידים</div>
    </a>
    """
    
    if is_admin:
        tiles_html += """
        <a href="/web/teachers" class="tile red">
          <div class="icon">👨‍🏫</div>
          <div class="label">מורים</div>
        </a>
        <a href="/web/messages" class="tile purple">
          <div class="icon">📢</div>
          <div class="label">הודעות</div>
        </a>
        <a href="/web/upgrades" class="tile orange">
          <div class="icon">🎁</div>
          <div class="label">שדרוגים</div>
        </a>
        <a href="/web/time-bonus" class="tile teal">
          <div class="icon">⏱️</div>
          <div class="label">בונוס זמנים</div>
        </a>
        <a href="/web/special-bonus" class="tile pink">
          <div class="icon">✨</div>
          <div class="label">בונוס מיוחד</div>
        </a>
        <a href="/web/holidays" class="tile green">
          <div class="icon">📅</div>
          <div class="label">חגים</div>
        </a>
        <a href="/web/purchases" class="tile indigo">
          <div class="icon">🛒</div>
          <div class="label">קניות</div>
        </a>
        <a href="/web/reports" class="tile cyan">
          <div class="icon">📊</div>
          <div class="label">דוחות</div>
        </a>
        <a href="/web/settings" class="tile gray">
          <div class="icon">⚙️</div>
          <div class="label">הגדרות</div>
        </a>
        """

    # Personal Area (Everyone)
    tiles_html += """
    <a href="/web/personal" class="tile dark">
      <div class="icon">👤</div>
      <div class="label">אזור אישי</div>
    </a>
    """

    body = f"""
    <style>
      .dashboard-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 16px; padding: 10px 0; }}
      .tile {{ display: flex; flex-direction: column; align-items: center; justify-content: center; height: 120px; border-radius: 16px; text-decoration: none; color: white; transition: transform 0.2s, box-shadow 0.2s; box-shadow: 0 4px 10px rgba(0,0,0,0.15); position:relative; overflow:hidden; }}
      .tile:hover {{ transform: translateY(-4px); box-shadow: 0 8px 20px rgba(0,0,0,0.25); }}
      .tile .icon {{ font-size: 42px; margin-bottom: 8px; text-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
      .tile .label {{ font-weight: 700; font-size: 16px; text-shadow: 0 1px 2px rgba(0,0,0,0.2); text-align:center; padding:0 8px; }}
      
      .tile.blue {{ background: linear-gradient(135deg, #3498db, #2980b9); }}
      .tile.red {{ background: linear-gradient(135deg, #e74c3c, #c0392b); }}
      .tile.purple {{ background: linear-gradient(135deg, #9b59b6, #8e44ad); }}
      .tile.orange {{ background: linear-gradient(135deg, #e67e22, #d35400); }}
      .tile.yellow {{ background: linear-gradient(135deg, #f1c40f, #f39c12); }}
      .tile.green {{ background: linear-gradient(135deg, #2ecc71, #27ae60); }}
      .tile.teal {{ background: linear-gradient(135deg, #1abc9c, #16a085); }}
      .tile.pink {{ background: linear-gradient(135deg, #e91e63, #c2185b); }}
      .tile.indigo {{ background: linear-gradient(135deg, #3f51b5, #303f9f); }}
      .tile.cyan {{ background: linear-gradient(135deg, #00bcd4, #0097a7); }}
      .tile.gray {{ background: linear-gradient(135deg, #95a5a6, #7f8c8d); }}
      .tile.dark {{ background: linear-gradient(135deg, #34495e, #2c3e50); }}
    </style>
    
    <h2>לוח בקרה</h2>
    <div class="dashboard-grid">
      {tiles_html}
    </div>
    """
    return _basic_web_shell("לוח בקרה", body, request=request)


def _stub_page(title: str, request: Request) -> Response:
    guard = _web_require_admin_teacher(request)
    if guard: return guard
    body = f"<h2>{title}</h2><p>העמוד בבנייה.</p><div class='actionbar'><a class='gray' href='/web/admin'>חזרה</a></div>"
    return HTMLResponse(_basic_web_shell(title, body, request=request))

@app.get('/web/messages', response_class=HTMLResponse)
def web_messages(request: Request): return _stub_page("הודעות", request)

@app.get('/web/upgrades', response_class=HTMLResponse)
def web_upgrades(request: Request): return _stub_page("שדרוגים", request)

@app.get('/web/time-bonus', response_class=HTMLResponse)
def web_time_bonus(request: Request): return _stub_page("בונוס זמנים", request)

@app.get('/web/special-bonus', response_class=HTMLResponse)
def web_special_bonus(request: Request): return _stub_page("בונוס מיוחד", request)

@app.get('/web/holidays', response_class=HTMLResponse)
def web_holidays(request: Request): return _stub_page("חגים", request)

@app.get('/web/purchases', response_class=HTMLResponse)
def web_purchases(request: Request): return _stub_page("קניות", request)

@app.get('/web/reports', response_class=HTMLResponse)
def web_reports(request: Request): return _stub_page("דוחות", request)


@app.get('/web/students', response_class=HTMLResponse)
def web_students(request: Request):
    try:
        guard = _web_require_teacher(request)
        if guard:
            return guard

        tenant_id = _web_tenant_from_cookie(request)
        if not tenant_id:
            return RedirectResponse(url='/web/signin', status_code=302)

        teacher = _web_current_teacher_permissions(request)
        is_admin = bool(_safe_int(teacher.get('is_admin'), 0) == 1)
        can_edit_card = bool(_safe_int(teacher.get('can_edit_student_card'), 0) == 1)

        body = """
    <style>
      .q-modal { display:none; position:fixed; top:0; left:0; right:0; bottom:0; z-index:10000; align-items:center; justify-content:center; padding:16px; background:rgba(0,0,0,0.75); backdrop-filter:blur(5px); }
      .q-card { width:min(500px, 100%); max-height:90vh; overflow-y:auto; background:#1e293b; border:1px solid #334155; border-radius:16px; padding:24px; color:#f8fafc; box-shadow:0 25px 50px -12px rgba(0,0,0,0.5); display:flex; flex-direction:column; }
      .q-title { font-weight:800; font-size:20px; margin-bottom:20px; color:#fff; }
      .q-actions { display:flex; gap:12px; justify-content:flex-end; margin-top:24px; }
      .q-btn { display:inline-flex; align-items:center; justify-content:center; padding:10px 20px; border-radius:8px; font-weight:700; text-decoration:none; cursor:pointer; transition:all 0.2s; border:none; font-size:14px; }
      .q-btn.blue { background:#3b82f6; color:#fff; }
      .q-btn.blue:hover { background:#2563eb; }
      .q-btn.gray { background:#64748b; color:#fff; }
      .q-btn.gray:hover { background:#475569; }
      
      .q-form-row { margin-bottom:16px; }
      .q-label { display:block; font-weight:600; color:#cbd5e1; font-size:13px; margin-bottom:6px; }
      .q-input, .q-select { width:100%; box-sizing:border-box; padding:10px 12px; border-radius:8px; border:1px solid #475569; background:#0f172a; color:#fff; font-size:14px; outline:none; transition:border-color 0.2s; font-family:inherit; }
      .q-input:focus, .q-select:focus { border-color:#3b82f6; }
      .q-hint { font-size:12px; color:#94a3b8; margin-top:4px; }
    </style>

    <div style="display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-bottom:10px;">
      <input id="q" placeholder="חיפוש" style="padding:10px 12px; border:1px solid var(--line); border-radius:10px; min-width:220px;" />
      <span id="st" style="opacity:.85;">טוען...</span>
      <a class="gray" href="/web/logout" style="margin-right:auto;">יציאה</a>
    </div>
    <div style="display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-bottom:10px;">
      <a id="btnNew" class="blue" href="javascript:void(0)" style="padding:10px 14px; border-radius:10px; font-weight:900;">➕ הוסף תלמיד</a>
      <a id="btnEdit" class="blue" href="javascript:void(0)" style="padding:10px 14px; border-radius:10px; font-weight:900;">✏️ ערוך</a>
      <a id="btnDelete" class="blue" href="javascript:void(0)" style="padding:10px 14px; border-radius:10px; font-weight:900;">🗑️ מחיקה</a>
      <a id="btnQuick" class="blue" href="javascript:void(0)" style="padding:10px 14px; border-radius:10px; font-weight:900;">⚡ עדכון מהיר</a>
      <span id="sel" style="opacity:.86;">לא נבחר תלמיד</span>
    </div>
    <div style="overflow:auto;">
      <table style="width:100%; border-collapse:collapse; font-size:13px;">
        <thead>
          <tr>
            <th style="text-align:right; padding:8px; border-bottom:1px solid var(--line);">בחר</th>
            <th style="text-align:right; padding:8px; border-bottom:1px solid var(--line);">מס'</th>
            <th style="text-align:right; padding:8px; border-bottom:1px solid var(--line);">משפחה</th>
            <th style="text-align:right; padding:8px; border-bottom:1px solid var(--line);">פרטי</th>
            <th style="text-align:right; padding:8px; border-bottom:1px solid var(--line);">כיתה</th>
            <th style="text-align:right; padding:8px; border-bottom:1px solid var(--line);">נקודות</th>
            <th style="text-align:right; padding:8px; border-bottom:1px solid var(--line);">כרטיס</th>
          </tr>
        </thead>
        <tbody id="rows"></tbody>
      </table>
    </div>

    <div id="q_modal" class="q-modal">
      <div class="q-card">
        <div class="q-title">עדכון מהיר</div>
        <div id="q_body"></div>
        <div class="q-actions">
          <a id="q_cancel" class="q-btn gray" href="javascript:void(0)">ביטול</a>
          <a id="q_run" class="q-btn blue" href="javascript:void(0)">בצע עדכון</a>
        </div>
      </div>
    </div>
    <script>
      const qEl = document.getElementById('q');
      const stEl = document.getElementById('st');
      const rowsEl = document.getElementById('rows');
      const selEl = document.getElementById('sel');
      const btnEdit = document.getElementById('btnEdit');
      const btnDelete = document.getElementById('btnDelete');
      const btnNew = document.getElementById('btnNew');
      const btnQuick = document.getElementById('btnQuick');
      const qModal = document.getElementById('q_modal');
      const qBody = document.getElementById('q_body');
      const qRun = document.getElementById('q_run');
      const qCancel = document.getElementById('q_cancel');
      const IS_ADMIN = __IS_ADMIN__;
      const CAN_EDIT_CARD = __CAN_EDIT_CARD__;
      let selectedId = null;
      let timer = null;

      function renderQuickForm() {
        if (!qBody) return;
        qBody.innerHTML = '' +
          '<div class="q-form-row">' +
            '<label class="q-label">סוג עדכון</label>' +
            '<select id="q_operation" class="q-select">' +
              '<option value="add">הוספת נקודות</option>' +
              '<option value="subtract">הפחתת נקודות</option>' +
              '<option value="set">קביעת סכום מוחלט</option>' +
            '</select>' +
          '</div>' +
          '<div class="q-form-row">' +
            '<label class="q-label">כמות נקודות</label>' +
            '<input id="q_points" type="number" value="1" class="q-input" />' +
          '</div>' +
          '<div class="q-form-row">' +
            '<label class="q-label">למי לעדכן?</label>' +
            '<select id="q_mode" class="q-select">' +
              '<option value="card">לפי מספר כרטיס (בודד)</option>' +
              '<option value="serial_range">לפי טווח מספרים סידוריים</option>' +
              '<option value="class">לפי כיתה/כיתות</option>' +
              '<option value="students">לפי בחירה בטבלה</option>' +
              ((IS_ADMIN === 1) ? '<option value="all_school">כל בית הספר (מנהל בלבד)</option>' : '') +
            '</select>' +
          '</div>' +
          
          '<div id="q_row_card" class="q-form-row">' +
            '<label class="q-label">מספר כרטיס</label>' +
            '<input id="q_card" class="q-input" style="direction:ltr; text-align:left;" placeholder="סרוק או הקלד כרטיס..." />' +
          '</div>' +
          
          '<div id="q_row_serial" class="q-form-row" style="display:none;">' +
            '<label class="q-label">טווח מספרים סידוריים</label>' +
            '<div style="display:flex; gap:10px;">' +
              '<input id="q_serial_from" type="number" placeholder="מ-" class="q-input" />' +
              '<input id="q_serial_to" type="number" placeholder="עד" class="q-input" />' +
            '</div>' +
            '<div class="q-hint">כולל את המספרים שבקצוות</div>' +
          '</div>' +
          
          '<div id="q_row_class" class="q-form-row" style="display:none;">' +
            '<label class="q-label">שמות כיתות</label>' +
            '<input id="q_class_names" placeholder="לדוגמה: ז1, ז2" class="q-input" />' +
            '<div class="q-hint">מופרד בפסיקים</div>' +
          '</div>' +
          
          '<div id="q_row_students" class="q-form-row" style="display:none;">' +
            '<div class="q-hint" style="font-size:14px; color:#94a3b8;">העדכון יחול על התלמידים שסימנת בתיבות הסימון בטבלה.</div>' +
          '</div>' +
          
          '<div id="q_row_all" class="q-form-row" style="display:none;">' +
            '<div class="q-hint" style="font-size:14px; color:#ef4444;">זהירות: העדכון יחול על כל התלמידים במוסד!</div>' +
          '</div>';

        const modeEl = document.getElementById('q_mode');
        function syncMode() {
          const m = String(modeEl ? modeEl.value : 'card');
          const a = document.getElementById('q_row_card');
          const b = document.getElementById('q_row_serial');
          const c = document.getElementById('q_row_class');
          const d = document.getElementById('q_row_students');
          const e = document.getElementById('q_row_all');
          if (a) a.style.display = (m === 'card') ? 'block' : 'none';
          if (b) b.style.display = (m === 'serial_range') ? 'block' : 'none';
          if (c) c.style.display = (m === 'class') ? 'block' : 'none';
          if (d) d.style.display = (m === 'students') ? 'block' : 'none';
          if (e) e.style.display = (m === 'all_school') ? 'block' : 'none';
          
          // Auto focus card input if card mode
          if (m === 'card' && document.getElementById('q_card')) {
             setTimeout(() => document.getElementById('q_card').focus(), 50);
          }
        }
        if (modeEl) modeEl.addEventListener('change', syncMode);
        syncMode();
      }

      function openQuickModal() {
        if (!qModal) return;
        renderQuickForm();
        qModal.style.display = 'flex';
        try { document.body.style.overflow = 'hidden'; } catch (e) {}
      }

      function closeQuickModal() {
        if (!qModal) return;
        qModal.style.display = 'none';
        try { document.body.style.overflow = ''; } catch (e) {}
      }

      function getSelectedStudentIds() {
        const ids = [];
        try {
          document.querySelectorAll('input.pick[type=checkbox]:checked').forEach(cb => {
            const sid = parseInt(String(cb.getAttribute('data-id') || '0'), 10);
            if (!Number.isNaN(sid) && sid > 0) ids.push(sid);
          });
        } catch (e) {
          return [];
        }
        return ids;
      }

      function setSelected(id) {
        selectedId = id;
        const on = (selectedId !== null);
        btnEdit.style.opacity = on ? '1' : '.55';
        btnEdit.style.pointerEvents = on ? 'auto' : 'none';
        btnDelete.style.opacity = (on && IS_ADMIN) ? '1' : '.55';
        btnDelete.style.pointerEvents = (on && IS_ADMIN) ? 'auto' : 'none';
        selEl.textContent = on ? ('נבחר תלמיד ID ' + String(selectedId)) : 'לא נבחר תלמיד';
        document.querySelectorAll('tr[data-id]').forEach(tr => {
          tr.style.outline = (String(tr.getAttribute('data-id')) === String(selectedId)) ? '2px solid #1abc9c' : 'none';
        });
      }

      async function load() {
        stEl.textContent = 'טוען...';
        const q = encodeURIComponent(qEl.value || '');
        const resp = await fetch('/api/students?q=' + q);
        const data = await resp.json();
        const items = Array.isArray(data.items) ? data.items : [];
        rowsEl.innerHTML = items.map(r => (
          '<tr data-id="' + String(r.id ?? '') + '">' +
            '<td style="padding:8px; border-bottom:1px solid var(--line);">' +
              '<input class="pick" type="checkbox" data-id="' + String(r.id ?? '') + '" />' +
            '</td>' +
            '<td style="padding:8px; border-bottom:1px solid var(--line);">' + (r.serial_number ?? '') + '</td>' +
            '<td style="padding:8px; border-bottom:1px solid var(--line);">' + (r.last_name ?? '') + '</td>' +
            '<td style="padding:8px; border-bottom:1px solid var(--line);">' + (r.first_name ?? '') + '</td>' +
            '<td style="padding:8px; border-bottom:1px solid var(--line);">' + (r.class_name ?? '') + '</td>' +
            '<td style="padding:8px; border-bottom:1px solid var(--line);">' + (r.points ?? '') + '</td>' +
            '<td style="padding:8px; border-bottom:1px solid var(--line); direction:ltr; text-align:left;">' + (CAN_EDIT_CARD ? (r.card_number ?? '') : '••••••') + '</td>' +
          '</tr>'
        )).join('');
        stEl.textContent = 'נטענו ' + items.length + ' תלמידים';

        document.querySelectorAll('tr[data-id]').forEach(tr => {
          tr.addEventListener('click', () => setSelected(tr.getAttribute('data-id')));
        });
        if (selectedId) setSelected(selectedId);
      }

      btnEdit.style.opacity = '.55';
      btnEdit.style.pointerEvents = 'none';
      if (!IS_ADMIN) {
        btnDelete.style.opacity = '.55';
        btnDelete.style.pointerEvents = 'none';
      }

      btnNew.addEventListener('click', () => alert('שלב הבא: modal הוספה/עריכה'));
      btnEdit.addEventListener('click', () => {
        if (!selectedId) return;
        alert('שלב הבא: modal עריכת תלמיד');
      });
      btnDelete.addEventListener('click', async () => {
        if (!selectedId || !IS_ADMIN) return;
        if (!confirm('למחוק תלמיד?')) return;
        const resp = await fetch('/api/students/delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ student_id: parseInt(String(selectedId), 10) })
        });
        if (!resp.ok) {
          const txt = await resp.text();
          alert('שגיאה: ' + txt);
          return;
        }
        selectedId = null;
        setSelected(null);
        await load();
      });
      btnQuick.addEventListener('click', () => openQuickModal());
      if (qCancel) qCancel.addEventListener('click', () => closeQuickModal());
      if (qRun) qRun.addEventListener('click', async () => {
        try {
          const opEl = document.getElementById('q_operation');
          const ptsEl = document.getElementById('q_points');
          const modeEl = document.getElementById('q_mode');

          const operation = String(opEl ? opEl.value : 'add');
          const points = parseInt(String(ptsEl ? ptsEl.value : '0'), 10);
          const mode = String(modeEl ? modeEl.value : 'card');
          if (Number.isNaN(points)) { alert('נקודות לא תקין'); return; }

          const payload = { operation: operation, points: points, mode: mode };

          if (mode === 'card') {
            const cardEl = document.getElementById('q_card');
            const card = String(cardEl ? cardEl.value : '').trim();
            if (!card) { alert('חסר כרטיס'); return; }
            payload.card_number = card;
          } else if (mode === 'serial_range') {
            const fEl = document.getElementById('q_serial_from');
            const tEl = document.getElementById('q_serial_to');
            const sf = parseInt(String(fEl ? fEl.value : ''), 10);
            const st = parseInt(String(tEl ? tEl.value : ''), 10);
            if (Number.isNaN(sf) || Number.isNaN(st) || sf <= 0 || st <= 0) { alert('טווח לא תקין'); return; }
            payload.serial_from = sf;
            payload.serial_to = st;
          } else if (mode === 'class') {
            const clsEl = document.getElementById('q_class_names');
            const raw = String(clsEl ? clsEl.value : '').trim();
            const arr = raw.split(',').map(s => String(s || '').trim()).filter(Boolean);
            if (!arr.length) { alert('חסר כיתה'); return; }
            payload.class_names = arr;
          } else if (mode === 'students') {
            const ids = getSelectedStudentIds();
            if (!ids.length) { alert('לא נבחרו תלמידים (תיבות סימון)'); return; }
            payload.student_ids = ids;
          } else if (mode === 'all_school') {
            if (IS_ADMIN !== 1) { alert('מנהל בלבד'); return; }
          } else {
            alert('מצב לא מוכר');
            return;
          }

          qRun.style.opacity = '.7';
          qRun.style.pointerEvents = 'none';
          const resp = await fetch('/api/students/quick-update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
          });
          qRun.style.opacity = '1';
          qRun.style.pointerEvents = 'auto';
          if (!resp.ok) {
            const txt = await resp.text();
            alert('שגיאה: ' + txt);
            return;
          }
          closeQuickModal();
          await load();
        } catch (e) {
          try { qRun.style.opacity = '1'; qRun.style.pointerEvents = 'auto'; } catch (e2) {}
          alert('שגיאה');
        }
      });
      if (qModal) {
        qModal.addEventListener('click', (ev) => {
          if (ev.target === qModal) closeQuickModal();
        });
      }
      document.addEventListener('keydown', (ev) => {
        if (ev.key === 'Escape') closeQuickModal();
      });
      qEl.addEventListener('input', () => {
        clearTimeout(timer);
        timer = setTimeout(load, 250);
      });
      load();
    </script>
    """

        body = body.replace('__IS_ADMIN__', '1' if is_admin else '0')
        body = body.replace('__CAN_EDIT_CARD__', '1' if can_edit_card else '0')
        return HTMLResponse(_basic_web_shell("ניהול תלמידים", body, request=request))
    except Exception as exc:
        print('WEB_STUDENTS_ERROR', repr(exc))
        traceback.print_exc()
        try:
            tb = traceback.format_exc()
            return HTMLResponse(
                '<h3>Internal Server Error</h3><pre>' + html.escape(tb) + '</pre>',
                status_code=500
            )
        except Exception:
            return HTMLResponse('Internal Server Error', status_code=500)


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
