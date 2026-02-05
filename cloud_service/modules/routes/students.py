from fastapi import APIRouter, Request, HTTPException, Body
from fastapi.responses import HTMLResponse
from typing import Dict, Any, List
import json

from ..utils import basic_web_shell
from ..auth import web_require_teacher, web_tenant_from_cookie, safe_int, web_current_teacher
from ..db import tenant_db_connection, sql_placeholder, table_columns
from ..config import USE_POSTGRES
from ..models import StudentSavePayload, StudentDeletePayload, StudentManualArrivalPayload
from ..sync_logic import record_sync_event, apply_change_to_tenant_db

router = APIRouter()

@router.get("/web/students", response_class=HTMLResponse)
def web_students(request: Request):
    try:
        guard = web_require_teacher(request)
        if guard: return guard
        
        teacher = web_current_teacher(request) or {}
        is_admin = (int(teacher.get('is_admin') or 0) == 1)
        
        # Determine allowed classes logic if needed (not fully implemented in auth yet)
        # For now, admins see all, teachers might see filtered.
        
        html_content = """
        <div style="max-width:1200px; margin:0 auto;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px; flex-wrap:wrap; gap:10px;">
                <h2 style="margin:0;">ניהול תלמידים</h2>
                <div style="display:flex; gap:10px;">
                    <button class="blue" onclick="openAdd()" id="btn-add">➕ תלמיד חדש</button>
                    <button class="gray" onclick="load()">🔄 רענן</button>
                </div>
            </div>

            <div class="card" style="margin-bottom:20px; padding:15px; display:flex; gap:15px; flex-wrap:wrap; align-items:center;">
                <div style="flex:1; min-width:200px;">
                    <input type="text" id="s_search" placeholder="חיפוש לפי שם, תעודת זהות, כיתה..." class="form-input" onkeyup="if(event.key==='Enter') load()">
                </div>
                <button class="blue" onclick="load()">🔍 חיפוש</button>
            </div>

            <div class="card" style="padding:0; overflow:hidden;">
                <div style="padding:10px; background:rgba(0,0,0,0.03); border-bottom:1px solid rgba(0,0,0,0.1); display:flex; justify-content:space-between; align-items:center;">
                    <div id="s_status" style="font-size:13px; font-weight:bold; opacity:0.7;">טוען...</div>
                    <div style="display:flex; gap:8px;">
                        <span id="s_selected" style="font-size:13px; padding-top:6px;">לא נבחר תלמיד</span>
                        <button id="s_edit" class="blue" style="font-size:12px; padding:4px 10px; opacity:0.5; pointer-events:none;" onclick="openEdit()">✏️ ערוך</button>
                        <button id="s_delete" class="red" style="font-size:12px; padding:4px 10px; background:#e74c3c; border:none; opacity:0.5; pointer-events:none;" onclick="delSelected()">🗑 מחק</button>
                    </div>
                </div>
                <div class="table-scroll" style="max-height:600px;">
                    <table style="width:100%; border-collapse:collapse; min-width:800px;">
                        <thead>
                            <tr style="text-align:right;">
                                <th style="padding:12px; width:60px;">ID</th>
                                <th style="padding:12px;">שם משפחה</th>
                                <th style="padding:12px;">שם פרטי</th>
                                <th style="padding:12px; width:100px;">כיתה</th>
                                <th style="padding:12px;">נקודות</th>
                                <th style="padding:12px;">הודעה פרטית</th>
                                <th style="padding:12px;">מס' כרטיס</th>
                                <th style="padding:12px;">ת"ז</th>
                            </tr>
                        </thead>
                        <tbody id="s_rows"></tbody>
                    </table>
                </div>
            </div>
        </div>

        <!-- Modal -->
        <div id="s_modal" class="modal-overlay">
            <div class="modal-content">
                <button class="modal-close" onclick="closeModal()">×</button>
                <h3 id="s_modal_title" style="margin-top:0;">עריכת תלמיד</h3>
                <input type="hidden" id="m_student_id">
                
                <div style="display:grid; grid-template-columns:1fr 1fr; gap:15px;">
                    <div class="form-group">
                        <label>שם פרטי</label>
                        <input id="m_first_name" class="form-input">
                    </div>
                    <div class="form-group">
                        <label>שם משפחה</label>
                        <input id="m_last_name" class="form-input">
                    </div>
                </div>
                
                <div style="display:grid; grid-template-columns:1fr 1fr; gap:15px;">
                    <div class="form-group">
                        <label>כיתה</label>
                        <input id="m_class_name" class="form-input">
                    </div>
                    <div class="form-group">
                        <label>תעודת זהות</label>
                        <input id="m_id_number" class="form-input">
                    </div>
                </div>

                <div class="form-group">
                    <label>מספר כרטיס</label>
                    <input id="m_card_number" class="form-input">
                </div>

                <div style="display:grid; grid-template-columns:1fr 1fr; gap:15px;">
                    <div class="form-group">
                        <label>נקודות</label>
                        <input type="number" id="m_points" class="form-input">
                    </div>
                    <div class="form-group" style="padding-top:30px;">
                        <label style="display:flex; align-items:center; gap:8px;">
                            <input type="checkbox" id="m_is_free_fix_blocked" style="width:18px; height:18px;">
                            חסום לתיקון חופשי
                        </label>
                    </div>
                </div>

                <div class="form-group">
                    <label>הודעה פרטית (מוצגת לתלמיד)</label>
                    <input id="m_private_message" class="form-input">
                </div>

                <div style="margin-top:20px; display:flex; justify-content:flex-end; gap:10px;">
                    <button class="btn-gray" onclick="closeModal()">ביטול</button>
                    <button class="btn-primary" onclick="save()">שמירה</button>
                </div>
            </div>
        </div>

        <script>
            let selectedId = null;
            const rowsEl = document.getElementById('s_rows');
            const statusEl = document.getElementById('s_status');
            const searchEl = document.getElementById('s_search');
            const selectedEl = document.getElementById('s_selected');
            const btnEdit = document.getElementById('s_edit');
            const btnDelete = document.getElementById('s_delete');
            const modal = document.getElementById('s_modal');
            
            // Fields
            const mId = document.getElementById('m_student_id');
            const mFirst = document.getElementById('m_first_name');
            const mLast = document.getElementById('m_last_name');
            const mClass = document.getElementById('m_class_name');
            const mIdNum = document.getElementById('m_id_number');
            const mCard = document.getElementById('m_card_number');
            const mPoints = document.getElementById('m_points');
            const mMsg = document.getElementById('m_private_message');
            const mBlock = document.getElementById('m_is_free_fix_blocked');

            function esc(s) {
                return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
            }

            function setSelected(id) {
                selectedId = id;
                const on = (selectedId !== null);
                btnEdit.style.opacity = on ? '1' : '0.5';
                btnEdit.style.pointerEvents = on ? 'auto' : 'none';
                btnDelete.style.opacity = on ? '1' : '0.5';
                btnDelete.style.pointerEvents = on ? 'auto' : 'none';
                selectedEl.textContent = on ? 'נבחר תלמיד ID ' + id : 'לא נבחר תלמיד';
                
                document.querySelectorAll('#s_rows tr').forEach(tr => {
                    tr.style.background = (tr.dataset.id == id) ? 'rgba(52, 152, 219, 0.2)' : '';
                });
            }

            async function load() {
                statusEl.textContent = 'טוען...';
                rowsEl.innerHTML = '';
                try {
                    const q = encodeURIComponent(searchEl.value);
                    const resp = await fetch('/api/students?q=' + q);
                    const data = await resp.json();
                    
                    if (!data.items || data.items.length === 0) {
                        rowsEl.innerHTML = '<tr><td colspan="8" style="padding:20px; text-align:center;">לא נמצאו תלמידים</td></tr>';
                        statusEl.textContent = '0 תלמידים';
                        return;
                    }
                    
                    statusEl.textContent = data.items.length + ' תלמידים (מציג 100 ראשונים)';
                    
                    rowsEl.innerHTML = data.items.map(s => `
                        <tr data-id="${s.id}" onclick="setSelected(${s.id})" style="border-bottom:1px solid rgba(255,255,255,0.05); cursor:pointer;">
                            <td style="padding:12px; opacity:0.7;">${s.id}</td>
                            <td style="padding:12px; font-weight:bold;">${esc(s.last_name)}</td>
                            <td style="padding:12px;">${esc(s.first_name)}</td>
                            <td style="padding:12px;">${esc(s.class_name)}</td>
                            <td style="padding:12px; color:#2ecc71; font-weight:bold;">${s.points}</td>
                            <td style="padding:12px; opacity:0.8;">${esc(s.private_message)}</td>
                            <td style="padding:12px; direction:ltr; text-align:right;">${esc(s.card_number)}</td>
                            <td style="padding:12px;">${esc(s.id_number)}</td>
                        </tr>
                    `).join('');
                    
                } catch (e) {
                    statusEl.textContent = 'שגיאה בטעינה';
                    console.error(e);
                }
            }

            function openModal() {
                modal.style.display = 'flex';
            }
            
            function closeModal() {
                modal.style.display = 'none';
            }

            function openAdd() {
                document.getElementById('s_modal_title').textContent = 'תלמיד חדש';
                mId.value = '';
                mFirst.value = '';
                mLast.value = '';
                mClass.value = '';
                mIdNum.value = '';
                mCard.value = '';
                mPoints.value = '0';
                mMsg.value = '';
                mBlock.checked = false;
                openModal();
            }

            async function openEdit() {
                if (!selectedId) return;
                document.getElementById('s_modal_title').textContent = 'עריכת תלמיד ' + selectedId;
                
                try {
                    const resp = await fetch('/api/students/' + selectedId);
                    const s = await resp.json();
                    
                    mId.value = s.id;
                    mFirst.value = s.first_name || '';
                    mLast.value = s.last_name || '';
                    mClass.value = s.class_name || '';
                    mIdNum.value = s.id_number || '';
                    mCard.value = s.card_number || '';
                    mPoints.value = s.points || 0;
                    mMsg.value = s.private_message || '';
                    mBlock.checked = !!s.is_free_fix_blocked;
                    
                    openModal();
                } catch(e) {
                    alert('שגיאה בטעינת נתונים');
                }
            }

            async function save() {
                const payload = {
                    student_id: mId.value ? parseInt(mId.value) : null,
                    first_name: mFirst.value,
                    last_name: mLast.value,
                    class_name: mClass.value,
                    id_number: mIdNum.value,
                    card_number: mCard.value,
                    points: parseInt(mPoints.value || 0),
                    private_message: mMsg.value,
                    is_free_fix_blocked: mBlock.checked ? 1 : 0
                };
                
                try {
                    const resp = await fetch('/api/students/save', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify(payload)
                    });
                    
                    if (!resp.ok) {
                        const txt = await resp.text();
                        alert('שגיאה: ' + txt);
                        return;
                    }
                    
                    closeModal();
                    load();
                } catch(e) {
                    alert('שגיאה בשמירה');
                }
            }

            async function delSelected() {
                if (!selectedId) return;
                if (!confirm('האם למחוק את התלמיד? פעולה זו אינה הפיכה.')) return;
                
                try {
                    const resp = await fetch('/api/students/delete', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({student_id: selectedId})
                    });
                    
                    if (!resp.ok) {
                        alert('שגיאה במחיקה');
                        return;
                    }
                    
                    selectedId = null;
                    load();
                } catch(e) {
                    alert('שגיאה בתקשורת');
                }
            }

            // Initial load
            load();
        </script>
        """
        return basic_web_shell("ניהול תלמידים", html_content, request=request)
    except Exception as e:
        return HTMLResponse(f"Error: {e}", status_code=500)

@router.get("/api/students")
def api_students_list(request: Request, q: str = "") -> Dict[str, Any]:
    guard = web_require_teacher(request)
    if guard: raise HTTPException(status_code=401, detail="Unauthorized")
    
    tenant_id = web_tenant_from_cookie(request)
    if not tenant_id: raise HTTPException(status_code=400, detail="Missing tenant")
    
    conn = tenant_db_connection(tenant_id)
    try:
        cur = conn.cursor()
        q_str = str(q or '').strip()
        sql = "SELECT id, first_name, last_name, class_name, points, private_message, card_number, id_number, is_free_fix_blocked FROM students"
        params = []
        if q_str:
            sql += " WHERE (first_name LIKE ? OR last_name LIKE ? OR card_number LIKE ? OR class_name LIKE ? OR id_number LIKE ?)"
            p = f"%{q_str}%"
            params = [p, p, p, p, p]
        
        sql += " ORDER BY class_name, last_name LIMIT 100"
        
        cur.execute(sql_placeholder(sql), params)
        rows = cur.fetchall() or []
        items = []
        for r in rows:
            d = dict(r) if isinstance(r, dict) else {k: r[k] for k in r.keys()} if hasattr(r, 'keys') else {
                'id': r[0], 'first_name': r[1], 'last_name': r[2], 'class_name': r[3], 
                'points': r[4], 'private_message': r[5], 'card_number': r[6], 'id_number': r[7],
                'is_free_fix_blocked': r[8] if len(r) > 8 else 0
            }
            items.append(d)
            
        return {'items': items}
    finally:
        try: conn.close()
        except: pass

@router.get("/api/students/{student_id}")
def api_student_get(request: Request, student_id: int):
    guard = web_require_teacher(request)
    if guard: raise HTTPException(status_code=401, detail="Unauthorized")
    
    tenant_id = web_tenant_from_cookie(request)
    conn = tenant_db_connection(tenant_id)
    try:
        cur = conn.cursor()
        cur.execute(sql_placeholder("SELECT * FROM students WHERE id = ? LIMIT 1"), (student_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Student not found")
        
        d = dict(row) if isinstance(row, dict) else {k: row[k] for k in row.keys()} if hasattr(row, 'keys') else {}
        # if tuple fallback needed, would be messy for all cols. assuming Row/RealDict works.
        
        return d
    finally:
        try: conn.close()
        except: pass

@router.post("/api/students/save")
def api_student_save(request: Request, payload: StudentSavePayload):
    guard = web_require_teacher(request)
    if guard: raise HTTPException(status_code=401, detail="Unauthorized")
    
    tenant_id = web_tenant_from_cookie(request)
    conn = tenant_db_connection(tenant_id)
    
    try:
        cur = conn.cursor()
        
        sid = payload.student_id
        is_new = not (sid and sid > 0)
        
        cols = {
            'first_name': payload.first_name,
            'last_name': payload.last_name,
            'class_name': payload.class_name,
            'card_number': payload.card_number,
            'id_number': payload.id_number,
            'points': payload.points if payload.points is not None else 0,
            'private_message': payload.private_message,
            'is_free_fix_blocked': payload.is_free_fix_blocked if payload.is_free_fix_blocked is not None else 0
        }
        
        if is_new:
            # Insert
            # Check unique card/id if provided? For now simple insert.
            columns = list(cols.keys())
            placeholders = ','.join(['?' for _ in columns])
            sql = f"INSERT INTO students ({','.join(columns)}) VALUES ({placeholders})"
            if USE_POSTGRES:
                sql = sql.replace('?', '%s') + " RETURNING id"
                cur.execute(sql, list(cols.values()))
                row = cur.fetchone()
                new_id = row['id'] if isinstance(row, dict) else row[0]
            else:
                cur.execute(sql, list(cols.values()))
                new_id = cur.lastrowid
                
            record_sync_event(
                tenant_id=tenant_id,
                station_id='web',
                entity_type='students',
                entity_id=str(new_id),
                action_type='create',
                payload=cols
            )
        else:
            # Update
            sets = []
            vals = []
            for k, v in cols.items():
                sets.append(f"{k} = ?")
                vals.append(v)
            vals.append(sid)
            
            sql = f"UPDATE students SET {','.join(sets)}, updated_at = CURRENT_TIMESTAMP WHERE id = ?"
            cur.execute(sql_placeholder(sql), vals)
            
            record_sync_event(
                tenant_id=tenant_id,
                station_id='web',
                entity_type='students',
                entity_id=str(sid),
                action_type='update',
                payload=cols
            )
            
        conn.commit()
        return {'ok': True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        try: conn.close()
        except: pass

@router.post("/api/students/delete")
def api_student_delete(request: Request, payload: StudentDeletePayload):
    guard = web_require_teacher(request)
    if guard: raise HTTPException(status_code=401, detail="Unauthorized")
    
    tenant_id = web_tenant_from_cookie(request)
    conn = tenant_db_connection(tenant_id)
    try:
        cur = conn.cursor()
        sid = payload.student_id
        
        # Delete related (points log, history)
        # Using soft delete or cascading? For now hard delete as requested.
        try:
            cur.execute(sql_placeholder("DELETE FROM points_log WHERE student_id = ?"), (sid,))
            cur.execute(sql_placeholder("DELETE FROM points_history WHERE student_id = ?"), (sid,))
        except:
            pass
            
        cur.execute(sql_placeholder("DELETE FROM students WHERE id = ?"), (sid,))
        conn.commit()
        
        record_sync_event(
            tenant_id=tenant_id,
            station_id='web',
            entity_type='students',
            entity_id=str(sid),
            action_type='delete',
            payload={}
        )
        
        return {'ok': True}
    finally:
        try: conn.close()
        except: pass
