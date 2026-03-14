from fastapi import APIRouter, Request, HTTPException, Body, UploadFile, File, Form
from fastapi.responses import HTMLResponse
from typing import Dict, Any, List
import json
import os
import shutil

from ..utils import time_to_minutes
from ..ui import basic_web_shell
from ..auth import web_require_admin_teacher, web_require_teacher, web_tenant_from_cookie, safe_int
from ..db import tenant_db_connection, sql_placeholder, integrity_errors
from ..config import USE_POSTGRES, DATA_DIR
from ..sync_logic import record_sync_event

router = APIRouter()

def get_tenant_asset_path(tenant_id: str, rel_path: str) -> str:
    # Ensure safe path
    safe_rel = rel_path.replace('..', '').strip('/\\')
    return os.path.join(DATA_DIR, 'tenants_assets', tenant_id, safe_rel)

@router.get("/web/messages", response_class=HTMLResponse)
def web_messages(request: Request):
    guard = web_require_admin_teacher(request)
    if guard: return guard
    
    html_content = """
    <div style="max-width:1000px; margin:0 auto;">
        <h2 style="margin-bottom:20px;">ניהול הודעות</h2>
        
        <div class="tabs" style="display:flex; gap:10px; margin-bottom:20px; border-bottom:1px solid rgba(255,255,255,0.1); padding-bottom:10px;">
            <button class="tab-btn active" onclick="switchTab('static')">📢 הודעות כלליות</button>
            <button class="tab-btn" onclick="switchTab('threshold')">🎯 לפי ניקוד</button>
            <button class="tab-btn" onclick="switchTab('news')">📰 חדשות</button>
            <button class="tab-btn" onclick="switchTab('timebonus')">⏰ בונוס זמנים</button>
            <button class="tab-btn" onclick="switchTab('ads')">🪧 פרסומות</button>
        </div>

        <!-- Static Messages -->
        <div id="tab-static" class="tab-content">
            <div class="card" style="padding:15px;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px;">
                    <h3>הודעות כלליות (מופיעות לכולם)</h3>
                    <button class="blue" onclick="addStatic()">➕ הוסף הודעה</button>
                </div>
                <div id="list-static">Loading...</div>
            </div>
        </div>

        <!-- Threshold (score-based) Messages -->
        <div id="tab-threshold" class="tab-content" style="display:none;">
            <div class="card" style="padding:15px;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px;">
                    <h3>הודעות לפי טווח נקודות</h3>
                    <button class="blue" onclick="addThreshold()">➕ הוסף טווח</button>
                </div>
                <div id="list-threshold">Loading...</div>
            </div>
        </div>

        <!-- Time Bonus Message -->
        <div id="tab-timebonus" class="tab-content" style="display:none;">
            <div class="card" style="padding:15px;">
                <h3>הודעת "הגעת ראשון להיום"</h3>
                <div class="form-group" style="margin-bottom:12px;">
                    <label class="ck" style="display:flex;align-items:center;gap:8px;font-weight:600;">
                        <input type="checkbox" id="tb-enabled" style="width:18px;height:18px;"> הפעל הודעה
                    </label>
                </div>
                <div class="form-group" style="margin-bottom:12px;">
                    <label style="display:block;margin-bottom:5px;font-weight:600;">מספר ראשונים (N)</label>
                    <input type="number" id="tb-n" min="1" value="1" style="width:100%;padding:8px;border:1px solid #ddd;border-radius:6px;box-sizing:border-box;">
                </div>
                <div class="form-group" style="margin-bottom:12px;">
                    <label style="display:block;margin-bottom:5px;font-weight:600;">טקסט ההודעה</label>
                    <input id="tb-text" value="*הגעת ראשון להיום!*" style="width:100%;padding:8px;border:1px solid #ddd;border-radius:6px;box-sizing:border-box;">
                </div>
                <button class="green" onclick="saveTimeBonus()">שמירה</button>
            </div>
        </div>

        <!-- News -->
        <div id="tab-news" class="tab-content" style="display:none;">
            <div class="card" style="padding:15px; margin-bottom:15px;">
                <h4 style="margin:0 0 12px;">הגדרות טיקר חדשות</h4>
                <div style="display:grid; grid-template-columns:1fr 1fr; gap:8px;">
                  <label style="display:flex;align-items:center;gap:6px;font-size:13px;color:#34495e;"><input type="checkbox" id="ns-weekday" style="width:16px;height:16px;"> הצג יום בשבוע</label>
                  <label style="display:flex;align-items:center;gap:6px;font-size:13px;color:#34495e;"><input type="checkbox" id="ns-hebrew-date" style="width:16px;height:16px;"> הצג תאריך עברי</label>
                  <label style="display:flex;align-items:center;gap:6px;font-size:13px;color:#34495e;"><input type="checkbox" id="ns-parsha" style="width:16px;height:16px;"> הצג פרשת שבוע</label>
                  <label style="display:flex;align-items:center;gap:6px;font-size:13px;color:#34495e;"><input type="checkbox" id="ns-holidays" style="width:16px;height:16px;"> הצג חגים/מועדים</label>
                  <label style="display:flex;align-items:center;gap:6px;font-size:13px;color:#34495e;"><input type="checkbox" id="ns-birthdays" style="width:16px;height:16px;"> הצג ימי הולדת עבריים</label>
                </div>
                <div style="margin-top:10px;">
                  <label style="display:block;font-weight:600;margin-bottom:3px;font-size:13px;color:#34495e;">תבנית הודעת יום הולדת</label>
                  <input id="ns-bday-template" placeholder="מזל טוב ליום ההולדת של {name}!" style="width:100%;padding:8px;border:1px solid #ccd0d5;border-radius:6px;box-sizing:border-box;">
                </div>
                <div style="margin-top:8px;">
                  <label style="display:block;font-weight:600;margin-bottom:3px;font-size:13px;color:#34495e;">תבנית הודעת בר/בת מצווה</label>
                  <input id="ns-bar-template" placeholder="מזל טוב לבר/בת המצווה של {name}!" style="width:100%;padding:8px;border:1px solid #ccd0d5;border-radius:6px;box-sizing:border-box;">
                </div>
                <button class="green" onclick="saveNewsSettings()" style="margin-top:10px;">שמור הגדרות</button>
            </div>
            <div class="card" style="padding:15px;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px;">
                    <h3>חדשות (מבזקים)</h3>
                    <button class="blue" onclick="addNews()">➕ הוסף חדשה</button>
                </div>
                <div id="list-news">Loading...</div>
            </div>
        </div>

        <!-- Ads -->
        <div id="tab-ads" class="tab-content" style="display:none;">
            <div class="card" style="padding:15px;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px;">
                    <h3>פרסומות (תמונות/טקסט)</h3>
                    <button class="blue" onclick="addAd()">➕ הוסף פרסומת</button>
                </div>
                <div id="list-ads">Loading...</div>
            </div>
        </div>
    </div>

    <!-- Message Modal -->
    <div id="msg-modal" style="display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,.5);z-index:999;align-items:flex-start;justify-content:center;padding-top:60px;">
      <div style="background:#fff;border-radius:12px;padding:24px;min-width:380px;max-width:520px;width:90%;max-height:80vh;overflow-y:auto;direction:rtl;">
        <h3 id="mm-title" style="margin:0 0 16px;color:#2c3e50;">הודעה חדשה</h3>
        <input type="hidden" id="mm-id"><input type="hidden" id="mm-type">
        <div style="margin-bottom:10px"><label style="display:block;font-weight:600;margin-bottom:3px;font-size:13px;color:#34495e;">טקסט *</label>
          <textarea id="mm-text" rows="3" style="width:100%;padding:8px;border:1px solid #ccd0d5;border-radius:6px;box-sizing:border-box;resize:vertical;"></textarea></div>
        <div id="mm-always-row" style="margin-bottom:10px;display:none"><label style="display:flex;align-items:center;gap:6px;font-weight:600;font-size:13px;color:#34495e;">
          <input type="checkbox" id="mm-always" style="width:18px;height:18px;"> הצג תמיד (גם ללא הצגת כרטיס)</label></div>
        <div id="mm-dates-row" style="margin-bottom:10px;display:none">
          <div style="display:flex;gap:10px;">
            <div style="flex:1;"><label style="display:block;font-weight:600;margin-bottom:3px;font-size:13px;color:#34495e;">תאריך התחלה</label>
              <input type="date" id="mm-start-date" style="width:100%;padding:8px;border:1px solid #ccd0d5;border-radius:6px;box-sizing:border-box;"></div>
            <div style="flex:1;"><label style="display:block;font-weight:600;margin-bottom:3px;font-size:13px;color:#34495e;">תאריך סיום</label>
              <input type="date" id="mm-end-date" style="width:100%;padding:8px;border:1px solid #ccd0d5;border-radius:6px;box-sizing:border-box;"></div>
          </div></div>
        <div id="mm-sort-row" style="margin-bottom:10px;display:none"><label style="display:block;font-weight:600;margin-bottom:3px;font-size:13px;color:#34495e;">סדר תצוגה</label>
          <input type="number" id="mm-sort" min="0" value="0" style="width:100%;padding:8px;border:1px solid #ccd0d5;border-radius:6px;box-sizing:border-box;"></div>
        <div id="mm-image-row" style="margin-bottom:10px;display:none"><label style="display:block;font-weight:600;margin-bottom:3px;font-size:13px;color:#34495e;">נתיב תמונה</label>
          <input id="mm-image" style="width:100%;padding:8px;border:1px solid #ccd0d5;border-radius:6px;box-sizing:border-box;"></div>
        <div id="mm-threshold-row" style="margin-bottom:10px;display:none">
          <label style="display:block;font-weight:600;margin-bottom:3px;font-size:13px;color:#34495e;">מינימום נקודות</label>
          <input type="number" id="mm-min" min="0" value="0" style="width:100%;padding:8px;border:1px solid #ccd0d5;border-radius:6px;box-sizing:border-box;">
          <label style="display:block;font-weight:600;margin-bottom:3px;margin-top:6px;font-size:13px;color:#34495e;">מקסימום נקודות</label>
          <input type="number" id="mm-max" min="0" value="999999" style="width:100%;padding:8px;border:1px solid #ccd0d5;border-radius:6px;box-sizing:border-box;">
        </div>
        <div style="margin-bottom:10px"><label style="display:flex;align-items:center;gap:6px;font-weight:600;font-size:13px;color:#34495e;">
          <input type="checkbox" id="mm-active" checked style="width:18px;height:18px;"> פעיל</label></div>
        <div style="display:flex;gap:8px;margin-top:16px;">
          <button class="green" onclick="saveMsg()">שמירה</button>
          <button onclick="closeMsg()" style="background:#95a5a6;color:#fff;border:none;padding:8px 16px;border-radius:6px;cursor:pointer;">ביטול</button>
        </div>
      </div>
    </div>

    <script>
        function switchTab(name) {
            document.querySelectorAll('.tab-content').forEach(el => el.style.display = 'none');
            document.getElementById('tab-' + name).style.display = 'block';
            document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
            event.target.classList.add('active');
            if (name === 'timebonus') { loadTimeBonus(); }
            else if (name === 'threshold') { load('threshold'); }
            else if (name === 'news') { load('news'); loadNewsSettings(); }
            else { load(name); }
        }
        
        async function load(type) {
            const list = document.getElementById('list-' + type);
            list.innerHTML = 'Loading...';
            try {
                const resp = await fetch('/api/messages/' + type);
                const data = await resp.json();
                
                if (!data.items || data.items.length === 0) {
                    list.innerHTML = '<div style="opacity:0.6; padding:20px; text-align:center;">אין הודעות</div>';
                    return;
                }
                
                list.innerHTML = data.items.map(item => `
                    <div style="background:#f5f7fa; padding:12px; margin-bottom:8px; border-radius:8px; display:flex; justify-content:space-between; align-items:center; border:1px solid #e8ecf0;">
                        <div style="display:flex; gap:5px;">
                            <button class="blue" style="padding:5px 10px; font-size:12px;" onclick="edit('${type}', ${item.id})">ערוך</button>
                            <button style="padding:5px 10px; font-size:12px; background:#e74c3c; border:none; color:#fff; border-radius:6px; cursor:pointer;" onclick="del('${type}', ${item.id})">מחק</button>
                        </div>
                        <div style="text-align:right;">
                            <div style="font-weight:bold; color:#2c3e50;">${item.text || item.message || '(תמונה)'}</div>
                            <div style="font-size:12px; color:#7f8c8d;">
                                ${item.is_active ? '<span style="color:#2ecc71">פעיל</span>' : '<span style="color:#e74c3c">לא פעיל</span>'}
                                ${type==='threshold' && (item.min_points!=null||item.max_points!=null) ? ' | <span style="color:#8e44ad;font-weight:600;">טווח: '+(item.min_points||0)+' – '+(item.max_points||'∞')+' נקודות</span>' : ''}
                                ${item.show_always ? ' | תמיד' : (type==='static' ? ' | עם כרטיס' : '')}
                                ${item.image_path ? ' | כולל תמונה' : ''}
                                ${item.start_date ? ' | מ-'+item.start_date : ''}${item.end_date ? ' עד '+item.end_date : ''}
                            </div>
                        </div>
                    </div>
                `).join('');
            } catch(e) {
                list.innerHTML = 'Error loading';
            }
        }
        
        function openMsg(type, item) {
            const m = document.getElementById('msg-modal');
            document.getElementById('mm-type').value = type;
            document.getElementById('mm-id').value = item ? item.id : '';
            document.getElementById('mm-text').value = item ? (item.text || item.message || '') : '';
            document.getElementById('mm-active').checked = item ? !!item.is_active : true;
            document.getElementById('mm-always-row').style.display = type==='static'?'block':'none';
            document.getElementById('mm-always').checked = item ? !!item.show_always : false;
            document.getElementById('mm-image-row').style.display = type === 'ads' ? 'block' : 'none';
            document.getElementById('mm-image').value = item ? (item.image_path || '') : '';
            document.getElementById('mm-threshold-row').style.display = type === 'threshold' ? 'block' : 'none';
            document.getElementById('mm-min').value = item ? (item.min_points || 0) : 0;
            document.getElementById('mm-max').value = item ? (item.max_points || 999999) : 999999;
            const hasDates = (type==='news'||type==='ads');
            document.getElementById('mm-dates-row').style.display = hasDates?'block':'none';
            document.getElementById('mm-start-date').value = item?(item.start_date||''):'';
            document.getElementById('mm-end-date').value = item?(item.end_date||''):'';
            document.getElementById('mm-sort-row').style.display = hasDates?'block':'none';
            document.getElementById('mm-sort').value = item?(item.sort_order||0):0;
            const titles = {static:'הודעה כללית',threshold:'הודעה לפי ניקוד',news:'חדשה',ads:'פרסומת'};
            document.getElementById('mm-title').textContent = (item ? 'עריכת ' : '') + (titles[type] || 'הודעה');
            m.style.display = 'flex';
        }
        function closeMsg() { document.getElementById('msg-modal').style.display = 'none'; }
        async function saveMsg() {
            const type = document.getElementById('mm-type').value;
            const body = {
                text: document.getElementById('mm-text').value,
                is_active: document.getElementById('mm-active').checked ? 1 : 0
            };
            const mid = document.getElementById('mm-id').value;
            if (mid) body.id = parseInt(mid);
            if (type === 'static') body.show_always = document.getElementById('mm-always').checked ? 1 : 0;
            if (type === 'ads') body.image_path = document.getElementById('mm-image').value;
            if (type === 'threshold') {
                body.min_points = parseInt(document.getElementById('mm-min').value) || 0;
                body.max_points = parseInt(document.getElementById('mm-max').value) || 999999;
            }
            if (type === 'news' || type === 'ads') {
                body.start_date = document.getElementById('mm-start-date').value || null;
                body.end_date = document.getElementById('mm-end-date').value || null;
                body.sort_order = parseInt(document.getElementById('mm-sort').value) || 0;
            }
            try {
                await fetch('/api/messages/' + type + '/save', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(body)
                });
                closeMsg();
                load(type);
            } catch(e) { alert('שגיאה: ' + e); }
        }
        function addStatic() { openMsg('static', null); }
        function addThreshold() { openMsg('threshold', null); }
        function addNews() { openMsg('news', null); }
        function addAd() { openMsg('ads', null); }
        async function edit(type, id) {
            try {
                const r = await fetch('/api/messages/' + type);
                const d = await r.json();
                const item = (d.items || []).find(x => x.id === id);
                if (item) openMsg(type, item);
            } catch(e) { alert('שגיאה בטעינה'); }
        }
        async function del(type, id) {
            if(!confirm('למחוק?')) return;
            await fetch('/api/messages/' + type + '/delete', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({id: id})
            });
            load(type);
        }

        async function loadTimeBonus() {
            try {
                const r = await fetch('/api/settings/get/time_bonus_message');
                const d = await r.json();
                document.getElementById('tb-enabled').checked = !!d.enabled;
                document.getElementById('tb-n').value = d.n || 1;
                document.getElementById('tb-text').value = d.text || '*הגעת ראשון להיום!*';
            } catch(e) {}
        }
        async function saveTimeBonus() {
            await fetch('/api/settings/save', {
                method:'POST', headers:{'Content-Type':'application/json'},
                body: JSON.stringify({key:'time_bonus_message', value:{
                    enabled: document.getElementById('tb-enabled').checked,
                    n: parseInt(document.getElementById('tb-n').value)||1,
                    text: document.getElementById('tb-text').value
                }})
            });
            alert('נשמר');
        }

        async function loadNewsSettings() {
            const keys = ['news_show_weekday','news_show_hebrew_date','news_show_parsha','news_show_holidays','news_show_birthdays','birthday_message_template','birthday_bar_mitzvah_template'];
            for (const k of keys) {
                try {
                    const r = await fetch('/api/settings/get/' + k);
                    const d = await r.json();
                    const v = d.value;
                    if (k === 'birthday_message_template') { document.getElementById('ns-bday-template').value = v || ''; continue; }
                    if (k === 'birthday_bar_mitzvah_template') { document.getElementById('ns-bar-template').value = v || ''; continue; }
                    const map = {news_show_weekday:'ns-weekday',news_show_hebrew_date:'ns-hebrew-date',news_show_parsha:'ns-parsha',news_show_holidays:'ns-holidays',news_show_birthdays:'ns-birthdays'};
                    if (map[k]) document.getElementById(map[k]).checked = (v === '1' || v === 'true' || v === true);
                } catch(e) {}
            }
        }
        async function saveNewsSettings() {
            const pairs = [
                ['news_show_weekday', document.getElementById('ns-weekday').checked ? '1' : '0'],
                ['news_show_hebrew_date', document.getElementById('ns-hebrew-date').checked ? '1' : '0'],
                ['news_show_parsha', document.getElementById('ns-parsha').checked ? '1' : '0'],
                ['news_show_holidays', document.getElementById('ns-holidays').checked ? '1' : '0'],
                ['news_show_birthdays', document.getElementById('ns-birthdays').checked ? '1' : '0'],
                ['birthday_message_template', document.getElementById('ns-bday-template').value],
                ['birthday_bar_mitzvah_template', document.getElementById('ns-bar-template').value],
            ];
            for (const [k, v] of pairs) {
                await fetch('/api/settings/save', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({key: k, value: v})});
            }
            alert('הגדרות חדשות נשמרו');
        }

        load('static');
        
        const style = document.createElement('style');
        style.innerHTML = `
            .tab-btn { background:none; border:none; color:rgba(255,255,255,0.6); padding:10px 20px; cursor:pointer; font-weight:bold; font-size:16px; border-bottom:3px solid transparent; }
            .tab-btn.active { color:#fff; border-bottom-color:#3498db; }
            .tab-btn:hover { color:#fff; }
        `;
        document.head.appendChild(style);
    </script>
    """
    return basic_web_shell("ניהול הודעות", html_content, request=request)

# API Endpoints for Messages

@router.get("/api/messages/static")
def api_messages_static_list(request: Request):
    return _list_messages(request, "static_messages")

@router.post("/api/messages/static/save")
def api_messages_static_save(request: Request, payload: Dict[str, Any]):
    return _save_message(request, "static_messages", payload, "static_message")

@router.post("/api/messages/static/delete")
def api_messages_static_delete(request: Request, payload: Dict[str, Any]):
    return _delete_message(request, "static_messages", payload, "static_message")

@router.get("/api/messages/threshold")
def api_messages_threshold_list(request: Request):
    return _list_messages(request, "threshold_messages")

@router.post("/api/messages/threshold/save")
def api_messages_threshold_save(request: Request, payload: Dict[str, Any]):
    return _save_message(request, "threshold_messages", payload, "threshold_message")

@router.post("/api/messages/threshold/delete")
def api_messages_threshold_delete(request: Request, payload: Dict[str, Any]):
    return _delete_message(request, "threshold_messages", payload, "threshold_message")

@router.get("/api/messages/news")
def api_messages_news_list(request: Request):
    return _list_messages(request, "news_items")

@router.post("/api/messages/news/save")
def api_messages_news_save(request: Request, payload: Dict[str, Any]):
    return _save_message(request, "news_items", payload, "news_item")

@router.post("/api/messages/news/delete")
def api_messages_news_delete(request: Request, payload: Dict[str, Any]):
    return _delete_message(request, "news_items", payload, "news_item")

@router.get("/api/messages/ads")
def api_messages_ads_list(request: Request):
    return _list_messages(request, "ads_items")

@router.post("/api/messages/ads/save")
def api_messages_ads_save(request: Request, payload: Dict[str, Any]):
    return _save_message(request, "ads_items", payload, "ads_item")

@router.post("/api/messages/ads/delete")
def api_messages_ads_delete(request: Request, payload: Dict[str, Any]):
    return _delete_message(request, "ads_items", payload, "ads_item")

@router.post("/api/messages/ads/upload-image")
async def api_messages_ads_upload(request: Request, file: UploadFile = File(...)):
    guard = web_require_admin_teacher(request)
    if guard: raise HTTPException(status_code=401)
    
    tenant_id = web_tenant_from_cookie(request)
    if not tenant_id: raise HTTPException(status_code=400)
    
    try:
        # Save to tenants_assets/tenant_id/ads_media/
        rel_dir = "ads_media"
        abs_dir = get_tenant_asset_path(tenant_id, rel_dir)
        os.makedirs(abs_dir, exist_ok=True)
        
        filename = f"{int(time_to_minutes('00:00') or 0)}_{file.filename}" # just randomish prefix
        # better:
        import time
        filename = f"{int(time.time())}_{file.filename}"
        
        dest_path = os.path.join(abs_dir, filename)
        content = await file.read()
        with open(dest_path, "wb") as f:
            f.write(content)
            
        rel_path = f"ads_media/{filename}"
        return {"ok": True, "path": rel_path}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# Helper functions for message CRUD
def _list_messages(request: Request, table: str) -> Dict[str, Any]:
    # guard = web_require_teacher(request) # or admin? usually admin
    # Let's say admin only for configuration messages
    guard = web_require_admin_teacher(request)
    if guard: raise HTTPException(status_code=401)
    
    tenant_id = web_tenant_from_cookie(request)
    conn = tenant_db_connection(tenant_id)
    try:
        cur = conn.cursor()
        sql = f"SELECT * FROM {table} ORDER BY id DESC"
        if table in ('news_items', 'ads_items'):
             # maybe order by sort_order
             pass
        
        cur.execute(sql_placeholder(sql))
        rows = cur.fetchall() or []
        items = []
        for r in rows:
            d = dict(r) if isinstance(r, dict) else {k: r[k] for k in r.keys()} if hasattr(r, 'keys') else {}
            # fallback tuple logic omitted for brevity
            items.append(d)
        return {'items': items}
    finally:
        try: conn.close()
        except: pass

def _save_message(request: Request, table: str, payload: Dict[str, Any], entity_type: str) -> Dict[str, Any]:
    guard = web_require_admin_teacher(request)
    if guard: raise HTTPException(status_code=401)
    
    tenant_id = web_tenant_from_cookie(request)
    conn = tenant_db_connection(tenant_id)
    try:
        cur = conn.cursor()
        mid = payload.get('id')
        text = payload.get('text') or payload.get('message') or ''
        is_active = 1 if payload.get('is_active') else 0
        
        # columns vary by table
        # static_messages: message, is_active
        # news_items: text, is_active, sort_order, start_date, end_date
        # ads_items: text, image_path, is_active, ...
        
        cols = {}
        if table == 'static_messages':
            cols = {'message': text, 'is_active': is_active, 'show_always': 1 if payload.get('show_always') else 0}
        elif table == 'threshold_messages':
            cols = {'message': text, 'is_active': is_active, 'min_points': payload.get('min_points', 0), 'max_points': payload.get('max_points', 999999)}
        elif table == 'news_items':
            cols = {'text': text, 'is_active': is_active, 'sort_order': payload.get('sort_order', 0), 'start_date': payload.get('start_date'), 'end_date': payload.get('end_date')}
        elif table == 'ads_items':
            cols = {'text': text, 'is_active': is_active, 'image_path': payload.get('image_path'), 'sort_order': payload.get('sort_order', 0), 'start_date': payload.get('start_date'), 'end_date': payload.get('end_date')}
            
        if not mid:
            # Create
            columns = list(cols.keys())
            placeholders = ','.join(['?' for _ in columns])
            sql = f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})"
            vals = list(cols.values())
            if USE_POSTGRES:
                sql = sql.replace('?', '%s') + " RETURNING id"
                cur.execute(sql, vals)
                row = cur.fetchone()
                mid = row['id'] if isinstance(row, dict) else row[0]
            else:
                cur.execute(sql, vals)
                mid = cur.lastrowid
            
            record_sync_event(
                tenant_id=tenant_id,
                station_id='web',
                entity_type=entity_type,
                entity_id=str(mid),
                action_type='create',
                payload=cols
            )
        else:
            # Update
            sets = []
            vals = []
            for k, v in cols.items():
                sets.append(f"{k}=?")
                vals.append(v)
            vals.append(mid)
            sql = f"UPDATE {table} SET {','.join(sets)} WHERE id=?"
            cur.execute(sql_placeholder(sql), vals)
            
            record_sync_event(
                tenant_id=tenant_id,
                station_id='web',
                entity_type=entity_type,
                entity_id=str(mid),
                action_type='update',
                payload=cols
            )
            
        conn.commit()
        return {'ok': True, 'id': mid}
    finally:
        try: conn.close()
        except: pass

def _delete_message(request: Request, table: str, payload: Dict[str, Any], entity_type: str) -> Dict[str, Any]:
    guard = web_require_admin_teacher(request)
    if guard: raise HTTPException(status_code=401)
    
    tenant_id = web_tenant_from_cookie(request)
    mid = payload.get('id')
    if not mid: raise HTTPException(status_code=400)
    
    conn = tenant_db_connection(tenant_id)
    try:
        cur = conn.cursor()
        cur.execute(sql_placeholder(f"DELETE FROM {table} WHERE id=?"), (mid,))
        conn.commit()
        
        record_sync_event(
            tenant_id=tenant_id,
            station_id='web',
            entity_type=entity_type,
            entity_id=str(mid),
            action_type='delete',
            payload={}
        )
        return {'ok': True}
    finally:
        try: conn.close()
        except: pass
