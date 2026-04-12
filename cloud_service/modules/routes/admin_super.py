from fastapi import APIRouter, Request, Response, Form, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from typing import Dict, Any, List, Optional
import datetime
import secrets
import json
import logging

from ..ui import basic_web_shell
from ..db import get_db_connection, sql_placeholder, ensure_tenant_db_exists, delete_tenant_db, tenant_db_connection, generate_numeric_tenant_id
from ..config import ADMIN_KEY, MASTER_LOGIN_SECRET, USE_POSTGRES, DATA_DIR
from ..auth import pbkdf2_hash
from ..admin_db import ensure_admin_tables, get_tenant_stats, get_all_plans, row_to_dict, verify_staff_login
import os
import shutil

logger = logging.getLogger("schoolpoints.admin")
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

_ADMIN_NAV = """
<div style="background:rgba(0,0,0,0.06);border-radius:14px;padding:8px 16px;margin-bottom:20px;display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
  <a href="/admin/institutions" style="padding:6px 14px;border-radius:10px;font-size:13px;font-weight:700;text-decoration:none;color:#333;background:rgba(255,255,255,0.7);">🏫 מוסדות</a>
  <a href="/admin/plans" style="padding:6px 14px;border-radius:10px;font-size:13px;font-weight:700;text-decoration:none;color:#333;background:rgba(255,255,255,0.7);">💰 מסלולים</a>
  <a href="/admin/payments" style="padding:6px 14px;border-radius:10px;font-size:13px;font-weight:700;text-decoration:none;color:#333;background:rgba(255,255,255,0.7);">💳 תשלומים</a>
  <a href="/admin/staff" style="padding:6px 14px;border-radius:10px;font-size:13px;font-weight:700;text-decoration:none;color:#333;background:rgba(255,255,255,0.7);">👥 צוות</a>
  <a href="/admin/registrations" style="padding:6px 14px;border-radius:10px;font-size:13px;font-weight:700;text-decoration:none;color:#333;background:rgba(255,255,255,0.7);">📋 הרשמות</a>
  <span style="flex:1;"></span>
  <a href="/admin/logout" style="padding:6px 14px;border-radius:10px;font-size:12px;text-decoration:none;color:#e74c3c;">🚪 יציאה</a>
</div>
"""

def super_admin_shell(title: str, body: str, request: Request = None) -> str:
    full_body = _ADMIN_NAV + body
    html = basic_web_shell(title, full_body, request, hide_sidebar=True)
    return html

def require_admin_key(request: Request) -> bool:
    try:
        cookie = request.cookies.get('admin_key')
        expected = admin_expected_key()
        if expected and str(cookie or '').strip() == expected:
            return True
        staff = request.cookies.get('admin_staff_session')
        if staff and _verify_staff_session(staff):
            return True
        if not expected:
            return True
        return False
    except:
        return False

def _verify_staff_session(token: str) -> bool:
    import hmac as _hmac, hashlib as _hl
    try:
        parts = token.split(':', 1)
        if len(parts) != 2: return False
        username, sig = parts
        secret = (admin_expected_key() or 'x').encode()
        exp = _hmac.new(secret, username.encode(), _hl.sha256).hexdigest()
        return _hmac.compare_digest(sig, exp)
    except: return False

def _create_staff_session(username: str) -> str:
    import hmac as _hmac, hashlib as _hl
    secret = (admin_expected_key() or 'x').encode()
    sig = _hmac.new(secret, username.encode(), _hl.sha256).hexdigest()
    return f"{username}:{sig}"

@router.get('/admin/login', response_class=HTMLResponse)
def admin_login_page(request: Request, err: str = '') -> str:
    err_html = f'<div style="background:#fee;color:#c00;padding:10px;border-radius:10px;margin-bottom:14px;text-align:center;">{err}</div>' if err else ''
    body = f"""
    <div style="max-width:420px; margin:40px auto;">
        <h2 style="text-align:center;">כניסת ניהול</h2>
        {err_html}
        <div class="card" style="padding:20px;margin-bottom:16px;">
            <h3 style="margin-top:0;">כניסת צוות</h3>
            <form method="post" action="/admin/login">
                <input type="hidden" name="login_type" value="staff">
                <div style="margin-bottom:10px;"><label style="font-size:12px;color:#666;">שם משתמש</label><input name="username" class="form-input" required autocomplete="username"></div>
                <div style="margin-bottom:10px;"><label style="font-size:12px;color:#666;">סיסמה</label><input name="password" type="password" class="form-input" required autocomplete="current-password"></div>
                <button type="submit" class="btn-primary" style="width:100%;">כניסה</button>
            </form>
        </div>
        <div class="card" style="padding:20px;">
            <h3 style="margin-top:0;">כניסה עם מפתח מנהל</h3>
            <form method="post" action="/admin/login">
                <input type="hidden" name="login_type" value="key">
                <div style="margin-bottom:10px;"><label style="font-size:12px;color:#666;">Admin Key</label><input name="admin_key" type="password" class="form-input" required></div>
                <button type="submit" class="btn-primary" style="width:100%;">כניסה</button>
            </form>
        </div>
    </div>
    """
    return basic_web_shell("כניסת ניהול", body, request)

@router.post('/admin/login')
def admin_login_submit(
    request: Request,
    login_type: str = Form('key'),
    admin_key: str = Form(''),
    username: str = Form(''),
    password: str = Form('')
) -> Response:
    if login_type == 'staff':
        u = str(username or '').strip()
        p = str(password or '').strip()
        if not u or not p:
            return RedirectResponse(url="/admin/login?err=חסר+שם+משתמש+או+סיסמה", status_code=302)
        staff = verify_staff_login(u, p)
        if not staff:
            return RedirectResponse(url="/admin/login?err=שם+משתמש+או+סיסמה+שגויים", status_code=302)
        resp = RedirectResponse(url="/admin/institutions", status_code=302)
        token = _create_staff_session(u)
        resp.set_cookie('admin_staff_session', token, httponly=True, samesite='lax', max_age=60*60*8)
        return resp
    else:
        expected = admin_expected_key()
        if expected and str(admin_key or '').strip() != expected:
            return RedirectResponse(url="/admin/login?err=מפתח+שגוי", status_code=302)
        resp = RedirectResponse(url="/admin/institutions", status_code=302)
        resp.set_cookie('admin_key', str(admin_key or '').strip(), httponly=True, samesite='lax', max_age=60*60*24*30)
        return resp

@router.get('/admin/logout')
def admin_logout() -> Response:
    resp = RedirectResponse(url="/admin/login", status_code=302)
    resp.delete_cookie('admin_key')
    resp.delete_cookie('admin_staff_session')
    return resp

@router.get('/admin/institutions', response_class=HTMLResponse)
def admin_institutions(request: Request) -> str:
    if not require_admin_key(request):
        return RedirectResponse(url="/admin/login", status_code=302) # type: ignore

    ensure_admin_tables()
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        try:
            cur.execute('SELECT tenant_id, name, api_key, created_at, contact_name, email, phone, plan, last_login, login_count, custom_price, license_expiry, max_stations FROM institutions ORDER BY created_at DESC')
        except Exception:
            try: conn.rollback()
            except: pass
            try:
                cur.execute('SELECT tenant_id, name, api_key, created_at, contact_name, email, phone, plan, last_login, login_count FROM institutions ORDER BY created_at DESC')
            except Exception:
                try: conn.rollback()
                except: pass
                cur.execute('SELECT tenant_id, name, api_key, created_at FROM institutions ORDER BY created_at DESC')
        rows = cur.fetchall() or []
        
        plan_colors = {'basic':'#3498db','extended':'#2ecc71','unlimited':'#9b59b6','trial':'#95a5a6'}
        list_html = ""
        for r in rows:
            d = row_to_dict(r)
            if not d:
                d = {'tenant_id': r[0], 'name': r[1], 'api_key': r[2], 'created_at': r[3] if len(r) > 3 else ''}
            tid = d.get('tenant_id') or ''
            plan_val = d.get('plan') or 'trial'
            pc = plan_colors.get(plan_val, '#95a5a6')
            created = str(d.get('created_at') or '-')[:10]
            last_log = str(d.get('last_login') or '-')[:16]
            logins = d.get('login_count') or 0
            cprice = d.get('custom_price') or ''
            lic = d.get('license_expiry') or ''

            list_html += f"""
            <tr style="border-bottom:1px solid #eee;">
                <td style="padding:8px;"><a href="/admin/institutions/{tid}" style="color:#2563eb;font-weight:700;text-decoration:none;">{d.get('name') or ''}</a></td>
                <td style="padding:8px;font-family:monospace;font-size:12px;">{tid}</td>
                <td style="padding:8px;font-size:13px;">{d.get('contact_name') or ''}</td>
                <td style="padding:8px;font-size:13px;">{d.get('email') or ''}</td>
                <td style="padding:8px;font-size:13px;">{d.get('phone') or ''}</td>
                <td style="padding:8px;"><span style="background:{pc};color:#fff;padding:2px 8px;border-radius:10px;font-size:12px;font-weight:700;">{plan_val}</span></td>
                <td style="padding:8px;font-size:12px;">{created}</td>
                <td style="padding:8px;font-size:12px;">{last_log}</td>
                <td style="padding:8px;text-align:center;">{logins}</td>
                <td style="padding:8px;white-space:nowrap;">
                    <a href="/admin/institutions/{tid}" style="font-size:11px;padding:3px 8px;background:#2563eb;color:#fff;border-radius:8px;text-decoration:none;margin-left:4px;">פרטים</a>
                    <form method="post" action="/admin/institutions/master-login" target="_blank" style="display:inline;">
                        <input type="hidden" name="tenant_id" value="{tid}">
                        <button style="font-size:11px;padding:3px 8px;background:#10b981;color:#fff;border:none;border-radius:8px;cursor:pointer;">כניסה</button>
                    </form>
                </td>
            </tr>
            """
    finally:
        try: conn.close()
        except: pass

    plans = get_all_plans()
    plan_opts = ''.join(f'<option value="{p["plan_key"]}">{p["display_name"]} (₪{p["price_monthly"]})</option>' for p in plans)

    body = f"""
    <h2>ניהול מוסדות</h2>
    {admin_status_bar()}

    <div class="card" style="padding:20px;">
        <h3 style="margin-top:0;">יצירת מוסד חדש</h3>
        <form method="post" action="/admin/institutions/create">
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
                <input name="name" placeholder="שם מוסד *" class="form-input" required>
                <input name="contact_name" placeholder="איש קשר" class="form-input">
                <input name="email" placeholder="אימייל" class="form-input" type="email">
                <input name="phone" placeholder="טלפון" class="form-input">
                <input name="tenant_id" placeholder="קוד מוסד (אוטומטי אם ריק)" class="form-input">
                <input name="institution_password" placeholder="סיסמה *" type="password" class="form-input" required>
                <select name="plan" class="form-input"><option value="">בחר מסלול</option>{plan_opts}</select>
                <input name="custom_price" placeholder="מחיר מותאם (אופציונלי)" class="form-input" type="number">
            </div>
            <div style="margin-top:10px;"><button class="btn-primary">צור מוסד</button></div>
        </form>
    </div>

    <div class="card" style="padding:0; margin-top:20px;overflow-x:auto;">
        <table style="width:100%; border-collapse:collapse;font-size:13px;">
            <thead style="background:rgba(0,0,0,0.05);">
                <tr>
                    <th style="padding:8px;text-align:right;">שם</th>
                    <th style="padding:8px;text-align:right;">קוד</th>
                    <th style="padding:8px;text-align:right;">איש קשר</th>
                    <th style="padding:8px;text-align:right;">אימייל</th>
                    <th style="padding:8px;text-align:right;">טלפון</th>
                    <th style="padding:8px;text-align:right;">מסלול</th>
                    <th style="padding:8px;text-align:right;">הרשמה</th>
                    <th style="padding:8px;text-align:right;">כניסה אחרונה</th>
                    <th style="padding:8px;text-align:center;">כניסות</th>
                    <th style="padding:8px;text-align:right;">פעולות</th>
                </tr>
            </thead>
            <tbody>
                {list_html}
            </tbody>
        </table>
    </div>
    """
    return super_admin_shell("\u05e0\u05d9\u05d4\u05d5\u05dc \u05de\u05d5\u05e1\u05d3\u05d5\u05ea", body, request)

@router.post('/admin/institutions/create')
def admin_institution_create(
    request: Request,
    name: str = Form(...),
    tenant_id: str = Form(''),
    institution_password: str = Form(...),
    contact_name: str = Form(''),
    email: str = Form(''),
    phone: str = Form(''),
    plan: str = Form('trial'),
    custom_price: str = Form('')
) -> Response:
    if not require_admin_key(request):
        return Response("Unauthorized", status_code=401)

    ensure_admin_tables()
    name = str(name).strip()
    pw = str(institution_password).strip()
    contact_name = str(contact_name or '').strip()
    email = str(email or '').strip()
    phone = str(phone or '').strip()
    plan = str(plan or 'trial').strip()
    custom_price = str(custom_price or '').strip()

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        if not tenant_id or not str(tenant_id).strip():
            tenant_id = generate_numeric_tenant_id(conn)
        else:
            tenant_id = str(tenant_id).strip()

        api_key = secrets.token_hex(16)
        pw_hash = pbkdf2_hash(pw)

        try:
            cur.execute(sql_placeholder(
                "INSERT INTO institutions (tenant_id,name,api_key,password_hash,contact_name,email,phone,plan,custom_price)"
                " VALUES (?,?,?,?,?,?,?,?,?)"),
                (tenant_id, name, api_key, pw_hash, contact_name, email, phone, plan, custom_price))
        except Exception:
            try: conn.rollback()
            except: pass
            cur.execute(sql_placeholder(
                'INSERT INTO institutions (tenant_id,name,api_key,password_hash) VALUES (?,?,?,?)'),
                (tenant_id, name, api_key, pw_hash))
        conn.commit()
        ensure_tenant_db_exists(tenant_id)
    except Exception as e:
        return HTMLResponse(f"<h3>שגיאה: {e}</h3><a href='/admin/institutions'>חזרה</a>")
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

# ---------------------------------------------------------------------------
# Institution Detail Page
# ---------------------------------------------------------------------------
@router.get('/admin/institutions/{tid}', response_class=HTMLResponse)
def admin_institution_detail(request: Request, tid: str) -> str:
    if not require_admin_key(request):
        return RedirectResponse(url="/admin/login", status_code=302)  # type: ignore
    ensure_admin_tables()

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql_placeholder('SELECT * FROM institutions WHERE tenant_id = ? LIMIT 1'), (tid,))
        row = cur.fetchone()
        if not row:
            return super_admin_shell("לא נמצא", "<h3>מוסד לא נמצא</h3><a href='/admin/institutions'>חזרה</a>", request)
        d = row_to_dict(row)
    finally:
        try: conn.close()
        except: pass

    stats = get_tenant_stats(tid)
    plans = get_all_plans()
    plan_opts = ''.join(
        f'<option value="{p["plan_key"]}" {"selected" if p["plan_key"]==d.get("plan","trial") else ""}>{p["display_name"]} (₪{p["price_monthly"]})</option>'
        for p in plans)

    # Payments for this institution
    payments_html = ""
    total_paid = 0
    try:
        conn2 = get_db_connection()
        cur2 = conn2.cursor()
        cur2.execute(sql_placeholder('SELECT * FROM institution_payments WHERE tenant_id = ? ORDER BY payment_date DESC'), (tid,))
        pay_rows = cur2.fetchall() or []
        for pr in pay_rows:
            pd = row_to_dict(pr)
            amt = int(pd.get('amount') or 0)
            total_paid += amt
            payments_html += f"""<tr style="border-bottom:1px solid #eee;">
                <td style="padding:6px;">{pd.get('payment_date') or '-'}</td>
                <td style="padding:6px;">₪{amt}</td>
                <td style="padding:6px;">{pd.get('payment_method') or '-'}</td>
                <td style="padding:6px;">{pd.get('reference') or ''}</td>
                <td style="padding:6px;font-size:12px;">{pd.get('notes') or ''}</td></tr>"""
        conn2.close()
    except Exception:
        pass

    plan_colors = {'basic':'#3498db','extended':'#2ecc71','unlimited':'#9b59b6','trial':'#95a5a6'}
    plan_val = d.get('plan') or 'trial'
    pc = plan_colors.get(plan_val, '#95a5a6')

    body = f"""
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px;">
        <a href="/admin/institutions" style="font-size:13px;color:#666;text-decoration:none;">← חזרה לרשימה</a>
        <h2 style="margin:0;">{d.get('name','')}</h2>
        <span style="background:{pc};color:#fff;padding:3px 12px;border-radius:12px;font-size:13px;font-weight:700;">{plan_val}</span>
    </div>

    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px;margin-bottom:20px;">
        <div class="card" style="padding:16px;text-align:center;">
            <div style="font-size:28px;font-weight:900;color:#2563eb;">{stats['students']}</div>
            <div style="font-size:13px;color:#666;">תלמידים</div>
        </div>
        <div class="card" style="padding:16px;text-align:center;">
            <div style="font-size:28px;font-weight:900;color:#10b981;">{stats['teachers']}</div>
            <div style="font-size:13px;color:#666;">מורים</div>
        </div>
        <div class="card" style="padding:16px;text-align:center;">
            <div style="font-size:28px;font-weight:900;color:#f59e0b;">₪{total_paid}</div>
            <div style="font-size:13px;color:#666;">שולם סה"כ</div>
        </div>
    </div>

    <div class="card" style="padding:20px;">
        <h3 style="margin-top:0;">עריכת פרטי מוסד</h3>
        <form method="post" action="/admin/institutions/{tid}/update">
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
                <div><label style="font-size:12px;color:#666;">שם מוסד</label><input name="name" value="{d.get('name','')}" class="form-input" required></div>
                <div><label style="font-size:12px;color:#666;">איש קשר</label><input name="contact_name" value="{d.get('contact_name','')}" class="form-input"></div>
                <div><label style="font-size:12px;color:#666;">אימייל</label><input name="email" value="{d.get('email','')}" class="form-input" type="email"></div>
                <div><label style="font-size:12px;color:#666;">טלפון</label><input name="phone" value="{d.get('phone','')}" class="form-input"></div>
                <div><label style="font-size:12px;color:#666;">מסלול</label><select name="plan" class="form-input">{plan_opts}</select></div>
                <div><label style="font-size:12px;color:#666;">מחיר מותאם (₪)</label><input name="custom_price" value="{d.get('custom_price','')}" class="form-input" type="number"></div>
                <div><label style="font-size:12px;color:#666;">תפוגת רישיון</label><input name="license_expiry" value="{d.get('license_expiry','')}" class="form-input" type="date"></div>
                <div><label style="font-size:12px;color:#666;">מקס עמדות</label><input name="max_stations" value="{d.get('max_stations','2')}" class="form-input" type="number"></div>
            </div>
            <div style="margin-top:10px;"><label style="font-size:12px;color:#666;">הערות פנימיות</label><textarea name="notes" class="form-input" rows="2">{d.get('notes','')}</textarea></div>
            <div style="margin-top:12px;display:flex;gap:10px;">
                <button class="btn-primary">שמור שינויים</button>
                <form method="post" action="/admin/institutions/master-login" target="_blank" style="display:inline;">
                    <input type="hidden" name="tenant_id" value="{tid}">
                    <button style="padding:8px 18px;background:#10b981;color:#fff;border:none;border-radius:10px;cursor:pointer;font-weight:700;">כניסה למערכת המוסד</button>
                </form>
            </div>
        </form>
    </div>

    <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:14px;">
        <div class="card" style="padding:14px;">
            <div style="font-size:12px;color:#666;">קוד מוסד</div>
            <div style="font-family:monospace;font-size:16px;font-weight:700;">{tid}</div>
        </div>
        <div class="card" style="padding:14px;">
            <div style="font-size:12px;color:#666;">תאריך הרשמה</div>
            <div style="font-size:15px;">{str(d.get('created_at',''))[:16]}</div>
        </div>
        <div class="card" style="padding:14px;">
            <div style="font-size:12px;color:#666;">כניסה אחרונה</div>
            <div style="font-size:15px;">{str(d.get('last_login','') or '-')[:16]}</div>
        </div>
        <div class="card" style="padding:14px;">
            <div style="font-size:12px;color:#666;">מספר כניסות</div>
            <div style="font-size:15px;">{d.get('login_count',0)}</div>
        </div>
    </div>

    <div class="card" style="padding:20px;margin-top:14px;">
        <h3 style="margin-top:0;">תשלומים</h3>
        <form method="post" action="/admin/payments/add" style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px;">
            <input type="hidden" name="tenant_id" value="{tid}">
            <input name="amount" placeholder="סכום ₪" class="form-input" type="number" required style="width:100px;">
            <input name="payment_date" class="form-input" type="date" style="width:150px;">
            <input name="payment_method" placeholder="אמצעי" class="form-input" style="width:120px;">
            <input name="reference" placeholder="אסמכתא" class="form-input" style="width:120px;">
            <input name="notes" placeholder="הערה" class="form-input" style="flex:1;">
            <button class="btn-primary" style="padding:6px 14px;">הוסף תשלום</button>
        </form>
        <table style="width:100%;border-collapse:collapse;font-size:13px;">
            <thead style="background:rgba(0,0,0,0.04);"><tr>
                <th style="padding:6px;text-align:right;">תאריך</th>
                <th style="padding:6px;text-align:right;">סכום</th>
                <th style="padding:6px;text-align:right;">אמצעי</th>
                <th style="padding:6px;text-align:right;">אסמכתא</th>
                <th style="padding:6px;text-align:right;">הערה</th>
            </tr></thead>
            <tbody>{payments_html if payments_html else '<tr><td colspan="5" style="padding:10px;text-align:center;color:#999;">אין תשלומים</td></tr>'}</tbody>
        </table>
    </div>

    <div class="card" style="padding:14px;margin-top:14px;background:rgba(231,76,60,0.05);">
        <h4 style="color:#e74c3c;margin-top:0;">אזור מסוכן</h4>
        <form method="post" action="/admin/institutions/delete" onsubmit="return confirm('בטוח למחוק? פעולה זו בלתי הפיכה!');">

            <input type="hidden" name="tenant_id" value="{tid}">
            <button style="background:#e74c3c;color:#fff;border:none;padding:8px 18px;border-radius:10px;cursor:pointer;font-weight:700;">מחק מוסד</button>
        </form>
    </div>
    """
    return super_admin_shell(f"מוסד: {d.get('name','')}", body, request)

# ---------------------------------------------------------------------------
# Institution Update
# ---------------------------------------------------------------------------
@router.post('/admin/institutions/{tid}/update')
def admin_institution_update(
    request: Request, tid: str,
    name: str = Form(...), contact_name: str = Form(''),
    email: str = Form(''), phone: str = Form(''),
    plan: str = Form('trial'), custom_price: str = Form(''),
    license_expiry: str = Form(''), max_stations: str = Form('2'),
    notes: str = Form('')
) -> Response:
    if not require_admin_key(request):
        return Response("Unauthorized", status_code=401)
    ensure_admin_tables()
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        try:
            cur.execute(sql_placeholder(
                "UPDATE institutions SET name=?, contact_name=?, email=?, phone=?, plan=?, custom_price=?, license_expiry=?, max_stations=?, notes=? WHERE tenant_id=?"),
                (name.strip(), contact_name.strip(), email.strip(), phone.strip(),
                 plan.strip(), custom_price.strip(), license_expiry.strip(),
                 int(max_stations or 2), notes.strip(), tid))
        except Exception:
            try: conn.rollback()
            except: pass
            cur.execute(sql_placeholder(
                "UPDATE institutions SET name=?, contact_name=?, email=?, phone=?, plan=? WHERE tenant_id=?"),
                (name.strip(), contact_name.strip(), email.strip(), phone.strip(), plan.strip(), tid))
        conn.commit()
    finally:
        try: conn.close()
        except: pass
    return RedirectResponse(url=f"/admin/institutions/{tid}", status_code=302)

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
