"""Additional admin pages: Plans, Payments, Staff."""
from fastapi import APIRouter, Request, Response, Form
from fastapi.responses import HTMLResponse, RedirectResponse
import json, logging
from ..ui import basic_web_shell
from .admin_super import super_admin_shell
from ..db import get_db_connection, sql_placeholder
from ..auth import pbkdf2_hash
from ..admin_db import ensure_admin_tables, get_all_plans, row_to_dict

logger = logging.getLogger("schoolpoints.admin_pages")
router = APIRouter()

def _req_admin(request):
    from ..config import ADMIN_KEY
    import hmac as _hmac, hashlib as _hl
    try:
        k = ADMIN_KEY
        c = request.cookies.get('admin_key')
        if k and str(c or '').strip() == k:
            return True
        staff = request.cookies.get('admin_staff_session')
        if staff:
            parts = staff.split(':', 1)
            if len(parts) == 2:
                secret = (k or 'x').encode()
                exp = _hmac.new(secret, parts[0].encode(), _hl.sha256).hexdigest()
                if _hmac.compare_digest(parts[1], exp):
                    return True
        if not k:
            return True
        return False
    except: return False

_NAV = '<div style="background:rgba(0,0,0,0.06);border-radius:14px;padding:8px 16px;margin-bottom:20px;display:flex;gap:8px;flex-wrap:wrap;align-items:center;"><a href="/admin/institutions" style="padding:6px 14px;border-radius:10px;font-size:13px;font-weight:700;text-decoration:none;color:#333;background:rgba(255,255,255,0.7);">מוסדות</a><a href="/admin/plans" style="padding:6px 14px;border-radius:10px;font-size:13px;font-weight:700;text-decoration:none;color:#333;background:rgba(255,255,255,0.7);">מסלולים</a><a href="/admin/payments" style="padding:6px 14px;border-radius:10px;font-size:13px;font-weight:700;text-decoration:none;color:#333;background:rgba(255,255,255,0.7);">תשלומים</a><a href="/admin/staff" style="padding:6px 14px;border-radius:10px;font-size:13px;font-weight:700;text-decoration:none;color:#333;background:rgba(255,255,255,0.7);">צוות</a><a href="/admin/registrations" style="padding:6px 14px;border-radius:10px;font-size:13px;font-weight:700;text-decoration:none;color:#333;background:rgba(255,255,255,0.7);">הרשמות</a><span style="flex:1;"></span><a href="/admin/logout" style="padding:6px 14px;border-radius:10px;font-size:12px;text-decoration:none;color:#e74c3c;">יציאה</a></div>'

def _shell(t, b, r=None): return super_admin_shell(t, b, r)

# ---------------------------------------------------------------------------
# Plan Management
# ---------------------------------------------------------------------------
@router.get('/admin/plans', response_class=HTMLResponse)
def admin_plans_page(request: Request) -> str:
    if not _req_admin(request):
        return RedirectResponse(url="/admin/login", status_code=302)
    ensure_admin_tables()
    plans = get_all_plans()
    rows = ""
    for p in plans:
        pk = p.get('plan_key','')
        price = int(p.get('price_monthly',0))
        dur = int(p.get('duration_months',1) or 1)
        total = price * dur
        _vis = int(p.get('is_visible') if p.get('is_visible') is not None else 1)
        vis = '✅' if _vis else '❌'
        feat_flag = '⭐' if int(p.get('is_featured') or 0) else ''
        price_str = f'₪{price}/חוד' + (f' (×{dur}=₪{total})' if dur > 1 else '')
        vis_btn = 'הסתר' if _vis else 'הצג'
        rows += f'<tr style="border-bottom:1px solid #eee;"><td style="padding:10px;font-weight:700;">{p.get("display_name","")} {feat_flag}</td><td style="padding:10px;font-family:monospace;">{pk}</td><td style="padding:10px;">{price_str}</td><td style="padding:10px;font-size:12px;">{p.get("description","")}</td><td style="padding:10px;text-align:center;">{vis}</td><td style="padding:10px;display:flex;gap:4px;"><a href="/admin/plans/{pk}" style="font-size:12px;padding:4px 10px;background:#2563eb;color:#fff;border-radius:8px;text-decoration:none;">ערוך</a><form method="post" action="/admin/plans/{pk}/toggle-visible" style="display:inline;"><button style="font-size:11px;padding:4px 8px;background:#e67e22;color:#fff;border:none;border-radius:8px;cursor:pointer;">{vis_btn}</button></form><form method="post" action="/admin/plans/{pk}/delete" style="display:inline;" onsubmit="return confirm(\'למחוק?\');"><button style="font-size:11px;padding:4px 8px;background:#e74c3c;color:#fff;border:none;border-radius:8px;cursor:pointer;">מחק</button></form></td></tr>'

    body = f"""
    <h2>ניהול מסלולים</h2>
    <div class="card" style="padding:0;overflow-x:auto;">
        <table style="width:100%;border-collapse:collapse;font-size:13px;">
            <thead style="background:rgba(0,0,0,0.05);"><tr>
                <th style="padding:10px;text-align:right;">שם תצוגה</th>
                <th style="padding:10px;text-align:right;">מפתח</th>
                <th style="padding:10px;text-align:right;">מחיר</th>
                <th style="padding:10px;text-align:right;">תיאור</th>
                <th style="padding:10px;text-align:center;">נראה</th>
                <th style="padding:10px;text-align:right;">פעולות</th>
            </tr></thead>
            <tbody>{rows}</tbody>
        </table>
    </div>
    <div class="card" style="padding:16px;margin-top:16px;">
        <h3 style="margin-top:0;">הוספת מסלול</h3>
        <form method="post" action="/admin/plans/add">
            <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:10px;">
                <input name="plan_key" placeholder="מפתח (אנגלית) *" class="form-input" required>
                <input name="display_name" placeholder="שם תצוגה *" class="form-input" required>
                <input name="price_monthly" placeholder="מחיר/חודש" type="number" class="form-input" required>
                <input name="duration_months" placeholder="מס' חודשים" type="number" value="1" class="form-input">
            </div>
            <div style="margin-top:10px;"><button class="btn-primary">הוסף</button></div>
        </form>
    </div>
    """
    return _shell("ניהול מסלולים", body, request)

@router.get('/admin/plans/{pk}', response_class=HTMLResponse)
def admin_plan_edit(request: Request, pk: str) -> str:
    if not _req_admin(request):
        return RedirectResponse(url="/admin/login", status_code=302)
    ensure_admin_tables()
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql_placeholder('SELECT * FROM plan_config WHERE plan_key=?'), (pk,))
        row = cur.fetchone()
        if not row:
            return _shell("לא נמצא", "<h3>מסלול לא נמצא</h3>", request)
        p = row_to_dict(row)
    finally:
        try: conn.close()
        except: pass
    feats = p.get('features_json','[]')
    try: fl = json.loads(feats) if isinstance(feats,str) else feats
    except: fl = []
    fs = '\n'.join(fl)
    is_feat = int(p.get('is_featured',0) or 0)
    is_vis = int(p.get('is_visible',1) or 1)
    dur = int(p.get('duration_months',1) or 1)
    body = f"""
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px;">
        <a href="/admin/plans" style="font-size:13px;color:#666;text-decoration:none;">← חזרה</a>
        <h2 style="margin:0;">עריכת מסלול: {p.get('display_name','')}</h2>
    </div>
    <div class="card" style="padding:20px;">
        <form method="post" action="/admin/plans/{pk}/update">
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
                <div><label style="font-size:12px;color:#666;">שם תצוגה</label><input name="display_name" value="{p.get('display_name','')}" class="form-input" required></div>
                <div><label style="font-size:12px;color:#666;">מחיר חודשי (₪)</label><input name="price_monthly" value="{p.get('price_monthly',0)}" class="form-input" type="number" required></div>
                <div><label style="font-size:12px;color:#666;">מס' חודשים</label><input name="duration_months" value="{dur}" class="form-input" type="number"></div>
                <div><label style="font-size:12px;color:#666;">מקס עמדות</label><input name="max_stations" value="{p.get('max_stations',2)}" class="form-input" type="number"></div>
                <div><label style="font-size:12px;color:#666;">סדר תצוגה</label><input name="sort_order" value="{p.get('sort_order',0)}" class="form-input" type="number"></div>
                <div style="display:flex;gap:16px;align-items:center;padding-top:18px;">
                    <label style="font-size:13px;"><input type="checkbox" name="is_featured" value="1" {'checked' if is_feat else ''}> מומלץ</label>
                    <label style="font-size:13px;"><input type="checkbox" name="is_visible" value="1" {'checked' if is_vis else ''}> נראה באתר</label>
                </div>
            </div>
            <div style="margin-top:10px;"><label style="font-size:12px;color:#666;">תיאור</label><input name="description" value="{p.get('description','')}" class="form-input"></div>
            <div style="margin-top:10px;"><label style="font-size:12px;color:#666;">פיצ'רים (שורה לכל פיצ'ר)</label><textarea name="features" class="form-input" rows="4">{fs}</textarea></div>
            <div style="margin-top:12px;"><button class="btn-primary">שמור</button></div>
        </form>
    </div>
    """
    return _shell(f"עריכת מסלול: {p.get('display_name','')}", body, request)

@router.post('/admin/plans/{pk}/update')
def admin_plan_update(request: Request, pk: str,
    display_name: str = Form(...), price_monthly: int = Form(0),
    duration_months: int = Form(1), max_stations: int = Form(2),
    sort_order: int = Form(0), description: str = Form(''),
    features: str = Form(''), is_featured: int = Form(0),
    is_visible: int = Form(0),
) -> Response:
    if not _req_admin(request):
        return Response("Unauthorized", status_code=401)
    feat_list = [f.strip() for f in features.split('\n') if f.strip()]
    feat_json = json.dumps(feat_list, ensure_ascii=False)
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql_placeholder(
            "UPDATE plan_config SET display_name=?, price_monthly=?, description=?, features_json=?, max_stations=?, sort_order=?, duration_months=?, is_featured=?, is_visible=? WHERE plan_key=?"),
            (display_name.strip(), price_monthly, description.strip(), feat_json, max_stations, sort_order, max(1, duration_months), 1 if is_featured else 0, 1 if is_visible else 0, pk))
        conn.commit()
    finally:
        try: conn.close()
        except: pass
    return RedirectResponse(url="/admin/plans", status_code=302)

@router.post('/admin/plans/{pk}/toggle-visible')
def admin_plan_toggle_visible(request: Request, pk: str) -> Response:
    if not _req_admin(request):
        return Response("Unauthorized", status_code=401)
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql_placeholder('SELECT is_visible FROM plan_config WHERE plan_key=?'), (pk,))
        row = cur.fetchone()
        if row:
            cur_vis = int((row['is_visible'] if isinstance(row, dict) else row[0]) or 0)
            cur.execute(sql_placeholder('UPDATE plan_config SET is_visible=? WHERE plan_key=?'), (0 if cur_vis else 1, pk))
            conn.commit()
    finally:
        try: conn.close()
        except: pass
    return RedirectResponse(url='/admin/plans', status_code=302)

@router.post('/admin/plans/{pk}/delete')
def admin_plan_delete(request: Request, pk: str) -> Response:
    if not _req_admin(request):
        return Response("Unauthorized", status_code=401)
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql_placeholder('DELETE FROM plan_config WHERE plan_key=?'), (pk,))
        conn.commit()
    finally:
        try: conn.close()
        except: pass
    return RedirectResponse(url='/admin/plans', status_code=302)

@router.post('/admin/plans/add')
def admin_plan_add(request: Request,
    plan_key: str = Form(...), display_name: str = Form(...),
    price_monthly: int = Form(0), duration_months: int = Form(1),
) -> Response:
    if not _req_admin(request):
        return Response("Unauthorized", status_code=401)
    ensure_admin_tables()
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql_placeholder(
            "INSERT INTO plan_config (plan_key,display_name,price_monthly,duration_months) VALUES (?,?,?,?)"),
            (plan_key.strip(), display_name.strip(), price_monthly, max(1, duration_months)))
        conn.commit()
    except Exception:
        pass
    finally:
        try: conn.close()
        except: pass
    return RedirectResponse(url=f'/admin/plans/{plan_key.strip()}', status_code=302)

# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------
@router.get('/admin/payments', response_class=HTMLResponse)
def admin_payments_page(request: Request) -> str:
    if not _req_admin(request):
        return RedirectResponse(url="/admin/login", status_code=302)
    ensure_admin_tables()
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute('SELECT p.*, i.name as inst_name FROM institution_payments p LEFT JOIN institutions i ON p.tenant_id=i.tenant_id ORDER BY p.payment_date DESC')
        pay_rows = cur.fetchall() or []
    except Exception:
        try: conn.rollback()
        except: pass
        try:
            cur.execute('SELECT * FROM institution_payments ORDER BY payment_date DESC')
            pay_rows = cur.fetchall() or []
        except Exception:
            pay_rows = []
    finally:
        try: conn.close()
        except: pass

    rows_html = ""
    total = 0
    for pr in pay_rows:
        pd = row_to_dict(pr)
        amt = int(pd.get('amount') or 0)
        total += amt
        tid = pd.get('tenant_id','')
        iname = pd.get('inst_name','') or tid
        rows_html += f'<tr style="border-bottom:1px solid #eee;"><td style="padding:8px;"><a href="/admin/institutions/{tid}" style="color:#2563eb;text-decoration:none;">{iname}</a></td><td style="padding:8px;">₪{amt}</td><td style="padding:8px;">{pd.get("payment_date","")}</td><td style="padding:8px;">{pd.get("payment_method","")}</td><td style="padding:8px;">{pd.get("reference","")}</td><td style="padding:8px;font-size:12px;">{pd.get("notes","")}</td></tr>'

    body = f"""
    <h2>תשלומים</h2>
    <div class="card" style="padding:16px;margin-bottom:16px;text-align:center;">
        <div style="font-size:32px;font-weight:900;color:#10b981;">₪{total}</div>
        <div style="font-size:14px;color:#666;">סה"כ תשלומים</div>
    </div>
    <div class="card" style="padding:0;overflow-x:auto;">
        <table style="width:100%;border-collapse:collapse;font-size:13px;">
            <thead style="background:rgba(0,0,0,0.05);"><tr>
                <th style="padding:8px;text-align:right;">מוסד</th>
                <th style="padding:8px;text-align:right;">סכום</th>
                <th style="padding:8px;text-align:right;">תאריך</th>
                <th style="padding:8px;text-align:right;">אמצעי</th>
                <th style="padding:8px;text-align:right;">אסמכתא</th>
                <th style="padding:8px;text-align:right;">הערה</th>
            </tr></thead>
            <tbody>{rows_html if rows_html else '<tr><td colspan="6" style="padding:14px;text-align:center;color:#999;">אין תשלומים</td></tr>'}</tbody>
        </table>
    </div>
    """
    return _shell("תשלומים", body, request)

@router.post('/admin/payments/add')
def admin_payment_add(request: Request,
    tenant_id: str = Form(...), amount: int = Form(0),
    payment_date: str = Form(''), payment_method: str = Form(''),
    reference: str = Form(''), notes: str = Form('')
) -> Response:
    if not _req_admin(request):
        return Response("Unauthorized", status_code=401)
    ensure_admin_tables()
    if not payment_date:
        import datetime
        payment_date = datetime.date.today().isoformat()
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql_placeholder(
            "INSERT INTO institution_payments (tenant_id,amount,payment_date,payment_method,reference,notes) VALUES (?,?,?,?,?,?)"),
            (tenant_id, amount, payment_date, payment_method.strip(), reference.strip(), notes.strip()))
        conn.commit()
    finally:
        try: conn.close()
        except: pass
    return RedirectResponse(url=f"/admin/institutions/{tenant_id}", status_code=302)

# ---------------------------------------------------------------------------
# Staff Management
# ---------------------------------------------------------------------------
_ROLE_LABELS = {'super':'מנהל ראשי','manager':'מנהל','viewer':'צופה'}

@router.get('/admin/staff', response_class=HTMLResponse)
def admin_staff_page(request: Request) -> str:
    if not _req_admin(request):
        return RedirectResponse(url="/admin/login", status_code=302)
    ensure_admin_tables()
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute('SELECT * FROM admin_staff ORDER BY created_at DESC')
        staff = cur.fetchall() or []
    except Exception:
        staff = []
    finally:
        try: conn.close()
        except: pass

    rows_html = ""
    for s in staff:
        sd = row_to_dict(s)
        role = sd.get('role','viewer')
        rl = _ROLE_LABELS.get(role, role)
        active = '✓' if sd.get('is_active',1) else '✗'
        sid = sd.get('id','')
        rows_html += f'<tr style="border-bottom:1px solid #eee;"><td style="padding:8px;font-weight:700;">{sd.get("display_name","")}</td><td style="padding:8px;">{sd.get("username","")}</td><td style="padding:8px;">{rl}</td><td style="padding:8px;text-align:center;">{active}</td><td style="padding:8px;font-size:12px;">{str(sd.get("created_at",""))[:10]}</td><td style="padding:8px;"><form method="post" action="/admin/staff/delete" style="display:inline;" onsubmit="return confirm(\'למחוק?\');"><input type="hidden" name="staff_id" value="{sid}"><button style="font-size:11px;padding:3px 8px;background:#e74c3c;color:#fff;border:none;border-radius:8px;cursor:pointer;">מחק</button></form></td></tr>'

    body = f"""
    <h2>ניהול צוות מנהלים</h2>
    <div class="card" style="padding:20px;margin-bottom:16px;">
        <h3 style="margin-top:0;">הוספת מנהל חדש</h3>
        <form method="post" action="/admin/staff/add">
            <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:10px;">
                <input name="username" placeholder="שם משתמש *" class="form-input" required>
                <input name="password" placeholder="סיסמה *" type="password" class="form-input" required>
                <input name="display_name" placeholder="שם תצוגה" class="form-input">
                <select name="role" class="form-input">
                    <option value="viewer">צופה</option>
                    <option value="manager">מנהל</option>
                    <option value="super">מנהל ראשי</option>
                </select>
            </div>
            <div style="margin-top:10px;"><button class="btn-primary">הוסף</button></div>
        </form>
    </div>
    <div class="card" style="padding:0;overflow-x:auto;">
        <table style="width:100%;border-collapse:collapse;font-size:13px;">
            <thead style="background:rgba(0,0,0,0.05);"><tr>
                <th style="padding:8px;text-align:right;">שם</th>
                <th style="padding:8px;text-align:right;">משתמש</th>
                <th style="padding:8px;text-align:right;">תפקיד</th>
                <th style="padding:8px;text-align:center;">פעיל</th>
                <th style="padding:8px;text-align:right;">נוצר</th>
                <th style="padding:8px;text-align:right;">פעולות</th>
            </tr></thead>
            <tbody>{rows_html if rows_html else '<tr><td colspan="6" style="padding:14px;text-align:center;color:#999;">אין מנהלים</td></tr>'}</tbody>
        </table>
    </div>
    """
    return _shell("ניהול צוות", body, request)

@router.post('/admin/staff/add')
def admin_staff_add(request: Request,
    username: str = Form(...), password: str = Form(...),
    display_name: str = Form(''), role: str = Form('viewer')
) -> Response:
    if not _req_admin(request):
        return Response("Unauthorized", status_code=401)
    ensure_admin_tables()
    pw_hash = pbkdf2_hash(password.strip())
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql_placeholder(
            "INSERT INTO admin_staff (username,password_hash,display_name,role) VALUES (?,?,?,?)"),
            (username.strip(), pw_hash, display_name.strip(), role.strip()))
        conn.commit()
    except Exception as e:
        return RedirectResponse(url="/admin/staff", status_code=302)
    finally:
        try: conn.close()
        except: pass
    return RedirectResponse(url="/admin/staff", status_code=302)

@router.post('/admin/staff/delete')
def admin_staff_delete(request: Request, staff_id: int = Form(...)) -> Response:
    if not _req_admin(request):
        return Response("Unauthorized", status_code=401)
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql_placeholder("DELETE FROM admin_staff WHERE id=?"), (staff_id,))
        conn.commit()
    finally:
        try: conn.close()
        except: pass
    return RedirectResponse(url="/admin/staff", status_code=302)
