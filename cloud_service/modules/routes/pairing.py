from fastapi import APIRouter, Request, HTTPException, Query, Form
from fastapi.responses import HTMLResponse
from typing import Dict, Any, Optional
from pydantic import BaseModel

from ..db import get_db_connection, sql_placeholder, integrity_errors
from ..utils import random_pair_code, time_to_minutes
from ..ui import public_web_shell, basic_web_shell
from ..auth import web_require_tenant, web_tenant_from_cookie
from ..config import USE_POSTGRES

router = APIRouter()

def ensure_device_pairings_table() -> None:
    conn = get_db_connection()
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
        try: conn.close()
        except: pass

def now_expr() -> str:
    return 'CURRENT_TIMESTAMP'

@router.post('/api/device/pair/start')
def api_device_pair_start(request: Request) -> Dict[str, Any]:
    ensure_device_pairings_table()
    code = random_pair_code()
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        # best-effort retry on rare collision
        for _ in range(4):
            try:
                cur.execute(
                    sql_placeholder('INSERT INTO device_pairings (code) VALUES (?)'),
                    (code,)
                )
                conn.commit()
                break
            except integrity_errors():
                code = random_pair_code()
                continue
        
        # Construct verify URL
        # We need public base url. We can get it from request or config.
        # Assuming utils has public_base_url
        from ..utils import public_base_url
        verify_url = public_base_url(request) + '/web/device/pair?code=' + code
        return {'ok': True, 'code': code, 'verify_url': verify_url}
    finally:
        try: conn.close()
        except: pass

@router.get('/api/device/pair/poll')
def api_device_pair_poll(code: str = Query(default='')) -> Dict[str, Any]:
    ensure_device_pairings_table()
    code = str(code or '').strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail='missing code')

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            sql_placeholder(
                'SELECT code, approved_at, consumed_at, tenant_id, api_key, push_url FROM device_pairings WHERE code = ? LIMIT 1'
            ),
            (code,)
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail='invalid code')
        
        r = dict(row) if isinstance(row, dict) else {k: row[k] for k in row.keys()} if hasattr(row, 'keys') else {}
        if not r and row: # fallback
             # If using tuple cursor (not RealDictCursor for PG or Row for Sqlite?)
             # Our db module ensures Row or RealDictCursor.
             pass

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
                sql_placeholder(f'UPDATE device_pairings SET consumed_at = {now_expr()} WHERE code = ?'),
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
        try: conn.close()
        except: pass

@router.get('/web/device/pair', response_class=HTMLResponse)
def web_device_pair(request: Request, code: str = '') -> str:
    guard = web_require_tenant(request)
    if guard:
        return guard
        
    code = str(code or '').strip().upper()
    if not code:
        body = "<h2>חיבור עמדה</h2><p>חסר קוד.</p><div class='actionbar'><a class='gray' href='/web/admin'>חזרה</a></div>"
        return basic_web_shell('חיבור עמדה', body, request=request)
        
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
    return basic_web_shell('חיבור עמדה', body, request=request)

@router.post('/web/device/pair', response_class=HTMLResponse)
def web_device_pair_submit(request: Request, code: str = Form(default='')) -> str:
    guard = web_require_tenant(request)
    if guard:
        return guard
        
    tenant_id = web_tenant_from_cookie(request)
    code = str(code or '').strip().upper()
    
    if not code:
        return basic_web_shell('חיבור עמדה', "<h2>שגיאה</h2><p>קוד חסר.</p>", request=request)

    ensure_device_pairings_table()
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql_placeholder('SELECT id, approved_at FROM device_pairings WHERE code = ? LIMIT 1'), (code,))
        row = cur.fetchone()
        if not row:
             return basic_web_shell('חיבור עמדה', "<h2>שגיאה</h2><p>קוד לא נמצא או פג תוקף.</p>", request=request)
        
        approved_at = row['approved_at'] if isinstance(row, dict) else row[1]
        if approved_at:
             return basic_web_shell('חיבור עמדה', "<h2>שגיאה</h2><p>הקוד כבר אושר.</p>", request=request)
             
        # Approve it
        # We need to get the tenant's API key.
        # Assuming we store it in institutions table or can generate one.
        # But wait, app.py logic for this...
        
        # Retrieve tenant info to get API key
        cur.execute(sql_placeholder('SELECT api_key FROM institutions WHERE tenant_id = ? LIMIT 1'), (tenant_id,))
        inst_row = cur.fetchone()
        if not inst_row:
             return basic_web_shell('חיבור עמדה', "<h2>שגיאה</h2><p>מוסד לא נמצא.</p>", request=request)
             
        api_key = inst_row['api_key'] if isinstance(inst_row, dict) else inst_row[0]
        
        # We also need a push_url. For now we use a default or empty.
        # In original app.py:
        # push_url = _public_base_url(request) + '/sync/push'
        from ..utils import public_base_url
        push_url = public_base_url(request) + '/sync/push'
        
        cur.execute(
            sql_placeholder(
                f'UPDATE device_pairings SET approved_at = {now_expr()}, tenant_id = ?, api_key = ?, push_url = ? WHERE code = ?'
            ),
            (tenant_id, api_key, push_url, code)
        )
        conn.commit()
        
        body = """
        <h2>החיבור אושר בהצלחה!</h2>
        <p>כעת העמדה תתחבר אוטומטית ותתחיל בסנכרון.</p>
        <div class='actionbar'>
          <a class='blue' href='/web/admin'>לוח בקרה</a>
        </div>
        """
        return basic_web_shell('חיבור עמדה', body, request=request)
    finally:
        try: conn.close()
        except: pass
