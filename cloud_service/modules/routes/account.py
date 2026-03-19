from fastapi import APIRouter, Request, Body, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from typing import Dict, Any
import html as html_mod, logging

from ..db import get_db_connection, sql_placeholder
from ..auth import web_tenant_from_cookie
from ..ui import public_web_shell

router = APIRouter()
logger = logging.getLogger("schoolpoints.account")

_PLAN_NAMES = {'basic': 'Basic', 'extended': 'Extended', 'unlimited': 'Unlimited', 'trial': 'Trial'}
_PLAN_PRICES = {'basic': 50, 'extended': 100, 'unlimited': 200, 'trial': 0}

def _get_institution(tenant_id):
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql_placeholder(
            'SELECT tenant_id,name,contact_name,email,phone,plan,created_at,last_login,login_count'
            ' FROM institutions WHERE tenant_id = ? LIMIT 1'), (tenant_id,))
        row = cur.fetchone()
        if not row:
            return None
        if isinstance(row, dict):
            return row
        cols = ['tenant_id','name','contact_name','email','phone','plan','created_at','last_login','login_count']
        return dict(zip(cols, row))
    finally:
        try: conn.close()
        except: pass

@router.get('/web/my-account', response_class=HTMLResponse)
def web_my_account(request: Request) -> str:
    tenant_id = web_tenant_from_cookie(request)
    if not tenant_id:
        return RedirectResponse(url='/web/signin?next=/web/my-account', status_code=302)
    inst = _get_institution(tenant_id)
    if not inst:
        return HTMLResponse(public_web_shell('\u05d0\u05d6\u05d5\u05e8 \u05d0\u05d9\u05e9\u05d9', '<h2>\u05de\u05d5\u05e1\u05d3 \u05dc\u05d0 \u05e0\u05de\u05e6\u05d0</h2>', request=request))
    plan = str(inst.get('plan') or 'trial')
    pn = _PLAN_NAMES.get(plan, plan)
    body = _ACCT_CSS + _build_account_html(inst, plan, pn)
    return public_web_shell('\u05d0\u05d6\u05d5\u05e8 \u05d0\u05d9\u05e9\u05d9', body, request=request)

def _build_account_html(inst, plan, pn):
    esc = html_mod.escape
    h = '<div class="aw">'
    h += '<h2 class="ah">\u05d0\u05d6\u05d5\u05e8 \u05d0\u05d9\u05e9\u05d9</h2>'
    h += '<div class="ac">'
    h += f'<div class="ai"><span>\u05de\u05d5\u05e1\u05d3:</span><b>{esc(str(inst.get("name") or ""))}</b></div>'
    h += f'<div class="ai"><span>\u05e7\u05d5\u05d3 \u05de\u05d5\u05e1\u05d3:</span><b style="direction:ltr">{esc(str(inst.get("tenant_id") or ""))}</b></div>'
    h += f'<div class="ai"><span>\u05d0\u05d9\u05e9 \u05e7\u05e9\u05e8:</span>{esc(str(inst.get("contact_name") or ""))}</div>'
    h += f'<div class="ai"><span>\u05d0\u05d9\u05de\u05d9\u05d9\u05dc:</span>{esc(str(inst.get("email") or ""))}</div>'
    h += f'<div class="ai"><span>\u05d8\u05dc\u05e4\u05d5\u05df:</span>{esc(str(inst.get("phone") or "-"))}</div>'
    h += f'<div class="ai"><span>\u05de\u05e1\u05dc\u05d5\u05dc \u05e0\u05d5\u05db\u05d7\u05d9:</span><b class="aplan">{esc(pn)}</b></div>'
    h += f'<div class="ai"><span>\u05ea\u05d0\u05e8\u05d9\u05da \u05d4\u05e8\u05e9\u05de\u05d4:</span>{esc(str(inst.get("created_at") or "-")[:19])}</div>'
    h += '</div>'
    # Upgrade section
    if plan in ('trial', 'basic', 'extended'):
        h += '<h3 class="ah" style="font-size:24px;margin-top:32px;">\u05e9\u05d3\u05e8\u05d5\u05d2 \u05de\u05e1\u05dc\u05d5\u05dc</h3>'
        h += '<div id="upMsg"></div>'
        h += '<div class="ug">'
        upgrades = []
        if plan in ('trial', 'basic'):
            upgrades.append(('extended', 'Extended', 100))
        if plan in ('trial', 'basic', 'extended'):
            upgrades.append(('unlimited', 'Unlimited', 200))
        for pid, pname, price in upgrades:
            h += f'<div class="uc" onclick="doUpgrade(\'{pid}\')">'
            h += f'<div class="un">{pname}</div>'
            h += f'<div class="up">&#8362;{price}<span>/\u05d7\u05d5\u05d3\u05e9</span></div></div>'
        h += '</div>'
    h += '<div style="margin-top:24px;text-align:center;">'
    h += '<a href="/web/admin" style="color:#667eea;font-weight:600;text-decoration:none;">\u05d7\u05d6\u05e8\u05d4 \u05dc\u05e0\u05d9\u05d4\u05d5\u05dc</a></div>'
    h += '</div>'
    h += """<script>
async function doUpgrade(p){
  if(!confirm('\u05dc\u05e9\u05d3\u05e8\u05d2 \u05dc\u05de\u05e1\u05dc\u05d5\u05dc '+p+'?')) return;
  var m=document.getElementById('upMsg');m.className='';m.textContent='';
  try{
    var r=await fetch('/api/upgrade-plan',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({plan:p})});
    var j=await r.json();
    if(r.ok&&j.ok){m.className='uok';m.textContent='\u05d4\u05de\u05e1\u05dc\u05d5\u05dc \u05e2\u05d5\u05d3\u05db\u05df!';setTimeout(function(){location.reload();},1500);}
    else{m.className='uer';m.textContent=j.detail||'\u05e9\u05d2\u05d9\u05d0\u05d4';}
  }catch(e){m.className='uer';m.textContent='\u05e9\u05d2\u05d9\u05d0\u05d4: '+e;}
}
</script>"""
    return h

_ACCT_CSS = """<style>
.aw{max-width:600px;margin:0 auto;padding:20px}
.ah{text-align:center;font-size:32px;margin-bottom:24px;background:linear-gradient(135deg,#667eea,#764ba2);-webkit-background-clip:text;-webkit-text-fill-color:transparent;font-weight:700}
.ac{background:var(--glass-bg);backdrop-filter:blur(24px);border:1px solid var(--glass-border);border-radius:20px;padding:28px;box-shadow:0 10px 40px rgba(0,0,0,.1)}
.ai{display:flex;justify-content:space-between;padding:12px 0;border-bottom:1px solid rgba(255,255,255,.06);font-size:15px}
.ai span{opacity:.7;font-weight:600}
.aplan{color:#2ecc71;font-size:18px}
.ug{display:flex;gap:16px;justify-content:center;margin-top:16px;flex-wrap:wrap}
.uc{border:2px solid var(--glass-border);border-radius:14px;padding:20px 28px;text-align:center;cursor:pointer;transition:all .3s;min-width:160px}
.uc:hover{border-color:#667eea;transform:translateY(-3px);box-shadow:0 8px 20px rgba(0,0,0,.2)}
.un{font-size:18px;font-weight:800;margin-bottom:6px}
.up{font-size:24px;font-weight:700;color:#2ecc71}.up span{font-size:13px;opacity:.7}
.uok{background:rgba(46,204,113,.12);border:1px solid rgba(46,204,113,.3);color:#2ecc71;padding:12px;border-radius:10px;text-align:center;margin:12px 0}
.uer{background:rgba(231,76,60,.12);border:1px solid rgba(231,76,60,.3);color:#e74c3c;padding:12px;border-radius:10px;text-align:center;margin:12px 0}
</style>"""

@router.post('/api/upgrade-plan')
def api_upgrade_plan(request: Request, payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    tenant_id = web_tenant_from_cookie(request)
    if not tenant_id:
        raise HTTPException(401, detail="Not authenticated")
    new_plan = str(payload.get('plan') or '').strip()
    if new_plan not in ('basic', 'extended', 'unlimited'):
        raise HTTPException(400, detail="Invalid plan")
    order = {'trial': 0, 'basic': 1, 'extended': 2, 'unlimited': 3}
    inst = _get_institution(tenant_id)
    if not inst:
        raise HTTPException(404, detail="Institution not found")
    cur_plan = str(inst.get('plan') or 'trial')
    if order.get(new_plan, 0) <= order.get(cur_plan, 0):
        raise HTTPException(400, detail="\u05dc\u05d0 \u05e0\u05d9\u05ea\u05df \u05dc\u05e9\u05d3\u05e8\u05d2 \u05dc\u05de\u05e1\u05dc\u05d5\u05dc \u05e0\u05de\u05d5\u05da \u05d9\u05d5\u05ea\u05e8")
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql_placeholder('UPDATE institutions SET plan = ? WHERE tenant_id = ?'), (new_plan, tenant_id))
        conn.commit()
        return {'ok': True, 'plan': new_plan}
    finally:
        try: conn.close()
        except: pass
