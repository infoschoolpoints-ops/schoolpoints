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
            <button class="tab-btn active" onclick="switchTab('static')">הודעות רצות</button>
            <button class="tab-btn" onclick="switchTab('news')">חדשות</button>
            <button class="tab-btn" onclick="switchTab('ads')">פרסומות</button>
        </div>

        <!-- Static Messages -->
        <div id="tab-static" class="tab-content">
            <div class="card" style="padding:15px;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px;">
                    <h3>הודעות רצות (פס גלילה)</h3>
                    <button class="blue" onclick="addStatic()">➕ הוסף הודעה</button>
                </div>
                <div id="list-static">Loading...</div>
            </div>
        </div>

        <!-- News -->
        <div id="tab-news" class="tab-content" style="display:none;">
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

    <!-- Modals would go here, simplified for brevity -->
    
    <script>
        function switchTab(name) {
            document.querySelectorAll('.tab-content').forEach(el => el.style.display = 'none');
            document.getElementById('tab-' + name).style.display = 'block';
            document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
            event.target.classList.add('active');
            load(name);
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
                    <div style="background:rgba(255,255,255,0.05); padding:10px; margin-bottom:10px; border-radius:8px; display:flex; justify-content:space-between; align-items:center;">
                        <div>
                            <div style="font-weight:bold;">${item.text || item.message || '(תמונה)'}</div>
                            <div style="font-size:12px; opacity:0.7;">
                                ${item.is_active ? '<span style="color:#2ecc71">פעיל</span>' : '<span style="color:#e74c3c">לא פעיל</span>'}
                                ${item.image_path ? ' | כולל תמונה' : ''}
                            </div>
                        </div>
                        <div style="display:flex; gap:5px;">
                            <button class="blue" style="padding:5px 10px; font-size:12px;" onclick="edit('${type}', ${item.id})">ערוך</button>
                            <button class="red" style="padding:5px 10px; font-size:12px; background:#e74c3c; border:none;" onclick="del('${type}', ${item.id})">מחק</button>
                        </div>
                    </div>
                `).join('');
            } catch(e) {
                list.innerHTML = 'Error loading';
            }
        }
        
        function addStatic() { alert('פונקציונליות בבנייה (API קיים)'); }
        function addNews() { alert('פונקציונליות בבנייה (API קיים)'); }
        function addAd() { alert('פונקציונליות בבנייה (API קיים)'); }
        function edit(type, id) { alert('עריכה: ' + type + ' ' + id); }
        async function del(type, id) {
            if(!confirm('למחוק?')) return;
            await fetch('/api/messages/' + type + '/delete', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({id: id})
            });
            load(type);
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
            cols = {'message': text, 'is_active': is_active}
        elif table == 'news_items':
            cols = {'text': text, 'is_active': is_active} # add others if needed
        elif table == 'ads_items':
            cols = {'text': text, 'is_active': is_active, 'image_path': payload.get('image_path')}
            
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
