"""
Reports & Export routes for modular web admin.
"""
import io
import csv
from typing import Dict, Any
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, Response, RedirectResponse

from ..ui import basic_web_shell
from ..db import tenant_db_connection, USE_POSTGRES, sql_placeholder
from ..auth import web_require_admin_teacher, web_require_teacher, web_tenant_from_cookie

router = APIRouter()


@router.get('/api/reports/stats')
def api_reports_stats(request: Request) -> Dict[str, Any]:
    guard = web_require_teacher(request)
    if guard:
        raise HTTPException(status_code=401)
    tenant_id = web_tenant_from_cookie(request)
    conn = tenant_db_connection(tenant_id)
    try:
        cur = conn.cursor()
        cur.execute("SELECT SUM(points) FROM students")
        row = cur.fetchone()
        total_balance = int(row[0] or 0) if row else 0
        try:
            cur.execute("SELECT SUM(total_points) FROM purchases_log WHERE is_refunded=0")
            row = cur.fetchone()
            total_redeemed = int(row[0] or 0) if row else 0
        except Exception:
            total_redeemed = 0
        cur.execute("SELECT first_name, last_name, class_name, points FROM students ORDER BY points DESC LIMIT 5")
        top_students = [dict(r) if not isinstance(r, dict) else r for r in (cur.fetchall() or [])]
        try:
            cur.execute("SELECT p.name, SUM(l.qty) as sold_qty FROM purchases_log l JOIN products p ON l.product_id=p.id WHERE l.is_refunded=0 GROUP BY p.name ORDER BY sold_qty DESC LIMIT 5")
            top_products = [dict(r) if not isinstance(r, dict) else r for r in (cur.fetchall() or [])]
        except Exception:
            top_products = []
        return {'total_balance': total_balance, 'total_redeemed': total_redeemed, 'top_students': top_students, 'top_products': top_products}
    finally:
        try: conn.close()
        except: pass


@router.get('/api/reports/teachers')
def api_reports_teachers(request: Request) -> Dict[str, Any]:
    guard = web_require_teacher(request)
    if guard:
        raise HTTPException(status_code=401)
    tenant_id = web_tenant_from_cookie(request)
    conn = tenant_db_connection(tenant_id)
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, name FROM teachers ORDER BY name")
        rows = [dict(r) if not isinstance(r, dict) else r for r in (cur.fetchall() or [])]
        return {'ok': True, 'teachers': rows}
    finally:
        try: conn.close()
        except: pass


@router.get('/api/reports/bonuses')
def api_reports_bonuses(request: Request) -> Dict[str, Any]:
    guard = web_require_teacher(request)
    if guard:
        raise HTTPException(status_code=401)
    tenant_id = web_tenant_from_cookie(request)
    conn = tenant_db_connection(tenant_id)
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, name, group_name FROM time_bonus_schedules ORDER BY name")
        rows = [dict(r) if not isinstance(r, dict) else r for r in (cur.fetchall() or [])]
        return {'ok': True, 'bonuses': rows}
    finally:
        try: conn.close()
        except: pass


@router.get('/web/export/download')
def web_export_download(request: Request) -> Response:
    guard = web_require_admin_teacher(request)
    if guard: return guard
    tenant_id = web_tenant_from_cookie(request)
    if not tenant_id: return RedirectResponse(url='/web/signin', status_code=302)
    conn = tenant_db_connection(tenant_id)
    try:
        cur = conn.cursor()
        cur.execute(sql_placeholder('SELECT serial_number,last_name,first_name,class_name,points,card_number FROM students ORDER BY class_name,last_name,first_name'))
        rows = cur.fetchall() or []
    finally:
        try: conn.close()
        except: pass
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["מס' סידורי",'שם משפחה','שם פרטי','כיתה',"מס' נקודות","מס' כרטיס"])
    for r in rows:
        d = dict(r) if not isinstance(r, dict) else r
        w.writerow([d.get('serial_number') or '',d.get('last_name') or '',d.get('first_name') or '',d.get('class_name') or '',d.get('points') if d.get('points') is not None else '',d.get('card_number') or ''])
    data = buf.getvalue().encode('utf-8-sig')
    return Response(content=data, media_type='text/csv; charset=utf-8', headers={'Content-Disposition':'attachment; filename="students_export.csv"'})


@router.get('/web/export/attendance')
def web_export_attendance(request: Request) -> Response:
    guard = web_require_admin_teacher(request)
    if guard: return guard
    tenant_id = web_tenant_from_cookie(request)
    if not tenant_id: return RedirectResponse(url='/web/signin', status_code=302)
    target_date = request.query_params.get('date', '')
    bonus_id = request.query_params.get('bonus_id', '')
    conn = tenant_db_connection(tenant_id)
    try:
        cur = conn.cursor()
        base = "SELECT g.given_date,g.given_at,s.serial_number,s.first_name,s.last_name,s.class_name,s.card_number,COALESCE(bs.group_name,bs.name,'') as bonus_name FROM time_bonus_given g JOIN students s ON g.student_id=s.id LEFT JOIN time_bonus_schedules bs ON g.bonus_schedule_id=bs.id"
        if target_date:
            cur.execute(sql_placeholder(base + " WHERE g.given_date=? ORDER BY s.class_name,s.last_name,s.first_name"), (target_date,))
        elif bonus_id:
            cur.execute(sql_placeholder(base + " WHERE g.bonus_schedule_id=? ORDER BY g.given_date DESC,s.class_name,s.last_name"), (int(bonus_id),))
        else:
            cur.execute(base + " ORDER BY g.given_date DESC,s.class_name,s.last_name LIMIT 5000")
        rows = cur.fetchall() or []
    finally:
        try: conn.close()
        except: pass
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(['תאריך','שעה',"מס' סידורי",'שם משפחה','שם פרטי','כיתה',"מס' כרטיס",'בונוס'])
    for r in rows:
        d = dict(r) if not isinstance(r, dict) else r
        ga = str(d.get('given_at') or '')
        tp = ga[11:16] if len(ga) > 15 else ga
        w.writerow([d.get('given_date') or '',tp,d.get('serial_number') or '',d.get('last_name') or '',d.get('first_name') or '',d.get('class_name') or '',d.get('card_number') or '',d.get('bonus_name') or ''])
    data = buf.getvalue().encode('utf-8-sig')
    fname = f"attendance_{target_date or 'all'}.csv"
    return Response(content=data, media_type='text/csv; charset=utf-8', headers={'Content-Disposition':f'attachment; filename="{fname}"'})


@router.get('/web/export/teacher-actions')
def web_export_teacher_actions(request: Request) -> Response:
    guard = web_require_admin_teacher(request)
    if guard: return guard
    tenant_id = web_tenant_from_cookie(request)
    if not tenant_id: return RedirectResponse(url='/web/signin', status_code=302)
    teacher_id = request.query_params.get('teacher_id', '')
    conn = tenant_db_connection(tenant_id)
    try:
        cur = conn.cursor()
        if teacher_id and teacher_id != '-1':
            try:
                cur.execute(sql_placeholder("SELECT name FROM teachers WHERE id=?"), (int(teacher_id),))
                trow = cur.fetchone()
                teacher_name = (dict(trow) if not isinstance(trow, dict) else trow).get('name', '') if trow else ''
            except Exception:
                teacher_name = ''
            cur.execute(sql_placeholder("SELECT l.created_at,l.action_type,l.actor_name,l.reason,l.delta,l.old_points,l.new_points,s.first_name,s.last_name,s.class_name FROM points_log l LEFT JOIN students s ON l.student_id=s.id WHERE l.actor_name=? ORDER BY l.id DESC LIMIT 5000"), (teacher_name,))
        else:
            cur.execute("SELECT l.created_at,l.action_type,l.actor_name,l.reason,l.delta,l.old_points,l.new_points,s.first_name,s.last_name,s.class_name FROM points_log l LEFT JOIN students s ON l.student_id=s.id ORDER BY l.id DESC LIMIT 5000")
        rows = cur.fetchall() or []
    finally:
        try: conn.close()
        except: pass
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(['תאריך','סוג פעולה','מורה','תלמיד','כיתה','שינוי','לפני','אחרי','סיבה'])
    for r in rows:
        d = dict(r) if not isinstance(r, dict) else r
        student = f"{d.get('first_name') or ''} {d.get('last_name') or ''}".strip()
        w.writerow([d.get('created_at') or '',d.get('action_type') or '',d.get('actor_name') or '',student,d.get('class_name') or '',d.get('delta') if d.get('delta') is not None else '',d.get('old_points') if d.get('old_points') is not None else '',d.get('new_points') if d.get('new_points') is not None else '',d.get('reason') or ''])
    data = buf.getvalue().encode('utf-8-sig')
    return Response(content=data, media_type='text/csv; charset=utf-8', headers={'Content-Disposition':'attachment; filename="teacher_actions.csv"'})


@router.get("/web/reports", response_class=HTMLResponse)
def web_reports(request: Request):
    guard = web_require_admin_teacher(request)
    if guard: return guard
    return basic_web_shell("דוחות", _reports_html(), request=request)


def _reports_html() -> str:
    return """
<style>
.stats-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:20px;margin-bottom:30px}
.stat-box{background:#fff;padding:24px;border-radius:12px;border:1px solid #e1e8ee;text-align:center}
.stat-num{font-size:36px;font-weight:900;color:#2c3e50;margin:10px 0}
.stat-label{color:#7f8c8d;font-size:14px;font-weight:600}
.lists-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:24px}
.list-card{background:#fff;border-radius:12px;border:1px solid #e1e8ee;overflow:hidden}
.list-header{background:#f8f9fa;padding:15px 20px;border-bottom:1px solid #eee;font-weight:700;font-size:16px}
.list-item{display:flex;justify-content:space-between;padding:12px 20px;border-bottom:1px solid #f4f6f8;font-size:14px}
.list-val{font-weight:700;color:#3498db}
.exp-sec{margin-top:30px;display:flex;flex-direction:column;gap:16px}
.exp-card{background:#f8f9fa;padding:16px;border-radius:10px;border:1px solid #eee}
</style>
<div class="stats-grid">
  <div class="stat-box"><div class="stat-label">יתרת נקודות</div><div class="stat-num" id="s-bal">...</div></div>
  <div class="stat-box"><div class="stat-label">נקודות שמומשו</div><div class="stat-num" id="s-red" style="color:#e67e22">...</div></div>
</div>
<div class="lists-grid">
  <div class="list-card"><div class="list-header">🏆 תלמידים מובילים</div><div id="top-st">טוען...</div></div>
  <div class="list-card"><div class="list-header">📦 מוצרים נמכרים</div><div id="top-pr">טוען...</div></div>
</div>
<div class="exp-sec">
  <h3>ייצוא נתונים</h3>
  <a href="/web/export/download" target="_blank"><button class="blue">⬇️ רשימת תלמידים</button></a>
  <div class="exp-card">
    <h4 style="margin:0 0 10px">📋 ייצוא נוכחות</h4>
    <div style="display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end">
      <div><label style="font-size:12px;font-weight:600;display:block;margin-bottom:4px">לפי תאריך</label><input type="date" id="att-date" style="padding:8px;border:1px solid #ddd;border-radius:6px"></div>
      <button class="green" onclick="exportAttByDate()">⬇️ ייצוא ליום</button>
      <div><label style="font-size:12px;font-weight:600;display:block;margin-bottom:4px">לפי בונוס</label><select id="att-bonus" style="padding:8px;border:1px solid #ddd;border-radius:6px;min-width:150px"><option value="">טוען...</option></select></div>
      <button class="green" onclick="exportAttByBonus()">⬇️ ייצוא לבונוס</button>
      <a href="/web/export/attendance" target="_blank"><button class="gray">⬇️ הכל</button></a>
    </div>
  </div>
  <div class="exp-card">
    <h4 style="margin:0 0 10px">👨‍🏫 ייצוא פעולות מורה</h4>
    <div style="display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end">
      <div><label style="font-size:12px;font-weight:600;display:block;margin-bottom:4px">בחר מורה</label><select id="ta-teacher" style="padding:8px;border:1px solid #ddd;border-radius:6px;min-width:180px"><option value="">טוען...</option></select></div>
      <button onclick="exportTeacherActions()" style="padding:8px 16px;border-radius:8px;border:none;cursor:pointer;font-weight:bold;color:white;background:#e67e22">⬇️ ייצוא</button>
      <a href="/web/export/teacher-actions?teacher_id=-1" target="_blank"><button class="gray">⬇️ כל המורים</button></a>
    </div>
  </div>
</div>
<script>
function esc(s){return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}
async function loadStats(){try{const r=await fetch('/api/reports/stats');const d=await r.json();
document.getElementById('s-bal').textContent=d.total_balance.toLocaleString();
document.getElementById('s-red').textContent=d.total_redeemed.toLocaleString();
const st=document.getElementById('top-st');
st.innerHTML=(d.top_students||[]).length?d.top_students.map(s=>'<div class="list-item"><span>'+esc(s.first_name)+' '+esc(s.last_name)+'</span><span class="list-val">'+s.points.toLocaleString()+'</span></div>').join(''):'<div style="padding:20px;text-align:center;color:#999">אין נתונים</div>';
const pr=document.getElementById('top-pr');
pr.innerHTML=(d.top_products||[]).length?d.top_products.map(p=>'<div class="list-item"><span>'+esc(p.name)+'</span><span class="list-val">'+p.sold_qty+'</span></div>').join(''):'<div style="padding:20px;text-align:center;color:#999">אין נתונים</div>';
}catch(e){console.error(e)}}
async function loadBonuses(){try{const r=await fetch('/api/reports/bonuses');const d=await r.json();const s=document.getElementById('att-bonus');s.innerHTML='<option value="">-- בחר בונוס --</option>';(d.bonuses||[]).forEach(b=>{s.innerHTML+='<option value="'+b.id+'">'+esc(b.group_name||b.name||'')+'</option>'})}catch(e){}}
async function loadTeachers(){try{const r=await fetch('/api/reports/teachers');const d=await r.json();const s=document.getElementById('ta-teacher');s.innerHTML='<option value="">-- בחר מורה --</option>';(d.teachers||[]).forEach(t=>{s.innerHTML+='<option value="'+t.id+'">'+esc(t.name||'')+'</option>'})}catch(e){}}
function exportAttByDate(){const d=document.getElementById('att-date').value;if(!d){alert('נא לבחור תאריך');return}window.open('/web/export/attendance?date='+d,'_blank')}
function exportAttByBonus(){const b=document.getElementById('att-bonus').value;if(!b){alert('נא לבחור בונוס');return}window.open('/web/export/attendance?bonus_id='+b,'_blank')}
function exportTeacherActions(){const t=document.getElementById('ta-teacher').value;if(!t){alert('נא לבחור מורה');return}window.open('/web/export/teacher-actions?teacher_id='+t,'_blank')}
loadStats();loadBonuses();loadTeachers();
</script>
"""
