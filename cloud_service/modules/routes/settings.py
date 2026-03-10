from fastapi import APIRouter, Request, HTTPException, Body
from fastapi.responses import HTMLResponse
from typing import Dict, Any, List
import json
import html

from ..ui import basic_web_shell
from ..auth import web_require_admin_teacher, web_require_teacher, web_tenant_from_cookie
from ..db import tenant_db_connection, sql_placeholder, integrity_errors
from ..config import USE_POSTGRES
from .upgrades_page import upgrades_html
from .purchases_page import purchases_html
from ..models import GenericSettingPayload
from ..sync_logic import record_sync_event

router = APIRouter()

def get_web_setting_json(conn, key: str, default_json: str = '{}') -> str:
    try:
        cur = conn.cursor()
        cur.execute(sql_placeholder("SELECT value_json FROM web_settings WHERE key = ? LIMIT 1"), (key,))
        row = cur.fetchone()
        if row:
            return (row['value_json'] if isinstance(row, dict) else row[0]) or default_json
        return default_json
    except Exception:
        return default_json

def set_web_setting_json(conn, key: str, value_json: str):
    cur = conn.cursor()
    # Upsert logic
    if USE_POSTGRES:
        sql = """
            INSERT INTO web_settings (key, value_json) VALUES (%s, %s)
            ON CONFLICT (key) DO UPDATE SET value_json = EXCLUDED.value_json
        """
        cur.execute(sql, (key, value_json))
    else:
        cur.execute("INSERT OR REPLACE INTO web_settings (key, value_json) VALUES (?, ?)", (key, value_json))
    conn.commit()

@router.get('/api/settings/{key}')
def api_settings_get(request: Request, key: str) -> Dict[str, Any]:
    guard = web_require_admin_teacher(request)
    if guard: raise HTTPException(status_code=401)
    
    tenant_id = web_tenant_from_cookie(request)
    conn = tenant_db_connection(tenant_id)
    try:
        val = get_web_setting_json(conn, key)
        return json.loads(val)
    except Exception:
        return {}
    finally:
        try: conn.close()
        except: pass

@router.post('/api/settings/save')
def api_settings_save(request: Request, payload: GenericSettingPayload) -> Dict[str, Any]:
    guard = web_require_admin_teacher(request)
    if guard: raise HTTPException(status_code=401)
    
    tenant_id = web_tenant_from_cookie(request)
    conn = tenant_db_connection(tenant_id)
    try:
        val_str = json.dumps(payload.value, ensure_ascii=False)
        set_web_setting_json(conn, payload.key, val_str)
        
        # Record sync event for specific settings if needed
        # (Usually settings sync is done via snapshot or specific logic, but let's record generic update)
        record_sync_event(
            tenant_id=tenant_id,
            station_id='web',
            entity_type='setting',
            entity_id=payload.key,
            action_type='update',
            payload={'key': payload.key, 'value': val_str}
        )
        return {'ok': True}
    finally:
        try: conn.close()
        except: pass


@router.get('/api/time-bonus')
def api_time_bonus_list(request: Request) -> Dict[str, Any]:
    guard = web_require_admin_teacher(request)
    if guard: raise HTTPException(status_code=401)

    tenant_id = web_tenant_from_cookie(request)
    if not tenant_id:
        raise HTTPException(status_code=400, detail='missing tenant')

    conn = tenant_db_connection(tenant_id)
    try:
        cur = conn.cursor()
        cur.execute(
            'SELECT id, name, group_name, start_time, end_time, bonus_points, is_active, '
            'is_general, classes, days_of_week, sound_key, is_shown_public '
            'FROM time_bonus_schedules ORDER BY group_name, start_time'
        )
        rows = cur.fetchall() or []
        rules = []
        for r in rows:
            rr = dict(r) if isinstance(r, dict) else {k: r[k] for k in r.keys()}
            rules.append({
                'id': rr.get('id'),
                'name': rr.get('name') or '',
                'group_name': rr.get('group_name') or rr.get('name') or '',
                'start_time': rr.get('start_time') or '',
                'end_time': rr.get('end_time') or '',
                'points': int(rr.get('bonus_points') or 0),
                'is_active': int(rr.get('is_active') or 0),
                'is_general': int(rr.get('is_general') or 1),
                'classes': rr.get('classes') or '',
                'days_of_week': rr.get('days_of_week') or '',
                'sound_key': rr.get('sound_key') or '',
                'is_shown_public': int(rr.get('is_shown_public') or 1),
            })
        return {'rules': rules}
    finally:
        try: conn.close()
        except: pass


@router.post('/api/time-bonus/save')
def api_time_bonus_save(request: Request, payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    guard = web_require_admin_teacher(request)
    if guard: raise HTTPException(status_code=401)

    tenant_id = web_tenant_from_cookie(request)
    if not tenant_id:
        raise HTTPException(status_code=400, detail='missing tenant')

    rules_in = payload.get('rules') or []
    if not isinstance(rules_in, list):
        raise HTTPException(status_code=400, detail='invalid rules')

    def _normalize_time_str(t: str) -> str:
        try:
            s = str(t or '').strip()
            if not s:
                return ''
            parts = s.split(':')
            if len(parts) != 2:
                return s
            hh = int(parts[0])
            mm = int(parts[1])
            if hh < 0 or hh > 23 or mm < 0 or mm > 59:
                return s
            return f"{hh:02d}:{mm:02d}"
        except Exception:
            return str(t or '').strip()

    conn = tenant_db_connection(tenant_id)
    try:
        cur = conn.cursor()
        cur.execute(
            'SELECT id, name, start_time, end_time, bonus_points, is_active, group_name '
            'FROM time_bonus_schedules'
        )
        existing_rows = cur.fetchall() or []
        existing_map = {}
        for r in existing_rows:
            rr = dict(r) if isinstance(r, dict) else {k: r[k] for k in r.keys()}
            try:
                rid = int(rr.get('id') or 0)
            except Exception:
                rid = 0
            if rid > 0:
                existing_map[rid] = rr

        keep_ids = set()
        saved_rules = []

        for rule in rules_in:
            if not isinstance(rule, dict):
                continue
            try:
                rid = int(rule.get('id') or 0)
            except Exception:
                rid = 0
            existing = existing_map.get(rid)
            name = str(rule.get('name') or (existing.get('name') if existing else '') or '').strip()
            start_time = _normalize_time_str(rule.get('start_time') or (existing.get('start_time') if existing else '') or '')
            end_time = _normalize_time_str(rule.get('end_time') or (existing.get('end_time') if existing else '') or '')
            points_val = rule.get('points')
            if points_val is None and existing is not None:
                points_val = existing.get('bonus_points')
            try:
                points = int(points_val or 0)
            except Exception:
                points = 0
            is_active_val = rule.get('is_active')
            if is_active_val is None and existing is not None:
                is_active_val = existing.get('is_active')
            try:
                is_active = int(is_active_val or 0)
            except Exception:
                is_active = 0

            if not name:
                continue
            group_name = str(rule.get('group_name') or (existing.get('group_name') if existing else '') or '').strip()
            classes = str(rule.get('classes') or (existing.get('classes') if existing else '') or '').strip()
            days_of_week = str(rule.get('days_of_week') or (existing.get('days_of_week') if existing else '') or '').strip()
            sound_key = str(rule.get('sound_key') or (existing.get('sound_key') if existing else '') or '').strip()
            is_general_val = rule.get('is_general')
            if is_general_val is None and existing is not None:
                is_general_val = existing.get('is_general')
            is_general = int(is_general_val if is_general_val is not None else 1)
            is_shown_public_val = rule.get('is_shown_public')
            if is_shown_public_val is None and existing is not None:
                is_shown_public_val = existing.get('is_shown_public')
            is_shown_public = int(is_shown_public_val if is_shown_public_val is not None else 1)

            if rid > 0 and existing is not None:
                cur.execute(
                    sql_placeholder(
                        'UPDATE time_bonus_schedules '
                        'SET name=?, group_name=?, start_time=?, end_time=?, bonus_points=?, is_active=?, '
                        'is_general=?, classes=?, days_of_week=?, sound_key=?, is_shown_public=?, updated_at=CURRENT_TIMESTAMP '
                        'WHERE id=?'
                    ),
                    (name, group_name, start_time, end_time, points, is_active, is_general, classes, days_of_week, sound_key, is_shown_public, rid)
                )
                keep_ids.add(rid)
                saved_rules.append({'id': rid, 'name': name, 'group_name': group_name, 'start_time': start_time, 'end_time': end_time, 'points': points, 'is_active': is_active, 'is_general': is_general, 'classes': classes, 'days_of_week': days_of_week, 'sound_key': sound_key, 'is_shown_public': is_shown_public})
                continue

            if USE_POSTGRES:
                cur.execute(
                    'INSERT INTO time_bonus_schedules (name, group_name, start_time, end_time, bonus_points, is_active, is_general, classes, days_of_week, sound_key, is_shown_public) '
                    'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id',
                    (name, group_name, start_time, end_time, points, is_active, is_general, classes, days_of_week, sound_key, is_shown_public)
                )
                row = cur.fetchone()
                new_id = row['id'] if isinstance(row, dict) else row[0]
            else:
                cur.execute(
                    'INSERT INTO time_bonus_schedules (name, group_name, start_time, end_time, bonus_points, is_active, is_general, classes, days_of_week, sound_key, is_shown_public) '
                    'VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                    (name, group_name, start_time, end_time, points, is_active, is_general, classes, days_of_week, sound_key, is_shown_public)
                )
                new_id = cur.lastrowid
            keep_ids.add(int(new_id or 0))
            saved_rules.append({'id': int(new_id or 0), 'name': name, 'group_name': group_name, 'start_time': start_time, 'end_time': end_time, 'points': points, 'is_active': is_active, 'is_general': is_general, 'classes': classes, 'days_of_week': days_of_week, 'sound_key': sound_key, 'is_shown_public': is_shown_public})

        delete_ids = [rid for rid in existing_map.keys() if rid not in keep_ids]
        if delete_ids:
            placeholders = ','.join(['?' for _ in delete_ids])
            if USE_POSTGRES:
                placeholders = ','.join(['%s' for _ in delete_ids])
            cur.execute(
                f'DELETE FROM time_bonus_schedules WHERE id IN ({placeholders})',
                tuple(delete_ids)
            )

        conn.commit()
        return {'ok': True, 'rules': saved_rules}
    finally:
        try: conn.close()
        except: pass

@router.get("/web/system-settings", response_class=HTMLResponse)
def web_system_settings(request: Request):
    guard = web_require_admin_teacher(request)
    if guard: return guard
    
    html_content = """
    <h2>הגדרות מערכת</h2>
    
    <div class="card" style="padding:20px; background:#fff; border-radius:10px; border:1px solid #eee;">
      <div class="form-group" style="margin-bottom:15px;">
        <label style="display:block; margin-bottom:5px; font-weight:600;">מצב פריסה</label>
        <select id="sys-mode" style="width:100%; padding:10px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box;">
          <option value="local">מקומי (Local)</option>
          <option value="cloud">ענן (Cloud)</option>
          <option value="hybrid">משולב (Hybrid)</option>
        </select>
      </div>
      <div class="form-group" style="margin-bottom:15px;">
        <label style="display:block; margin-bottom:5px; font-weight:600;">שיטת עבודה</label>
        <select id="sys-work-mode" style="width:100%; padding:10px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box;">
          <option value="points">נקודות (Points)</option>
          <option value="hours">שעות (Hours)</option>
          <option value="clock_in">שעון נוכחות (Clock-in)</option>
        </select>
      </div>
      <div class="form-group" style="margin-bottom:15px;">
        <label style="display:block; margin-bottom:5px; font-weight:600;">תיקייה משותפת (נתיב)</label>
        <input id="sys-shared" style="width:100%; padding:10px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box; direction:ltr; text-align:left;">
      </div>
      <div class="form-group" style="margin-bottom:15px;">
        <label style="display:block; margin-bottom:5px; font-weight:600;">נתיב לוגו (אופציונלי)</label>
        <input id="sys-logo" style="width:100%; padding:10px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box; direction:ltr; text-align:left;">
      </div>
      <div class="form-group" style="margin-bottom:15px;">
        <label style="display:block; margin-bottom:5px; font-weight:600;">שם מבצע</label>
        <input id="sys-campaign" style="width:100%; padding:10px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box;">
      </div>
      <div class="form-group" style="margin-bottom:15px;">
        <label style="display:block; margin-bottom:5px; font-weight:600;">תיקיית תמונות תלמידים (נתיב)</label>
        <input id="sys-photos" style="width:100%; padding:10px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box; direction:ltr; text-align:left;">
      </div>
      <div class="form-group" style="margin-bottom:15px;">
        <label style="display:block; margin-bottom:5px; font-weight:600;">מדפסת ברירת מחדל (אופציונלי)</label>
        <input id="sys-printer" style="width:100%; padding:10px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box; direction:ltr; text-align:left;">
      </div>
      <div>
        <button class="green" onclick="saveSystem()" style="padding:10px 20px; border-radius:6px; border:none; background:#2ecc71; color:white; font-weight:bold; cursor:pointer;">שמירה</button>
      </div>
    </div>

    <script>
      async function loadSystem() {
        try {
          const res = await fetch('/api/settings/system_settings');
          const data = await res.json();
          document.getElementById('sys-mode').value = data.deployment_mode || 'hybrid';
          document.getElementById('sys-work-mode').value = data.work_mode || 'points';
          document.getElementById('sys-shared').value = data.shared_folder || '';
          document.getElementById('sys-logo').value = data.logo_path || '';
          document.getElementById('sys-campaign').value = data.campaign_name || '';
          document.getElementById('sys-photos').value = data.photos_folder || '';
          document.getElementById('sys-printer').value = data.default_printer || '';
        } catch(e) {}
      }

      async function saveSystem() {
        const payload = {
            deployment_mode: document.getElementById('sys-mode').value,
            work_mode: document.getElementById('sys-work-mode').value,
            shared_folder: document.getElementById('sys-shared').value,
            logo_path: document.getElementById('sys-logo').value,
            campaign_name: document.getElementById('sys-campaign').value,
            photos_folder: document.getElementById('sys-photos').value,
            default_printer: document.getElementById('sys-printer').value
        };
        await fetch('/api/settings/save', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ key: 'system_settings', value: payload })
        });
        alert('נשמר בהצלחה');
      }

      loadSystem();
    </script>
    """
    return basic_web_shell("הגדרות מערכת", html_content, request=request)

@router.get("/web/display-settings", response_class=HTMLResponse)
def web_display_settings(request: Request):
    guard = web_require_admin_teacher(request)
    if guard: return guard
    
    tenant_id = web_tenant_from_cookie(request)
    conn = tenant_db_connection(tenant_id)
    try:
        value_json = get_web_setting_json(conn, 'display_settings', '{"enabled": true}')
    finally:
        try: conn.close()
        except: pass

    try: data = json.loads(value_json)
    except: data = {}

    def _v(k, default=''):
        return html.escape(str(data.get(k, default)))

    html_content = f"""
    <div style="max-width:800px; margin:0 auto;">
      <div style="margin-bottom:20px;">
        <h2 style="margin:0;">הגדרות תצוגה</h2>
      </div>

      <div class="card" style="padding:24px;">
        <div class="form-group" style="margin-bottom:15px;">
            <label style="display:block; font-weight:600; margin-bottom:5px;">כותרת ראשית (שם המוסד)</label>
            <input id="p_title" class="form-control" style="width:100%; padding:10px; border:1px solid #ddd; border-radius:8px;" value="{_v('title_text', 'ברוכים הבאים')}" />
        </div>
        <div class="form-group" style="margin-bottom:15px;">
            <label style="display:block; font-weight:600; margin-bottom:5px;">כותרת משנית</label>
            <input id="p_subtitle" class="form-control" style="width:100%; padding:10px; border:1px solid #ddd; border-radius:8px;" value="{_v('subtitle_text', '')}" />
        </div>
        <div class="form-group" style="margin-bottom:15px;">
            <label style="display:block; font-weight:600; margin-bottom:5px;">קישור ללוגו (URL)</label>
            <input id="p_logo" class="form-control" style="width:100%; padding:10px; border:1px solid #ddd; border-radius:8px; direction:ltr;" value="{_v('logo_url', '')}" />
        </div>
        <div class="form-group" style="margin-bottom:15px;">
            <label style="display:block; font-weight:600; margin-bottom:5px;">תמונת רקע (URL)</label>
            <input id="p_bg" class="form-control" style="width:100%; padding:10px; border:1px solid #ddd; border-radius:8px; direction:ltr;" value="{_v('background_url', '')}" />
        </div>
        
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:20px; margin-top:15px;">
            <div class="form-group">
                <label style="display:block; font-weight:600; margin-bottom:5px;">זמן רענון (שניות)</label>
                <input id="p_refresh" type="number" class="form-control" style="width:100%; padding:10px; border:1px solid #ddd; border-radius:8px;" value="{data.get('refresh_interval', 60)}" />
            </div>
            <div class="form-group">
                <label style="display:block; font-weight:600; margin-bottom:5px;">גודל גופן בסיסי (px)</label>
                <input id="p_fontsize" type="number" class="form-control" style="width:100%; padding:10px; border:1px solid #ddd; border-radius:8px;" value="{data.get('font_size', 16)}" />
            </div>
        </div>

        <div style="margin-top:20px; display:flex; gap:20px; flex-wrap:wrap;">
            <label class="ck" style="display:flex;align-items:center;gap:8px;"><input type="checkbox" id="p_enabled" {'checked' if data.get('enabled', True) else ''}> פעיל</label>
            <label class="ck" style="display:flex;align-items:center;gap:8px;"><input type="checkbox" id="p_dark" {'checked' if data.get('dark_mode', False) else ''}> מצב כהה</label>
            <label class="ck" style="display:flex;align-items:center;gap:8px;"><input type="checkbox" id="p_clock" {'checked' if data.get('show_clock', True) else ''}> הצג שעון</label>
            <label class="ck" style="display:flex;align-items:center;gap:8px;"><input type="checkbox" id="p_qr" {'checked' if data.get('show_qr', False) else ''}> הצג QR לסריקה</label>
        </div>

        <div style="margin-top:30px; border-top:1px solid #eee; padding-top:20px; text-align:left;">
            <button class="green" onclick="saveSettings()" style="padding:10px 20px; border-radius:8px; border:none; background:#2ecc71; color:white; font-weight:bold; cursor:pointer;">💾 שמור הגדרות</button>
            <a class="gray" href="/web/admin" style="padding:10px 20px; border-radius:8px; border:none; background:#95a5a6; color:white; font-weight:bold; cursor:pointer; text-decoration:none;">חזרה</a>
        </div>
      </div>
    </div>
    <script>
      async function saveSettings() {{
        const payload = {{
            title_text: document.getElementById('p_title').value,
            subtitle_text: document.getElementById('p_subtitle').value,
            logo_url: document.getElementById('p_logo').value,
            background_url: document.getElementById('p_bg').value,
            refresh_interval: parseInt(document.getElementById('p_refresh').value) || 60,
            font_size: parseInt(document.getElementById('p_fontsize').value) || 16,
            enabled: document.getElementById('p_enabled').checked,
            dark_mode: document.getElementById('p_dark').checked,
            show_clock: document.getElementById('p_clock').checked,
            show_qr: document.getElementById('p_qr').checked
        }};

        try {{
            const res = await fetch('/api/settings/save', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{ key: 'display_settings', value: payload }})
            }});
            if (res.ok) {{
                alert('נשמר בהצלחה');
            }} else {{
                alert('שגיאה בשמירה');
            }}
        }} catch (e) {{
            alert('שגיאה: ' + e);
        }}
      }}
    </script>
    """
    return basic_web_shell("הגדרות תצוגה", html_content, request=request)

@router.get("/web/colors", response_class=HTMLResponse)
def web_colors(request: Request):
    guard = web_require_admin_teacher(request)
    if guard: return guard
    
    html_content = """
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px;">
      <h2>צבעים לפי ניקוד</h2>
      <button class="green" onclick="openRangeModal()">+ טווח חדש</button>
    </div>
    
    <div class="card" style="padding:0; overflow:hidden;">
      <table style="width:100%; border-collapse:collapse;">
        <thead>
          <tr style="background:#f8f9fa; border-bottom:1px solid #eee;">
            <th style="padding:12px; text-align:right;">מינימום נקודות</th>
            <th style="padding:12px; text-align:right;">צבע</th>
            <th style="padding:12px; text-align:right;">פעולות</th>
          </tr>
        </thead>
        <tbody id="ranges-list"></tbody>
      </table>
    </div>

    <!-- Modal -->
    <div id="modal-range" class="modal-overlay" style="display:none; position:fixed; top:0; left:0; right:0; bottom:0; background:rgba(0,0,0,0.5); align-items:center; justify-content:center; z-index:1000;">
      <div class="modal" style="background:#fff; padding:24px; border-radius:12px; width:90%; max-width:400px; box-shadow:0 4px 20px rgba(0,0,0,0.2);">
        <h3 id="modal-title" style="margin-top:0;">טווח צבע</h3>
        <input type="hidden" id="range-index">
        <div class="form-group" style="margin-bottom:15px;">
          <label style="display:block; margin-bottom:5px; font-weight:600;">מינימום נקודות</label>
          <input type="number" id="range-min" style="width:100%; padding:8px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box;">
        </div>
        <div class="form-group" style="margin-bottom:15px;">
          <label style="display:block; margin-bottom:5px; font-weight:600;">צבע</label>
          <input type="color" id="range-color" style="width:100%; height:40px; padding:2px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box;">
        </div>
        <div style="display:flex; justify-content:flex-end; gap:10px; margin-top:20px;">
          <button class="gray" onclick="closeRangeModal()" style="padding:8px 16px; border:none; border-radius:6px; cursor:pointer;">ביטול</button>
          <button class="green" onclick="saveRange()" style="padding:8px 16px; background:#2ecc71; color:white; border:none; border-radius:6px; font-weight:600; cursor:pointer;">שמירה</button>
        </div>
      </div>
    </div>

    <script>
      let ranges = [];

      let fullColorSettings = {};
      async function loadRanges() {
        try {
          const res = await fetch('/api/settings/color_settings');
          const data = await res.json();
          let v = data.value;
          if (typeof v === 'string') try { v = JSON.parse(v); } catch(e) { v = {}; }
          if (!v || typeof v !== 'object') v = data;
          fullColorSettings = v;
          ranges = Array.isArray(v.color_ranges) ? v.color_ranges : (Array.isArray(v.ranges) ? v.ranges : []);
          ranges.sort((a, b) => (a.min || 0) - (b.min || 0));
          renderRanges();
        } catch(e) {}
      }

      function renderRanges() {
        const tbody = document.getElementById('ranges-list');
        if (ranges.length === 0) {
            tbody.innerHTML = '<tr><td colspan="3" style="padding:20px; text-align:center; color:#888;">אין טווחים מוגדרים</td></tr>';
            return;
        }
        tbody.innerHTML = ranges.map((r, idx) => `
          <tr style="border-bottom:1px solid #eee; hover:background:#fdfdfd;">
            <td style="padding:12px;">${r.min || 0}</td>
            <td style="padding:12px;"><span style="display:inline-block; width:20px; height:20px; background:${r.color}; vertical-align:middle; border:1px solid #ccc; border-radius:4px;"></span> ${r.color}</td>
            <td style="padding:12px;">
              <button onclick="editRange(${idx})" style="background:none; border:none; cursor:pointer; font-size:16px;">✏️</button>
              <button onclick="deleteRange(${idx})" style="background:none; border:none; cursor:pointer; font-size:16px;">🗑️</button>
            </td>
          </tr>
        `).join('');
      }

      function openRangeModal() {
        document.getElementById('range-index').value = '-1';
        document.getElementById('range-min').value = '0';
        document.getElementById('range-color').value = '#000000';
        document.getElementById('modal-title').textContent = 'הוספת טווח';
        document.getElementById('modal-range').style.display = 'flex';
      }

      function closeRangeModal() {
        document.getElementById('modal-range').style.display = 'none';
      }

      function editRange(idx) {
        const r = ranges[idx];
        document.getElementById('range-index').value = idx;
        document.getElementById('range-min').value = r.min || 0;
        document.getElementById('range-color').value = r.color || '#000000';
        document.getElementById('modal-title').textContent = 'עריכת טווח';
        document.getElementById('modal-range').style.display = 'flex';
      }

      async function saveRange() {
        const idx = parseInt(document.getElementById('range-index').value);
        const min = parseInt(document.getElementById('range-min').value) || 0;
        const color = document.getElementById('range-color').value;
        
        const newRange = { min, color };
        
        if (idx >= 0) {
            ranges[idx] = newRange;
        } else {
            ranges.push(newRange);
        }
        
        ranges.sort((a, b) => (a.min || 0) - (b.min || 0));
        
        await saveToServer();
        closeRangeModal();
        renderRanges();
      }

      async function deleteRange(idx) {
        if (!confirm('למחוק?')) return;
        ranges.splice(idx, 1);
        await saveToServer();
        renderRanges();
      }

      async function saveToServer() {
        fullColorSettings.color_ranges = ranges;
        delete fullColorSettings.ranges;
        await fetch('/api/settings/save', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ key: 'color_settings', value: fullColorSettings })
        });
      }

      loadRanges();
    </script>
    """
    return basic_web_shell("צבעים", html_content, request=request)

@router.get("/web/sounds", response_class=HTMLResponse)
def web_sounds(request: Request):
    guard = web_require_admin_teacher(request)
    if guard: return guard
    
    html_content = """
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px;">
      <h2>הגדרות צלילים</h2>
      <button class="green" onclick="openSoundModal()">+ צליל חדש</button>
    </div>
    
    <div class="card" style="padding:0; overflow:hidden;">
      <table style="width:100%; border-collapse:collapse;">
        <thead>
          <tr style="background:#f8f9fa; border-bottom:1px solid #eee;">
            <th style="padding:12px; text-align:right;">אירוע</th>
            <th style="padding:12px; text-align:right;">קובץ / URL</th>
            <th style="padding:12px; text-align:right;">פעולות</th>
          </tr>
        </thead>
        <tbody id="sounds-list"></tbody>
      </table>
    </div>

    <!-- Modal -->
    <div id="modal-sound" class="modal-overlay" style="display:none; position:fixed; top:0; left:0; right:0; bottom:0; background:rgba(0,0,0,0.5); align-items:center; justify-content:center; z-index:1000;">
      <div class="modal" style="background:#fff; padding:24px; border-radius:12px; width:90%; max-width:400px; box-shadow:0 4px 20px rgba(0,0,0,0.2);">
        <h3 id="modal-title" style="margin-top:0;">הגדרת צליל</h3>
        <input type="hidden" id="sound-index">
        <div class="form-group" style="margin-bottom:15px;">
          <label style="display:block; margin-bottom:5px; font-weight:600;">אירוע</label>
          <select id="sound-event" style="width:100%; padding:10px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box;">
            <option value="scan_success">סריקה מוצלחת (scan_success)</option>
            <option value="scan_error">שגיאת סריקה (scan_error)</option>
            <option value="bonus_success">קבלת בונוס (bonus_success)</option>
            <option value="shop_purchase">רכישה בקופה (shop_purchase)</option>
            <option value="level_up">עליית רמה (level_up)</option>
            <option value="custom">אחר (מותאם אישית)</option>
          </select>
          <input id="sound-event-custom" placeholder="שם אירוע..." style="width:100%; padding:8px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box; margin-top:5px; display:none;">
        </div>
        <div class="form-group" style="margin-bottom:15px;">
          <label style="display:block; margin-bottom:5px; font-weight:600;">קובץ / URL</label>
          <input id="sound-file" style="width:100%; padding:8px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box; direction:ltr; text-align:left;">
        </div>
        <div style="display:flex; justify-content:flex-end; gap:10px; margin-top:20px;">
          <button class="gray" onclick="closeSoundModal()" style="padding:8px 16px; border:none; border-radius:6px; cursor:pointer;">ביטול</button>
          <button class="green" onclick="saveSound()" style="padding:8px 16px; background:#2ecc71; color:white; border:none; border-radius:6px; font-weight:600; cursor:pointer;">שמירה</button>
        </div>
      </div>
    </div>

    <script>
      let sounds = [];
      let fullCS = {};

      async function loadSounds() {
        try {
          const res = await fetch('/api/settings/color_settings');
          const data = await res.json();
          let v = data.value;
          if (typeof v === 'string') try { v = JSON.parse(v); } catch(e) { v = {}; }
          if (!v || typeof v !== 'object') v = data;
          fullCS = v;
          const es = v.event_sounds || {};
          sounds = Object.entries(es).map(([k,f]) => ({event:k, file:String(f)}));
          renderSounds();
        } catch(e) {}
      }

      function renderSounds() {
        const tbody = document.getElementById('sounds-list');
        if (sounds.length === 0) {
            tbody.innerHTML = '<tr><td colspan="3" style="padding:20px; text-align:center; color:#888;">אין צלילים מוגדרים</td></tr>';
            return;
        }
        tbody.innerHTML = sounds.map((s, idx) => `
          <tr style="border-bottom:1px solid #eee; hover:background:#fdfdfd;">
            <td style="padding:12px;">${esc(s.event)}</td>
            <td style="padding:12px; direction:ltr; text-align:left;">${esc(s.file)}</td>
            <td style="padding:12px;">
              <button onclick="editSound(${idx})" style="background:none; border:none; cursor:pointer; font-size:16px;">✏️</button>
              <button onclick="deleteSound(${idx})" style="background:none; border:none; cursor:pointer; font-size:16px;">🗑️</button>
            </td>
          </tr>
        `).join('');
      }

      const evtSelect = document.getElementById('sound-event');
      const evtCustom = document.getElementById('sound-event-custom');
      
      evtSelect.addEventListener('change', () => {
        evtCustom.style.display = evtSelect.value === 'custom' ? 'block' : 'none';
      });

      function openSoundModal() {
        document.getElementById('sound-index').value = '-1';
        evtSelect.value = 'scan_success';
        evtCustom.style.display = 'none';
        evtCustom.value = '';
        document.getElementById('sound-file').value = '';
        document.getElementById('modal-title').textContent = 'הוספת צליל';
        document.getElementById('modal-sound').style.display = 'flex';
      }

      function closeSoundModal() {
        document.getElementById('modal-sound').style.display = 'none';
      }

      function editSound(idx) {
        const s = sounds[idx];
        document.getElementById('sound-index').value = idx;
        const standard = ['scan_success','scan_error','bonus_success','shop_purchase','level_up'].includes(s.event);
        evtSelect.value = standard ? s.event : 'custom';
        evtCustom.style.display = standard ? 'none' : 'block';
        evtCustom.value = standard ? '' : s.event;
        document.getElementById('sound-file').value = s.file || '';
        document.getElementById('modal-title').textContent = 'עריכת צליל';
        document.getElementById('modal-sound').style.display = 'flex';
      }

      async function saveSound() {
        const idx = parseInt(document.getElementById('sound-index').value);
        let event = evtSelect.value;
        if (event === 'custom') event = evtCustom.value.trim();
        const file = document.getElementById('sound-file').value.trim();
        
        if (!event || !file) return alert('נא להזין אירוע וקובץ');

        const newSound = { event, file };
        
        if (idx >= 0) {
            sounds[idx] = newSound;
        } else {
            sounds.push(newSound);
        }
        
        await saveToServer();
        closeSoundModal();
        renderSounds();
      }

      async function deleteSound(idx) {
        if (!confirm('למחוק?')) return;
        sounds.splice(idx, 1);
        await saveToServer();
        renderSounds();
      }

      async function saveToServer() {
        const es = {};
        sounds.forEach(s => { if (s.event && s.file) es[s.event] = s.file; });
        fullCS.event_sounds = es;
        await fetch('/api/settings/save', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ key: 'color_settings', value: fullCS })
        });
      }

      function esc(s) {
        return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
      }

      loadSounds();
    </script>
    """
    return basic_web_shell("צלילים", html_content, request=request)

@router.get("/web/bonuses", response_class=HTMLResponse)
def web_bonuses(request: Request):
    guard = web_require_admin_teacher(request)
    if guard: return guard
    
    html_content = """
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px;">
      <h2>בונוסים</h2>
      <button class="green" onclick="openBonusModal()">+ בונוס חדש</button>
    </div>
    
    <div class="card" style="padding:0; overflow:hidden;">
      <table style="width:100%; border-collapse:collapse;">
        <thead>
          <tr style="background:#f8f9fa; border-bottom:1px solid #eee;">
            <th style="padding:12px; text-align:right;">שם</th>
            <th style="padding:12px; text-align:right;">ניקוד</th>
            <th style="padding:12px; text-align:right;">פעולות</th>
          </tr>
        </thead>
        <tbody id="bonuses-list"></tbody>
      </table>
    </div>

    <!-- Modal -->
    <div id="modal-bonus" class="modal-overlay" style="display:none; position:fixed; top:0; left:0; right:0; bottom:0; background:rgba(0,0,0,0.5); align-items:center; justify-content:center; z-index:1000;">
      <div class="modal" style="background:#fff; padding:24px; border-radius:12px; width:90%; max-width:400px; box-shadow:0 4px 20px rgba(0,0,0,0.2);">
        <h3 id="modal-title" style="margin-top:0;">בונוס</h3>
        <input type="hidden" id="bonus-index">
        <div class="form-group" style="margin-bottom:15px;">
          <label style="display:block; margin-bottom:5px; font-weight:600;">שם הבונוס</label>
          <input id="bonus-name" style="width:100%; padding:8px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box;">
        </div>
        <div class="form-group" style="margin-bottom:15px;">
          <label style="display:block; margin-bottom:5px; font-weight:600;">ניקוד</label>
          <input type="number" id="bonus-points" style="width:100%; padding:8px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box;">
        </div>
        <div style="display:flex; justify-content:flex-end; gap:10px; margin-top:20px;">
          <button class="gray" onclick="closeBonusModal()" style="padding:8px 16px; border:none; border-radius:6px; cursor:pointer;">ביטול</button>
          <button class="green" onclick="saveBonus()" style="padding:8px 16px; background:#2ecc71; color:white; border:none; border-radius:6px; font-weight:600; cursor:pointer;">שמירה</button>
        </div>
      </div>
    </div>

    <script>
      let bonuses = [];

      async function loadBonuses() {
        try {
          const res = await fetch('/api/settings/bonuses_settings');
          const data = await res.json();
          bonuses = Array.isArray(data.items) ? data.items : [];
          renderBonuses();
        } catch(e) {}
      }

      function renderBonuses() {
        const tbody = document.getElementById('bonuses-list');
        if (bonuses.length === 0) {
            tbody.innerHTML = '<tr><td colspan="3" style="padding:20px; text-align:center; color:#888;">אין בונוסים מוגדרים</td></tr>';
            return;
        }
        tbody.innerHTML = bonuses.map((b, idx) => `
          <tr style="border-bottom:1px solid #eee; hover:background:#fdfdfd;">
            <td style="padding:12px;">${esc(b.name)}</td>
            <td style="padding:12px;">${b.points}</td>
            <td style="padding:12px;">
              <button onclick="editBonus(${idx})" style="background:none; border:none; cursor:pointer; font-size:16px;">✏️</button>
              <button onclick="deleteBonus(${idx})" style="background:none; border:none; cursor:pointer; font-size:16px;">🗑️</button>
            </td>
          </tr>
        `).join('');
      }

      function openBonusModal() {
        document.getElementById('bonus-index').value = '-1';
        document.getElementById('bonus-name').value = '';
        document.getElementById('bonus-points').value = '';
        document.getElementById('modal-title').textContent = 'הוספת בונוס';
        document.getElementById('modal-bonus').style.display = 'flex';
      }

      function closeBonusModal() {
        document.getElementById('modal-bonus').style.display = 'none';
      }

      function editBonus(idx) {
        const b = bonuses[idx];
        document.getElementById('bonus-index').value = idx;
        document.getElementById('bonus-name').value = b.name || '';
        document.getElementById('bonus-points').value = b.points || 0;
        document.getElementById('modal-title').textContent = 'עריכת בונוס';
        document.getElementById('modal-bonus').style.display = 'flex';
      }

      async function saveBonus() {
        const idx = parseInt(document.getElementById('bonus-index').value);
        const name = document.getElementById('bonus-name').value.trim();
        const points = parseInt(document.getElementById('bonus-points').value) || 0;
        
        if (!name) return alert('נא להזין שם');

        const newBonus = { name, points };
        
        if (idx >= 0) {
            bonuses[idx] = newBonus;
        } else {
            bonuses.push(newBonus);
        }
        
        await saveToServer();
        closeBonusModal();
        renderBonuses();
      }

      async function deleteBonus(idx) {
        if (!confirm('למחוק?')) return;
        bonuses.splice(idx, 1);
        await saveToServer();
        renderBonuses();
      }

      async function saveToServer() {
        await fetch('/api/settings/save', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ key: 'bonuses_settings', value: { items: bonuses } })
        });
      }

      function esc(s) {
        return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
      }

      loadBonuses();
    </script>
    """
    return basic_web_shell("בונוסים", html_content, request=request)

@router.get("/web/coins", response_class=HTMLResponse)
def web_coins(request: Request):
    guard = web_require_admin_teacher(request)
    if guard: return guard
    
    html_content = """
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px;">
      <h2>מטבעות ויעדים</h2>
      <button class="green" onclick="openCoinModal()">+ מטבע/יעד חדש</button>
    </div>
    
    <div class="card" style="padding:0; overflow:hidden;">
      <table style="width:100%; border-collapse:collapse;">
        <thead>
          <tr style="background:#f8f9fa; border-bottom:1px solid #eee;">
            <th style="padding:12px; text-align:right;">שם</th>
            <th style="padding:12px; text-align:right;">שווי (נקודות)</th>
            <th style="padding:12px; text-align:right;">פעולות</th>
          </tr>
        </thead>
        <tbody id="coins-list"></tbody>
      </table>
    </div>

    <!-- Modal -->
    <div id="modal-coin" class="modal-overlay" style="display:none; position:fixed; top:0; left:0; right:0; bottom:0; background:rgba(0,0,0,0.5); align-items:center; justify-content:center; z-index:1000;">
      <div class="modal" style="background:#fff; padding:24px; border-radius:12px; width:90%; max-width:400px; box-shadow:0 4px 20px rgba(0,0,0,0.2);">
        <h3 id="modal-title" style="margin-top:0;">מטבע / יעד</h3>
        <input type="hidden" id="coin-index">
        <div class="form-group" style="margin-bottom:15px;">
          <label style="display:block; margin-bottom:5px; font-weight:600;">שם המטבע/יעד</label>
          <input id="coin-name" style="width:100%; padding:8px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box;">
        </div>
        <div class="form-group" style="margin-bottom:15px;">
          <label style="display:block; margin-bottom:5px; font-weight:600;">שווי בנקודות</label>
          <input type="number" id="coin-value" style="width:100%; padding:8px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box;">
        </div>
        <div style="display:flex; justify-content:flex-end; gap:10px; margin-top:20px;">
          <button class="gray" onclick="closeCoinModal()" style="padding:8px 16px; border:none; border-radius:6px; cursor:pointer;">ביטול</button>
          <button class="green" onclick="saveCoin()" style="padding:8px 16px; background:#2ecc71; color:white; border:none; border-radius:6px; font-weight:600; cursor:pointer;">שמירה</button>
        </div>
      </div>
    </div>

    <script>
      let coins = [];
      let fullCS2 = {};

      async function loadCoins() {
        try {
          const res = await fetch('/api/settings/color_settings');
          const data = await res.json();
          let v = data.value;
          if (typeof v === 'string') try { v = JSON.parse(v); } catch(e) { v = {}; }
          if (!v || typeof v !== 'object') v = data;
          fullCS2 = v;
          coins = Array.isArray(v.coins) ? v.coins : [];
          renderCoins();
        } catch(e) {}
      }

      function renderCoins() {
        const tbody = document.getElementById('coins-list');
        if (coins.length === 0) {
            tbody.innerHTML = '<tr><td colspan="3" style="padding:20px; text-align:center; color:#888;">אין מטבעות מוגדרים</td></tr>';
            return;
        }
        tbody.innerHTML = coins.map((c, idx) => `
          <tr style="border-bottom:1px solid #eee; hover:background:#fdfdfd;">
            <td style="padding:12px;">${esc(c.name)}</td>
            <td style="padding:12px;">${c.value || 0}</td>
            <td style="padding:12px;">
              <button onclick="editCoin(${idx})" style="background:none; border:none; cursor:pointer; font-size:16px;">✏️</button>
              <button onclick="deleteCoin(${idx})" style="background:none; border:none; cursor:pointer; font-size:16px;">🗑️</button>
            </td>
          </tr>
        `).join('');
      }

      function openCoinModal() {
        document.getElementById('coin-index').value = '-1';
        document.getElementById('coin-name').value = '';
        document.getElementById('coin-value').value = '';
        document.getElementById('modal-title').textContent = 'הוספת מטבע';
        document.getElementById('modal-coin').style.display = 'flex';
      }

      function closeCoinModal() {
        document.getElementById('modal-coin').style.display = 'none';
      }

      function editCoin(idx) {
        const c = coins[idx];
        document.getElementById('coin-index').value = idx;
        document.getElementById('coin-name').value = c.name || '';
        document.getElementById('coin-value').value = c.value || 0;
        document.getElementById('modal-title').textContent = 'עריכת מטבע';
        document.getElementById('modal-coin').style.display = 'flex';
      }

      async function saveCoin() {
        const idx = parseInt(document.getElementById('coin-index').value);
        const name = document.getElementById('coin-name').value.trim();
        const value = parseInt(document.getElementById('coin-value').value) || 0;
        
        if (!name) return alert('נא להזין שם');

        const newCoin = { name, value };
        
        if (idx >= 0) {
            coins[idx] = newCoin;
        } else {
            coins.push(newCoin);
        }
        
        await saveToServer();
        closeCoinModal();
        renderCoins();
      }

      async function deleteCoin(idx) {
        if (!confirm('למחוק?')) return;
        coins.splice(idx, 1);
        await saveToServer();
        renderCoins();
      }

      async function saveToServer() {
        fullCS2.coins = coins;
        await fetch('/api/settings/save', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ key: 'color_settings', value: fullCS2 })
        });
      }

      function esc(s) {
        return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
      }

      loadCoins();
    </script>
    """
    return basic_web_shell("מטבעות", html_content, request=request)

@router.get("/web/goals", response_class=HTMLResponse)
def web_goals(request: Request):
    guard = web_require_admin_teacher(request)
    if guard: return guard
    
    html_content = """
    <div style="max-width:600px; margin:0 auto;">
        <div class="card" style="padding:24px;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:24px;">
                <h2 style="margin:0;">הגדרות יעד (Goal Bar)</h2>
                <div style="font-size:13px; color:#666;">הגדרות הפס שמופיע בתצוגה</div>
            </div>

            <div class="form-group" style="margin-bottom:20px; padding:15px; background:#f8f9fa; border-radius:8px;">
                <label style="display:flex; align-items:center; cursor:pointer; gap:10px; font-weight:bold;">
                    <input type="checkbox" id="goal-enabled" style="width:20px; height:20px;">
                    הפעל תצוגת יעד
                </label>
                <div style="font-size:12px; color:#666; margin-right:30px; margin-top:4px;">האם להציג את פס ההתקדמות על גבי המסך הראשי</div>
            </div>

            <div class="form-group">
                <label>צבע מילוי (התקדמות)</label>
                <div style="display:flex; gap:10px;">
                    <input type="color" id="goal-fill" style="width:60px; height:40px; padding:0; border:none; cursor:pointer;">
                    <input type="text" id="goal-fill-text" style="direction:ltr;" onchange="document.getElementById('goal-fill').value = this.value">
                </div>
            </div>

            <div class="form-group">
                <label>צבע רקע (ריק)</label>
                <div style="display:flex; gap:10px;">
                    <input type="color" id="goal-empty" style="width:60px; height:40px; padding:0; border:none; cursor:pointer;">
                    <input type="text" id="goal-empty-text" style="direction:ltr;" onchange="document.getElementById('goal-empty').value = this.value">
                </div>
            </div>

            <div class="form-group">
                <label>צבע מסגרת</label>
                <div style="display:flex; gap:10px;">
                    <input type="color" id="goal-border" style="width:60px; height:40px; padding:0; border:none; cursor:pointer;">
                    <input type="text" id="goal-border-text" style="direction:ltr;" onchange="document.getElementById('goal-border').value = this.value">
                </div>
            </div>

            <div class="form-group" style="margin-bottom:20px;">
                <label style="display:flex; align-items:center; cursor:pointer; gap:10px;">
                    <input type="checkbox" id="goal-percent" style="width:18px; height:18px;">
                    הצג אחוזים (%) בתוך הפס
                </label>
            </div>

            <div style="margin-top:30px; text-align:left;">
                <button class="green" onclick="saveGoals()" style="padding:12px 30px; font-size:16px; font-weight:bold; border-radius:8px; border:none; background:#2ecc71; color:white; cursor:pointer;">שמור שינויים</button>
            </div>
        </div>
    </div>

    <script>
        // Sync color inputs
        ['fill', 'empty', 'border'].forEach(k => {
            const picker = document.getElementById('goal-' + k);
            const text = document.getElementById('goal-' + k + '-text');
            picker.addEventListener('input', () => text.value = picker.value);
            text.addEventListener('input', () => picker.value = text.value);
        });

        async function loadGoals() {
            try {
                const res = await fetch('/api/settings/goal_settings');
                const data = await res.json();
                
                document.getElementById('goal-enabled').checked = !!data.enabled;
                document.getElementById('goal-percent').checked = !!data.show_percent;
                
                setColor('fill', data.filled_color || '#2ecc71');
                setColor('empty', data.empty_color || '#ecf0f1');
                setColor('border', data.border_color || '#2c3e50');
            } catch(e) {
                console.error(e);
            }
        }

        function setColor(key, val) {
            document.getElementById('goal-' + key).value = val;
            document.getElementById('goal-' + key + '-text').value = val;
        }

        async function saveGoals() {
            const payload = {
                enabled: document.getElementById('goal-enabled').checked,
                show_percent: document.getElementById('goal-percent').checked,
                filled_color: document.getElementById('goal-fill').value,
                empty_color: document.getElementById('goal-empty').value,
                border_color: document.getElementById('goal-border').value
            };

            try {
                await fetch('/api/settings/save', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ key: 'goal_settings', value: payload })
                });
                alert('הגדרות נשמרו בהצלחה');
            } catch(e) {
                alert('שגיאה בשמירה');
            }
        }

        loadGoals();
    </script>
    """
    return basic_web_shell("יעדים", html_content, request=request)

@router.get("/web/holidays", response_class=HTMLResponse)
def web_holidays(request: Request):
    guard = web_require_admin_teacher(request)
    if guard: return guard
    
    html_content = """
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px;">
      <h2>חגים וחופשות</h2>
      <button class="green" onclick="openHolidayModal()">+ חג חדש</button>
    </div>
    
    <div class="card" style="padding:0; overflow:hidden;">
      <table style="width:100%; border-collapse:collapse;">
        <thead>
          <tr style="background:#f8f9fa; border-bottom:1px solid #eee;">
            <th style="padding:12px; text-align:right;">שם החג</th>
            <th style="padding:12px; text-align:right;">תאריך התחלה</th>
            <th style="padding:12px; text-align:right;">תאריך סיום</th>
            <th style="padding:12px; text-align:right;">פעולות</th>
          </tr>
        </thead>
        <tbody id="holidays-list"></tbody>
      </table>
    </div>

    <!-- Modal -->
    <div id="modal-holiday" class="modal-overlay" style="display:none; position:fixed; top:0; left:0; right:0; bottom:0; background:rgba(0,0,0,0.5); align-items:center; justify-content:center; z-index:1000;">
      <div class="modal" style="background:#fff; padding:24px; border-radius:12px; width:90%; max-width:400px; box-shadow:0 4px 20px rgba(0,0,0,0.2);">
        <h3 id="modal-title" style="margin-top:0;">חג / חופשה</h3>
        <input type="hidden" id="holiday-index">
        <div class="form-group" style="margin-bottom:15px;">
          <label style="display:block; margin-bottom:5px; font-weight:600;">שם החג</label>
          <input id="holiday-name" style="width:100%; padding:8px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box;">
        </div>
        <div class="form-group" style="margin-bottom:15px;">
          <label style="display:block; margin-bottom:5px; font-weight:600;">תאריך התחלה</label>
          <input type="date" id="holiday-start" style="width:100%; padding:8px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box;">
        </div>
        <div class="form-group" style="margin-bottom:15px;">
          <label style="display:block; margin-bottom:5px; font-weight:600;">תאריך סיום</label>
          <input type="date" id="holiday-end" style="width:100%; padding:8px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box;">
        </div>
        <div class="form-group" style="margin-bottom:15px;">
          <label style="display:block; margin-bottom:5px; font-weight:600;">הודעה (אופציונלי)</label>
          <input id="holiday-message" placeholder="הודעה שתוצג בימי החג" style="width:100%; padding:8px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box;">
        </div>
        <div class="form-group" style="margin-bottom:15px;">
          <label style="display:block; margin-bottom:5px; font-weight:600;">כתובת תמונה (אופציונלי)</label>
          <input id="holiday-image" placeholder="URL של תמונת חג" style="width:100%; padding:8px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box; direction:ltr;">
        </div>
        <label style="display:flex;align-items:center;gap:6px;font-size:13px;margin-bottom:15px;"><input type="checkbox" id="holiday-block" style="width:16px;height:16px;"> חסום סריקות בימי החג</label>
        <div style="display:flex; justify-content:flex-end; gap:10px; margin-top:20px;">
          <button class="gray" onclick="closeHolidayModal()" style="padding:8px 16px; border:none; border-radius:6px; cursor:pointer;">ביטול</button>
          <button class="green" onclick="saveHoliday()" style="padding:8px 16px; background:#2ecc71; color:white; border:none; border-radius:6px; font-weight:600; cursor:pointer;">שמירה</button>
        </div>
      </div>
    </div>

    <script>
      let holidays = [];

      async function loadHolidays() {
        try {
          const res = await fetch('/api/settings/holidays');
          const data = await res.json();
          holidays = Array.isArray(data.items) ? data.items : [];
          renderHolidays();
        } catch(e) {}
      }

      function renderHolidays() {
        const tbody = document.getElementById('holidays-list');
        if (holidays.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" style="padding:20px; text-align:center; color:#888;">אין חגים מוגדרים</td></tr>';
            return;
        }
        tbody.innerHTML = holidays.map((h, idx) => `
          <tr style="border-bottom:1px solid #eee; hover:background:#fdfdfd;">
            <td style="padding:12px;">${esc(h.name)}</td>
            <td style="padding:12px;">${formatDate(h.start_date)}</td>
            <td style="padding:12px;">${formatDate(h.end_date)}</td>
            <td style="padding:12px;">
              <button onclick="editHoliday(${idx})" style="background:none; border:none; cursor:pointer; font-size:16px;">✏️</button>
              <button onclick="deleteHoliday(${idx})" style="background:none; border:none; cursor:pointer; font-size:16px;">🗑️</button>
            </td>
          </tr>
        `).join('');
      }

      function formatDate(d) {
        if (!d) return '';
        try { return d.split('T')[0].split('-').reverse().join('.'); } catch(e) { return d; }
      }

      function openHolidayModal() {
        document.getElementById('holiday-index').value = '-1';
        document.getElementById('holiday-name').value = '';
        document.getElementById('holiday-start').value = '';
        document.getElementById('holiday-end').value = '';
        document.getElementById('holiday-message').value = '';
        document.getElementById('holiday-image').value = '';
        document.getElementById('holiday-block').checked = false;
        document.getElementById('modal-title').textContent = 'הוספת חג';
        document.getElementById('modal-holiday').style.display = 'flex';
      }

      function closeHolidayModal() {
        document.getElementById('modal-holiday').style.display = 'none';
      }

      function editHoliday(idx) {
        const h = holidays[idx];
        document.getElementById('holiday-index').value = idx;
        document.getElementById('holiday-name').value = h.name || '';
        document.getElementById('holiday-start').value = h.start_date || '';
        document.getElementById('holiday-end').value = h.end_date || '';
        document.getElementById('holiday-message').value = h.message || '';
        document.getElementById('holiday-image').value = h.image_url || '';
        document.getElementById('holiday-block').checked = !!h.block_scans;
        document.getElementById('modal-title').textContent = 'עריכת חג';
        document.getElementById('modal-holiday').style.display = 'flex';
      }

      async function saveHoliday() {
        const idx = parseInt(document.getElementById('holiday-index').value);
        const name = document.getElementById('holiday-name').value.trim();
        const start = document.getElementById('holiday-start').value;
        const end = document.getElementById('holiday-end').value;
        
        if (!name) return alert('נא להזין שם');

        const newHoliday = {
          name, start_date: start, end_date: end,
          message: document.getElementById('holiday-message').value,
          image_url: document.getElementById('holiday-image').value,
          block_scans: document.getElementById('holiday-block').checked
        };
        
        if (idx >= 0) {
            holidays[idx] = newHoliday;
        } else {
            holidays.push(newHoliday);
        }
        
        await saveToServer();
        closeHolidayModal();
        renderHolidays();
      }

      async function deleteHoliday(idx) {
        if (!confirm('למחוק חג זה?')) return;
        holidays.splice(idx, 1);
        await saveToServer();
        renderHolidays();
      }

      async function saveToServer() {
        await fetch('/api/settings/save', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ key: 'holidays', value: { items: holidays } })
        });
      }

      function esc(s) {
        return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
      }

      loadHolidays();
    </script>
    """
    return basic_web_shell("חגים וחופשות", html_content, request=request)

@router.get("/web/upgrades", response_class=HTMLResponse)
def web_upgrades(request: Request):
    guard = web_require_admin_teacher(request)
    if guard: return guard
    return basic_web_shell("צלילים, צבעים ומטבעות", upgrades_html(), request=request)

@router.get("/web/special-bonus", response_class=HTMLResponse)
def web_special_bonus(request: Request):
    guard = web_require_admin_teacher(request)
    if guard: return guard

    html_content = """
    <div class="card" style="max-width:800px; margin:0 auto; padding:20px;">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px;">
        <h2 style="margin:0;">בונוסים מיוחדים</h2>
        <button class="green" onclick="openItemModal()">+ הוסף חדש</button>
      </div>
      <table style="width:100%; border-collapse:collapse;">
        <thead>
          <tr style="background:#f8f9fa; border-bottom:1px solid #eee;">
            <th style="padding:12px; text-align:right;">תיאור</th>
            <th style="padding:12px; text-align:right;">ניקוד</th>
            <th style="padding:12px; text-align:right;">פעולות</th>
          </tr>
        </thead>
        <tbody id="items-list"></tbody>
      </table>
    </div>

    <!-- Modal -->
    <div id="modal-item" class="modal-overlay" style="display:none; position:fixed; top:0; left:0; right:0; bottom:0; background:rgba(0,0,0,0.5); align-items:center; justify-content:center; z-index:1000;">
      <div class="modal" style="background:#fff; padding:24px; border-radius:12px; width:90%; max-width:400px; box-shadow:0 4px 20px rgba(0,0,0,0.2);">
        <h3 id="modal-title" style="margin-top:0;">פריט בונוס</h3>
        <input type="hidden" id="item-index">
        <div class="form-group" style="margin-bottom:15px;">
          <label style="display:block; margin-bottom:5px; font-weight:600;">תיאור</label>
          <input id="item-name" style="width:100%; padding:8px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box;">
        </div>
        <div class="form-group" style="margin-bottom:15px;">
          <label style="display:block; margin-bottom:5px; font-weight:600;">ניקוד</label>
          <input type="number" id="item-points" style="width:100%; padding:8px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box;">
        </div>
        <div style="display:flex; justify-content:flex-end; gap:10px; margin-top:20px;">
          <button class="gray" onclick="closeItemModal()" style="padding:8px 16px; border:none; border-radius:6px; cursor:pointer;">ביטול</button>
          <button class="green" onclick="saveItem()" style="padding:8px 16px; background:#2ecc71; color:white; border:none; border-radius:6px; font-weight:600; cursor:pointer;">שמירה</button>
        </div>
      </div>
    </div>

    <script>
      let items = [];

      async function loadItems() {
        try {
          const res = await fetch('/api/settings/special_bonus');
          const data = await res.json();
          items = Array.isArray(data.items) ? data.items : [];
          renderItems();
        } catch(e) {}
      }

      function renderItems() {
        const tbody = document.getElementById('items-list');
        if (items.length === 0) {
            tbody.innerHTML = '<tr><td colspan="3" style="padding:20px; text-align:center; color:#888;">אין פריטים</td></tr>';
            return;
        }
        tbody.innerHTML = items.map((b, idx) => `
          <tr style="border-bottom:1px solid #eee; hover:background:#fdfdfd;">
            <td style="padding:12px;">${esc(b.name)}</td>
            <td style="padding:12px;">${b.points}</td>
            <td style="padding:12px;">
              <button onclick="editItem(${idx})" style="background:none; border:none; cursor:pointer; font-size:16px;">✏️</button>
              <button onclick="deleteItem(${idx})" style="background:none; border:none; cursor:pointer; font-size:16px;">🗑️</button>
            </td>
          </tr>
        `).join('');
      }

      function openItemModal() {
        document.getElementById('item-index').value = '-1';
        document.getElementById('item-name').value = '';
        document.getElementById('item-points').value = '';
        document.getElementById('modal-title').textContent = 'הוספת פריט';
        document.getElementById('modal-item').style.display = 'flex';
      }

      function closeItemModal() {
        document.getElementById('modal-item').style.display = 'none';
      }

      function editItem(idx) {
        const b = items[idx];
        document.getElementById('item-index').value = idx;
        document.getElementById('item-name').value = b.name || '';
        document.getElementById('item-points').value = b.points || 0;
        document.getElementById('modal-title').textContent = 'עריכת פריט';
        document.getElementById('modal-item').style.display = 'flex';
      }

      async function saveItem() {
        const idx = parseInt(document.getElementById('item-index').value);
        const name = document.getElementById('item-name').value.trim();
        const points = parseInt(document.getElementById('item-points').value) || 0;
        
        if (!name) return alert('נא להזין שם');

        const newItem = { name, points };
        
        if (idx >= 0) {
            items[idx] = newItem;
        } else {
            items.push(newItem);
        }
        
        await saveToServer();
        closeItemModal();
        renderItems();
      }

      async function deleteItem(idx) {
        if (!confirm('למחוק?')) return;
        items.splice(idx, 1);
        await saveToServer();
        renderItems();
      }

      async function saveToServer() {
        await fetch('/api/settings/save', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ key: 'special_bonus', value: { items: items } })
        });
      }

      function esc(s) {
        return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
      }

      loadItems();
    </script>
    """
    return basic_web_shell("בונוס מיוחד", html_content, request=request)

@router.get("/web/time-bonus", response_class=HTMLResponse)
def web_time_bonus(request: Request):
    guard = web_require_admin_teacher(request)
    if guard: return guard
    
    html_content = """
    <div style="display:flex; justify-content:flex-start; align-items:center; margin-bottom:20px;">
      <button class="green" onclick="openRuleModal()">+ כלל חדש</button>
    </div>
    
    <div class="card" style="padding:0; overflow:hidden;">
      <table style="width:100%; border-collapse:collapse;">
        <thead>
          <tr style="background: rgba(15, 32, 39, 0.98); border-bottom:1px solid rgba(255,255,255,0.12);">
            <th style="padding:12px; text-align:right; color:#fff;">שם הכלל</th>
            <th style="padding:12px; text-align:right; color:#fff;">שעות</th>
            <th style="padding:12px; text-align:right; color:#fff;">בונוס (נקודות)</th>
            <th style="padding:12px; text-align:right; color:#fff;">פעולות</th>
          </tr>
        </thead>
        <tbody id="rules-list"></tbody>
      </table>
    </div>

    <!-- Modal -->
    <div id="modal-rule" class="modal-overlay" style="display:none; position:fixed; top:0; left:0; right:0; bottom:0; background:rgba(0,0,0,0.5); align-items:flex-start; justify-content:center; z-index:1000; padding-top:40px;">
      <div class="modal" style="background:#fff; padding:24px; border-radius:12px; width:90%; max-width:520px; max-height:85vh; overflow-y:auto; box-shadow:0 4px 20px rgba(0,0,0,0.2); direction:rtl;">
        <h3 id="modal-title" style="margin-top:0;">כלל בונוס זמן</h3>
        <input type="hidden" id="rule-index">
        <div style="margin-bottom:12px;">
          <label style="display:block; margin-bottom:4px; font-weight:600;">שם הכלל</label>
          <input id="rule-name" style="width:100%; padding:8px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box;">
        </div>
        <div style="margin-bottom:12px;">
          <label style="display:block; margin-bottom:4px; font-weight:600;">שם קבוצה</label>
          <input id="rule-group" placeholder="(אופציונלי – לקיבוץ כללים יחד)" style="width:100%; padding:8px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box;">
        </div>
        <div style="display:flex; gap:10px; margin-bottom:12px;">
            <div style="flex:1;">
                <label style="display:block; margin-bottom:4px; font-weight:600;">התחלה</label>
                <input type="time" id="rule-start" style="width:100%; padding:8px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box; direction:ltr;">
            </div>
            <div style="flex:1;">
                <label style="display:block; margin-bottom:4px; font-weight:600;">סיום</label>
                <input type="time" id="rule-end" style="width:100%; padding:8px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box; direction:ltr;">
            </div>
        </div>
        <div style="margin-bottom:12px;">
          <label style="display:block; margin-bottom:4px; font-weight:600;">תוספת נקודות</label>
          <input type="number" id="rule-points" style="width:100%; padding:8px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box;">
        </div>
        <div style="margin-bottom:12px;">
          <label style="display:block; margin-bottom:4px; font-weight:600;">ימים בשבוע (הפרד בפסיק, לדוגמה: 1,2,3,4,5)</label>
          <input id="rule-days" placeholder="ריק = כל הימים" style="width:100%; padding:8px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box; direction:ltr;">
        </div>
        <div style="margin-bottom:12px;">
          <label style="display:block; margin-bottom:4px; font-weight:600;">כיתות (הפרד בפסיק, לדוגמה: א,ב,ג)</label>
          <input id="rule-classes" placeholder="ריק = כל הכיתות" style="width:100%; padding:8px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box;">
        </div>
        <div style="margin-bottom:12px;">
          <label style="display:block; margin-bottom:4px; font-weight:600;">צליל</label>
          <input id="rule-sound" placeholder="מפתח צליל (אופציונלי)" style="width:100%; padding:8px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box;">
        </div>
        <div style="display:flex; gap:16px; margin-bottom:12px; flex-wrap:wrap;">
          <label style="display:flex;align-items:center;gap:6px;font-size:13px;"><input type="checkbox" id="rule-general" checked style="width:16px;height:16px;"> כללי (לכולם)</label>
          <label style="display:flex;align-items:center;gap:6px;font-size:13px;"><input type="checkbox" id="rule-public" checked style="width:16px;height:16px;"> הצג בעמדה ציבורית</label>
          <label style="display:flex;align-items:center;gap:6px;font-size:13px;"><input type="checkbox" id="rule-active" checked style="width:16px;height:16px;"> פעיל</label>
        </div>
        <div style="display:flex; justify-content:flex-end; gap:10px; margin-top:16px;">
          <button class="gray" onclick="closeRuleModal()" style="padding:8px 16px; border:none; border-radius:6px; cursor:pointer;">ביטול</button>
          <button class="green" onclick="saveRule()" style="padding:8px 16px; background:#2ecc71; color:white; border:none; border-radius:6px; font-weight:600; cursor:pointer;">שמירה</button>
        </div>
      </div>
    </div>

    <script>
      let rules = [];

      async function loadRules() {
        try {
          const res = await fetch('/api/time-bonus');
          const data = await res.json();
          rules = Array.isArray(data.rules) ? data.rules : [];
          renderRules();
        } catch(e) {}
      }

      function renderRules() {
        const tbody = document.getElementById('rules-list');
        if (rules.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" style="padding:20px; text-align:center; color:#888;">אין כללים מוגדרים</td></tr>';
            return;
        }
        // Group by group_name
        const groups = {};
        rules.forEach((r, idx) => {
            const g = r.group_name || r.name || 'ללא קבוצה';
            if (!groups[g]) groups[g] = [];
            groups[g].push({...r, _idx: idx});
        });
        let html = '';
        let gIdx = 0;
        for (const [gName, items] of Object.entries(groups)) {
            if (gIdx > 0) html += '<tr><td colspan="4" style="padding:4px; background:#dfe6e9;"></td></tr>';
            html += '<tr style="background:rgba(52,152,219,0.15);"><td colspan="4" style="padding:10px 12px; font-weight:bold; color:#2c3e50;">📋 ' + esc(gName) + ' (' + items.length + ' כללים)</td></tr>';
            items.forEach(r => {
                html += '<tr style="border-bottom:1px solid #eee;">' +
                  '<td style="padding:10px 12px 10px 12px;">' + esc(r.name) + '</td>' +
                  '<td style="padding:10px 12px; direction:ltr; text-align:right;">' + r.start_time + ' - ' + r.end_time + '</td>' +
                  '<td style="padding:10px 12px;">' + r.points + '</td>' +
                  '<td style="padding:10px 12px;">' +
                    '<button onclick="editRule(' + r._idx + ')" style="background:none;border:none;cursor:pointer;font-size:16px;">✏️</button>' +
                    '<button onclick="deleteRule(' + r._idx + ')" style="background:none;border:none;cursor:pointer;font-size:16px;">🗑️</button>' +
                  '</td></tr>';
            });
            gIdx++;
        }
        tbody.innerHTML = html;
      }

      function openRuleModal() {
        document.getElementById('rule-index').value = '-1';
        document.getElementById('rule-name').value = '';
        document.getElementById('rule-group').value = '';
        document.getElementById('rule-start').value = '';
        document.getElementById('rule-end').value = '';
        document.getElementById('rule-points').value = '';
        document.getElementById('rule-days').value = '';
        document.getElementById('rule-classes').value = '';
        document.getElementById('rule-sound').value = '';
        document.getElementById('rule-general').checked = true;
        document.getElementById('rule-public').checked = true;
        document.getElementById('rule-active').checked = true;
        document.getElementById('modal-title').textContent = 'הוספת כלל';
        document.getElementById('modal-rule').style.display = 'flex';
      }

      function closeRuleModal() {
        document.getElementById('modal-rule').style.display = 'none';
      }

      function editRule(idx) {
        const r = rules[idx];
        document.getElementById('rule-index').value = idx;
        document.getElementById('rule-name').value = r.name || '';
        document.getElementById('rule-group').value = r.group_name || '';
        document.getElementById('rule-start').value = r.start_time || '';
        document.getElementById('rule-end').value = r.end_time || '';
        document.getElementById('rule-points').value = r.points || 0;
        document.getElementById('rule-days').value = r.days_of_week || '';
        document.getElementById('rule-classes').value = r.classes || '';
        document.getElementById('rule-sound').value = r.sound_key || '';
        document.getElementById('rule-general').checked = r.is_general !== 0;
        document.getElementById('rule-public').checked = r.is_shown_public !== 0;
        document.getElementById('rule-active').checked = r.is_active !== 0;
        document.getElementById('modal-title').textContent = 'עריכת כלל';
        document.getElementById('modal-rule').style.display = 'flex';
      }

      async function saveRule() {
        const idx = parseInt(document.getElementById('rule-index').value);
        const name = document.getElementById('rule-name').value.trim();
        const start = document.getElementById('rule-start').value;
        const end = document.getElementById('rule-end').value;
        const points = parseInt(document.getElementById('rule-points').value) || 0;
        
        if (!name) return alert('נא להזין שם');

        const existingId = (idx >= 0 && rules[idx]) ? rules[idx].id : null;
        const newRule = {
          id: existingId, name, start_time: start, end_time: end, points,
          group_name: document.getElementById('rule-group').value.trim(),
          days_of_week: document.getElementById('rule-days').value.trim(),
          classes: document.getElementById('rule-classes').value.trim(),
          sound_key: document.getElementById('rule-sound').value.trim(),
          is_general: document.getElementById('rule-general').checked ? 1 : 0,
          is_shown_public: document.getElementById('rule-public').checked ? 1 : 0,
          is_active: document.getElementById('rule-active').checked ? 1 : 0
        };
        
        if (idx >= 0) {
            rules[idx] = newRule;
        } else {
            rules.push(newRule);
        }
        
        await saveToServer();
        closeRuleModal();
        renderRules();
      }

      async function deleteRule(idx) {
        if (!confirm('למחוק?')) return;
        rules.splice(idx, 1);
        await saveToServer();
        renderRules();
      }

      async function saveToServer() {
        await fetch('/api/time-bonus/save', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ rules: rules })
        });
      }

      function esc(s) {
        return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
      }

      loadRules();
    </script>
    """
    return basic_web_shell("בונוס זמנים", html_content, request=request)

@router.get("/web/cashier", response_class=HTMLResponse)
def web_cashier(request: Request):
    guard = web_require_admin_teacher(request)
    if guard: return guard
    
    html_content = """
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px;">
      <h2>עמדת קופה</h2>
      <button class="green" onclick="openItemModal()">+ פריט קופה חדש</button>
    </div>
    
    <div class="card" style="padding:20px; background:#fff; border-radius:10px; border:1px solid #eee; margin-bottom:20px;">
      <label class="ck" style="display:flex; align-items:center; gap:8px; font-weight:600;">
        <input type="checkbox" id="cashier-enabled" style="width:18px; height:18px;" onchange="saveToServer()"> קופה פעילה
      </label>
    </div>

    <div class="card" style="padding:0; overflow:hidden;">
      <table style="width:100%; border-collapse:collapse;">
        <thead>
          <tr style="background:#f8f9fa; border-bottom:1px solid #eee;">
            <th style="padding:12px; text-align:right;">שם הפריט</th>
            <th style="padding:12px; text-align:right;">מחיר (נקודות)</th>
            <th style="padding:12px; text-align:right;">פעולות</th>
          </tr>
        </thead>
        <tbody id="items-list"></tbody>
      </table>
    </div>

    <!-- Modal -->
    <div id="modal-item" class="modal-overlay" style="display:none; position:fixed; top:0; left:0; right:0; bottom:0; background:rgba(0,0,0,0.5); align-items:center; justify-content:center; z-index:1000;">
      <div class="modal" style="background:#fff; padding:24px; border-radius:12px; width:90%; max-width:400px; box-shadow:0 4px 20px rgba(0,0,0,0.2);">
        <h3 id="modal-title" style="margin-top:0;">פריט קופה</h3>
        <input type="hidden" id="item-index">
        <div class="form-group" style="margin-bottom:15px;">
          <label style="display:block; margin-bottom:5px; font-weight:600;">שם הפריט</label>
          <input id="item-name" style="width:100%; padding:8px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box;">
        </div>
        <div class="form-group" style="margin-bottom:15px;">
          <label style="display:block; margin-bottom:5px; font-weight:600;">מחיר בנקודות</label>
          <input type="number" id="item-price" style="width:100%; padding:8px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box;">
        </div>
        <div style="display:flex; justify-content:flex-end; gap:10px; margin-top:20px;">
          <button class="gray" onclick="closeItemModal()" style="padding:8px 16px; border:none; border-radius:6px; cursor:pointer;">ביטול</button>
          <button class="green" onclick="saveItem()" style="padding:8px 16px; background:#2ecc71; color:white; border:none; border-radius:6px; font-weight:600; cursor:pointer;">שמירה</button>
        </div>
      </div>
    </div>

    <script>
      let items = [];
      let enabled = true;

      async function loadItems() {
        try {
          const res = await fetch('/api/settings/cashier_settings');
          const data = await res.json();
          items = Array.isArray(data.items) ? data.items : [];
          enabled = !!data.enabled;
          document.getElementById('cashier-enabled').checked = enabled;
          renderItems();
        } catch(e) {}
      }

      function renderItems() {
        const tbody = document.getElementById('items-list');
        if (items.length === 0) {
            tbody.innerHTML = '<tr><td colspan="3" style="padding:20px; text-align:center; color:#888;">אין פריטים</td></tr>';
            return;
        }
        tbody.innerHTML = items.map((b, idx) => `
          <tr style="border-bottom:1px solid #eee; hover:background:#fdfdfd;">
            <td style="padding:12px;">${esc(b.name)}</td>
            <td style="padding:12px;">${b.price}</td>
            <td style="padding:12px;">
              <button onclick="editItem(${idx})" style="background:none; border:none; cursor:pointer; font-size:16px;">✏️</button>
              <button onclick="deleteItem(${idx})" style="background:none; border:none; cursor:pointer; font-size:16px;">🗑️</button>
            </td>
          </tr>
        `).join('');
      }

      function openItemModal() {
        document.getElementById('item-index').value = '-1';
        document.getElementById('item-name').value = '';
        document.getElementById('item-price').value = '';
        document.getElementById('modal-title').textContent = 'הוספת פריט';
        document.getElementById('modal-item').style.display = 'flex';
      }

      function closeItemModal() {
        document.getElementById('modal-item').style.display = 'none';
      }

      function editItem(idx) {
        const b = items[idx];
        document.getElementById('item-index').value = idx;
        document.getElementById('item-name').value = b.name || '';
        document.getElementById('item-price').value = b.price || 0;
        document.getElementById('modal-title').textContent = 'עריכת פריט';
        document.getElementById('modal-item').style.display = 'flex';
      }

      async function saveItem() {
        const idx = parseInt(document.getElementById('item-index').value);
        const name = document.getElementById('item-name').value.trim();
        const price = parseInt(document.getElementById('item-price').value) || 0;
        
        if (!name) return alert('נא להזין שם');

        const newItem = { name, price };
        
        if (idx >= 0) {
            items[idx] = newItem;
        } else {
            items.push(newItem);
        }
        
        await saveToServer();
        closeItemModal();
        renderItems();
      }

      async function deleteItem(idx) {
        if (!confirm('למחוק?')) return;
        items.splice(idx, 1);
        await saveToServer();
        renderItems();
      }

      async function saveToServer() {
        const en = document.getElementById('cashier-enabled').checked;
        await fetch('/api/settings/save', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ key: 'cashier_settings', value: { enabled: en, items: items } })
        });
      }

      function esc(s) {
        return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
      }

      loadItems();
    </script>
    """
    return basic_web_shell("עמדת קופה", html_content, request=request)

@router.get('/api/settings/public-closures')
def api_public_closures_list(request: Request) -> Dict[str, Any]:
    guard = web_require_admin_teacher(request)
    if guard: raise HTTPException(status_code=401)
    
    tenant_id = web_tenant_from_cookie(request)
    conn = tenant_db_connection(tenant_id)
    try:
        val = get_web_setting_json(conn, 'public_closures', '{"items":[]}')
        data = json.loads(val)
        return data
    except:
        return {'items': []}
    finally:
        try: conn.close()
        except: pass

@router.post('/api/settings/public-closures/save')
def api_public_closures_save(request: Request, payload: Dict[str, Any]):
    guard = web_require_admin_teacher(request)
    if guard: raise HTTPException(status_code=401)
    
    tenant_id = web_tenant_from_cookie(request)
    conn = tenant_db_connection(tenant_id)
    try:
        # Load existing
        val = get_web_setting_json(conn, 'public_closures', '{"items":[]}')
        data = json.loads(val)
        items = data.get('items', [])
        
        # Add new
        import time
        new_item = {
            'id': int(time.time()),
            'start_at': payload.get('start_at'),
            'end_at': payload.get('end_at'),
            'reason': payload.get('reason')
        }
        items.append(new_item)
        
        # Save
        set_web_setting_json(conn, 'public_closures', json.dumps({'items': items}))
        return {'ok': True}
    finally:
        try: conn.close()
        except: pass

@router.post('/api/settings/public-closures/delete')
def api_public_closures_delete(request: Request, payload: Dict[str, Any]):
    guard = web_require_admin_teacher(request)
    if guard: raise HTTPException(status_code=401)
    
    tenant_id = web_tenant_from_cookie(request)
    conn = tenant_db_connection(tenant_id)
    try:
        val = get_web_setting_json(conn, 'public_closures', '{"items":[]}')
        data = json.loads(val)
        items = data.get('items', [])
        
        items = [i for i in items if int(i.get('id', 0)) != int(payload.get('id', 0))]
        
        set_web_setting_json(conn, 'public_closures', json.dumps({'items': items}))
        return {'ok': True}
    finally:
        try: conn.close()
        except: pass

@router.get("/web/anti-spam", response_class=HTMLResponse)
def web_anti_spam(request: Request):
    guard = web_require_admin_teacher(request)
    if guard: return guard
    
    html_content = """
    <h2 style="margin-bottom:16px;">🛡️ הגדרות אנטי-ספאם</h2>
    <div class="card" style="padding:20px; margin-bottom:16px;">
      <label style="display:flex;align-items:center;gap:8px;font-weight:700;font-size:15px;margin-bottom:12px;">
        <input type="checkbox" id="as-enabled" style="width:18px;height:18px;"> הפעל אנטי-ספאם</label>
      <div id="as-rules"></div>
      <button class="blue" onclick="addRule()" style="margin-top:8px;">+ הוסף כלל</button>
      <button class="green" onclick="saveAS()" style="margin-top:8px;margin-right:8px;">שמירה</button>
    </div>
    <hr style="border:none;border-top:1px solid rgba(255,255,255,0.1);margin:20px 0;">
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px;">
      <h2>חסימות סריקה (closures)</h2>
      <button class="green" onclick="openClosureModal()">+ חסימה חדשה</button>
    </div>
    
    <div class="card" style="padding:0; overflow:hidden;">
      <table style="width:100%; border-collapse:collapse;">
        <thead>
          <tr style="background:#f8f9fa; border-bottom:1px solid #eee;">
            <th style="padding:12px; text-align:right;">סיבה</th>
            <th style="padding:12px; text-align:right;">התחלה</th>
            <th style="padding:12px; text-align:right;">סיום</th>
            <th style="padding:12px; text-align:right;">פעולות</th>
          </tr>
        </thead>
        <tbody id="closures-list"></tbody>
      </table>
    </div>

    <!-- Modal -->
    <div id="modal-closure" class="modal-overlay" style="display:none; position:fixed; top:0; left:0; right:0; bottom:0; background:rgba(0,0,0,0.5); align-items:center; justify-content:center; z-index:1000;">
      <div class="modal" style="background:#fff; padding:24px; border-radius:12px; width:90%; max-width:400px; box-shadow:0 4px 20px rgba(0,0,0,0.2);">
        <h3 id="modal-title" style="margin-top:0;">הוספת חסימה</h3>
        <div class="form-group" style="margin-bottom:15px;">
          <label style="display:block; margin-bottom:5px; font-weight:600;">סיבה (אופציונלי)</label>
          <input id="c-reason" style="width:100%; padding:8px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box;">
        </div>
        <div class="form-group" style="margin-bottom:15px;">
          <label style="display:block; margin-bottom:5px; font-weight:600;">התחלה</label>
          <input type="datetime-local" id="c-start-at" style="width:100%; padding:8px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box; direction:ltr;">
        </div>
        <div class="form-group" style="margin-bottom:15px;">
          <label style="display:block; margin-bottom:5px; font-weight:600;">סיום</label>
          <input type="datetime-local" id="c-end-at" style="width:100%; padding:8px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box; direction:ltr;">
        </div>
        <div style="display:flex; justify-content:flex-end; gap:10px; margin-top:20px;">
          <button class="gray" onclick="closeClosureModal()" style="padding:8px 16px; border:none; border-radius:6px; cursor:pointer;">ביטול</button>
          <button class="green" onclick="saveClosure()" style="padding:8px 16px; background:#2ecc71; color:white; border:none; border-radius:6px; font-weight:600; cursor:pointer;">שמירה</button>
        </div>
      </div>
    </div>

    <script>
      let closures = [];

      async function loadClosures() {
        try {
            const res = await fetch('/api/settings/public-closures');
            const data = await res.json();
            closures = data.items || [];
            renderClosures();
        } catch(e) {}
      }

      function renderClosures() {
        const tbody = document.getElementById('closures-list');
        if (closures.length === 0) {
            tbody.innerHTML = '<tr><td colspan="4" style="padding:20px; text-align:center; color:#888;">אין חסימות פעילות</td></tr>';
            return;
        }
        tbody.innerHTML = closures.map((c) => `
          <tr style="border-bottom:1px solid #eee; hover:background:#fdfdfd;">
            <td style="padding:12px;">${esc(c.reason)}</td>
            <td style="padding:12px; direction:ltr; text-align:right;">${c.start_at.replace('T', ' ')}</td>
            <td style="padding:12px; direction:ltr; text-align:right;">${c.end_at.replace('T', ' ')}</td>
            <td style="padding:12px;">
              <button onclick="deleteClosure(${c.id})" style="background:none; border:none; cursor:pointer; font-size:16px;">🗑️</button>
            </td>
          </tr>
        `).join('');
      }

      function openClosureModal() {
        document.getElementById('c-reason').value = '';
        
        // Default start now, end in 1 hour
        const now = new Date();
        now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
        document.getElementById('c-start-at').value = now.toISOString().slice(0, 16);
        
        now.setHours(now.getHours() + 1);
        document.getElementById('c-end-at').value = now.toISOString().slice(0, 16);
        
        document.getElementById('modal-closure').style.display = 'flex';
      }

      function closeClosureModal() {
        document.getElementById('modal-closure').style.display = 'none';
      }

      async function saveClosure() {
        const payload = {
            reason: document.getElementById('c-reason').value,
            start_at: document.getElementById('c-start-at').value,
            end_at: document.getElementById('c-end-at').value
        };

        const res = await fetch('/api/settings/public-closures/save', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(payload)
        });
        
        closeClosureModal();
        loadClosures();
      }

      async function deleteClosure(id) {
        if (!confirm('למחוק חסימה זו?')) return;
        const res = await fetch('/api/settings/public-closures/delete', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ id: id })
        });
        loadClosures();
      }

      function esc(s) {
        return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
      }

      let asRules = [];
      async function loadAS() {
        try {
          const r = await fetch('/api/settings/anti_spam_config');
          const d = await r.json();
          let v = d.value;
          if (typeof v === 'string') try { v = JSON.parse(v); } catch(e) { v = {}; }
          if (!v || typeof v !== 'object') v = {};
          document.getElementById('as-enabled').checked = !!(v.anti_spam_enabled);
          asRules = Array.isArray(v.anti_spam_rules) ? v.anti_spam_rules : [];
          renderAS();
        } catch(e) {}
      }
      function renderAS() {
        const c = document.getElementById('as-rules');
        if (!asRules.length) { c.innerHTML = '<div style="color:#888;font-size:13px;">אין כללים</div>'; return; }
        c.innerHTML = asRules.map((r,i) => `
          <div style="background:#f5f7fa;padding:10px;border-radius:8px;margin-bottom:8px;border:1px solid #e8ecf0;">
            <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:6px;">
              <select onchange="asRules[${i}].type=this.value" style="padding:6px;border:1px solid #ddd;border-radius:4px;">
                <option value="warning" ${r.type==='warning'?'selected':''}>⚠️ אזהרה</option>
                <option value="block" ${r.type==='block'?'selected':''}>🚫 חסימה</option>
              </select>
              <label style="font-size:12px;">אחרי <input type="number" value="${r.count||10}" min="1" onchange="asRules[${i}].count=parseInt(this.value)||1" style="width:60px;padding:4px;border:1px solid #ddd;border-radius:4px;"> תיקופים</label>
              <label style="font-size:12px;">בתוך <input type="number" value="${r.minutes||1}" min="1" onchange="asRules[${i}].minutes=parseInt(this.value)||1" style="width:60px;padding:4px;border:1px solid #ddd;border-radius:4px;"> דקות</label>
              ${r.type==='block' ? '<label style="font-size:12px;">חסימה ל-<input type="number" value="'+(r.duration||60)+'" min="1" onchange="asRules['+i+'].duration=parseInt(this.value)||60" style="width:70px;padding:4px;border:1px solid #ddd;border-radius:4px;"> דקות</label>' : ''}
              <button onclick="asRules.splice(${i},1);renderAS();" style="background:#e74c3c;color:#fff;border:none;padding:4px 10px;border-radius:4px;cursor:pointer;font-size:12px;">X</button>
            </div>
            <input value="${esc(r.message||'')}" onchange="asRules[${i}].message=this.value" placeholder="הודעה לתלמיד" style="width:100%;padding:6px;border:1px solid #ddd;border-radius:6px;box-sizing:border-box;font-size:12px;">
          </div>
        `).join('');
      }
      function addRule() {
        asRules.push({type:'warning',count:10,minutes:1,duration:0,message:'שים לב! אתה מתקף יותר מדי פעמים.'});
        renderAS();
      }
      async function saveAS() {
        const val = { anti_spam_enabled: document.getElementById('as-enabled').checked, anti_spam_rules: asRules };
        await fetch('/api/settings/save', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({key:'anti_spam_config',value:JSON.stringify(val)})});
        alert('הגדרות אנטי-ספאם נשמרו');
      }
      loadAS();
      loadClosures();
    </script>
    """
    return basic_web_shell("אנטי-ספאם", html_content, request=request)

@router.get('/api/settings/max-points')
def api_max_points_get(request: Request) -> Dict[str, Any]:
    guard = web_require_teacher(request)
    if guard: raise HTTPException(status_code=401)
    
    tenant_id = web_tenant_from_cookie(request)
    conn = tenant_db_connection(tenant_id)
    try:
        val = get_web_setting_json(conn, 'max_points_config', '{}')
        return json.loads(val)
    finally:
        try: conn.close()
        except: pass

@router.post('/api/settings/max-points')
def api_max_points_save(request: Request, payload: Dict[str, Any]) -> Dict[str, Any]:
    guard = web_require_teacher(request)
    if guard: raise HTTPException(status_code=401)
    
    tenant_id = web_tenant_from_cookie(request)
    conn = tenant_db_connection(tenant_id)
    try:
        set_web_setting_json(conn, 'max_points_config', json.dumps(payload))
        return {'ok': True}
    finally:
        try: conn.close()
        except: pass


def _max_points_html():
    return _MP_BODY + _MP_JS


_MP_BODY = """
<div style="max-width:800px;margin:0 auto;">
<h2 style="color:#fff;">מגבלת ניקוד (תקרה דינמית)</h2>
<div class="card" style="padding:20px;background:#fff;border-radius:10px;border:1px solid #eee;">
  <div style="margin-bottom:15px;"><label style="display:block;margin-bottom:5px;font-weight:600;">מדיניות</label>
    <select id="mp-policy" style="width:100%;padding:10px;border:1px solid #ddd;border-radius:6px;box-sizing:border-box;">
      <option value="none">ללא מגבלה</option><option value="warn">אזהרה בלבד</option><option value="block">חסימה</option>
    </select></div>
  <div style="margin-bottom:15px;"><label style="display:block;margin-bottom:5px;font-weight:600;">תאריך התחלה</label>
    <input type="date" id="mp-start" style="width:100%;padding:10px;border:1px solid #ddd;border-radius:6px;box-sizing:border-box;"></div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:15px;">
    <div><label style="display:block;margin-bottom:5px;font-weight:600;">נקודות יומיות (ברירת מחדל)</label>
      <input type="number" id="mp-daily" min="0" value="0" style="width:100%;padding:10px;border:1px solid #ddd;border-radius:6px;box-sizing:border-box;"></div>
    <div><label style="display:block;margin-bottom:5px;font-weight:600;">נקודות שבועיות (0=ללא)</label>
      <input type="number" id="mp-weekly" min="0" value="0" style="width:100%;padding:10px;border:1px solid #ddd;border-radius:6px;box-sizing:border-box;"></div>
  </div>
  <div style="margin-bottom:15px;"><label style="display:block;margin-bottom:5px;font-weight:600;">אזהרה כש-X נקודות עד התקרה</label>
    <input type="number" id="mp-warn" min="0" value="0" style="width:100%;padding:10px;border:1px solid #ddd;border-radius:6px;box-sizing:border-box;"></div>
  <h4 style="margin:18px 0 8px;color:#2c3e50;">נקודות לפי יום בשבוע (ריק = ברירת מחדל)</h4>
  <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(100px,1fr));gap:8px;margin-bottom:15px;" id="mp-weekdays"></div>
  <h4 style="margin:18px 0 8px;color:#2c3e50;">כללים מיוחדים לתקופות</h4>
  <div id="mp-special"></div>
  <button onclick="addSpecial()" style="background:#3498db;color:#fff;border:none;padding:6px 14px;border-radius:6px;cursor:pointer;margin-bottom:15px;">+ כלל מיוחד</button>
  <h4 style="margin:18px 0 8px;color:#2c3e50;">תוספות חופשיות (חד-פעמיות)</h4>
  <div id="mp-free"></div>
  <button onclick="addFree()" style="background:#3498db;color:#fff;border:none;padding:6px 14px;border-radius:6px;cursor:pointer;margin-bottom:15px;">+ תוספת</button>
  <div style="margin-top:16px;"><button class="green" onclick="saveMP()" style="padding:10px 24px;">שמירה</button></div>
</div></div>
"""

_MP_JS = """
<script>
const DAYS=['ראשון','שני','שלישי','רביעי','חמישי','שישי','שבת'];
let mpCfg={};
async function loadMP(){
  try{const r=await fetch('/api/settings/max_points_config');mpCfg=await r.json();if(!mpCfg||typeof mpCfg!=='object')mpCfg={};}catch(e){mpCfg={};}
  document.getElementById('mp-policy').value=mpCfg.policy||'none';
  document.getElementById('mp-start').value=mpCfg.start_date||new Date().toISOString().slice(0,10);
  document.getElementById('mp-daily').value=mpCfg.daily_points||0;
  document.getElementById('mp-weekly').value=mpCfg.weekly_points||0;
  document.getElementById('mp-warn').value=mpCfg.warn_within_points||0;
  renderWD();renderSP();renderFA();
}
function renderWD(){
  const c=document.getElementById('mp-weekdays');
  const dpw=mpCfg.daily_points_by_weekday||{};
  c.innerHTML=DAYS.map((d,i)=>'<div><label style="font-size:12px;font-weight:600;display:block;margin-bottom:2px;">'+d+'</label><input type="number" id="wd-'+i+'" min="0" value="'+(dpw[i]!=null?dpw[i]:'')+'" placeholder="ברירת" style="width:100%;padding:6px;border:1px solid #ddd;border-radius:4px;box-sizing:border-box;"></div>').join('');
}
function renderSP(){
  const c=document.getElementById('mp-special');const rules=mpCfg.daily_special_rules||[];
  if(!rules.length){c.innerHTML='<div style="color:#888;font-size:13px;margin-bottom:8px;">אין כללים מיוחדים</div>';return;}
  c.innerHTML=rules.map((r,i)=>'<div style="display:flex;gap:6px;align-items:center;margin-bottom:6px;flex-wrap:wrap;"><input type="date" value="'+(r.start||'')+'" onchange="mpCfg.daily_special_rules['+i+'].start=this.value" style="padding:6px;border:1px solid #ddd;border-radius:4px;"><span>עד</span><input type="date" value="'+(r.end||'')+'" onchange="mpCfg.daily_special_rules['+i+'].end=this.value" style="padding:6px;border:1px solid #ddd;border-radius:4px;"><input type="number" value="'+(r.daily_points||0)+'" onchange="mpCfg.daily_special_rules['+i+'].daily_points=parseInt(this.value)||0" style="width:80px;padding:6px;border:1px solid #ddd;border-radius:4px;" placeholder="נקודות"><input value="'+(r.note||'')+'" onchange="mpCfg.daily_special_rules['+i+'].note=this.value" style="flex:1;min-width:80px;padding:6px;border:1px solid #ddd;border-radius:4px;" placeholder="הערה"><button onclick="mpCfg.daily_special_rules.splice('+i+',1);renderSP();" style="background:#e74c3c;color:#fff;border:none;padding:4px 10px;border-radius:4px;cursor:pointer;">X</button></div>').join('');
}
function addSpecial(){if(!mpCfg.daily_special_rules)mpCfg.daily_special_rules=[];mpCfg.daily_special_rules.push({start:'',end:'',daily_points:0,note:''});renderSP();}
function renderFA(){
  const c=document.getElementById('mp-free');const fa=mpCfg.free_additions||[];
  if(!fa.length){c.innerHTML='<div style="color:#888;font-size:13px;margin-bottom:8px;">אין תוספות</div>';return;}
  c.innerHTML=fa.map((r,i)=>'<div style="display:flex;gap:6px;align-items:center;margin-bottom:6px;"><input type="date" value="'+(r.date||'')+'" onchange="mpCfg.free_additions['+i+'].date=this.value" style="padding:6px;border:1px solid #ddd;border-radius:4px;"><input type="number" value="'+(r.points||0)+'" onchange="mpCfg.free_additions['+i+'].points=parseInt(this.value)||0" style="width:80px;padding:6px;border:1px solid #ddd;border-radius:4px;" placeholder="נקודות"><input value="'+(r.note||'')+'" onchange="mpCfg.free_additions['+i+'].note=this.value" style="flex:1;min-width:80px;padding:6px;border:1px solid #ddd;border-radius:4px;" placeholder="הערה"><button onclick="mpCfg.free_additions.splice('+i+',1);renderFA();" style="background:#e74c3c;color:#fff;border:none;padding:4px 10px;border-radius:4px;cursor:pointer;">X</button></div>').join('');
}
function addFree(){if(!mpCfg.free_additions)mpCfg.free_additions=[];mpCfg.free_additions.push({date:'',points:0,note:''});renderFA();}
async function saveMP(){
  const dpw={};DAYS.forEach(function(d,i){var v=document.getElementById('wd-'+i).value;if(v!=='')dpw[i]=parseInt(v)||0;});
  const payload={policy:document.getElementById('mp-policy').value,start_date:document.getElementById('mp-start').value,
    daily_points:parseInt(document.getElementById('mp-daily').value)||0,weekly_points:parseInt(document.getElementById('mp-weekly').value)||0,
    warn_within_points:parseInt(document.getElementById('mp-warn').value)||0,
    daily_points_by_weekday:Object.keys(dpw).length?dpw:null,daily_special_rules:mpCfg.daily_special_rules||[],free_additions:mpCfg.free_additions||[]};
  await fetch('/api/settings/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({key:'max_points_config',value:payload})});
  alert('נשמר');
}
loadMP();
</script>
"""


@router.get("/web/max-points", response_class=HTMLResponse)
def web_max_points(request: Request):
    guard = web_require_admin_teacher(request)
    if guard: return guard
    html_content = _max_points_html()
    return basic_web_shell("מגבלת ניקוד", html_content, request=request)


@router.get("/web/quiet-mode", response_class=HTMLResponse)
def web_quiet_mode(request: Request):
    guard = web_require_admin_teacher(request)
    if guard: return guard
    html_content = """
    <h2 style="margin-bottom:16px;">🌙 מצב שקט</h2>
    <div class="card" style="padding:20px;">
      <div id="qm-ranges"></div>
      <button class="blue" onclick="addQR()" style="margin-top:8px;">+ הוסף טווח</button>
      <button class="green" onclick="saveQM()" style="margin-top:8px;margin-right:8px;">שמירה</button>
    </div>
    <script>
      let qmRanges = [];
      async function loadQM() {
        try {
          const r = await fetch('/api/settings/quiet_mode_config');
          const d = await r.json();
          let v = d.value;
          if (typeof v === 'string') try { v = JSON.parse(v); } catch(e) { v = {}; }
          if (!v || typeof v !== 'object') v = {};
          let raw = v.quiet_mode_ranges;
          if (typeof raw === 'string') try { raw = JSON.parse(raw); } catch(e) { raw = []; }
          qmRanges = Array.isArray(raw) ? raw : [];
          if (!qmRanges.length && v.quiet_mode_enabled) {
            qmRanges = [{start: v.quiet_mode_start||'', end: v.quiet_mode_end||'', mode:'low', volume: v.quiet_mode_volume||20}];
          }
          renderQM();
        } catch(e) {}
      }
      function renderQM() {
        const c = document.getElementById('qm-ranges');
        if (!qmRanges.length) { c.innerHTML = '<div style="color:#888;font-size:13px;">אין טווחי שקט מוגדרים</div>'; return; }
        c.innerHTML = qmRanges.map((r,i) => `
          <div style="background:#f5f7fa;padding:10px;border-radius:8px;margin-bottom:8px;border:1px solid #e8ecf0;display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
            <label style="font-size:12px;">התחלה <input type="time" value="${r.start||''}" onchange="qmRanges[${i}].start=this.value" style="padding:4px;border:1px solid #ddd;border-radius:4px;direction:ltr;"></label>
            <label style="font-size:12px;">סיום <input type="time" value="${r.end||''}" onchange="qmRanges[${i}].end=this.value" style="padding:4px;border:1px solid #ddd;border-radius:4px;direction:ltr;"></label>
            <select onchange="qmRanges[${i}].mode=this.value" style="padding:4px;border:1px solid #ddd;border-radius:4px;">
              <option value="mute" ${r.mode==='mute'?'selected':''}>השתקה מלאה</option>
              <option value="low" ${r.mode==='low'?'selected':''}>ווליום נמוך</option>
            </select>
            <label style="font-size:12px;">ווליום <input type="number" value="${r.volume||20}" min="0" max="100" onchange="qmRanges[${i}].volume=parseInt(this.value)||0" style="width:60px;padding:4px;border:1px solid #ddd;border-radius:4px;"></label>
            <button onclick="qmRanges.splice(${i},1);renderQM();" style="background:#e74c3c;color:#fff;border:none;padding:4px 10px;border-radius:4px;cursor:pointer;font-size:12px;">X</button>
          </div>
        `).join('');
      }
      function addQR() {
        qmRanges.push({start:'22:00',end:'07:00',mode:'low',volume:20});
        renderQM();
      }
      async function saveQM() {
        const val = {quiet_mode_enabled: qmRanges.length > 0, quiet_mode_ranges: JSON.stringify(qmRanges)};
        if (qmRanges.length > 0) { val.quiet_mode_start = qmRanges[0].start; val.quiet_mode_end = qmRanges[0].end; val.quiet_mode_volume = qmRanges[0].volume; }
        await fetch('/api/settings/save', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({key:'quiet_mode_config',value:JSON.stringify(val)})});
        alert('הגדרות מצב שקט נשמרו');
      }
      loadQM();
    </script>
    """
    return basic_web_shell("מצב שקט", html_content, request=request)


@router.get("/web/settings", response_class=HTMLResponse)
def web_settings_hub(request: Request):
    guard = web_require_admin_teacher(request)
    if guard: return guard
    tiles = [
        ('/web/system-settings', '⚙', 'הגדרות מערכת'),
        ('/web/display-settings', '🖥', 'הגדרות תצוגה'),
    ]
    grid = ''.join(f'<a href="{u}" style="display:block;padding:20px;background:#fff;border-radius:12px;border:1px solid #eee;text-align:center;text-decoration:none;"><div style="font-size:32px;margin-bottom:8px;">{ic}</div><div style="font-weight:700;color:#2c3e50;">{lb}</div></a>' for u,ic,lb in tiles)
    html_content = f'<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:16px;">{grid}</div>'
    return basic_web_shell("הגדרות", html_content, request=request)


@router.get('/api/products')
def api_products_list(request: Request) -> Dict[str, Any]:
    guard = web_require_admin_teacher(request)
    if guard: raise HTTPException(status_code=401)
    tid = web_tenant_from_cookie(request)
    conn = tenant_db_connection(tid)
    try:
        cur = conn.cursor()
        cur.execute('SELECT * FROM products ORDER BY sort_order, id')
        return {'ok': True, 'items': [dict(r) for r in (cur.fetchall() or [])]}
    finally:
        try: conn.close()
        except: pass

@router.post('/api/products/save')
def api_products_save(request: Request, payload: Dict[str, Any] = Body(...)):
    guard = web_require_admin_teacher(request)
    if guard: raise HTTPException(status_code=401)
    tid = web_tenant_from_cookie(request)
    conn = tenant_db_connection(tid)
    try:
        cur = conn.cursor()
        pid = payload.pop('id', None)
        cols = ['name','display_name','category_id','price_points','stock_qty','is_active',
                'consolidated_voucher','sort_order','allowed_classes','deduct_points',
                'min_points_required','max_per_student','max_per_class','image_path','voucher_per_unit']
        vals = {c: payload.get(c) for c in cols if c in payload}
        if pid:
            sets = ', '.join(f"{k} = ?" for k in vals)
            cur.execute(sql_placeholder(f"UPDATE products SET {sets}, updated_at=CURRENT_TIMESTAMP WHERE id=?"), list(vals.values())+[pid])
            conn.commit()
            record_sync_event(tenant_id=tid, station_id='web', entity_type='product', entity_id=str(pid), action_type='update', payload={**vals,'id':pid})
        else:
            ks = list(vals.keys())
            cur.execute(sql_placeholder(f"INSERT INTO products ({','.join(ks)}) VALUES ({','.join('?' for _ in ks)})"), list(vals.values()))
            conn.commit()
            pid = cur.lastrowid
            record_sync_event(tenant_id=tid, station_id='web', entity_type='product', entity_id=str(pid), action_type='create', payload={**vals,'id':pid})
        return {'ok': True, 'id': pid}
    finally:
        try: conn.close()
        except: pass

@router.post('/api/products/delete')
def api_products_delete(request: Request, payload: Dict[str, Any] = Body(...)):
    guard = web_require_admin_teacher(request)
    if guard: raise HTTPException(status_code=401)
    tid = web_tenant_from_cookie(request)
    conn = tenant_db_connection(tid)
    try:
        pid = payload.get('id')
        conn.cursor().execute(sql_placeholder('DELETE FROM products WHERE id=?'), (pid,))
        conn.commit()
        record_sync_event(tenant_id=tid, station_id='web', entity_type='product', entity_id=str(pid), action_type='delete', payload={})
        return {'ok': True}
    finally:
        try: conn.close()
        except: pass

@router.get('/api/product-categories')
def api_categories_list(request: Request) -> Dict[str, Any]:
    guard = web_require_admin_teacher(request)
    if guard: raise HTTPException(status_code=401)
    tid = web_tenant_from_cookie(request)
    conn = tenant_db_connection(tid)
    try:
        cur = conn.cursor()
        cur.execute('SELECT * FROM product_categories ORDER BY sort_order, id')
        return {'ok': True, 'items': [dict(r) for r in (cur.fetchall() or [])]}
    finally:
        try: conn.close()
        except: pass

@router.post('/api/product-categories/save')
def api_categories_save(request: Request, payload: Dict[str, Any] = Body(...)):
    guard = web_require_admin_teacher(request)
    if guard: raise HTTPException(status_code=401)
    tid = web_tenant_from_cookie(request)
    conn = tenant_db_connection(tid)
    try:
        cur = conn.cursor()
        cid = payload.pop('id', None)
        cols = ['name','sort_order','is_active','show_in_catalog','max_items_per_student','max_items_per_class','min_points_required']
        vals = {c: payload.get(c) for c in cols if c in payload}
        if cid:
            sets = ', '.join(f"{k} = ?" for k in vals)
            cur.execute(sql_placeholder(f"UPDATE product_categories SET {sets}, updated_at=CURRENT_TIMESTAMP WHERE id=?"), list(vals.values())+[cid])
            conn.commit()
            record_sync_event(tenant_id=tid, station_id='web', entity_type='product_category', entity_id=str(cid), action_type='update', payload={**vals,'id':cid})
        else:
            ks = list(vals.keys())
            cur.execute(sql_placeholder(f"INSERT INTO product_categories ({','.join(ks)}) VALUES ({','.join('?' for _ in ks)})"), list(vals.values()))
            conn.commit()
            cid = cur.lastrowid
            record_sync_event(tenant_id=tid, station_id='web', entity_type='product_category', entity_id=str(cid), action_type='create', payload={**vals,'id':cid})
        return {'ok': True, 'id': cid}
    finally:
        try: conn.close()
        except: pass

@router.post('/api/product-categories/delete')
def api_categories_delete(request: Request, payload: Dict[str, Any] = Body(...)):
    guard = web_require_admin_teacher(request)
    if guard: raise HTTPException(status_code=401)
    tid = web_tenant_from_cookie(request)
    conn = tenant_db_connection(tid)
    try:
        cid = payload.get('id')
        conn.cursor().execute(sql_placeholder('DELETE FROM product_categories WHERE id=?'), (cid,))
        conn.commit()
        record_sync_event(tenant_id=tid, station_id='web', entity_type='product_category', entity_id=str(cid), action_type='delete', payload={})
        return {'ok': True}
    finally:
        try: conn.close()
        except: pass

@router.get("/web/purchases", response_class=HTMLResponse)
def web_purchases(request: Request):
    guard = web_require_admin_teacher(request)
    if guard: return guard
    return basic_web_shell("ניהול קופה", purchases_html(), request=request)


@router.get("/web/personal", response_class=HTMLResponse)
def web_personal(request: Request):
    guard = web_require_admin_teacher(request)
    if guard: return guard
    html_content = """
    <div class="card" style="padding:20px; background:#fff; border-radius:10px; border:1px solid #eee;">
      <div class="form-group" style="margin-bottom:15px;">
        <label style="display:block; margin-bottom:5px; font-weight:600;">שם המורה</label>
        <input id="per-name" style="width:100%; padding:10px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box;">
      </div>
      <div class="form-group" style="margin-bottom:15px;">
        <label style="display:block; margin-bottom:5px; font-weight:600;">אימייל</label>
        <input id="per-email" type="email" style="width:100%; padding:10px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box; direction:ltr;">
      </div>
      <div class="form-group" style="margin-bottom:15px;">
        <label style="display:block; margin-bottom:5px; font-weight:600;">סיסמה חדשה (השאר ריק אם אין שינוי)</label>
        <input id="per-pass" type="password" style="width:100%; padding:10px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box; direction:ltr;">
      </div>
      <button class="green" onclick="savePersonal()">שמירה</button>
    </div>
    <script>
      async function loadPersonal(){try{const r=await fetch('/api/settings/personal');const d=await r.json();document.getElementById('per-name').value=d.name||'';document.getElementById('per-email').value=d.email||'';}catch(e){}}
      async function savePersonal(){const p={name:document.getElementById('per-name').value,email:document.getElementById('per-email').value};const pw=document.getElementById('per-pass').value;if(pw)p.password=pw;await fetch('/api/settings/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({key:'personal',value:p})});alert('נשמר');}
      loadPersonal();
    </script>
    """
    return basic_web_shell("אזור אישי", html_content, request=request)
