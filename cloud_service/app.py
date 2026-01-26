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
from fastapi import FastAPI, Header, HTTPException, Form, Query, Request
from fastapi.responses import HTMLResponse, Response, RedirectResponse
from pydantic import BaseModel

app = FastAPI(title="SchoolPoints Sync")

APP_BUILD_TAG = "2026-01-26-webroutes"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
DATA_DIR = os.path.join(BASE_DIR, 'data')
DB_PATH = os.path.join(DATA_DIR, 'cloud.db')

if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

try:
    from database import Database
except Exception:
    Database = None


def _db() -> sqlite3.Connection:
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


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
    changes_total = cur.fetchone()[0]
    cur.execute('SELECT COUNT(*) AS total FROM institutions')
    inst_total = cur.fetchone()[0]
    cur.execute('SELECT MAX(received_at) AS last_received FROM changes')
    row = cur.fetchone()
    last_received = row['last_received'] if row else None
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


def _web_require_login(request: Request) -> Response | None:
    if _web_auth_ok(request):
        return None
    return RedirectResponse(url="/web/login", status_code=302)


def _init_db() -> None:
    conn = _db()
    cur = conn.cursor()
    cur.execute(
        '''
        CREATE TABLE IF NOT EXISTS institutions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            api_key TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        '''
    )
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
    conn.commit()
    conn.close()


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


@app.post("/sync/push")
def sync_push(payload: SyncPushRequest, api_key: str = Header(default="")) -> Dict[str, Any]:
    if not payload.tenant_id:
        raise HTTPException(status_code=400, detail="missing tenant_id")
    if not api_key:
        raise HTTPException(status_code=401, detail="missing api_key")

    conn = _db()
    cur = conn.cursor()
    cur.execute(
        'SELECT id FROM institutions WHERE tenant_id = ? AND api_key = ? LIMIT 1',
        (payload.tenant_id, api_key)
    )
    row = cur.fetchone()
    if not row:
        allow_auto = str(os.getenv('AUTO_CREATE_TENANT') or '').strip() == '1'
        if allow_auto:
            try:
                cur.execute(
                    'INSERT INTO institutions (tenant_id, name, api_key) VALUES (?, ?, ?)',
                    (payload.tenant_id, payload.tenant_id, api_key)
                )
                conn.commit()
                cur.execute(
                    'SELECT id FROM institutions WHERE tenant_id = ? AND api_key = ? LIMIT 1',
                    (payload.tenant_id, api_key)
                )
                row = cur.fetchone()
            except sqlite3.IntegrityError:
                row = None
        if not row:
            conn.close()
            raise HTTPException(status_code=401, detail="invalid api_key")

    for ch in payload.changes:
        cur.execute(
            '''
            INSERT INTO changes (tenant_id, station_id, entity_type, entity_id, action_type, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ''',
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
    conn.commit()
    conn.close()

    # placeholder behavior
    return {
        "ok": True,
        "received": len(payload.changes),
        "tenant_id": payload.tenant_id,
        "station_id": payload.station_id,
    }


@app.get("/admin/setup", response_class=HTMLResponse)
def admin_setup_form(admin_key: str = '') -> str:
    expected = str(os.getenv('ADMIN_KEY') or '').strip()
    if expected and admin_key != expected:
        return "<h3>Invalid admin key</h3>"
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
            <label>API Key (אופציונלי - יווצר אוטומטית)</label>
            <input name="api_key" placeholder="השאר ריק ליצירה אוטומטית" />
            <button type="submit">צור מוסד</button>
          </form>
          <div class="links">
            <a href="/admin/institutions">רשימת מוסדות</a>
            <a href="/web/admin">עמדת ניהול ווב</a>
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


@app.get("/web/login", response_class=HTMLResponse)
def web_login() -> str:
    institutions = _institutions()
    options = "".join(
        f"<option value='{i['tenant_id']}'>{i['name']} ({i['tenant_id']})</option>"
        for i in institutions
    )
    body = f"""
    <h2>כניסה למערכת</h2>
    <form method="post">
      <label>שם משתמש</label>
      <input name="username" required />
      <label>סיסמה</label>
      <input name="password" type="password" required />
      <label>מוסד</label>
      <select name="tenant_id" required>{options}</select>
      <button type="submit">התחברות</button>
    </form>
    """
    return _basic_web_shell("כניסה למערכת", body)


@app.post("/web/login", response_class=HTMLResponse)
def web_login_submit(
    username: str = Form(...),
    password: str = Form(...),
    tenant_id: str = Form(...)
) -> Response:
    creds = _web_auth_credentials()
    if username.strip() != creds['user'] or password.strip() != creds['pass']:
        body = "<h2>שגיאת התחברות</h2><p>שם משתמש או סיסמה לא תקינים.</p>"
        return HTMLResponse(_basic_web_shell("כניסה למערכת", body))
    response = RedirectResponse(url="/web/admin", status_code=302)
    response.set_cookie("web_user", username.strip(), httponly=True)
    response.set_cookie("web_tenant", tenant_id.strip(), httponly=True)
    return response


@app.get("/web/logout")
def web_logout() -> Response:
    response = RedirectResponse(url="/web/login", status_code=302)
    response.delete_cookie("web_user")
    response.delete_cookie("web_tenant")
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
            <a class="tab" href="/web/admin">ניהול תלמידים</a>
            <a class="tab" href="/web/bonuses">בונוסים</a>
            <a class="tab" href="/web/holidays">חגים/חופשות</a>
            <a class="tab" href="/web/logs">לוגים</a>
            <a class="tab" href="/web/settings">הגדרות</a>
          </div>
          {body_html}
          <div class="links">
            <a href="/web/admin">עמדת ניהול ווב</a>
            <a href="/admin/institutions">מוסדות</a>
            <a href="/admin/sync-status">סטטוס סינכרון</a>
          </div>
        </div>
      </div>
    </body>
    </html>
    """


@app.get("/web/students/new", response_class=HTMLResponse)
def web_student_new(request: Request):
    guard = _web_require_login(request)
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
    guard = _web_require_login(request)
    if guard:
        return guard
    conn = _school_db()
    cur = conn.cursor()
    cur.execute(
        '''
        INSERT INTO students (first_name, last_name, class_name, id_number, points)
        VALUES (?, ?, ?, ?, ?)
        ''',
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
    guard = _web_require_login(request)
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
    guard = _web_require_login(request)
    if guard:
        return guard
    conn = _school_db()
    cur = conn.cursor()
    cur.execute(
        'UPDATE students SET points = ?, private_message = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
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
    guard = _web_require_login(request)
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
    guard = _web_require_login(request)
    if guard:
        return guard
    conn = _school_db()
    cur = conn.cursor()
    cur.execute('DELETE FROM students WHERE id = ?', (int(student_id),))
    conn.commit()
    conn.close()
    body = """
    <h2>תלמיד נמחק</h2>
    <p>הרשומה הוסרה.</p>
    """
    return _basic_web_shell("מחיקת תלמיד", body)


@app.get("/web/import", response_class=HTMLResponse)
def web_import(request: Request):
    guard = _web_require_login(request)
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
    guard = _web_require_login(request)
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
    guard = _web_require_login(request)
    if guard:
        return guard
    conn = _school_db()
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
    guard = _web_require_login(request)
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
    guard = _web_require_login(request)
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


@app.get("/web/logs", response_class=HTMLResponse)
def web_logs(request: Request):
    guard = _web_require_login(request)
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
    guard = _web_require_login(request)
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
def admin_sync_status(admin_key: str = '') -> str:
    expected = str(os.getenv('ADMIN_KEY') or '').strip()
    if expected and admin_key != expected:
        return "<h3>Invalid admin key</h3>"
    conn = _db()
    cur = conn.cursor()
    cur.execute('SELECT COUNT(*) AS total FROM changes')
    total = cur.fetchone()[0]
    cur.execute('SELECT COUNT(*) AS total FROM institutions')
    inst_total = cur.fetchone()[0]
    cur.execute('SELECT MAX(received_at) AS last_received FROM changes')
    last_received = (cur.fetchone() or {}).get('last_received') if hasattr(cur.fetchone(), 'get') else None
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
            <a href="/web/admin">עמדת ניהול ווב</a>
          </div>
        </div>
      </div>
    </body>
    </html>
    """


@app.get("/admin/changes", response_class=HTMLResponse)
def admin_changes(admin_key: str = '') -> str:
    expected = str(os.getenv('ADMIN_KEY') or '').strip()
    if expected and admin_key != expected:
        return "<h3>Invalid admin key</h3>"
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
          """ + _admin_status_bar() + """
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
            <a href="/web/admin">עמדת ניהול ווב</a>
          </div>
        </div>
      </div>
    </body>
    </html>
    """


@app.get("/admin/institutions", response_class=HTMLResponse)
def admin_institutions(admin_key: str = '') -> str:
    expected = str(os.getenv('ADMIN_KEY') or '').strip()
    if expected and admin_key != expected:
        return "<h3>Invalid admin key</h3>"
    conn = _db()
    cur = conn.cursor()
    cur.execute('SELECT tenant_id, name, api_key, created_at FROM institutions ORDER BY id DESC')
    rows = cur.fetchall() or []
    conn.close()
    items = "".join(
        f"<tr><td>{r['tenant_id']}</td><td>{r['name']}</td><td>{r['api_key']}</td><td>{r['created_at']}</td></tr>"
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
          """ + _admin_status_bar() + """
          <h2>מוסדות רשומים</h2>
          <table>
            <thead>
              <tr><th>Tenant ID</th><th>שם מוסד</th><th>API Key</th><th>נוצר</th></tr>
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


@app.get("/api/students")
def api_students(
    request: Request,
    q: str = Query(default='', description="search"),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    tenant_id: str = Query(default='')
) -> Dict[str, Any]:
    cookie_tenant = _web_tenant_from_cookie(request)
    active_tenant = cookie_tenant or _current_tenant_id()
    if active_tenant and tenant_id and tenant_id != active_tenant:
        return {"items": [], "limit": limit, "offset": offset, "query": q}
    conn = _school_db()
    cur = conn.cursor()
    query = """
        SELECT id, first_name, last_name, class_name, points, card_number, id_number, serial_number, photo_number
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
    cur.execute(query, params)
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return {
        "items": rows,
        "limit": limit,
        "offset": offset,
        "query": q,
    }


@app.get("/web/admin", response_class=HTMLResponse)
def web_admin(request: Request):
    guard = _web_require_login(request)
    if guard:
        return guard
    tenant_id = _web_tenant_from_cookie(request) or _current_tenant_id()
    institutions = _institutions()
    options = "".join(
        f"<option value='{i['tenant_id']}'{' selected' if i['tenant_id'] == tenant_id else ''}>{i['name']} ({i['tenant_id']})</option>"
        for i in institutions
    )
    js = """
      <script>
        const rowsEl = document.getElementById('rows');
        const statusEl = document.getElementById('status');
        const searchEl = document.getElementById('search');
        let timer = null;
        async function load() {
          statusEl.textContent = 'טוען...';
          const q = encodeURIComponent(searchEl.value || '');
          const tenant = document.getElementById('tenant').value || '';
          const resp = await fetch(`/api/students?q=${q}&tenant_id=${encodeURIComponent(tenant)}`);
          const data = await resp.json();
          rowsEl.innerHTML = data.items.map(r => `
            <tr>
              <td style="padding:8px;border-top:1px solid #e8eef2;">${r.points ?? ''}</td>
              <td style="padding:8px;border-top:1px solid #e8eef2;">${r.first_name ?? ''}</td>
              <td style="padding:8px;border-top:1px solid #e8eef2;">${r.last_name ?? ''}</td>
              <td style="padding:8px;border-top:1px solid #e8eef2;">${r.class_name ?? ''}</td>
              <td style="padding:8px;border-top:1px solid #e8eef2;">${r.id_number ?? ''}</td>
              <td style="padding:8px;border-top:1px solid #e8eef2;">${r.card_number ?? ''}</td>
            </tr>`).join('');
          statusEl.textContent = `נטענו ${data.items.length} תלמידים`;
        }
        document.getElementById('tenant').addEventListener('change', load);
        searchEl.addEventListener('input', () => {
          clearTimeout(timer);
          timer = setTimeout(load, 300);
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
          <a class="tab" href="/admin/setup">רישום מוסד</a>
          <a class="tab" href="/admin/institutions">מוסדות</a>
          <a class="tab" href="/admin/sync-status">סטטוס סינכרון</a>
          <a class="tab" href="/admin/changes">שינויים אחרונים</a>
          <a class="tab" href="/web/bonuses">בונוסים</a>
          <a class="tab" href="/web/holidays">חגים/חופשות</a>
          <a class="tab" href="/web/logs">לוגים</a>
          <a class="tab" href="/web/settings">הגדרות</a>
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
          <select id="tenant" disabled>{options}</select>
          <input id="search" placeholder="חיפוש" />
          <span id="status" style="color:#637381;">טוען...</span>
        </div>
        <div class="card">
          <div style="overflow:auto;">
            <table>
              <thead>
                <tr>
                  <th>נקודות</th>
                  <th>שם פרטי</th>
                  <th>שם משפחה</th>
                  <th>כיתה</th>
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
    </body>
    </html>
    """


@app.post("/admin/setup", response_class=HTMLResponse)
def admin_setup_submit(
    name: str = Form(...),
    tenant_id: str = Form(...),
    api_key: str = Form(default=''),
    admin_key: str = ''
) -> str:
    expected = str(os.getenv('ADMIN_KEY') or '').strip()
    if expected and admin_key != expected:
        return "<h3>Invalid admin key</h3>"
    conn = _db()
    cur = conn.cursor()
    api_key = api_key.strip() or secrets.token_urlsafe(16)
    try:
        cur.execute(
            'INSERT INTO institutions (tenant_id, name, api_key) VALUES (?, ?, ?)',
            (tenant_id.strip(), name.strip(), api_key)
        )
        conn.commit()
        return f"<h3>Institution created.</h3><p>API Key: <b>{api_key}</b></p><p>עדכן ב־config.json: sync_api_key, sync_tenant_id</p>"
    except sqlite3.IntegrityError:
        return "<h3>Tenant ID already exists.</h3>"
    finally:
        conn.close()


@app.get("/view/changes", response_class=HTMLResponse)
def view_changes(tenant_id: str, api_key: str) -> str:
    conn = _db()
    cur = conn.cursor()
    cur.execute(
        'SELECT id FROM institutions WHERE tenant_id = ? AND api_key = ? LIMIT 1',
        (tenant_id, api_key)
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        return "<h3>Unauthorized</h3>"
    cur.execute(
        '''
        SELECT received_at, station_id, entity_type, action_type, entity_id, payload_json
        FROM changes
        WHERE tenant_id = ?
        ORDER BY id DESC
        LIMIT 200
        ''',
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
