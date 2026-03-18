from fastapi import APIRouter, Request, Body, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from typing import Dict, Any
import datetime, secrets, re, html as html_mod, logging

from ..db import (
    get_db_connection, sql_placeholder, integrity_errors,
    ensure_pending_registrations_table, ensure_tenant_db_exists,
    generate_numeric_tenant_id, ensure_password_reset_tokens_table
)
from ..config import USE_POSTGRES, REGISTRATION_NOTIFY_EMAIL
from ..auth import pbkdf2_hash, check_password_hash
from ..email import send_email
from ..ui import public_web_shell

router = APIRouter()
logger = logging.getLogger("schoolpoints.register")

_FORM_CSS = """
<style>
.rw{max-width:700px;margin:0 auto;padding:20px}
.rh{text-align:center;margin-bottom:36px}
.rh h2{font-size:42px;margin:0 0 14px;background:linear-gradient(135deg,#667eea,#764ba2);-webkit-background-clip:text;-webkit-text-fill-color:transparent;font-weight:700}
.rh p{font-size:18px;margin:0;opacity:.9;line-height:1.6}
.rc{background:var(--glass-bg);backdrop-filter:blur(24px);-webkit-backdrop-filter:blur(24px);border:1px solid var(--glass-border);border-radius:24px;padding:40px;box-shadow:0 20px 60px rgba(0,0,0,.1)}
.st{font-size:22px;font-weight:700;margin:28px 0 18px;padding-bottom:10px;border-bottom:1px solid rgba(255,255,255,.1)}
.st:first-child{margin-top:0}
.fg{margin-bottom:20px}
.fg label{display:block;margin-bottom:8px;font-size:15px;font-weight:600;color:var(--text-primary)}
.ri{width:100%;padding:14px 18px;font-size:15px;border:2px solid var(--glass-border);border-radius:12px;background:rgba(255,255,255,.05);color:var(--text-primary);transition:all .3s;box-sizing:border-box}
.ri:focus{border-color:#667eea;background:rgba(255,255,255,.08);outline:none;box-shadow:0 0 0 3px rgba(102,126,234,.1)}
.ht{font-size:12px;opacity:.6;margin-top:4px}
.cb{display:flex;align-items:flex-start;gap:12px;margin:24px 0}
.cb input[type=checkbox]{width:20px;height:20px;margin-top:2px}
.cb label{margin:0;font-weight:400;line-height:1.6}
.cb a{color:#667eea;text-decoration:none;font-weight:600}
.ss{margin-top:32px;text-align:center}
.bp{padding:16px 44px;font-size:19px;font-weight:700;border-radius:12px;background:linear-gradient(135deg,#667eea,#764ba2);border:none;color:#fff;cursor:pointer;transition:all .3s;width:100%;max-width:400px}
.bp:hover{transform:translateY(-2px);box-shadow:0 10px 30px rgba(102,126,234,.3)}
.bp:disabled{opacity:.6;cursor:not-allowed;transform:none}
.mo{padding:16px 20px;border-radius:12px;margin:16px 0;font-size:15px;line-height:1.6}
.mok{background:rgba(46,204,113,.12);border:1px solid rgba(46,204,113,.3);color:#2ecc71}
.mer{background:rgba(231,76,60,.12);border:1px solid rgba(231,76,60,.3);color:#e74c3c}
.lr{margin-top:20px;font-size:15px;text-align:center}
.lr a{color:#667eea;text-decoration:none;font-weight:600;margin:0 8px}
.lr a:hover{text-decoration:underline}
@media(max-width:768px){.rc{padding:28px 20px}.rh h2{font-size:32px}}
</style>
"""

@router.get('/web/register', response_class=HTMLResponse)
def web_register(request: Request) -> str:
    body = _FORM_CSS + _REG_FORM
    return public_web_shell("\u05e4\u05ea\u05d9\u05d7\u05ea \u05d7\u05e9\u05d1\u05d5\u05df", body, request=request)


_REG_FORM = """
<div class="rw"><div class="rh">
<h2>פתיחת חשבון מוסד</h2>
<p>הצטרפו למערכת ניהול הנקודות המתקדמת בישראל</p></div>
<form id="regForm" onsubmit="submitReg(event)"><div class="rc">
<div class="st">פרטי המוסד</div>
<div class="fg"><label>שם המוסד *</label><input name="institution_name" class="ri" required placeholder="לדוגמה: בית ספר השלום"/></div>
<div class="fg"><label>קוד מוסד (מזהה ייחודי) *</label><input name="institution_code" class="ri" required pattern="[a-zA-Z0-9_-]+" placeholder="אותיות וספרות, ללא רווחים" style="direction:ltr;text-align:left;"/><div class="ht">קוד זה ישמש לכניסה. לדוגמה: shalom_school</div></div>
<div class="st">איש קשר</div>
<div class="fg"><label>שם מלא *</label><input name="contact_name" class="ri" required placeholder="שם פרטי ושם משפחה"/></div>
<div class="fg"><label>אימייל *</label><input name="email" type="email" class="ri" required placeholder="name@example.com" style="direction:ltr;text-align:left;"/></div>
<div class="fg"><label>טלפון</label><input name="phone" class="ri" placeholder="050-1234567" style="direction:ltr;text-align:left;"/></div>
<div class="st">סיסמה</div>
<div class="fg"><label>סיסמת ניהול *</label><input name="password" type="password" class="ri" required minlength="4" placeholder="לפחות 4 תווים"/></div>
<div class="fg"><label>אימות סיסמה *</label><input name="password2" type="password" class="ri" required minlength="4" placeholder="הזן שוב"/></div>
<div class="cb"><input type="checkbox" id="terms" name="terms" required><label for="terms">קראתי ואני מסכים/ה ל<a href="/web/terms" target="_blank">תנאי השימוש</a></label></div>
<div id="regMsg"></div>
<div class="ss"><button type="submit" class="bp" id="submitBtn">פתיחת חשבון</button></div>
<div class="lr">כבר יש לך חשבון? <a href="/web/signin">כניסה</a> | <a href="/web/forgot-password">שכחתי סיסמה</a></div>
</div></form></div>
<script>
async function submitReg(e){
  e.preventDefault();
  const btn=document.getElementById("submitBtn"),msg=document.getElementById("regMsg");
  const fd=new FormData(e.target),d=Object.fromEntries(fd.entries());
  d.terms=!!document.getElementById("terms").checked;
  if(d.password!==d.password2){msg.className="mo mer";msg.textContent="הסיסמאות אינן תואמות";return;}
  btn.disabled=true;btn.textContent="מעבד...";msg.className="";msg.textContent="";
  try{
    const r=await fetch("/api/register",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(d)});
    const j=await r.json();
    if(r.ok&&j.ok){msg.className="mo mok";msg.innerHTML="החשבון נפתח בהצלחה! מיד תועבר/י...";setTimeout(()=>{window.location.href="/web/signin";},2000);}
    else{let det=j.detail||"שגיאה";msg.className="mo mer";msg.textContent=det;btn.disabled=false;btn.textContent="פתיחת חשבון";}
  }catch(err){msg.className="mo mer";msg.textContent="שגיאת תקשורת: "+err;btn.disabled=false;btn.textContent="פתיחת חשבון";}
}
</script>
"""

@router.post('/api/register')
def api_register(request: Request, payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    ensure_pending_registrations_table()
    inst_name = str(payload.get('institution_name') or '').strip()
    inst_code = str(payload.get('institution_code') or '').strip()
    contact   = str(payload.get('contact_name') or '').strip()
    email     = str(payload.get('email') or '').strip()
    phone     = str(payload.get('phone') or '').strip()
    password  = str(payload.get('password') or '').strip()
    terms_ok  = payload.get('terms')
    if not inst_name or not email or not password or not contact:
        raise HTTPException(status_code=400, detail="\u05d7\u05e1\u05e8\u05d9\u05dd \u05e9\u05d3\u05d5\u05ea \u05d7\u05d5\u05d1\u05d4")
    if not terms_ok:
        raise HTTPException(status_code=400, detail="\u05d9\u05e9 \u05dc\u05d0\u05e9\u05e8 \u05d0\u05ea \u05ea\u05e0\u05d0\u05d9 \u05d4\u05e9\u05d9\u05de\u05d5\u05e9")
    if not inst_code:
        raise HTTPException(status_code=400, detail="\u05d7\u05e1\u05e8 \u05e7\u05d5\u05d3 \u05de\u05d5\u05e1\u05d3")
    if not re.match(r'^[a-zA-Z0-9\-_]+$', inst_code):
        raise HTTPException(status_code=400, detail="\u05e7\u05d5\u05d3 \u05de\u05d5\u05e1\u05d3 \u05d7\u05d9\u05d9\u05d1 \u05dc\u05d4\u05db\u05d9\u05dc \u05d0\u05d5\u05ea\u05d9\u05d5\u05ea \u05d5\u05e1\u05e4\u05e8\u05d5\u05ea \u05d1\u05dc\u05d1\u05d3")
    if len(password) < 4:
        raise HTTPException(status_code=400, detail="\u05e1\u05d9\u05e1\u05de\u05d4 \u05d7\u05d9\u05d9\u05d1\u05ea \u05dc\u05e4\u05d7\u05d5\u05ea 4 \u05ea\u05d5\u05d5\u05d9\u05dd")
    password_hash = pbkdf2_hash(password)
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql_placeholder('SELECT 1 FROM institutions WHERE tenant_id = ? LIMIT 1'), (inst_code,))
        if cur.fetchone():
            raise HTTPException(status_code=409, detail='institution_code already exists')
        try:
            cur.execute(sql_placeholder('SELECT 1 FROM institutions WHERE email = ? LIMIT 1'), (email,))
            if cur.fetchone():
                raise HTTPException(status_code=409, detail='email already registered')
        except HTTPException:
            raise
        except Exception:
            pass
        api_key = secrets.token_urlsafe(24)
        try:
            cur.execute(sql_placeholder(
                "INSERT INTO institutions (tenant_id, name, api_key, password_hash, contact_name, email, phone, plan)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)"),
                (inst_code, inst_name, api_key, password_hash, contact, email, phone, 'trial'))
        except Exception as e:
            logger.error(f"Insert institution error: {e}")
            cur.execute(sql_placeholder(
                "INSERT INTO institutions (tenant_id, name, api_key, password_hash)"
                " VALUES (?, ?, ?, ?)"),
                (inst_code, inst_name, api_key, password_hash))
        try:
            ensure_tenant_db_exists(str(inst_code))
        except Exception as e:
            try: conn.rollback()
            except: pass
            raise HTTPException(status_code=500, detail=f'DB creation failed: {e}')
        conn.commit()
        _send_welcome_email(contact, email, inst_name, inst_code)
        if REGISTRATION_NOTIFY_EMAIL:
            try:
                abody = '<div dir="rtl">'
                abody += f'<h3>\u05de\u05d5\u05e1\u05d3 \u05d7\u05d3\u05e9</h3>'
                abody += f'<b>\u05de\u05d5\u05e1\u05d3:</b> {html_mod.escape(inst_name)}<br>'
                abody += f'<b>\u05e7\u05d5\u05d3:</b> {html_mod.escape(inst_code)}<br>'
                abody += f'<b>\u05d0\u05d9\u05e9 \u05e7\u05e9\u05e8:</b> {html_mod.escape(contact)}<br>'
                abody += f'<b>\u05d0\u05d9\u05de\u05d9\u05d9\u05dc:</b> {html_mod.escape(email)}<br>'
                abody += f'<b>\u05d8\u05dc\u05e4\u05d5\u05df:</b> {html_mod.escape(phone)}</div>'
                send_email(REGISTRATION_NOTIFY_EMAIL, 'SchoolPoints: new institution', abody)
            except Exception:
                pass
        return {'ok': True, 'tenant_id': inst_code}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Register error: {e}")
        raise HTTPException(status_code=500, detail="Internal error")
    finally:
        try: conn.close()
        except: pass

def _send_welcome_email(contact, email, inst_name, inst_code):
    try:
        body = '<div dir="rtl" style="font-family:Arial;line-height:1.8;color:#333;">'
        body += '<h2 style="color:#2ecc71;">\u05d1\u05e8\u05d5\u05db\u05d9\u05dd \u05d4\u05d1\u05d0\u05d9\u05dd \u05dc-SchoolPoints!</h2>'
        body += f'<p>\u05e9\u05dc\u05d5\u05dd {html_mod.escape(contact)},</p>'
        body += f'<p>\u05d4\u05d7\u05e9\u05d1\u05d5\u05df \u05e9\u05dc <b>{html_mod.escape(inst_name)}</b> \u05e0\u05e4\u05ea\u05d7 \u05d1\u05d4\u05e6\u05dc\u05d7\u05d4!</p>'
        body += f'<p><b>\u05e7\u05d5\u05d3 \u05de\u05d5\u05e1\u05d3:</b> {html_mod.escape(inst_code)}</p>'
        body += '<p>\u05db\u05d3\u05d9 \u05dc\u05d4\u05ea\u05d7\u05d9\u05dc \u05dc\u05d4\u05e9\u05ea\u05de\u05e9 \u05d1\u05de\u05e2\u05e8\u05db\u05ea:</p>'
        body += '<ol>'
        body += '<li>\u05d4\u05d9\u05db\u05e0\u05e1\u05d5 \u05dc- <a href="https://schoolpoints.co.il/web/signin">\u05d3\u05e3 \u05d4\u05db\u05e0\u05d9\u05e1\u05d4</a></li>'
        body += f'<li>\u05d4\u05d6\u05d9\u05e0\u05d5 \u05d0\u05ea \u05e7\u05d5\u05d3 \u05d4\u05de\u05d5\u05e1\u05d3: <b>{html_mod.escape(inst_code)}</b></li>'
        body += '<li>\u05d4\u05d6\u05d9\u05e0\u05d5 \u05d0\u05ea \u05d4\u05e1\u05d9\u05e1\u05de\u05d4 \u05e9\u05d1\u05d7\u05e8\u05ea\u05dd</li>'
        body += '</ol>'
        body += '<p>\u05d1\u05d4\u05e6\u05dc\u05d7\u05d4!<br>\u05e6\u05d5\u05d5\u05ea SchoolPoints</p></div>'
        send_email(email, 'SchoolPoints - \u05d1\u05e8\u05d5\u05db\u05d9\u05dd \u05d4\u05d1\u05d0\u05d9\u05dd!', body)
    except Exception as e:
        logger.error(f"Welcome email error: {e}")

# ============================================================================
#  FORGOT PASSWORD PAGE
# ============================================================================
@router.get('/web/forgot-password', response_class=HTMLResponse)
def web_forgot_password(request: Request) -> str:
    body = _FORM_CSS + _FORGOT_HTML
    return public_web_shell("\u05e9\u05db\u05d7\u05ea\u05d9 \u05e1\u05d9\u05e1\u05de\u05d4", body, request=request)

_FORGOT_HTML = """
<div class="rw"><div class="rh">
<h2>שכחתי סיסמה</h2>
<p>הזינו את כתובת האימייל שלכם ונשלח קישור לאיפוס</p></div>
<form id="fForm" onsubmit="submitForgot(event)"><div class="rc">
<div class="fg"><label>אימייל</label><input name="email" type="email" class="ri" required placeholder="name@example.com" style="direction:ltr;text-align:left;"/></div>
<div id="fMsg"></div>
<div class="ss"><button type="submit" class="bp" id="fBtn">שלח קישור איפוס</button></div>
<div class="lr"><a href="/web/signin">חזרה לכניסה</a> | <a href="/web/register">פתיחת חשבון</a></div>
</div></form></div>
<script>
async function submitForgot(e){
  e.preventDefault();
  const btn=document.getElementById("fBtn"),msg=document.getElementById("fMsg");
  const em=e.target.email.value;
  btn.disabled=true;btn.textContent="שולח...";msg.className="";msg.textContent="";
  try{
    const r=await fetch("/api/forgot-password",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({email:em})});
    const j=await r.json();
    msg.className="mo mok";msg.textContent=j.message||"אם האימייל קיים במערכת, נשלח קישור איפוס.";
  }catch(err){msg.className="mo mer";msg.textContent="שגיאה: "+err;}
  btn.disabled=false;btn.textContent="שלח קישור איפוס";
}
</script>
"""

@router.post('/api/forgot-password')
def api_forgot_password(request: Request, payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    ensure_password_reset_tokens_table()
    email = str(payload.get('email') or '').strip()
    if not email:
        raise HTTPException(status_code=400, detail="Missing email")
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql_placeholder('SELECT tenant_id, name FROM institutions WHERE email = ? LIMIT 1'), (email,))
        row = cur.fetchone()
        if not row:
            return {'ok': True, 'message': '\u05d0\u05dd \u05d4\u05d0\u05d9\u05de\u05d9\u05d9\u05dc \u05e7\u05d9\u05d9\u05dd \u05d1\u05de\u05e2\u05e8\u05db\u05ea, \u05e0\u05e9\u05dc\u05d7 \u05e7\u05d9\u05e9\u05d5\u05e8 \u05d0\u05d9\u05e4\u05d5\u05e1.'}
        token = secrets.token_urlsafe(32)
        cur.execute(sql_placeholder(
            'INSERT INTO password_reset_tokens (email, token) VALUES (?, ?)'), (email, token))
        conn.commit()
        reset_url = f'https://schoolpoints.co.il/web/reset-password?token={token}'
        ebody = '<div dir="rtl" style="font-family:Arial;line-height:1.8;">'
        ebody += '<h2>\u05d0\u05d9\u05e4\u05d5\u05e1 \u05e1\u05d9\u05e1\u05de\u05d4 - SchoolPoints</h2>'
        ebody += '<p>\u05e7\u05d9\u05d1\u05dc\u05e0\u05d5 \u05d1\u05e7\u05e9\u05d4 \u05dc\u05d0\u05d9\u05e4\u05d5\u05e1 \u05d4\u05e1\u05d9\u05e1\u05de\u05d4 \u05e9\u05dc\u05db\u05dd.</p>'
        ebody += f'<p><a href="{reset_url}" style="padding:12px 24px;background:#667eea;color:#fff;text-decoration:none;border-radius:8px;display:inline-block;">\u05dc\u05d7\u05e6\u05d5 \u05db\u05d0\u05df \u05dc\u05d0\u05d9\u05e4\u05d5\u05e1 \u05d4\u05e1\u05d9\u05e1\u05de\u05d4</a></p>'
        ebody += '<p style="font-size:13px;opacity:.7;">\u05d4\u05e7\u05d9\u05e9\u05d5\u05e8 \u05ea\u05e7\u05e3 \u05ea\u05d5\u05da 24 \u05e9\u05e2\u05d5\u05ea. \u05d0\u05dd \u05dc\u05d0 \u05d1\u05d9\u05e7\u05e9\u05ea\u05dd \u05d0\u05d9\u05e4\u05d5\u05e1, \u05d4\u05ea\u05e2\u05dc\u05de\u05d5 \u05de\u05d4\u05d5\u05d3\u05e2\u05d4 \u05d6\u05d5.</p></div>'
        try:
            send_email(email, 'SchoolPoints - \u05d0\u05d9\u05e4\u05d5\u05e1 \u05e1\u05d9\u05e1\u05de\u05d4', ebody)
        except Exception as e:
            logger.error(f"Reset email error: {e}")
        return {'ok': True, 'message': '\u05d0\u05dd \u05d4\u05d0\u05d9\u05de\u05d9\u05d9\u05dc \u05e7\u05d9\u05d9\u05dd \u05d1\u05de\u05e2\u05e8\u05db\u05ea, \u05e0\u05e9\u05dc\u05d7 \u05e7\u05d9\u05e9\u05d5\u05e8 \u05d0\u05d9\u05e4\u05d5\u05e1.'}
    finally:
        try: conn.close()
        except: pass

# ============================================================================
#  RESET PASSWORD PAGE
# ============================================================================
@router.get('/web/reset-password', response_class=HTMLResponse)
def web_reset_password(request: Request) -> str:
    token = request.query_params.get('token', '')
    body = _FORM_CSS + _RESET_HTML.replace('__TOKEN__', html_mod.escape(token))
    return public_web_shell("\u05d0\u05d9\u05e4\u05d5\u05e1 \u05e1\u05d9\u05e1\u05de\u05d4", body, request=request)

_RESET_HTML = """
<div class="rw"><div class="rh">
<h2>איפוס סיסמה</h2>
<p>הזינו סיסמה חדשה לחשבון שלכם</p></div>
<form id="rsForm" onsubmit="submitReset(event)"><div class="rc">
<input type="hidden" name="token" value="__TOKEN__"/>
<div class="fg"><label>סיסמה חדשה</label><input name="password" type="password" class="ri" required minlength="4" placeholder="לפחות 4 תווים"/></div>
<div class="fg"><label>אימות סיסמה</label><input name="password2" type="password" class="ri" required minlength="4" placeholder="הזן שוב"/></div>
<div id="rsMsg"></div>
<div class="ss"><button type="submit" class="bp" id="rsBtn">עדכן סיסמה</button></div>
<div class="lr"><a href="/web/signin">חזרה לכניסה</a></div>
</div></form></div>
<script>
async function submitReset(e){
  e.preventDefault();
  const btn=document.getElementById("rsBtn"),msg=document.getElementById("rsMsg");
  const fd=new FormData(e.target),d=Object.fromEntries(fd.entries());
  if(d.password!==d.password2){msg.className="mo mer";msg.textContent="הסיסמאות אינן תואמות";return;}
  btn.disabled=true;btn.textContent="מעדכן...";msg.className="";msg.textContent="";
  try{
    const r=await fetch("/api/reset-password",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(d)});
    const j=await r.json();
    if(r.ok&&j.ok){msg.className="mo mok";msg.textContent="הסיסמה עודכנה! מיד תועבר/י...";setTimeout(()=>{window.location.href="/web/signin";},2000);}
    else{msg.className="mo mer";msg.textContent=j.detail||"שגיאה";btn.disabled=false;btn.textContent="עדכן סיסמה";}
  }catch(err){msg.className="mo mer";msg.textContent="שגיאה: "+err;btn.disabled=false;btn.textContent="עדכן סיסמה";}
}
</script>
"""

@router.post('/api/reset-password')
def api_reset_password(request: Request, payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    ensure_password_reset_tokens_table()
    token = str(payload.get('token') or '').strip()
    password = str(payload.get('password') or '').strip()
    if not token or not password:
        raise HTTPException(status_code=400, detail="Missing token or password")
    if len(password) < 4:
        raise HTTPException(status_code=400, detail="Password too short")
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql_placeholder(
            'SELECT email FROM password_reset_tokens WHERE token = ? AND used = 0 LIMIT 1'), (token,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=400, detail="\u05e7\u05d9\u05e9\u05d5\u05e8 \u05dc\u05d0 \u05ea\u05e7\u05e3 \u05d0\u05d5 \u05db\u05d1\u05e8 \u05e0\u05d5\u05e6\u05dc")
        email = row['email'] if isinstance(row, dict) else row[0]
        new_hash = pbkdf2_hash(password)
        cur.execute(sql_placeholder(
            'UPDATE institutions SET password_hash = ? WHERE email = ?'), (new_hash, email))
        cur.execute(sql_placeholder(
            'UPDATE password_reset_tokens SET used = 1 WHERE token = ?'), (token,))
        conn.commit()
        return {'ok': True, 'message': 'Password updated'}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Reset password error: {e}")
        raise HTTPException(status_code=500, detail="Internal error")
    finally:
        try: conn.close()
        except: pass
