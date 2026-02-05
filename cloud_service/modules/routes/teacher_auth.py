from fastapi import APIRouter, Request, Response, Form, Query
from typing import Dict, Any
from fastapi.responses import HTMLResponse, RedirectResponse
import urllib.parse

from ..utils import public_web_shell
from ..auth import web_require_tenant, web_tenant_from_cookie, web_next_from_request, master_token_valid, web_teacher_from_cookie
from ..db import tenant_db_connection, sql_placeholder, integrity_errors, get_db_connection
from ..config import USE_POSTGRES

router = APIRouter()

@router.get('/web/teacher-login', response_class=HTMLResponse)
def web_teacher_login(request: Request) -> Response:
    guard = web_require_tenant(request)
    if guard:
        return guard
    
    # If master is logged in, redirect to admin
    tenant_id = web_tenant_from_cookie(request)
    if tenant_id:
        master_cookie = request.cookies.get('web_master')
        if master_cookie and master_token_valid(master_cookie, tenant_id):
             return RedirectResponse(url='/web/admin', status_code=302)

    nxt = web_next_from_request(request, '/web/admin')
    body = f"""
    <h2>כניסת מורה</h2>
    <div style="color:#637381; margin-top:-6px;">יש להעביר כרטיס מורה או להזין מספר כרטיס.</div>
    <form method="post" action="/web/teacher-login?next={urllib.parse.quote(nxt, safe='')}" style="margin-top:12px; max-width:520px;">
      <label style="display:block;margin:10px 0 6px;font-weight:800;">כרטיס מורה</label>
      <input name="card_number" type="password" autofocus style="width:100%;padding:12px;border:1px solid var(--line);border-radius:10px;font-size:15px;" required />
      <div class="actionbar" style="justify-content:flex-start;">
        <button class="green" type="submit">כניסה</button>
        <a class="gray" href="/web/logout">החלפת מוסד</a>
      </div>
    </form>
    """
    return HTMLResponse(public_web_shell('כניסת מורה', body))

@router.post('/web/teacher-login', response_class=HTMLResponse)
def web_teacher_login_submit(
    request: Request,
    card_number: str = Form(default=''),
) -> Response:
    guard = web_require_tenant(request)
    if guard:
        return guard
    tenant_id = web_tenant_from_cookie(request)
    card_number = str(card_number or '').strip()
    if not card_number:
        return HTMLResponse(public_web_shell('כניסת מורה', '<h2>שגיאה</h2><p>חסר כרטיס.</p>'))

    conn = tenant_db_connection(tenant_id)
    try:
        cur = conn.cursor()
        # We assume columns exist or handled by sync
        try:
            cur.execute(
                sql_placeholder(
                    'SELECT id, name, is_admin FROM teachers WHERE card_number = ? OR card_number2 = ? OR card_number3 = ? LIMIT 1'
                ),
                (card_number, card_number, card_number)
            )
            row = cur.fetchone()
            if not row:
                return HTMLResponse(public_web_shell('כניסת מורה', '<h2>שגיאה</h2><p>מורה לא נמצא.</p>'))
            
            t_id = row['id'] if isinstance(row, dict) else row[0]
            
            nxt = web_next_from_request(request, '/web/admin')
            resp = RedirectResponse(url=nxt, status_code=302)
            resp.set_cookie('web_teacher', str(t_id), httponly=True, samesite='lax', max_age=60 * 60 * 24 * 7)
            return resp
        except Exception as e:
             return HTMLResponse(public_web_shell('שגיאה', f'<h2>שגיאה</h2><p>תקלה בבסיס הנתונים: {e}</p>'))
    finally:
        try: conn.close()
        except: pass

@router.get('/web/bootstrap-choice', response_class=HTMLResponse)
def web_bootstrap_choice(request: Request, next: str = Query(default='/web/admin')) -> Response:
    guard = web_require_tenant(request)
    if guard:
        return guard
    tenant_id = web_tenant_from_cookie(request)
    if not tenant_id:
        return RedirectResponse(url='/web/signin', status_code=302)
    nxt = web_next_from_request(request, '/web/admin')
    if nxt in ('/web/login', '/web/signin', '/web/teacher-login'):
        nxt = '/web/admin'

    try:
        tconn = tenant_db_connection(tenant_id)
        try:
            cur = tconn.cursor()
            # Basic check if teachers exist
            try:
                cur.execute('SELECT COUNT(*) FROM teachers')
                row = cur.fetchone()
                cnt = 0
                if row:
                    if isinstance(row, dict):
                        # Handle varied keys: COUNT(*), count, etc.
                        cnt = int(list(row.values())[0] if row else 0)
                    else:
                        cnt = int(row[0])
                
                if cnt > 0:
                    return RedirectResponse(url='/web/teacher-login', status_code=302)
            except Exception:
                pass # Table might not exist yet
        finally:
            try: tconn.close()
            except: pass
    except Exception:
        pass

    body = f"""
    <h2>חיבור ראשוני למוסד</h2>
    <div style="color:#637381; margin-top:-6px; line-height:1.8;">
      נראה שאין עדיין מורים בענן. אם יש לך תוכנה קיימת עם נתונים – יש לבצע חיבור (Pairing) כדי לטעון את המורים והנתונים.
    </div>
    <div class="card" style="margin-top:14px; padding:16px;">
      <div style="font-weight:800;">יש לך תוכנה קיימת?</div>
      <div style="margin-top:6px; color:#637381;">פתח/י את התוכנה בעמדת הניהול, הפעל חיבור, והזן כאן את קוד ההתאמה:</div>
      <form method="get" action="/web/device/pair" style="margin-top:10px; display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
        <input name="code" placeholder="קוד חיבור" style="padding:10px;border:1px solid var(--line);border-radius:10px;font-size:15px; width:200px;" required />
        <button class="green" type="submit">אישור חיבור</button>
      </form>
    </div>
    <div class="card" style="margin-top:14px; padding:16px;">
      <div style="font-weight:800;">אין לך תוכנה קיימת?</div>
      <div style="margin-top:6px; color:#637381;">צור/י מנהל ראשוני חדש בענן.</div>
      <div class="actionbar" style="justify-content:flex-start;">
        <a class="blue" href="/web/bootstrap-admin?next={urllib.parse.quote(nxt, safe='')}">יצירת מנהל ראשוני</a>
      </div>
    </div>
    """
    return HTMLResponse(public_web_shell('חיבור ראשוני', body, request=request))

@router.get('/web/bootstrap-admin', response_class=HTMLResponse)
def web_bootstrap_admin(request: Request, next: str = Query(default='/web/admin')) -> Response:
    guard = web_require_tenant(request)
    if guard:
        return guard
    tenant_id = web_tenant_from_cookie(request)
    if not tenant_id:
        return RedirectResponse(url='/web/signin', status_code=302)
    nxt = web_next_from_request(request, '/web/admin')
    if nxt in ('/web/login', '/web/signin', '/web/teacher-login'):
        nxt = '/web/admin'

    body = f"""
    <h2>הגדרת מנהל ראשוני</h2>
    <div style="color:#637381; margin-top:-6px; line-height:1.8;">נראה שזו כניסה ראשונה למוסד. יש ליצור מורה מנהל ראשוני.</div>
    <form method="post" action="/web/bootstrap-admin?next={urllib.parse.quote(nxt, safe='')}" style="margin-top:12px; max-width:520px;">
      <label style="display:block;margin:10px 0 6px;font-weight:800;">שם המנהל</label>
      <input name="name" class="form-input" required />
      <label style="display:block;margin:10px 0 6px;font-weight:800;">מספר כרטיס מנהל</label>
      <input name="card_number" class="form-input" style="direction:ltr; text-align:left;" required />
      <div class="actionbar" style="justify-content:flex-start;">
        <button class="green" type="submit">יצירה וכניסה</button>
        <a class="gray" href="/web/logout">ביטול</a>
      </div>
    </form>
    """
    return HTMLResponse(public_web_shell('הגדרת מנהל ראשוני', body, request=request))

@router.post('/web/bootstrap-admin', response_class=HTMLResponse)
def web_bootstrap_admin_submit(
    request: Request,
    next: str = Query(default='/web/admin'),
    name: str = Form(default=''),
    card_number: str = Form(default=''),
) -> Response:
    guard = web_require_tenant(request)
    if guard:
        return guard
    tenant_id = web_tenant_from_cookie(request)
    if not tenant_id:
        return RedirectResponse(url='/web/signin', status_code=302)
    nxt = web_next_from_request(request, '/web/admin')
    if nxt in ('/web/login', '/web/signin', '/web/teacher-login'):
        nxt = '/web/admin'

    nm = str(name or '').strip()
    cn = str(card_number or '').strip()
    if not nm or not cn:
        return HTMLResponse(public_web_shell('שגיאה', '<h2>שגיאה</h2><p>חסרים פרטים.</p>', request=request), status_code=400)

    conn = tenant_db_connection(tenant_id)
    try:
        cur = conn.cursor()
        # Check count again
        try:
            cur.execute('SELECT COUNT(*) FROM teachers')
            row = cur.fetchone()
            cnt = 0
            if row:
                cnt = row['COUNT(*)'] if isinstance(row, dict) else row[0]
            if cnt > 0:
                return RedirectResponse(url='/web/teacher-login', status_code=302)
        except Exception:
            pass # Table might not exist, but we assume it does if we are here or we create it

        teacher_id = None
        if USE_POSTGRES:
            cur.execute('SELECT COALESCE(MAX(id), 0) + 1 FROM teachers')
            row = cur.fetchone()
            if isinstance(row, dict):
                # row is dict
                val = list(row.values())[0] if row else 1
                teacher_id = int(val or 1)
            else:
                teacher_id = int((row[0] if row else 1) or 1)
                
            cur.execute(
                sql_placeholder('INSERT INTO teachers (id, name, card_number, is_admin) VALUES (?, ?, ?, 1)'),
                (int(teacher_id), nm, cn)
            )
        else:
            cur.execute(
                sql_placeholder('INSERT INTO teachers (name, card_number, is_admin) VALUES (?, ?, 1)'),
                (nm, cn)
            )
            teacher_id = int(cur.lastrowid or 0)
        conn.commit()
    except Exception as e:
        # Check for integrity error
        err_msg = str(e).lower()
        if 'unique' in err_msg or 'constraint' in err_msg:
             return HTMLResponse(
                public_web_shell('שגיאה', '<h2>שגיאה</h2><p>לא ניתן ליצור מורה. ייתכן שמספר הכרטיס כבר קיים.</p>', request=request),
                status_code=400
            )
        return HTMLResponse(public_web_shell('שגיאה', f'<h2>שגיאה</h2><p>תקלה: {e}</p>'), status_code=500)
    finally:
        try: conn.close()
        except: pass

    resp = RedirectResponse(url=nxt, status_code=302)
    resp.set_cookie('web_teacher', str(teacher_id or ''), httponly=True, samesite='lax', max_age=60 * 60 * 24 * 7)
    return resp

@router.get('/web/whoami')
def web_whoami(request: Request) -> Dict[str, Any]:
    
    tenant_id = web_tenant_from_cookie(request)
    teacher_id = web_teacher_from_cookie(request)
    inst_name = ''
    teacher_name = ''
    is_admin = False
    
    if tenant_id:
        try:
            conn = get_db_connection()
            try:
                cur = conn.cursor()
                cur.execute(sql_placeholder('SELECT name FROM institutions WHERE tenant_id = ? LIMIT 1'), (tenant_id,))
                row = cur.fetchone()
                if row:
                    inst_name = row['name'] if isinstance(row, dict) else row[0]
            finally:
                conn.close()
            
            if teacher_id:
                try:
                    tconn = tenant_db_connection(tenant_id)
                    try:
                        cur = tconn.cursor()
                        cur.execute(sql_placeholder('SELECT name, is_admin FROM teachers WHERE id = ? LIMIT 1'), (int(teacher_id),))
                        trow = cur.fetchone()
                        if trow:
                            teacher_name = trow['name'] if isinstance(trow, dict) else trow[0]
                            ia = trow['is_admin'] if isinstance(trow, dict) else trow[1]
                            is_admin = (ia == 1)
                    finally:
                        tconn.close()
                except:
                    pass
        except: pass

    return {
        'tenant_id': tenant_id,
        'institution_name': inst_name,
        'teacher_id': teacher_id,
        'teacher_name': teacher_name,
        'is_admin': is_admin
    }
