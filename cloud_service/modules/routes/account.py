from fastapi import APIRouter, Request, Body, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from typing import Dict, Any, List
import html as html_mod, logging, json as _json, urllib.parse as _up

from ..db import get_db_connection, sql_placeholder
from ..auth import web_tenant_from_cookie
from ..ui import public_web_shell
from ..admin_db import ensure_admin_tables, get_all_plans

router = APIRouter()
logger = logging.getLogger("schoolpoints.account")


def _get_institution(tenant_id):
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql_placeholder(
            'SELECT tenant_id,name,contact_name,email,phone,plan,created_at,last_login,login_count,license_expiry,api_key'
            ' FROM institutions WHERE tenant_id = ? LIMIT 1'), (tenant_id,))
        row = cur.fetchone()
        if not row:
            return None
        if isinstance(row, dict):
            return row
        cols = ['tenant_id','name','contact_name','email','phone','plan','created_at','last_login','login_count','license_expiry','api_key']
        return dict(zip(cols, row))
    except Exception:
        return None
    finally:
        try: conn.close()
        except: pass


def _get_plans_map() -> Dict[str, Dict]:
    """Get all active plans keyed by plan_key."""
    try:
        ensure_admin_tables()
        plans = get_all_plans()
        return {str(p.get('plan_key','')): p for p in plans if int(p.get('is_active') or 0) == 1}
    except Exception:
        return {}


def _plan_display_name(plan_key: str, plans_map: Dict) -> str:
    p = plans_map.get(plan_key)
    if p:
        return str(p.get('display_name') or plan_key)
    if plan_key == 'trial':
        return 'ניסיון (7 ימים)'
    return plan_key


@router.get('/web/my-account', response_class=HTMLResponse)
def web_my_account(request: Request) -> str:
    tenant_id = web_tenant_from_cookie(request)
    if not tenant_id:
        return RedirectResponse(url='/web/signin?next=/web/my-account', status_code=302)
    inst = _get_institution(tenant_id)
    if not inst:
        return HTMLResponse(public_web_shell('\u05d0\u05d6\u05d5\u05e8 \u05d0\u05d9\u05e9\u05d9', '<h2>\u05de\u05d5\u05e1\u05d3 \u05dc\u05d0 \u05e0\u05de\u05e6\u05d0</h2>', request=request))
    plan = str(inst.get('plan') or 'trial')
    plans_map = _get_plans_map()
    pn = _plan_display_name(plan, plans_map)
    body = _ACCT_CSS + _build_account_html(inst, plan, pn, plans_map)
    return public_web_shell('\u05d0\u05d6\u05d5\u05e8 \u05d0\u05d9\u05e9\u05d9', body, request=request)


def _build_account_html(inst, plan, pn, plans_map):
    esc = html_mod.escape
    email = str(inst.get('email') or '')
    expiry = str(inst.get('license_expiry') or '')[:10]

    h = '<div class="aw">'
    h += '<h2 class="ah">\u05d0\u05d6\u05d5\u05e8 \u05d0\u05d9\u05e9\u05d9</h2>'
    h += '<div class="ac">'
    h += f'<div class="ai"><span>\u05de\u05d5\u05e1\u05d3:</span><b>{esc(str(inst.get("name") or ""))}</b></div>'
    h += f'<div class="ai"><span>\u05e7\u05d5\u05d3 \u05de\u05d5\u05e1\u05d3:</span><b style="direction:ltr">{esc(str(inst.get("tenant_id") or ""))}</b></div>'
    h += f'<div class="ai"><span>\u05d0\u05d9\u05e9 \u05e7\u05e9\u05e8:</span>{esc(str(inst.get("contact_name") or ""))}</div>'
    h += f'<div class="ai"><span>\u05d0\u05d9\u05de\u05d9\u05d9\u05dc:</span>{esc(email)}</div>'
    h += f'<div class="ai"><span>\u05d8\u05dc\u05e4\u05d5\u05df:</span>{esc(str(inst.get("phone") or "-"))}</div>'
    h += f'<div class="ai"><span>\u05de\u05e1\u05dc\u05d5\u05dc \u05e0\u05d5\u05db\u05d7\u05d9:</span><b class="aplan">{esc(pn)}</b></div>'
    if expiry:
        h += f'<div class="ai"><span>\u05ea\u05d5\u05e7\u05e3 \u05e8\u05d9\u05e9\u05d9\u05d5\u05df:</span><b>{esc(expiry)}</b></div>'
    h += f'<div class="ai"><span>\u05ea\u05d0\u05e8\u05d9\u05da \u05d4\u05e8\u05e9\u05de\u05d4:</span>{esc(str(inst.get("created_at") or "-")[:19])}</div>'
    h += '</div>'

    # --- API Key section ---
    ak = str(inst.get('api_key') or '')
    tid = esc(str(inst.get('tenant_id') or ''))
    if ak:
        h += f'''<div style="margin-top:20px;background:rgba(255,193,7,.08);border:1px solid rgba(255,193,7,.3);border-radius:14px;padding:18px 20px;">
          <div style="font-weight:700;font-size:15px;margin-bottom:10px;">&#128273; מפתח API לחיבור התוכנה לענן</div>
          <div style="display:flex;gap:8px;align-items:center;">
            <input id="apiKeyBox" type="password" value="{esc(ak)}" readonly
              style="flex:1;font-family:monospace;font-size:13px;padding:9px 12px;border:1px solid rgba(255,255,255,.2);border-radius:8px;background:rgba(0,0,0,.2);color:#fff;direction:ltr;text-align:left;" />
            <button onclick="var b=document.getElementById('apiKeyBox');b.type=b.type==='password'?'text':'password';this.textContent=b.type==='password'?'&#128065;':'&#128274;';"
              style="padding:9px 12px;border-radius:8px;background:rgba(255,255,255,.1);border:1px solid rgba(255,255,255,.2);color:#fff;cursor:pointer;font-size:16px;">&#128065;</button>
            <button onclick="navigator.clipboard.writeText('{esc(ak)}').then(()=>{{this.textContent='\u2705';setTimeout(()=>this.textContent='📋',1800);}});"
              style="padding:9px 12px;border-radius:8px;background:rgba(255,255,255,.1);border:1px solid rgba(255,255,255,.2);color:#fff;cursor:pointer;font-size:16px;">&#128203;</button>
          </div>
          <div style="margin-top:8px;font-size:12px;opacity:.6;">Tenant ID + מפתח API נדרשים להגדרת הסנכרון בתוכנה</div>
        </div>'''
    # --- Registration file download ---
    h += f'''<div style="margin-top:20px;background:rgba(46,204,113,.08);border:1px solid rgba(46,204,113,.3);border-radius:14px;padding:18px 20px;">
      <div style="font-weight:700;font-size:15px;margin-bottom:8px;">&#128196; קובץ הרשמה לתוכנה</div>
      <div style="font-size:13px;opacity:.75;margin-bottom:12px;">הורד קובץ JSON ויבא אותו בתוכנה לחיבור אוטומטי לענן (tenant_id + מפתח API).</div>
      <button onclick="downloadRegFile('{esc(str(inst.get('tenant_id') or ''))}','{esc(ak or '')}')"
        style="padding:9px 20px;background:#2ecc71;border:none;border-radius:8px;color:#fff;font-weight:700;font-size:14px;cursor:pointer;">
        &#11015; הורד קובץ הרשמה
      </button>
    </div>
    <script>
    function downloadRegFile(tid, ak){{
      var obj = {{tenant_id:tid, api_key:ak, server_url:"https://schoolpoints.co.il"}};
      var blob = new Blob([JSON.stringify(obj,null,2)], {{type:"application/json"}});
      var a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "schoolpoints_registration.json";
      a.click();
    }}
    </script>'''

    # --- Inline activation form ---
    h += f'''<div style="margin-top:20px;background:rgba(102,126,234,.08);border:1px solid rgba(102,126,234,.3);border-radius:14px;padding:20px 20px 16px;">
      <div style="font-weight:700;font-size:15px;margin-bottom:4px;">&#128273; הפעלת רישיון (לא-מקוון)</div>
      <div style="font-size:13px;opacity:.7;margin-bottom:14px;">העתק את <b>קוד המערכת</b> מהתוכנה (הגדרות &rarr; רישיון) והזן כאן כדי לקבל קוד הפעלה.</div>
      <div style="display:flex;gap:8px;margin-bottom:10px;">
        <input id="sysCodeIn" type="text" placeholder="XXXX-XXXX-XXXX-XXXX" maxlength="24"
          style="flex:1;padding:10px 12px;border:1px solid rgba(255,255,255,.2);background:rgba(0,0,0,.2);color:#fff;border-radius:8px;font-family:Consolas,monospace;font-size:13px;direction:ltr;text-align:left;"/>
        <button id="genKeyBtn" onclick="genActivationKey('{esc(str(inst.get('tenant_id') or ''))}','{esc(ak or '')}')"
          style="padding:10px 18px;background:linear-gradient(135deg,#667eea,#764ba2);border:none;border-radius:8px;color:#fff;font-weight:700;font-size:14px;cursor:pointer;white-space:nowrap;">
          &#9889; צור קוד
        </button>
      </div>
      <div id="actKeyResult" style="display:none;margin-top:10px;background:rgba(46,204,113,.1);border:1px solid rgba(46,204,113,.3);border-radius:10px;padding:14px;text-align:center;">
        <div style="font-size:12px;opacity:.7;margin-bottom:6px;">קוד הפעלה — הדבק בתוכנה:</div>
        <div id="actKeyVal" style="font-family:Consolas,monospace;font-size:15px;font-weight:700;letter-spacing:1px;word-break:break-all;color:#2ecc71;user-select:all;cursor:text;"></div>
        <button onclick="copyActKey()" id="copyActBtn"
          style="margin-top:10px;padding:7px 20px;background:#2ecc71;border:none;border-radius:8px;color:#fff;font-weight:700;font-size:13px;cursor:pointer;">
          &#128203; העתק
        </button>
      </div>
      <div id="actKeyMsg" style="min-height:18px;font-size:13px;margin-top:6px;text-align:center;"></div>
    </div>
    <script>
    async function genActivationKey(tid, apiKey){{
      var sys = (document.getElementById('sysCodeIn').value||'').trim();
      var msg = document.getElementById('actKeyMsg');
      var btn = document.getElementById('genKeyBtn');
      var res = document.getElementById('actKeyResult');
      msg.textContent=''; msg.style.color='';
      res.style.display='none';
      if(!sys){{ msg.textContent='יש להזין קוד מערכת'; msg.style.color='#e74c3c'; return; }}
      btn.disabled=true; btn.textContent='מייצר...';
      try{{
        var r = await fetch('/api/license/generate',{{
          method:'POST',
          headers:{{'Content-Type':'application/json'}},
          body: JSON.stringify({{tenant_id:tid, api_key:apiKey, system_code:sys}})
        }});
        var d = await r.json();
        if(d.ok){{
          document.getElementById('actKeyVal').textContent = d.activation_key;
          res.style.display='block';
          msg.textContent='הקוד נוצר בהצלחה &#10003;'; msg.style.color='#2ecc71';
        }}else{{
          msg.textContent = d.error||'שגיאה'; msg.style.color='#e74c3c';
        }}
      }}catch(e){{ msg.textContent='שגיאת תקשורת'; msg.style.color='#e74c3c'; }}
      btn.disabled=false; btn.textContent='&#9889; צור קוד';
    }}
    function copyActKey(){{
      var txt = document.getElementById('actKeyVal').textContent;
      navigator.clipboard.writeText(txt).then(function(){{
        var b=document.getElementById('copyActBtn');
        b.textContent='&#10003; הועתק!';
        setTimeout(function(){{b.textContent='&#128203; העתק';}},2000);
      }});
    }}
    </script>'''

    # --- Upgrade / change plan section ---
    available = [p for pk, p in plans_map.items()
                 if pk != plan and int(p.get('is_active') or 0) == 1
                 and int(p.get('is_visible') if p.get('is_visible') is not None else 1) == 1
                 and int(p.get('price_monthly') or 0) > 0]
    available.sort(key=lambda p: int(p.get('sort_order') or 0))

    if available or plan == 'trial':
        h += '<h3 class="ah" style="font-size:24px;margin-top:32px;">\u05e9\u05d3\u05e8\u05d5\u05d2 / \u05e9\u05d9\u05e0\u05d5\u05d9 \u05de\u05e1\u05dc\u05d5\u05dc</h3>'
        h += '<div class="ug">'
        for p in available:
            pk = esc(str(p.get('plan_key','')))
            dn = esc(str(p.get('display_name','')))
            price = int(p.get('price_monthly') or 0)
            dur = int(p.get('duration_months') or 1)
            total = price * dur
            featured = int(p.get('is_featured') or 0)
            border = 'border-color:#667eea;' if featured else ''
            badge = '<div style="background:#e74c3c;color:#fff;font-size:11px;padding:2px 10px;border-radius:20px;margin-bottom:6px;display:inline-block;font-weight:700;">\u05de\u05d5\u05de\u05dc\u05e5</div>' if featured else ''
            if dur > 1:
                price_html = f'<div class="up">&#8362;{price}<span>/\u05d7\u05d5\u05d3\u05e9</span></div><div style="font-size:12px;opacity:.7;margin-top:-4px;">\u05e1\u05d4\u05f4\u05db &#8362;{total}</div>'
            else:
                price_html = f'<div class="up">&#8362;{total}</div>'
            pay_url = f'/web/payment?reg_email={_up.quote(email)}&plan={_up.quote(pk)}'
            h += f'<a href="{pay_url}" class="uc" style="text-decoration:none;color:inherit;{border}">'
            h += f'{badge}<div class="un">{dn}</div>{price_html}</a>'
        h += '</div>'

    h += '<div style="margin-top:24px;text-align:center;">'
    h += '<a href="/web/admin" style="color:#667eea;font-weight:600;text-decoration:none;">\u05d7\u05d6\u05e8\u05d4 \u05dc\u05e0\u05d9\u05d4\u05d5\u05dc</a></div>'
    h += '</div>'
    return h


_ACCT_CSS = """<style>
.aw{max-width:640px;margin:0 auto;padding:20px}
.ah{text-align:center;font-size:32px;margin-bottom:24px;background:linear-gradient(135deg,#667eea,#764ba2);-webkit-background-clip:text;-webkit-text-fill-color:transparent;font-weight:700}
.ac{background:var(--glass-bg);backdrop-filter:blur(24px);-webkit-backdrop-filter:blur(24px);border:1px solid var(--glass-border);border-radius:20px;padding:28px;box-shadow:0 10px 40px rgba(0,0,0,.1)}
.ai{display:flex;justify-content:space-between;padding:12px 0;border-bottom:1px solid rgba(255,255,255,.06);font-size:15px}
.ai span{opacity:.7;font-weight:600}
.aplan{color:#2ecc71;font-size:18px}
.ug{display:flex;gap:16px;justify-content:center;margin-top:16px;flex-wrap:wrap}
.uc{border:2px solid var(--glass-border);border-radius:14px;padding:20px 28px;text-align:center;cursor:pointer;transition:all .3s;min-width:180px;display:block}
.uc:hover{border-color:#667eea;transform:translateY(-3px);box-shadow:0 8px 20px rgba(0,0,0,.2)}
.un{font-size:18px;font-weight:800;margin-bottom:6px}
.up{font-size:24px;font-weight:700;color:#2ecc71}.up span{font-size:13px;opacity:.7}
</style>"""


@router.get('/web/expired', response_class=HTMLResponse)
def web_expired(request: Request) -> str:
    """Page shown when institution's license has expired."""
    tenant_id = web_tenant_from_cookie(request)
    if not tenant_id:
        return RedirectResponse(url='/web/signin', status_code=302)
    inst = _get_institution(tenant_id)
    plans_map = _get_plans_map()
    plan = str((inst or {}).get('plan') or 'trial')
    pn = _plan_display_name(plan, plans_map)
    expiry = str((inst or {}).get('license_expiry') or '')[:10]
    email = str((inst or {}).get('email') or '')

    # Build upgrade cards
    cards = ''
    available = [p for pk, p in plans_map.items()
                 if int(p.get('is_active') or 0) == 1
                 and int(p.get('is_visible') if p.get('is_visible') is not None else 1) == 1
                 and int(p.get('price_monthly') or 0) > 0]
    available.sort(key=lambda p: int(p.get('sort_order') or 0))
    for p in available:
        pk = html_mod.escape(str(p.get('plan_key','')))
        dn = html_mod.escape(str(p.get('display_name','')))
        price = int(p.get('price_monthly') or 0)
        dur = int(p.get('duration_months') or 1)
        total = price * dur
        pay_url = f'/web/payment?reg_email={_up.quote(email)}&plan={_up.quote(pk)}'
        cards += f'''<a href="{pay_url}" style="display:block;border:2px solid rgba(255,255,255,.15);border-radius:14px;padding:20px;text-align:center;text-decoration:none;color:inherit;min-width:180px;transition:all .3s;">
          <div style="font-size:18px;font-weight:800;margin-bottom:6px;">{dn}</div>
          <div style="font-size:24px;font-weight:700;color:#2ecc71;">&#8362;{price}<span style="font-size:13px;opacity:.7;">/\u05d7\u05d5\u05d3\u05e9</span></div>
          <div style="font-size:12px;opacity:.7;">\u05e1\u05d4\u05f4\u05db &#8362;{total}</div>
        </a>'''

    body = f'''
    <div style="max-width:560px;margin:0 auto;padding:40px 20px;text-align:center;">
      <div style="font-size:64px;margin-bottom:16px;">⏳</div>
      <h2 style="color:#e74c3c;">\u05d4\u05de\u05e0\u05d5\u05d9 \u05e9\u05dc\u05da \u05e4\u05d2 \u05ea\u05d5\u05e7\u05e3</h2>
      <p style="opacity:.8;">\u05de\u05e1\u05dc\u05d5\u05dc: <b>{html_mod.escape(pn)}</b> | \u05ea\u05d5\u05e7\u05e3: <b>{html_mod.escape(expiry)}</b></p>
      <p style="opacity:.7;">\u05d4\u05de\u05e2\u05e8\u05db\u05ea \u05d7\u05e1\u05d5\u05de\u05d4 \u05dc\u05e6\u05e4\u05d9\u05d9\u05d4 \u05d1\u05dc\u05d1\u05d3. \u05db\u05d3\u05d9 \u05dc\u05d4\u05de\u05e9\u05d9\u05da \u05dc\u05d4\u05e9\u05ea\u05de\u05e9, \u05d9\u05e9 \u05dc\u05d7\u05d3\u05e9 \u05d0\u05ea \u05d4\u05de\u05e0\u05d5\u05d9.</p>

      <div style="display:flex;gap:16px;justify-content:center;margin:28px 0;flex-wrap:wrap;">
        {cards}
      </div>

      <div style="margin-top:16px;">
        <a href="/web/my-account" style="color:#667eea;font-weight:600;text-decoration:none;">\u05d0\u05d6\u05d5\u05e8 \u05d0\u05d9\u05e9\u05d9</a>
        &nbsp;|&nbsp;
        <a href="/web/logout" style="color:#e74c3c;text-decoration:none;">\u05d9\u05e6\u05d9\u05d0\u05d4</a>
      </div>
    </div>
    '''
    return public_web_shell('\u05de\u05e0\u05d5\u05d9 \u05e4\u05d2 \u05ea\u05d5\u05e7\u05e3', body, request=request)


@router.post('/api/upgrade-plan')
def api_upgrade_plan(request: Request, payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """Upgrade plan — updates institution record and license_expiry. Called after successful payment."""
    tenant_id = web_tenant_from_cookie(request)
    if not tenant_id:
        raise HTTPException(401, detail="Not authenticated")
    new_plan = str(payload.get('plan') or '').strip()
    plans_map = _get_plans_map()
    if new_plan not in plans_map and new_plan != 'trial':
        raise HTTPException(400, detail="\u05de\u05e1\u05dc\u05d5\u05dc \u05dc\u05d0 \u05ea\u05e7\u05d9\u05df")
    inst = _get_institution(tenant_id)
    if not inst:
        raise HTTPException(404, detail="\u05de\u05d5\u05e1\u05d3 \u05dc\u05d0 \u05e0\u05de\u05e6\u05d0")
    from ..registration_logic import _compute_license_expiry
    new_expiry = _compute_license_expiry(new_plan)
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql_placeholder('UPDATE institutions SET plan = ?, license_expiry = ? WHERE tenant_id = ?'),
                    (new_plan, new_expiry, tenant_id))
        conn.commit()
        return {'ok': True, 'plan': new_plan, 'license_expiry': new_expiry}
    finally:
        try: conn.close()
        except: pass
