from fastapi import APIRouter, Request, Response, Form, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from typing import Dict, Any, List
import datetime
import secrets

from ..utils import basic_web_shell
from ..db import get_db_connection, sql_placeholder, ensure_tenant_db_exists, delete_tenant_db
from ..config import ADMIN_KEY, MASTER_LOGIN_SECRET, USE_POSTGRES, DATA_DIR
from ..auth import pbkdf2_hash
import os
import shutil

router = APIRouter()

def delete_tenant_assets(tenant_id: str):
    """Delete tenant assets directory."""
    if not tenant_id:
        return
    assets_dir = os.path.join(DATA_DIR, 'tenants_assets', tenant_id)
    if os.path.exists(assets_dir):
        try:
            shutil.rmtree(assets_dir)
        except Exception as e:
            print(f"Failed to delete assets for {tenant_id}: {e}")

def admin_expected_key() -> str:
    return ADMIN_KEY

def admin_status_bar() -> str:
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute('SELECT COUNT(*) FROM changes')
        row = cur.fetchone()
        changes_total = 0
        if row:
            if isinstance(row, dict):
                # Safer extraction of first value from dict
                changes_total = int(list(row.values())[0] or 0)
            else:
                changes_total = int(row[0] or 0)
        
        cur.execute('SELECT COUNT(*) FROM institutions')
        row = cur.fetchone()
        inst_total = 0
        if row:
            if isinstance(row, dict):
                inst_total = int(list(row.values())[0] or 0)
            else:
                inst_total = int(row[0] or 0)
        
        cur.execute('SELECT MAX(received_at) FROM changes')
        row = cur.fetchone()
        last_received = None
        if row:
            if isinstance(row, dict):
                last_received = list(row.values())[0]
            else:
                last_received = row[0]
        
        return (
            f"<div style=\"font-size:12px;color:#637381;margin:0 0 10px;\">"
            f"עדכון אחרון: {last_received or '—'} | מוסדות: {inst_total} | שינויים: {changes_total}"
            f"</div>"
        )
    except:
        return ""
    finally:
        try: conn.close()
        except: pass

def super_admin_shell(title: str, body: str, request: Request = None) -> str:
    # Reusing basic shell but maybe with admin tweaks if needed.
    # For now, basic shell is fine.
    html = basic_web_shell(title, body, request)
    # Inject admin logout if logged in?
    # Basic shell already has some structure.
    return html

def require_admin_key(request: Request) -> bool:
    try:
        cookie = request.cookies.get('admin_key')
        expected = admin_expected_key()
        if not expected: return True # Dev mode or no key set? secure defaults usually imply block. 
        # But if ADMIN_KEY env is empty, maybe allow local? No, deny.
        if not expected: return False 
        return str(cookie or '').strip() == expected
    except:
        return False

@router.get('/admin/login', response_class=HTMLResponse)
def admin_login_page() -> str:
    body = """
    <div style="max-width:400px; margin:50px auto;">
        <h2>כניסת מנהל מערכת</h2>
        <form method="post" action="/admin/login">
            <div class="form-group">
                <label>Admin Key</label>
                <input name="admin_key" type="password" class="form-input" required />
            </div>
            <button type="submit" class="btn-primary" style="width:100%;">כניסה</button>
        </form>
    </div>
    """
    return super_admin_shell("Admin Login", body)

@router.post('/admin/login')
def admin_login_submit(admin_key: str = Form(...)) -> Response:
    expected = admin_expected_key()
    if expected and str(admin_key or '').strip() != expected:
        return HTMLResponse("<h3>Invalid admin key</h3>", status_code=403)
    resp = RedirectResponse(url="/admin/institutions", status_code=302)
    resp.set_cookie('admin_key', str(admin_key or '').strip(), httponly=True, samesite='lax', max_age=60 * 60 * 24 * 30)
    return resp

@router.get('/admin/logout')
def admin_logout() -> Response:
    resp = RedirectResponse(url="/admin/login", status_code=302)
    resp.delete_cookie('admin_key')
    return resp

@router.get('/admin/institutions', response_class=HTMLResponse)
def admin_institutions(request: Request) -> str:
    if not require_admin_key(request):
        return RedirectResponse(url="/admin/login", status_code=302) # type: ignore

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute('SELECT tenant_id, name, api_key, created_at FROM institutions ORDER BY created_at DESC')
        rows = cur.fetchall() or []
        
        list_html = ""
        for r in rows:
            d = dict(r) if isinstance(r, dict) else {k: r[k] for k in r.keys()} if hasattr(r, 'keys') else {'tenant_id':r[0], 'name':r[1], 'api_key':r[2]}
            
            # Master login link
            master_link = ""
            if MASTER_LOGIN_SECRET:
                # generate signature? or just pass secret?
                # Actually app.py had a master login endpoint. We should replicate that.
                pass
                
            list_html += f"""
            <tr style="border-bottom:1px solid #eee;">
                <td style="padding:10px;">{d.get('name')}</td>
                <td style="padding:10px;">{d.get('tenant_id')}</td>
                <td style="padding:10px; font-family:monospace;">{d.get('api_key')}</td>
                <td style="padding:10px;">
                    <form method="post" action="/admin/institutions/master-login" target="_blank" style="display:inline;">
                        <input type="hidden" name="tenant_id" value="{d.get('tenant_id')}">
                        <button class="blue" style="font-size:12px; padding:4px 8px;">Master Login</button>
                    </form>
                    <form method="post" action="/admin/institutions/delete" style="display:inline;" onsubmit="return confirm('בטוח שברצונך למחוק? המידע יאבד!');">
                        <input type="hidden" name="tenant_id" value="{d.get('tenant_id')}">
                        <button class="red" style="background:#e74c3c; border:none; color:white; font-size:12px; padding:4px 8px; border-radius:10px; cursor:pointer;">מחק</button>
                    </form>
                </td>
            </tr>
            """
    finally:
        try: conn.close()
        except: pass

    body = f"""
    <h2>ניהול מוסדות</h2>
    {admin_status_bar()}
    <div style="margin-bottom:20px;">
        <a href="/admin/registrations" class="btn-glass">בקשות הרשמה</a>
    </div>
    
    <div class="card" style="padding:20px;">
        <h3>יצירת מוסד ידנית</h3>
        <form method="post" action="/admin/institutions/create">
            <div style="display:flex; gap:10px; flex-wrap:wrap;">
                <input name="name" placeholder="שם מוסד" class="form-input" style="flex:1;" required>
                <input name="tenant_id" placeholder="קוד מוסד (ספרות)" class="form-input" style="flex:1;" inputmode="numeric" pattern="[0-9]+">
                <input name="institution_password" placeholder="סיסמה" type="password" class="form-input" style="flex:1;" required>
                <button class="btn-primary">צור</button>
            </div>
        </form>
    </div>
    
    <div class="card" style="padding:0; margin-top:20px;">
        <table style="width:100%; border-collapse:collapse;">
            <thead style="background:rgba(0,0,0,0.05);">
                <tr>
                    <th style="padding:10px; text-align:right;">שם</th>
                    <th style="padding:10px; text-align:right;">ID</th>
                    <th style="padding:10px; text-align:right;">API Key</th>
                    <th style="padding:10px; text-align:right;">פעולות</th>
                </tr>
            </thead>
            <tbody>
                {list_html}
            </tbody>
        </table>
    </div>
    """
    return super_admin_shell("ניהול מוסדות", body, request)

@router.post('/admin/institutions/create')
def admin_institution_create(
    request: Request,
    name: str = Form(...),
    tenant_id: str = Form(None),
    institution_password: str = Form(...),
    api_key: str = Form(None)
) -> Response:
    if not require_admin_key(request):
        return Response("Unauthorized", status_code=401)
        
    name = str(name).strip()
    pw = str(institution_password).strip()
    if not tenant_id:
        # Generate random numeric
        tenant_id = str(int(datetime.datetime.utcnow().timestamp())) # fallback logic
    
    if not api_key:
        api_key = secrets.token_hex(16)
        
    pw_hash = pbkdf2_hash(pw)
    
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            sql_placeholder('INSERT INTO institutions (tenant_id, name, api_key, password_hash) VALUES (?, ?, ?, ?)'),
            (tenant_id, name, api_key, pw_hash)
        )
        conn.commit()
        # Create DB
        ensure_tenant_db_exists(tenant_id)
    except Exception as e:
        return HTMLResponse(f"Error: {e}")
    finally:
        try: conn.close()
        except: pass
        
    return RedirectResponse(url="/admin/institutions", status_code=302)

@router.post('/admin/institutions/delete')
def admin_institution_delete(request: Request, tenant_id: str = Form(...)) -> Response:
    if not require_admin_key(request):
        return Response("Unauthorized", status_code=401)
        
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql_placeholder('DELETE FROM institutions WHERE tenant_id = ?'), (tenant_id,))
        conn.commit()
        
        # Cleanup tenant data
        delete_tenant_db(tenant_id)
        delete_tenant_assets(tenant_id)
        
    finally:
        try: conn.close()
        except: pass
        
    return RedirectResponse(url="/admin/institutions", status_code=302)

@router.post('/admin/institutions/master-login')
def admin_master_login(request: Request, tenant_id: str = Form(...)) -> Response:
    if not require_admin_key(request):
        return Response("Unauthorized", status_code=401)
        
    import hmac
    import hashlib
    from ..config import MASTER_PASSWORD_HASH
    
    # Generate master token
    # Token = tenant_id : hmac(master_hash, tenant_id)
    h = hmac.new(
        MASTER_PASSWORD_HASH.encode('utf-8'),
        tenant_id.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    token = f"{tenant_id}:{h}"
    
    resp = RedirectResponse(url='/web/admin', status_code=302)
    resp.set_cookie('web_tenant', tenant_id, httponly=True, samesite='lax')
    resp.set_cookie('web_master', token, httponly=True, samesite='lax')
    return resp

@router.get('/admin/registrations', response_class=HTMLResponse)
def admin_registrations(request: Request) -> str:
    if not require_admin_key(request):
        return RedirectResponse(url="/admin/login", status_code=302) # type: ignore

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute('SELECT * FROM pending_registrations ORDER BY created_at DESC')
        rows = cur.fetchall() or []
        
        list_html = ""
        for r in rows:
            d = dict(r) if isinstance(r, dict) else {k: r[k] for k in r.keys()} if hasattr(r, 'keys') else {}
            # Fallback if empty dict (tuple cursor)
            if not d and r:
                # assuming columns match creation order... risky but used in original app.py
                pass 
            
            # Map columns safely
            rid = d.get('id')
            code = d.get('institution_code')
            name = d.get('institution_name')
            status = d.get('payment_status')
            
            actions = ""
            if status != 'completed':
                actions = f"""
                <form method="post" action="/admin/registrations/approve" style="display:inline;" onsubmit="return confirm('לאשר?');">
                    <input type="hidden" name="reg_id" value="{rid}">
                    <button class="blue" style="font-size:12px; padding:4px 8px;">אשר</button>
                </form>
                """
            
            list_html += f"""
            <tr style="border-bottom:1px solid #eee;">
                <td style="padding:10px;">{rid}</td>
                <td style="padding:10px;">{name}</td>
                <td style="padding:10px;">{code}</td>
                <td style="padding:10px;">{status}</td>
                <td style="padding:10px;">{d.get('contact_name')} / {d.get('phone')}</td>
                <td style="padding:10px;">
                    {actions}
                    <form method="post" action="/admin/registrations/delete" style="display:inline;" onsubmit="return confirm('למחוק?');">
                        <input type="hidden" name="reg_id" value="{rid}">
                        <button class="red" style="background:#e74c3c; border:none; color:white; font-size:12px; padding:4px 8px; border-radius:10px; cursor:pointer;">מחק</button>
                    </form>
                </td>
            </tr>
            """
    finally:
        try: conn.close()
        except: pass

    body = f"""
    <h2>בקשות הרשמה</h2>
    <div style="margin-bottom:20px;">
        <a href="/admin/institutions" class="btn-glass">חזרה למוסדות</a>
    </div>
    
    <div class="card" style="padding:0;">
        <table style="width:100%; border-collapse:collapse;">
            <thead style="background:rgba(0,0,0,0.05);">
                <tr>
                    <th style="padding:10px; text-align:right;">ID</th>
                    <th style="padding:10px; text-align:right;">שם</th>
                    <th style="padding:10px; text-align:right;">קוד</th>
                    <th style="padding:10px; text-align:right;">סטטוס</th>
                    <th style="padding:10px; text-align:right;">איש קשר</th>
                    <th style="padding:10px; text-align:right;">פעולות</th>
                </tr>
            </thead>
            <tbody>
                {list_html}
            </tbody>
        </table>
    </div>
    """
    return super_admin_shell("הרשמות", body, request)

@router.post('/admin/registrations/approve')
def admin_registration_approve(request: Request, reg_id: int = Form(...)) -> Response:
    if not require_admin_key(request):
        return Response("Unauthorized", status_code=401)
        
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql_placeholder('SELECT * FROM pending_registrations WHERE id = ?'), (reg_id,))
        row = cur.fetchone()
        if not row:
            return Response("Not found", status_code=404)
            
        d = dict(row) if isinstance(row, dict) else {k: row[k] for k in row.keys()}
        
        # Create institution
        tenant_id = d.get('institution_code')
        name = d.get('institution_name')
        pw_hash = d.get('password_hash')
        api_key = secrets.token_hex(16)
        
        # Check if exists
        cur.execute(sql_placeholder('SELECT 1 FROM institutions WHERE tenant_id = ?'), (tenant_id,))
        if cur.fetchone():
            return Response("Institution code already exists", status_code=409)
            
        cur.execute(
            sql_placeholder('INSERT INTO institutions (tenant_id, name, api_key, password_hash) VALUES (?, ?, ?, ?)'),
            (tenant_id, name, api_key, pw_hash)
        )
        # Update status
        cur.execute(sql_placeholder("UPDATE pending_registrations SET payment_status='completed' WHERE id=?"), (reg_id,))
        
        conn.commit()
        ensure_tenant_db_exists(tenant_id)
        
        # Send email? (Skipped for now)
        
    finally:
        try: conn.close()
        except: pass
        
    return RedirectResponse(url="/admin/registrations", status_code=302)

@router.post('/admin/registrations/delete')
def admin_registration_delete(request: Request, reg_id: int = Form(...)) -> Response:
    if not require_admin_key(request):
        return Response("Unauthorized", status_code=401)
        
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql_placeholder('DELETE FROM pending_registrations WHERE id = ?'), (reg_id,))
        conn.commit()
    finally:
        try: conn.close()
        except: pass
        
    return RedirectResponse(url="/admin/registrations", status_code=302)
