from fastapi import APIRouter, Request, HTTPException, Body
from fastapi.responses import HTMLResponse
from typing import Dict, Any, List
import json

from ..ui import basic_web_shell
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
                <div style="display:flex; gap:10px; flex-wrap:wrap;">
                    <button class="blue" onclick="openAdd()" id="btn-add">➕ תלמיד חדש</button>
                    <button style="background:#e67e22;color:#fff;border:none;padding:10px 14px;border-radius:10px;font-weight:900;cursor:pointer;" onclick="openBulk()">⚡ עדכון מהיר</button>
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
                        <button id="s_qpoints" class="green" style="font-size:12px; padding:4px 10px; background:#27ae60; color:white; border:none; border-radius:4px; opacity:0.5; pointer-events:none;" onclick="openQuickPoints()">⚡ עדכון נקודות</button>
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
                                <th style="padding:12px;">תיקוף אחרון</th>
                                <th style="padding:12px;">יום הולדת</th>
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

        <!-- Quick Points Modal -->
        <div id="qp_modal" class="modal-overlay">
            <div class="modal-content" style="max-width:380px;">
                <button class="modal-close" onclick="closeQP()">×</button>
                <h3 style="margin-top:0;">⚡ עדכון נקודות מהיר</h3>
                <div id="qp_info" style="margin-bottom:12px; font-size:14px; color:#666;"></div>
                <div class="form-group" style="margin-bottom:12px;">
                    <label>שינוי נקודות (מספר חיובי להוסיף, שלילי להוריד)</label>
                    <input type="number" id="qp_delta" class="form-input" value="0" style="font-size:18px; text-align:center;">
                </div>
                <div class="form-group" style="margin-bottom:12px;">
                    <label>סיבה (אופציונלי)</label>
                    <input id="qp_reason" class="form-input" placeholder="למשל: בונוס, תיקון...">
                </div>
                <div style="display:flex; gap:8px; justify-content:center; margin-bottom:10px;">
                    <button onclick="qpSet(-10)" style="padding:6px 14px; border:1px solid #e74c3c; background:#fff; color:#e74c3c; border-radius:6px; cursor:pointer; font-weight:bold;">-10</button>
                    <button onclick="qpSet(-5)" style="padding:6px 14px; border:1px solid #e74c3c; background:#fff; color:#e74c3c; border-radius:6px; cursor:pointer; font-weight:bold;">-5</button>
                    <button onclick="qpSet(-1)" style="padding:6px 14px; border:1px solid #e74c3c; background:#fff; color:#e74c3c; border-radius:6px; cursor:pointer; font-weight:bold;">-1</button>
                    <button onclick="qpSet(1)" style="padding:6px 14px; border:1px solid #27ae60; background:#fff; color:#27ae60; border-radius:6px; cursor:pointer; font-weight:bold;">+1</button>
                    <button onclick="qpSet(5)" style="padding:6px 14px; border:1px solid #27ae60; background:#fff; color:#27ae60; border-radius:6px; cursor:pointer; font-weight:bold;">+5</button>
                    <button onclick="qpSet(10)" style="padding:6px 14px; border:1px solid #27ae60; background:#fff; color:#27ae60; border-radius:6px; cursor:pointer; font-weight:bold;">+10</button>
                </div>
                <div style="display:flex; justify-content:flex-end; gap:10px; margin-top:16px;">
                    <button class="btn-gray" onclick="closeQP()">ביטול</button>
                    <button class="btn-primary" style="background:#27ae60;" onclick="submitQP()">עדכן</button>
                </div>
            </div>
        </div>

        <!-- Modal -->
        <div id="s_modal" class="modal-overlay">
            <div class="modal-content" style="max-width:600px;">
                <button class="modal-close" onclick="closeModal()">×</button>
                <h3 id="s_modal_title" style="margin-top:0;">עריכת תלמיד</h3>
                <input type="hidden" id="m_student_id">
                <div style="max-height:65vh;overflow-y:auto;">
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
                  <div class="form-group"><label>שם פרטי</label><input id="m_first_name" class="form-input"></div>
                  <div class="form-group"><label>שם משפחה</label><input id="m_last_name" class="form-input"></div>
                </div>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
                  <div class="form-group"><label>כיתה</label><input id="m_class_name" class="form-input"></div>
                  <div class="form-group"><label>ת"ז</label><input id="m_id_number" class="form-input"></div>
                </div>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
                  <div class="form-group"><label>מס' כרטיס</label><input id="m_card_number" class="form-input"></div>
                  <div class="form-group"><label>מס' סידורי</label><input type="number" id="m_serial_number" class="form-input"></div>
                </div>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
                  <div class="form-group"><label>נקודות</label><input type="number" id="m_points" class="form-input"></div>
                  <div class="form-group"><label>מס'/נתיב תמונה</label><input id="m_photo_number" class="form-input"></div>
                </div>
                <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;">
                  <div class="form-group"><label>מגדר</label><select id="m_gender" class="form-input"><option value="">—</option><option value="M">בן</option><option value="F">בת</option></select></div>
                  <div class="form-group"><label>יום (עברי)</label><select id="m_hb_day" class="form-input"><option value="">—</option></select></div>
                  <div class="form-group"><label>חודש (עברי)</label><select id="m_hb_month" class="form-input"><option value="">—</option><option value="7">תשרי</option><option value="8">חשון</option><option value="9">כסלו</option><option value="10">טבת</option><option value="11">שבט</option><option value="12">אדר</option><option value="13">אדר ב'</option><option value="1">ניסן</option><option value="2">אייר</option><option value="3">סיון</option><option value="4">תמוז</option><option value="5">אב</option><option value="6">אלול</option></select></div>
                </div>
                <div class="form-group"><label>הודעה פרטית</label><input id="m_private_message" class="form-input"></div>
                <label style="display:flex;align-items:center;gap:8px;margin-top:8px;"><input type="checkbox" id="m_is_free_fix_blocked" style="width:18px;height:18px;"> חסום לתיקון חופשי</label>
                </div>
                <div style="margin-top:16px;display:flex;justify-content:flex-end;gap:10px;">
                    <button class="btn-gray" onclick="closeModal()">ביטול</button>
                    <button class="btn-primary" onclick="save()">שמירה</button>
                </div>
            </div>
        </div>

        <!-- Bulk Quick Update Modal -->
        <div id="bulk_modal" class="modal-overlay">
            <div class="modal-content" style="max-width:480px;">
                <button class="modal-close" onclick="closeBulk()">×</button>
                <h3 style="margin-top:0;">⚡ עדכון מהיר (מרובה)</h3>
                <div class="form-group" style="margin-bottom:10px;"><label>מצב</label>
                  <select id="bk_mode" class="form-input" onchange="bkModeChanged()"><option value="class">לפי כיתה</option><option value="all_school">כל בית הספר</option><option value="serial_range">לפי טווח סידורי</option></select></div>
                <div id="bk_class_row" class="form-group" style="margin-bottom:10px;"><label>כיתה</label><select id="bk_class" class="form-input"></select></div>
                <div id="bk_serial_row" style="display:none;margin-bottom:10px;"><div style="display:flex;gap:10px;">
                  <div class="form-group" style="flex:1;"><label>מסידורי</label><input type="number" id="bk_from" class="form-input"></div>
                  <div class="form-group" style="flex:1;"><label>עד סידורי</label><input type="number" id="bk_to" class="form-input"></div>
                </div></div>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px;">
                  <div class="form-group"><label>פעולה</label><select id="bk_op" class="form-input"><option value="add">הוסף (+)</option><option value="subtract">הורד (−)</option><option value="set">קבע (=)</option></select></div>
                  <div class="form-group"><label>נקודות</label><input type="number" id="bk_pts" class="form-input" min="0" value="0"></div>
                </div>
                <div class="form-group" style="margin-bottom:10px;"><label>סיבה</label><input id="bk_reason" class="form-input" placeholder="למשל: בונוס שבועי"></div>
                <div id="bk_status" style="margin-bottom:10px;font-size:13px;color:#e67e22;"></div>
                <div style="display:flex;justify-content:flex-end;gap:10px;">
                  <button class="btn-gray" onclick="closeBulk()">ביטול</button>
                  <button class="btn-primary" style="background:#e67e22;" onclick="submitBulk()">⚡ עדכן</button>
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
            const btnQP = document.getElementById('s_qpoints');
            const modal = document.getElementById('s_modal');
            const qpModal = document.getElementById('qp_modal');
            
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
            const mSerial = document.getElementById('m_serial_number');
            const mPhoto = document.getElementById('m_photo_number');
            const mGender = document.getElementById('m_gender');
            const mHbDay = document.getElementById('m_hb_day');
            const mHbMonth = document.getElementById('m_hb_month');
            const bulkModal = document.getElementById('bulk_modal');
            // Populate hebrew days 1-30
            for(let i=1;i<=30;i++){const o=document.createElement('option');o.value=i;o.textContent=i;mHbDay.appendChild(o);}

            function esc(s) {
                return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
            }
            function fmtDate(d) {
                if (!d) return '-';
                try { return d.replace('T',' ').substring(0,16); } catch(e) { return d; }
            }
            const hMonths = ['','תשרי','חשון','כסלו','טבת','שבט','אדר','ניסן','אייר','סיון','תמוז','אב','אלול'];
            function fmtBday(s) {
                if (!s.hebrew_birth_day && !s.hebrew_birth_month) return '-';
                let d = s.hebrew_birth_day || '?';
                let m = hMonths[s.hebrew_birth_month] || '?';
                return d + ' ' + m;
            }

            function setSelected(id) {
                selectedId = id;
                const on = (selectedId !== null);
                btnEdit.style.opacity = on ? '1' : '0.5';
                btnEdit.style.pointerEvents = on ? 'auto' : 'none';
                btnDelete.style.opacity = on ? '1' : '0.5';
                btnDelete.style.pointerEvents = on ? 'auto' : 'none';
                btnQP.style.opacity = on ? '1' : '0.5';
                btnQP.style.pointerEvents = on ? 'auto' : 'none';
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
                        rowsEl.innerHTML = '<tr><td colspan="10" style="padding:20px; text-align:center;">לא נמצאו תלמידים</td></tr>';
                        statusEl.textContent = '0 תלמידים';
                        return;
                    }
                    
                    _allStudents = data.items;
                    statusEl.textContent = data.items.length + ' תלמידים';
                    
                    rowsEl.innerHTML = data.items.map(s => `
                        <tr data-id="${s.id}" onclick="setSelected(${s.id})" style="border-bottom:1px solid rgba(255,255,255,0.05); cursor:pointer;">
                            <td style="padding:12px; opacity:0.7;">${s.id}</td>
                            <td style="padding:12px; font-weight:bold;">${esc(s.last_name)}</td>
                            <td style="padding:12px;">${esc(s.first_name)}</td>
                            <td style="padding:12px;">${esc(s.class_name)}</td>
                            <td style="padding:12px; color:#2ecc71; font-weight:bold;">${s.points}</td>
                            <td style="padding:12px; font-size:12px;">${fmtDate(s.last_swiped_at)}</td>
                            <td style="padding:12px; font-size:12px;">${fmtBday(s)}</td>
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
                mSerial.value = '';
                mPhoto.value = '';
                mGender.value = '';
                mHbDay.value = '';
                mHbMonth.value = '';
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
                    mSerial.value = s.serial_number || '';
                    mPhoto.value = s.photo_number || '';
                    mGender.value = s.gender || '';
                    mHbDay.value = s.hebrew_birth_day || '';
                    mHbMonth.value = s.hebrew_birth_month || '';
                    
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
                    is_free_fix_blocked: mBlock.checked ? 1 : 0,
                    serial_number: mSerial.value || null,
                    photo_number: mPhoto.value || null,
                    gender: mGender.value || null,
                    hebrew_birth_day: mHbDay.value ? parseInt(mHbDay.value) : null,
                    hebrew_birth_month: mHbMonth.value ? parseInt(mHbMonth.value) : null
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

            // Quick Points
            let _allStudents = [];
            function openQuickPoints() {
                if (!selectedId) return;
                const s = _allStudents.find(x => x.id == selectedId);
                if (!s) return;
                document.getElementById('qp_info').textContent = s.first_name + ' ' + s.last_name + ' — נקודות נוכחיות: ' + (s.points || 0);
                document.getElementById('qp_delta').value = 0;
                document.getElementById('qp_reason').value = '';
                qpModal.style.display = 'flex';
                document.getElementById('qp_delta').focus();
            }
            function closeQP() { qpModal.style.display = 'none'; }
            function qpSet(v) {
                const el = document.getElementById('qp_delta');
                el.value = parseInt(el.value || 0) + v;
            }
            async function submitQP() {
                const delta = parseInt(document.getElementById('qp_delta').value || 0);
                if (delta === 0) { alert('נא להזין מספר שונה מאפס'); return; }
                const reason = document.getElementById('qp_reason').value.trim();
                try {
                    const resp = await fetch('/api/students/quick-points', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({student_id: selectedId, delta: delta, reason: reason})
                    });
                    if (!resp.ok) { alert('שגיאה בעדכון'); return; }
                    closeQP();
                    load();
                } catch(e) { alert('שגיאה: ' + e); }
            }

            // Bulk Quick Update
            function openBulk() {
                bulkModal.style.display='flex';
                document.getElementById('bk_status').textContent='';
                // populate class dropdown from loaded students
                const classes = [...new Set(_allStudents.map(s=>s.class_name).filter(Boolean))].sort();
                const sel = document.getElementById('bk_class');
                sel.innerHTML = classes.map(c=>'<option value="'+esc(c)+'">'+esc(c)+'</option>').join('');
                bkModeChanged();
            }
            function closeBulk() { bulkModal.style.display='none'; }
            function bkModeChanged() {
                const m = document.getElementById('bk_mode').value;
                document.getElementById('bk_class_row').style.display = m==='class'?'block':'none';
                document.getElementById('bk_serial_row').style.display = m==='serial_range'?'block':'none';
            }
            async function submitBulk() {
                const mode = document.getElementById('bk_mode').value;
                const op = document.getElementById('bk_op').value;
                const pts = parseInt(document.getElementById('bk_pts').value)||0;
                const reason = document.getElementById('bk_reason').value.trim();
                if(pts===0){alert('נא להזין מספר נקודות');return;}
                const body = {operation:op, points:pts, mode:mode, reason:reason||'עדכון מהיר מהאתר'};
                if(mode==='class') body.class_names=[document.getElementById('bk_class').value];
                if(mode==='serial_range'){body.serial_from=parseInt(document.getElementById('bk_from').value)||0;body.serial_to=parseInt(document.getElementById('bk_to').value)||0;}
                document.getElementById('bk_status').textContent='מעדכן...';
                try {
                    const r = await fetch('/api/students/bulk-quick-update',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
                    const d = await r.json();
                    if(d.ok){document.getElementById('bk_status').textContent='עודכנו '+d.updated+' תלמידים';setTimeout(()=>{closeBulk();load();},1200);}
                    else{document.getElementById('bk_status').textContent='שגיאה: '+(d.detail||'');}
                } catch(e){document.getElementById('bk_status').textContent='שגיאה: '+e;}
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
        sql = "SELECT id, first_name, last_name, class_name, points, private_message, card_number, id_number, is_free_fix_blocked, last_swiped_at, hebrew_birth_day, hebrew_birth_month, hebrew_birth_year, gender, serial_number, photo_number FROM students"
        params = []
        if q_str:
            sql += " WHERE (first_name LIKE ? OR last_name LIKE ? OR card_number LIKE ? OR class_name LIKE ? OR id_number LIKE ?)"
            p = f"%{q_str}%"
            params = [p, p, p, p, p]
        
        sql += " ORDER BY class_name, last_name"
        
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
            'is_free_fix_blocked': payload.is_free_fix_blocked if payload.is_free_fix_blocked is not None else 0,
            'serial_number': payload.serial_number,
            'photo_number': payload.photo_number,
            'hebrew_birth_day': payload.hebrew_birth_day,
            'hebrew_birth_month': payload.hebrew_birth_month,
            'hebrew_birth_year': payload.hebrew_birth_year,
            'gender': payload.gender,
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
                entity_type='student',
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
                entity_type='student',
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
            entity_type='student',
            entity_id=str(sid),
            action_type='delete',
            payload={}
        )
        
        return {'ok': True}
    finally:
        try: conn.close()
        except: pass

@router.post("/api/students/quick-points")
def api_student_quick_points(request: Request, payload: Dict[str, Any] = Body(...)):
    guard = web_require_teacher(request)
    if guard: raise HTTPException(status_code=401, detail="Unauthorized")

    tenant_id = web_tenant_from_cookie(request)
    if not tenant_id: raise HTTPException(status_code=400, detail="Missing tenant")

    sid = int(payload.get('student_id') or 0)
    delta = int(payload.get('delta') or 0)
    reason = str(payload.get('reason') or '').strip()
    if sid <= 0 or delta == 0:
        raise HTTPException(status_code=400, detail="Invalid student_id or delta")

    conn = tenant_db_connection(tenant_id)
    try:
        cur = conn.cursor()
        cur.execute(sql_placeholder("SELECT id, points FROM students WHERE id = ? LIMIT 1"), (sid,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Student not found")
        old_points = int((row['points'] if isinstance(row, dict) else row[1]) or 0)
        new_points = old_points + delta

        cur.execute(sql_placeholder("UPDATE students SET points = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?"), (new_points, sid))

        # Log to points_log if table exists
        try:
            if USE_POSTGRES:
                cur.execute(
                    "INSERT INTO points_log (student_id, points_change, reason, source, created_at) VALUES (%s,%s,%s,%s,CURRENT_TIMESTAMP)",
                    (sid, delta, reason or 'עדכון מהיר מהאתר', 'web')
                )
            else:
                cur.execute(
                    "INSERT INTO points_log (student_id, points_change, reason, source, created_at) VALUES (?,?,?,?,datetime('now'))",
                    (sid, delta, reason or 'עדכון מהיר מהאתר', 'web')
                )
        except Exception:
            pass

        conn.commit()

        record_sync_event(
            tenant_id=tenant_id,
            station_id='web',
            entity_type='student_points',
            entity_id=str(sid),
            action_type='update',
            payload={'student_id': sid, 'old_points': old_points, 'new_points': new_points, 'delta': delta, 'reason': reason or 'עדכון מהיר מהאתר'}
        )

        return {'ok': True, 'new_points': new_points}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        try: conn.close()
        except: pass
