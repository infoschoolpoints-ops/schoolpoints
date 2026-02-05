from fastapi import APIRouter, Request, HTTPException, Body
from fastapi.responses import HTMLResponse
from typing import Dict, Any, List
import json

from ..utils import basic_web_shell
from ..auth import web_require_admin_teacher, web_tenant_from_cookie, safe_int, web_current_teacher
from ..db import tenant_db_connection, sql_placeholder, table_columns
from ..config import USE_POSTGRES
from ..models import TeacherSavePayload, TeacherClassesPayload, TeacherDeletePayload
from ..sync_logic import record_sync_event, apply_change_to_tenant_db

router = APIRouter()

@router.get("/web/teachers", response_class=HTMLResponse)
def web_teachers(request: Request):
    guard = web_require_admin_teacher(request)
    if guard: return guard
    
    html_content = """
    <div style="max-width:1200px; margin:0 auto;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px;">
            <h2 style="margin:0;">ניהול מורים</h2>
            <div style="display:flex; gap:10px;">
                <button class="blue" onclick="openAdd()" id="t_new">➕ מורה חדש</button>
                <button class="gray" onclick="load()">🔄 רענן</button>
            </div>
        </div>

        <div class="card" style="margin-bottom:20px; padding:15px; display:flex; gap:15px; align-items:center;">
            <div style="flex:1;">
                <input type="text" id="t_search" placeholder="חיפוש לפי שם או כרטיס..." class="form-input" onkeyup="if(event.key==='Enter') load()">
            </div>
            <button class="blue" onclick="load()">🔍 חיפוש</button>
        </div>

        <div class="card" style="padding:0; overflow:hidden;">
            <div style="padding:10px; background:rgba(0,0,0,0.03); border-bottom:1px solid rgba(0,0,0,0.1); display:flex; justify-content:space-between; align-items:center;">
                <div id="t_status" style="font-size:13px; font-weight:bold; opacity:0.7;">טוען...</div>
                <div style="display:flex; gap:8px;">
                    <span id="t_selected" style="font-size:13px; padding-top:6px;">לא נבחר מורה</span>
                    <button id="t_edit" class="blue" style="font-size:12px; padding:4px 10px; opacity:0.5; pointer-events:none;" onclick="openEdit()">✏️ ערוך</button>
                    <button id="t_delete" class="red" style="font-size:12px; padding:4px 10px; background:#e74c3c; border:none; opacity:0.5; pointer-events:none;" onclick="delSelected()">🗑 מחק</button>
                </div>
            </div>
            <div class="table-scroll">
                <table style="width:100%; border-collapse:collapse; min-width:800px;">
                    <thead>
                        <tr style="text-align:right;">
                            <th style="padding:12px;">שם המורה</th>
                            <th style="padding:12px;">כרטיס</th>
                            <th style="padding:12px;">תפקיד</th>
                            <th style="padding:12px;">כיתות</th>
                            <th style="padding:12px;">תקרת נק' לתלמיד</th>
                            <th style="padding:12px;">תקרת הרצות</th>
                            <th style="padding:12px;">שימוש יומי</th>
                            <th style="padding:12px;">נקודות היום</th>
                        </tr>
                    </thead>
                    <tbody id="t_rows"></tbody>
                </table>
            </div>
        </div>
    </div>

    <div id="t_modal" class="modal-overlay" style="display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.5); align-items:center; justify-content:center; z-index:9999;">
        <div class="modal-content" style="background:white; width:600px; max-width:90%; padding:20px; border-radius:8px; max-height:90vh; overflow-y:auto; box-shadow:0 4px 12px rgba(0,0,0,0.15); color:black;">
            <h3 id="t_modal_title" style="margin-top:0;">עריכת מורה</h3>
            <input type="hidden" id="m_teacher_id">
            
            <div style="margin-bottom:10px;">
                <label style="display:block; margin-bottom:4px; font-weight:bold;">שם המורה:</label>
                <input type="text" id="m_name" class="form-input" style="width:100%; box-sizing:border-box;">
            </div>
            
            <div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:10px; margin-top:10px;">
                <div>
                    <label style="display:block; margin-bottom:4px; font-size:13px;">כרטיס 1:</label>
                    <input type="text" id="m_card1" class="form-input" style="width:100%; box-sizing:border-box;">
                </div>
                 <div>
                    <label style="display:block; margin-bottom:4px; font-size:13px;">כרטיס 2:</label>
                    <input type="text" id="m_card2" class="form-input" style="width:100%; box-sizing:border-box;">
                </div>
                 <div>
                    <label style="display:block; margin-bottom:4px; font-size:13px;">כרטיס 3:</label>
                    <input type="text" id="m_card3" class="form-input" style="width:100%; box-sizing:border-box;">
                </div>
            </div>

            <div style="margin-top:15px; display:flex; gap:20px; flex-wrap:wrap;">
                <label class="ck" style="display:flex;align-items:center;gap:5px;"><input type="checkbox" id="m_is_admin"> מנהל מערכת</label>
                <label class="ck" style="display:flex;align-items:center;gap:5px;"><input type="checkbox" id="m_can_edit_student_card"> עריכת כרטיס תלמיד</label>
                <label class="ck" style="display:flex;align-items:center;gap:5px;"><input type="checkbox" id="m_can_edit_student_photo"> עריכת תמונת תלמיד</label>
            </div>

            <h4 style="margin:15px 0 5px 0; border-bottom:1px solid #eee; padding-bottom:4px;">הגדרות בונוס (אופציונלי)</h4>
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px;">
                <div>
                    <label style="display:block; margin-bottom:4px; font-size:13px;">מקסימום נקודות לתלמיד:</label>
                    <input type="number" id="m_bonus_max_points_per_student" class="form-input" style="width:100%; box-sizing:border-box;" placeholder="ללא הגבלה">
                </div>
                 <div>
                    <label style="display:block; margin-bottom:4px; font-size:13px;">מקסימום הרצות כולל:</label>
                    <input type="number" id="m_bonus_max_total_runs" class="form-input" style="width:100%; box-sizing:border-box;" placeholder="ללא הגבלה">
                </div>
            </div>

            <h4 style="margin:15px 0 5px 0; border-bottom:1px solid #eee; padding-bottom:4px;">כיתות מורשות</h4>
            <div style="display:flex; gap:10px; margin-bottom:5px;">
                 <button type="button" id="m_select_all" onclick="document.getElementById('m_classes_box').querySelectorAll('input').forEach(c=>c.checked=true)" style="font-size:12px; padding:2px 6px;">בחר הכל</button>
                 <button type="button" id="m_clear_all" onclick="document.getElementById('m_classes_box').querySelectorAll('input').forEach(c=>c.checked=false)" style="font-size:12px; padding:2px 6px;">נקה הכל</button>
            </div>
            <div id="m_classes_box" style="border:1px solid #ccc; padding:10px; height:100px; overflow-y:auto; display:flex; flex-wrap:wrap; gap:10px; border-radius:4px; background:#f9f9f9; color:black;"></div>
            
            <div style="margin-top:20px; text-align:left; display:flex; gap:10px; justify-content:flex-end;">
                <button id="m_cancel" onclick="closeModal()" class="btn-gray">ביטול</button>
                <button id="m_save" class="btn-primary" onclick="save()">שמירה</button>
            </div>
        </div>
    </div>

    <script>
        const rowsEl = document.getElementById('t_rows');
        const statusEl = document.getElementById('t_status');
        const searchEl = document.getElementById('t_search');
        const selectedEl = document.getElementById('t_selected');
        const btnEdit = document.getElementById('t_edit');
        const btnDelete = document.getElementById('t_delete');
        const modal = document.getElementById('t_modal');
        const modalTitle = document.getElementById('t_modal_title');
        const mId = document.getElementById('m_teacher_id');
        const mName = document.getElementById('m_name');
        const mCard1 = document.getElementById('m_card1');
        const mCard2 = document.getElementById('m_card2');
        const mCard3 = document.getElementById('m_card3');
        const mIsAdmin = document.getElementById('m_is_admin');
        const mCanEditCard = document.getElementById('m_can_edit_student_card');
        const mCanEditPhoto = document.getElementById('m_can_edit_student_photo');
        const mMaxPoints = document.getElementById('m_bonus_max_points_per_student');
        const mMaxRuns = document.getElementById('m_bonus_max_total_runs');
        const classesBox = document.getElementById('m_classes_box');

        let selectedId = null;

        function esc(s) {
          return String(s ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
        }

        function setSelected(id) {
          selectedId = id;
          const on = (selectedId !== null);
          btnEdit.style.opacity = on ? '1' : '.55';
          btnDelete.style.opacity = on ? '1' : '.55';
          btnEdit.style.pointerEvents = on ? 'auto' : 'none';
          btnDelete.style.pointerEvents = on ? 'auto' : 'none';
          selectedEl.textContent = on ? 'נבחר מורה ID ' + selectedId : 'לא נבחר מורה';
          document.querySelectorAll('tr[data-id]').forEach(tr => {
            tr.style.background = (String(tr.getAttribute('data-id')) === String(selectedId)) ? 'rgba(52, 152, 219, 0.2)' : '';
          });
        }

        function openModal() {
          modal.style.display = 'flex';
        }

        function closeModal() {
          modal.style.display = 'none';
        }

        function setAdminMode(isAdmin) {
          const on = !!isAdmin;
          // In admin mode maybe disable class selection if admin has access to all? 
          // Usually admins have access to all, but let's keep it editable.
        }

        async function loadAllClasses() {
          try {
            const resp = await fetch('/api/classes');
            const data = await resp.json();
            const items = Array.isArray(data.items) ? data.items : [];
            return items.map(x => String(x)).filter(x => x.trim()).sort();
          } catch (e) {
            return [];
          }
        }

        function renderClasses(allClasses, selected) {
          const sel = new Set((selected || []).map(x => String(x)));
          if (!allClasses || allClasses.length === 0) {
            classesBox.innerHTML = '<div style="opacity:.86;">אין כיתות במערכת</div>';
            return;
          }
          classesBox.innerHTML = allClasses.map(cls => {
            const checked = sel.has(String(cls)) ? 'checked' : '';
            return `<label class="ck" style="display:flex;align-items:center;gap:5px;width:120px;"><input type="checkbox" value="${esc(cls)}" ${checked}/> ${esc(cls)}</label>`;
          }).join('');
        }

        async function load() {
          statusEl.textContent = 'טוען...';
          const q = encodeURIComponent(searchEl.value || '');
          const resp = await fetch('/api/teachers?q=' + q);
          const data = await resp.json();
          rowsEl.innerHTML = data.items.map(r => `
            <tr data-id="${r.id}" onclick="setSelected('${r.id}')" style="cursor:pointer; border-bottom:1px solid rgba(0,0,0,0.05);">
              <td class="cell" style="padding:10px;">${esc(r.name)}</td>
              <td class="cell ltr" style="padding:10px; text-align:left;">${esc(r.masked_card)}</td>
              <td class="cell" style="padding:10px;">${esc(r.role)}</td>
              <td class="cell" style="padding:10px;">${esc(r.classes_str)}</td>
              <td class="cell" style="padding:10px;">${esc(r.bonus_max_points_per_student ?? '')}</td>
              <td class="cell" style="padding:10px;">${esc(r.bonus_max_total_runs ?? '')}</td>
              <td class="cell" style="padding:10px;">${esc(r.bonus_runs_used_today_str ?? '')}</td>
              <td class="cell" style="padding:10px;">${esc(r.bonus_points_today ?? '')}</td>
            </tr>`).join('');
          statusEl.textContent = 'נטענו ' + data.items.length + ' מורים';
          setSelected(null);
        }

        async function save() {
            const payload = {
                teacher_id: mId.value ? parseInt(mId.value) : null,
                name: mName.value,
                card_number: mCard1.value,
                card_number2: mCard2.value,
                card_number3: mCard3.value,
                is_admin: mIsAdmin.checked ? 1 : 0,
                can_edit_student_card: mCanEditCard.checked ? 1 : 0,
                can_edit_student_photo: mCanEditPhoto.checked ? 1 : 0,
                bonus_max_points_per_student: mMaxPoints.value ? parseInt(mMaxPoints.value) : null,
                bonus_max_total_runs: mMaxRuns.value ? parseInt(mMaxRuns.value) : null
            };
            
            try {
                const resp = await fetch('/api/teachers/save', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                
                if (!resp.ok) {
                    alert('שגיאה בשמירה');
                    return;
                }
                
                const res = await resp.json();
                const newId = res.teacher_id;
                
                // Save classes
                const selClasses = [];
                classesBox.querySelectorAll('input[type="checkbox"]').forEach(cb => {
                    if (cb.checked) selClasses.push(cb.value);
                });
                
                await fetch('/api/teacher-classes/set', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ teacher_id: newId, classes: selClasses })
                });
                
                closeModal();
                load();
            } catch(e) {
                alert('שגיאה בתקשורת');
            }
        }

        async function delSelected() {
          if (!selectedId) return;
          if (!confirm('האם למחוק את המורה?')) return;
          
          try {
              const resp = await fetch('/api/teachers/delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ teacher_id: parseInt(selectedId) })
              });
              if (!resp.ok) {
                alert('שגיאה במחיקה');
                return;
              }
              load();
          } catch(e) {
              alert('שגיאה בתקשורת');
          }
        }

        async function openAdd() {
          modalTitle.textContent = 'הוספת מורה';
          mId.value = '';
          mName.value = '';
          mCard1.value = '';
          mCard2.value = '';
          mCard3.value = '';
          mIsAdmin.checked = false;
          mCanEditCard.checked = true;
          mCanEditPhoto.checked = true;
          mMaxPoints.value = '';
          mMaxRuns.value = '';
          const allClasses = await loadAllClasses();
          renderClasses(allClasses, []);
          openModal();
        }

        async function openEdit() {
          if (!selectedId) return;
          modalTitle.textContent = 'עריכת מורה ' + selectedId;
          try {
              const resp = await fetch('/api/teachers/' + selectedId);
              const t = await resp.json();
              
              mId.value = t.id;
              mName.value = t.name || '';
              mCard1.value = t.card_number || '';
              mCard2.value = t.card_number2 || '';
              mCard3.value = t.card_number3 || '';
              mIsAdmin.checked = !!t.is_admin;
              mCanEditCard.checked = !!t.can_edit_student_card;
              mCanEditPhoto.checked = !!t.can_edit_student_photo;
              mMaxPoints.value = t.bonus_max_points_per_student || '';
              mMaxRuns.value = t.bonus_max_total_runs || '';
              
              const allClasses = await loadAllClasses();
              renderClasses(allClasses, t.classes || []);
              
              openModal();
          } catch(e) {
              alert('שגיאה בטעינה');
          }
        }
        
        load();
    </script>
    """
    return basic_web_shell("ניהול מורים", html_content, request=request)

@router.get("/api/teachers")
def api_teachers_list(request: Request, q: str = "") -> Dict[str, Any]:
    guard = web_require_admin_teacher(request)
    if guard: raise HTTPException(status_code=401)
    
    tenant_id = web_tenant_from_cookie(request)
    conn = tenant_db_connection(tenant_id)
    try:
        cur = conn.cursor()
        q_str = str(q or '').strip()
        sql = "SELECT * FROM teachers"
        params = []
        if q_str:
            sql += " WHERE name LIKE ? OR card_number LIKE ?"
            p = f"%{q_str}%"
            params = [p, p]
        sql += " ORDER BY name LIMIT 100"
        
        cur.execute(sql_placeholder(sql), params)
        rows = cur.fetchall() or []
        
        items = []
        for r in rows:
            d = dict(r) if isinstance(r, dict) else {k: r[k] for k in r.keys()} if hasattr(r, 'keys') else {}
            # Mask card
            cn = str(d.get('card_number') or '')
            d['masked_card'] = (cn[:2] + '***' + cn[-2:]) if len(cn) > 4 else '***'
            d['role'] = 'מנהל' if d.get('is_admin') else 'מורה'
            
            # Fetch classes
            try:
                # Optimized: ideally join, but N+1 okay for 100 rows for now
                cur2 = conn.cursor()
                cur2.execute(sql_placeholder("SELECT class_name FROM teacher_classes WHERE teacher_id=?"), (d['id'],))
                res = cur2.fetchall()
                classes = [row[0] for row in res]
                d['classes_str'] = ", ".join(classes)
            except:
                d['classes_str'] = ""
                
            items.append(d)
            
        return {'items': items}
    finally:
        try: conn.close()
        except: pass

@router.get("/api/teachers/{teacher_id}")
def api_teacher_get(request: Request, teacher_id: int):
    guard = web_require_admin_teacher(request)
    if guard: raise HTTPException(status_code=401)
    
    tenant_id = web_tenant_from_cookie(request)
    conn = tenant_db_connection(tenant_id)
    try:
        cur = conn.cursor()
        cur.execute(sql_placeholder("SELECT * FROM teachers WHERE id = ?"), (teacher_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404)
        
        d = dict(row) if isinstance(row, dict) else {k: row[k] for k in row.keys()} if hasattr(row, 'keys') else {}
        
        # Classes
        cur.execute(sql_placeholder("SELECT class_name FROM teacher_classes WHERE teacher_id=?"), (teacher_id,))
        d['classes'] = [r[0] for r in cur.fetchall()]
        
        return d
    finally:
        try: conn.close()
        except: pass

@router.post("/api/teachers/save")
def api_teacher_save(request: Request, payload: TeacherSavePayload):
    guard = web_require_admin_teacher(request)
    if guard: raise HTTPException(status_code=401)
    
    tenant_id = web_tenant_from_cookie(request)
    conn = tenant_db_connection(tenant_id)
    try:
        cur = conn.cursor()
        
        cols = payload.dict(exclude_unset=True)
        tid = cols.pop('teacher_id', None)
        
        if not tid:
            # Insert
            # Get max ID manually for numeric ID consistency if SQLite
            # Actually, standard autoincrement or serial is fine, but for teachers we usually want stable IDs.
            # Let's rely on DB autoincrement for simplicity, or max+1 strategy if we want to mimic legacy.
            
            columns = list(cols.keys())
            placeholders = ','.join(['?' for _ in columns])
            sql = f"INSERT INTO teachers ({','.join(columns)}) VALUES ({placeholders})"
            if USE_POSTGRES:
                sql = sql.replace('?', '%s') + " RETURNING id"
                cur.execute(sql, list(cols.values()))
                row = cur.fetchone()
                tid = row['id'] if isinstance(row, dict) else row[0]
            else:
                cur.execute(sql, list(cols.values()))
                tid = cur.lastrowid
                
            record_sync_event(
                tenant_id=tenant_id,
                station_id='web',
                entity_type='teachers',
                entity_id=str(tid),
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
            vals.append(tid)
            
            sql = f"UPDATE teachers SET {','.join(sets)} WHERE id = ?"
            cur.execute(sql_placeholder(sql), vals)
            
            record_sync_event(
                tenant_id=tenant_id,
                station_id='web',
                entity_type='teachers',
                entity_id=str(tid),
                action_type='update',
                payload=cols
            )
            
        conn.commit()
        return {'ok': True, 'teacher_id': tid}
    finally:
        try: conn.close()
        except: pass

@router.post("/api/teacher-classes/set")
def api_teacher_classes_set(request: Request, payload: TeacherClassesPayload):
    guard = web_require_admin_teacher(request)
    if guard: raise HTTPException(status_code=401)
    
    tenant_id = web_tenant_from_cookie(request)
    conn = tenant_db_connection(tenant_id)
    try:
        cur = conn.cursor()
        
        # Replace classes
        cur.execute(sql_placeholder("DELETE FROM teacher_classes WHERE teacher_id = ?"), (payload.teacher_id,))
        
        if payload.classes:
            sql = "INSERT INTO teacher_classes (teacher_id, class_name) VALUES (?, ?)"
            if USE_POSTGRES:
                sql = sql.replace('?', '%s')
                import psycopg2.extras
                psycopg2.extras.execute_batch(cur, sql, [(payload.teacher_id, c) for c in payload.classes])
            else:
                cur.executemany(sql, [(payload.teacher_id, c) for c in payload.classes])
                
        conn.commit()
        
        # Record sync event for classes? Usually teachers update covers it or separate event.
        # Let's record a custom event for classes update
        record_sync_event(
            tenant_id=tenant_id,
            station_id='web',
            entity_type='teacher_classes',
            entity_id=str(payload.teacher_id),
            action_type='replace',
            payload={'classes': payload.classes}
        )
        
        return {'ok': True}
    finally:
        try: conn.close()
        except: pass

@router.post("/api/teachers/delete")
def api_teacher_delete(request: Request, payload: TeacherDeletePayload):
    guard = web_require_admin_teacher(request)
    if guard: raise HTTPException(status_code=401)
    
    tenant_id = web_tenant_from_cookie(request)
    conn = tenant_db_connection(tenant_id)
    try:
        cur = conn.cursor()
        cur.execute(sql_placeholder("DELETE FROM teacher_classes WHERE teacher_id = ?"), (payload.teacher_id,))
        cur.execute(sql_placeholder("DELETE FROM teachers WHERE id = ?"), (payload.teacher_id,))
        conn.commit()
        
        record_sync_event(
            tenant_id=tenant_id,
            station_id='web',
            entity_type='teachers',
            entity_id=str(payload.teacher_id),
            action_type='delete',
            payload={}
        )
        
        return {'ok': True}
    finally:
        try: conn.close()
        except: pass
