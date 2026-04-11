from fastapi import APIRouter, HTTPException, Body, Request, Query
from fastapi.responses import HTMLResponse
from typing import Dict, Any
import datetime
import json
import hmac
import hashlib
import base64
import html as html_mod
import logging

from ..models import LicenseFetchPayload
from ..db import get_db_connection, sql_placeholder, ensure_tenant_db_exists
from ..auth import check_password_hash
from ..ui import public_web_shell

logger = logging.getLogger("schoolpoints.license")
router = APIRouter()

# ---------------------------------------------------------------------------
# SP5 license key generation (mirrors license_manager.py logic)
# ---------------------------------------------------------------------------
_HMAC_SECRET = b"SchoolPoints-Offline-License-Key-2024-11-Strong-Secret"


def _normalize_key(key: str) -> str:
    return "".join(ch for ch in (key or "").upper() if ch.isalnum())


def _format_key_groups(core: str, group: int = 5) -> str:
    core = _normalize_key(core)
    if not core:
        return ''
    groups = [core[i : i + group] for i in range(0, len(core), group)]
    return "-".join(groups)


def _generate_sp5_key(school_name: str, system_code: str, *,
                       days_valid: int, max_stations: int, allow_cashier: bool) -> str:
    """Generate an SP5 payload activation key (same algo as license_manager.py)."""
    school_name = (school_name or '').strip()
    sys_norm = _normalize_key(system_code)
    if not school_name or not sys_norm:
        return ''
    days_valid = max(1, int(days_valid or 1))
    max_stations = max(1, int(max_stations or 2))

    payload = {
        'v': 'SP5',
        'school': school_name,
        'sys': sys_norm,
        'days': days_valid,
        'max': max_stations,
        'cashier': bool(allow_cashier),
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    sig = hmac.new(_HMAC_SECRET, raw, hashlib.sha256).digest()[:10]
    key_stream = hashlib.sha256(_HMAC_SECRET + sys_norm.encode('utf-8')).digest()
    blob = raw + sig
    out = bytearray(len(blob))
    klen = len(key_stream)
    for i, b in enumerate(blob):
        out[i] = b ^ key_stream[i % klen]
    token = base64.b32encode(bytes(out)).decode('ascii').replace('=', '').upper()
    return _format_key_groups('SP5' + token, 5)


def _plan_to_license_params(plan_key: str) -> Dict[str, Any]:
    """Map a plan_key to SP5 license parameters using plan_config table."""
    from ..admin_db import ensure_admin_tables
    ensure_admin_tables()
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql_placeholder(
            'SELECT duration_months, max_stations FROM plan_config WHERE plan_key = ? AND is_active = 1 LIMIT 1'),
            (plan_key,))
        row = cur.fetchone()
        if row:
            dur = int((row['duration_months'] if isinstance(row, dict) else row[0]) or 1)
            max_st = int((row['max_stations'] if isinstance(row, dict) else row[1]) or 999)
            return {'days': dur * 30 + 5, 'max_stations': max_st, 'cashier': True}
    except Exception:
        pass
    finally:
        try: conn.close()
        except: pass
    # Fallback defaults by plan name
    if plan_key == 'annual':
        return {'days': 370, 'max_stations': 999, 'cashier': True}
    if plan_key == 'short':
        return {'days': 65, 'max_stations': 999, 'cashier': True}
    return {'days': 35, 'max_stations': 2, 'cashier': True}


def _get_institution(tenant_id: str) -> Dict[str, Any]:
    """Load institution record by tenant_id."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql_placeholder(
            'SELECT name, api_key, password_hash, plan FROM institutions WHERE tenant_id = ? LIMIT 1'),
            (tenant_id,))
        row = cur.fetchone()
        if not row:
            return {}
        if isinstance(row, dict):
            return dict(row)
        return {'name': row[0], 'api_key': row[1], 'password_hash': row[2], 'plan': row[3]}
    except Exception:
        return {}
    finally:
        try: conn.close()
        except: pass


def _authenticate_institution(inst: Dict[str, Any], *, api_key: str = '', password: str = '') -> bool:
    """Check api_key or password against institution record."""
    if api_key and api_key == str(inst.get('api_key') or '').strip():
        return True
    if password:
        pw_hash = str(inst.get('password_hash') or '')
        if pw_hash and check_password_hash(pw_hash, password):
            return True
    return False


# ---------------------------------------------------------------------------
# API: Generate activation key for an institution
# ---------------------------------------------------------------------------
@router.post('/api/license/generate')
def api_license_generate(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Generate an SP5 activation key for a given institution + system code.
    
    Auth: api_key or password.
    Returns activation_key that the user enters in the desktop software.
    """
    tenant_id = str(payload.get('tenant_id') or '').strip()
    system_code = str(payload.get('system_code') or '').strip()
    api_key = str(payload.get('api_key') or '').strip()
    password = str(payload.get('password') or '').strip()

    if not tenant_id or not system_code:
        return {'ok': False, 'error': 'חסר מזהה מוסד או קוד מערכת'}

    inst = _get_institution(tenant_id)
    if not inst:
        return {'ok': False, 'error': 'מוסד לא נמצא'}

    if not _authenticate_institution(inst, api_key=api_key, password=password):
        return {'ok': False, 'error': 'סיסמה שגויה'}

    plan = str(inst.get('plan') or 'trial').strip()
    school_name = str(inst.get('name') or '').strip()

    if plan in ('trial', ''):
        return {'ok': False, 'error': 'המוסד במסלול ניסיון — יש לשלם כדי לקבל קוד הפעלה'}

    params = _plan_to_license_params(plan)
    activation_key = _generate_sp5_key(
        school_name, system_code,
        days_valid=params['days'],
        max_stations=params['max_stations'],
        allow_cashier=params['cashier'],
    )

    if not activation_key:
        return {'ok': False, 'error': 'שגיאה ביצירת קוד הפעלה'}

    logger.info(f"[LICENSE] Generated SP5 key for {tenant_id} plan={plan} sys={system_code[:8]}...")
    return {
        'ok': True,
        'activation_key': activation_key,
        'school_name': school_name,
        'plan': plan,
        'days': params['days'],
        'max_stations': params['max_stations'],
    }


# ---------------------------------------------------------------------------
# Web: Activation page — paste system code, get activation key
# ---------------------------------------------------------------------------
@router.get('/web/activate', response_class=HTMLResponse)
def web_activate_page(request: Request, tenant_id: str = Query(default='')) -> str:
    safe_tid = html_mod.escape(tenant_id)

    body = f"""
    <style>
      .act-wrap {{ max-width:520px; margin:30px auto; }}
      .act-card {{ background:rgba(255,255,255,.06); border:1px solid rgba(255,255,255,.15); border-radius:16px; padding:28px; backdrop-filter:blur(10px); }}
      .act-card h2 {{ text-align:center; margin:0 0 6px; font-size:22px; }}
      .act-sub {{ text-align:center; opacity:.7; margin-bottom:20px; font-size:14px; }}
      .act-field {{ margin-bottom:16px; }}
      .act-field label {{ display:block; font-size:13px; opacity:.8; margin-bottom:6px; }}
      .act-field input {{ width:100%; padding:10px 12px; border:1px solid rgba(255,255,255,.2); background:rgba(255,255,255,.08); color:#fff; border-radius:8px; font-size:14px; font-family:Consolas,monospace; box-sizing:border-box; direction:ltr; text-align:left; }}
      .act-field input:focus {{ outline:none; border-color:#667eea; }}
      .act-field input[readonly] {{ opacity:.7; }}
      #genBtn {{ width:100%; padding:14px; background:linear-gradient(135deg,#667eea,#764ba2); color:#fff; border:none; border-radius:10px; font-size:16px; font-weight:700; cursor:pointer; transition:opacity .2s; }}
      #genBtn:disabled {{ opacity:.5; cursor:not-allowed; }}
      .act-result {{ display:none; margin-top:20px; background:rgba(46,204,113,.1); border:1px solid rgba(46,204,113,.3); border-radius:12px; padding:20px; text-align:center; }}
      .act-result h3 {{ color:#2ecc71; margin:0 0 10px; }}
      .act-key {{ font-family:Consolas,monospace; font-size:13px; word-break:break-all; background:rgba(0,0,0,.2); padding:12px; border-radius:8px; margin:10px 0; direction:ltr; text-align:center; user-select:all; }}
      .act-copy {{ display:inline-block; padding:8px 20px; background:#2ecc71; color:#fff; border:none; border-radius:8px; font-size:14px; cursor:pointer; margin-top:8px; }}
      .act-copy:hover {{ background:#27ae60; }}
      #actMsg {{ text-align:center; margin-top:10px; font-size:14px; min-height:20px; }}
      .act-steps {{ margin-top:20px; font-size:13px; opacity:.7; line-height:1.8; }}
      .act-steps b {{ color:#2ecc71; }}
    </style>
    <div class="act-wrap"><div class="act-card">
      <h2>הפעלת רישיון</h2>
      <div class="act-sub">הזן את פרטי המוסד וקוד המערכת מהתוכנה כדי לקבל קוד הפעלה</div>

      <div class="act-field">
        <label>מזהה מוסד (Tenant ID)</label>
        <input type="text" id="tenantId" value="{safe_tid}" placeholder="לדוגמה: 12345678" />
      </div>
      <div class="act-field">
        <label>סיסמת ניהול</label>
        <input type="password" id="password" placeholder="הסיסמה שבחרת בהרשמה" />
      </div>
      <div class="act-field">
        <label>קוד מערכת (מוצג בתוכנה: הגדרות → רישום מערכת)</label>
        <input type="text" id="systemCode" placeholder="XXXX-XXXX-XXXX-XXXX" style="letter-spacing:1px;" />
      </div>

      <button id="genBtn">קבל קוד הפעלה</button>
      <div id="actMsg"></div>

      <div class="act-result" id="resultBox">
        <h3>קוד ההפעלה שלך</h3>
        <div class="act-key" id="actKey"></div>
        <button class="act-copy" onclick="copyKey()">העתק קוד</button>
        <div id="planInfo" style="margin-top:10px; font-size:13px; opacity:.8;"></div>
      </div>

      <div class="act-steps">
        <b>שלבים:</b><br/>
        1. פתח את התוכנה במחשב<br/>
        2. לחץ על ⚙ הגדרות מערכת → רישום מערכת<br/>
        3. העתק את <b>קוד המערכת</b> והדבק אותו כאן למעלה<br/>
        4. לחץ "קבל קוד הפעלה"<br/>
        5. העתק את קוד ההפעלה והדבק בתוכנה
      </div>
    </div></div>

    <script>
    (function() {{
      var btn = document.getElementById('genBtn');
      var msg = document.getElementById('actMsg');

      btn.addEventListener('click', function() {{
        var tid = (document.getElementById('tenantId').value || '').trim();
        var pwd = (document.getElementById('password').value || '').trim();
        var sys = (document.getElementById('systemCode').value || '').trim();
        msg.textContent = '';
        msg.style.color = '';
        document.getElementById('resultBox').style.display = 'none';

        if (!tid || !pwd || !sys) {{
          msg.textContent = 'יש למלא את כל השדות';
          msg.style.color = '#e74c3c';
          return;
        }}

        btn.disabled = true;
        btn.textContent = 'מייצר קוד...';

        fetch('/api/license/generate', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ tenant_id: tid, password: pwd, system_code: sys }})
        }})
        .then(function(r) {{ return r.json(); }})
        .then(function(data) {{
          btn.disabled = false;
          btn.textContent = 'קבל קוד הפעלה';
          if (data.ok) {{
            document.getElementById('actKey').textContent = data.activation_key;
            document.getElementById('planInfo').textContent =
              'מסלול: ' + (data.plan || '') + ' | תוקף: ' + (data.days || '') + ' ימים | עמדות: ' + (data.max_stations || '');
            document.getElementById('resultBox').style.display = 'block';
            msg.textContent = 'הקוד נוצר בהצלחה!';
            msg.style.color = '#2ecc71';
          }} else {{
            msg.textContent = data.error || 'שגיאה';
            msg.style.color = '#e74c3c';
          }}
        }})
        .catch(function(e) {{
          btn.disabled = false;
          btn.textContent = 'קבל קוד הפעלה';
          msg.textContent = 'שגיאת תקשורת';
          msg.style.color = '#e74c3c';
        }});
      }});
    }})();

    function copyKey() {{
      var key = document.getElementById('actKey').textContent;
      if (navigator.clipboard) {{
        navigator.clipboard.writeText(key).then(function() {{
          var btn = document.querySelector('.act-copy');
          btn.textContent = 'הועתק!';
          setTimeout(function() {{ btn.textContent = 'העתק קוד'; }}, 2000);
        }});
      }} else {{
        var range = document.createRange();
        range.selectNode(document.getElementById('actKey'));
        window.getSelection().removeAllRanges();
        window.getSelection().addRange(range);
        document.execCommand('copy');
      }}
    }}
    </script>
    """
    return public_web_shell("הפעלת רישיון", body, request=request)


# ---------------------------------------------------------------------------
# Existing API: Fetch license info
# ---------------------------------------------------------------------------
@router.post('/api/license/fetch')
def api_license_fetch(payload: LicenseFetchPayload) -> Dict[str, Any]:
    tenant_id = str(payload.tenant_id or '').strip()
    api_key = str(payload.api_key or '').strip()
    password = str(payload.password or '').strip()
    
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Missing tenant_id")

    inst = _get_institution(tenant_id)
    if not inst:
        raise HTTPException(status_code=404, detail="Institution not found")

    if not _authenticate_institution(inst, api_key=api_key, password=password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    plan = str(inst.get('plan') or 'trial').strip()
    params = _plan_to_license_params(plan) if plan not in ('trial', '') else {'days': 7, 'max_stations': 2, 'cashier': True}

    return {
        'ok': True,
        'license': {
            'tenant_id': tenant_id,
            'name': inst.get('name', ''),
            'plan': plan,
            'status': 'active' if plan not in ('trial', '') else 'trial',
            'days': params['days'],
            'max_stations': params['max_stations'],
            'api_key': inst.get('api_key', '')
        }
    }
