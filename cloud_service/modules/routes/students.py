from fastapi import APIRouter, Request, HTTPException, Body
from fastapi.responses import HTMLResponse
from typing import Dict, Any, List
import json

from ..ui import basic_web_shell
from ..auth import web_require_teacher, web_tenant_from_cookie, safe_int, web_current_teacher
from ..db import tenant_db_connection, sql_placeholder, table_columns, insert_points_log
from ..config import USE_POSTGRES
from ..models import StudentSavePayload, StudentDeletePayload, StudentManualArrivalPayload
from ..sync_logic import record_sync_event, apply_change_to_tenant_db

router = APIRouter()


def _fmt_rel_update(dt_str, delta=None):
    """Format like the desktop app: 'היום 11:28 +5' / 'אתמול 17:48' / '17.2 14:30'."""
    if not dt_str:
        return ''
    try:
        from datetime import datetime, date, timezone
        try:
            from zoneinfo import ZoneInfo
            _tz = ZoneInfo('Asia/Jerusalem')
        except Exception:
            _tz = timezone.utc
        dt_utc = datetime.strptime(str(dt_str).replace('T', ' ')[:19], '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
        dt = dt_utc.astimezone(_tz).replace(tzinfo=None)
        today = datetime.now(_tz).date()
        t = dt.strftime('%H:%M')
        if dt.date() == today:
            pre = f'היום {t}'
        elif (today - dt.date()).days == 1:
            pre = f'אתמול {t}'
        elif (today - dt.date()).days == 2:
            pre = f'שלשום {t}'
        else:
            pre = f'{dt.day}.{dt.month} {t}'
        if delta is not None and int(delta) != 0:
            sign = '+' if int(delta) > 0 else ''
            return f'{pre} {sign}{int(delta)}'
        return pre
    except Exception:
        return str(dt_str)[:16]

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
        <style>
        .stu-toolbar {
            position: sticky;
            top: 64px;
            z-index: 50;
            background: rgba(15, 32, 39, 0.95);
            backdrop-filter: blur(12px);
            border-bottom: 1px solid rgba(255,255,255,0.1);
            padding: 10px 14px;
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
            align-items: center;
            justify-content: space-between;
            margin: -24px -24px 14px -24px;
        }
        .stu-toolbar-left, .stu-toolbar-right { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
        .stu-btn {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 8px 14px;
            border-radius: 8px;
            border: 0;
            font-weight: 800;
            font-size: 13px;
            cursor: pointer;
            color: #fff;
            transition: transform .1s, filter .1s;
        }
        .stu-btn:hover { transform: translateY(-1px); filter: brightness(1.1); }
        .stu-btn:disabled { opacity: .4; pointer-events: none; }
        .stu-btn-blue { background: #3498db; }
        .stu-btn-green { background: #27ae60; }
        .stu-btn-orange { background: #e67e22; }
        .stu-btn-red { background: #e74c3c; }
        .stu-btn-purple { background: #9b59b6; }
        .stu-btn-gray { background: #7f8c8d; }
        .stu-search { flex:1; min-width:220px; max-width:420px; }
        .stu-search input { width:100%; padding:8px 12px; border-radius:8px; border:1px solid rgba(255,255,255,0.15); background:rgba(0,0,0,0.25); color:#fff; font-size:14px; }
        .stu-search input::placeholder { color: rgba(255,255,255,0.5); }
        .stu-table-wrap { background:#fff; border-radius:0 0 12px 12px; overflow:hidden; border:1px solid rgba(0,0,0,0.08); box-shadow:0 4px 14px rgba(0,0,0,0.08); }
        .stu-table-wrap table { width:100%; border-collapse:collapse; font-size:13px; }
        .stu-table-wrap th { background: linear-gradient(135deg, #2c3e50, #34495e); color:#fff; padding:10px 8px; font-weight:800; text-align:right; white-space:nowrap; position: sticky; top: 0; }
        .stu-table-wrap td { padding:8px; border-bottom:1px solid rgba(0,0,0,0.06); color:#1f2d3a; vertical-align:middle; }
        .stu-table-wrap tr:nth-child(even) { background: #f8f9fa; }
        .stu-table-wrap tr:hover { background: #e8f4f8; }
        .stu-table-wrap tr.selected { background: #d6eaf8 !important; }
        .stu-points { color:#27ae60; font-weight:900; cursor:pointer; }
        .stu-points:hover { text-decoration: underline; }
        .stu-small { font-size:12px; opacity:.85; }
        .stu-num { direction:ltr; text-align:right; font-family: monospace; }
        </style>
        <div>
            <div class="stu-toolbar">
                <div class="stu-toolbar-left">
                    <button class="stu-btn stu-btn-green" onclick="openAdd()">➕ תלמיד חדש</button>
                    <button class="stu-btn stu-btn-orange" onclick="openBulk()">⚡ עדכון מהיר</button>
                    <button class="stu-btn stu-btn-blue" onclick="openQuickPoints()" id="s_qpoints" disabled>⚡ נקודות לנבחר</button>
                    <button class="stu-btn stu-btn-purple" onclick="openEdit()" id="s_edit" disabled>✏️ ערוך</button>
                    <button class="stu-btn stu-btn-red" onclick="delSelected()" id="s_delete" disabled>🗑 מחק</button>
                </div>
                <div class="stu-toolbar-right">
                    <select id="s_class_filter" onchange="renderRows()" style="padding:8px 10px;border-radius:8px;border:1px solid rgba(255,255,255,0.15);background:rgba(0,0,0,0.25);color:#fff;font-size:14px;max-width:150px;">
                        <option value="">כל הכיתות</option>
                    </select>
                    <div class="stu-search"><input type="text" id="s_search" placeholder="חיפוש לפי שם, ת&quot;ז, כיתה..." onkeyup="if(event.key==='Enter') load()"></div>
                    <button class="stu-btn stu-btn-gray" onclick="load()">� רענן</button>
                    <button class="stu-btn stu-btn-purple" onclick="toggleColPanel()">📋 עמודות</button>
                </div>
            </div>

            <div id="col_panel" style="display:none; padding:10px; background:rgba(255,255,255,0.08); border-radius:8px; margin-bottom:12px; flex-wrap:wrap; gap:12px; align-items:center;">
                <span style="font-weight:800; color:#fff;">עמודות:</span>
                <label style="font-size:13px; color:#fff;"><input type="checkbox" id="col_class" checked onchange="applyColVis()"> כיתה</label>
                <label style="font-size:13px; color:#fff;"><input type="checkbox" id="col_points" checked onchange="applyColVis()"> נקודות</label>
                <label style="font-size:13px; color:#fff;"><input type="checkbox" id="col_upd" checked onchange="applyColVis()"> עדכון אחרון</label>
                <label style="font-size:13px; color:#fff;"><input type="checkbox" id="col_swipe" checked onchange="applyColVis()"> תיקוף אחרון</label>
                <label style="font-size:13px; color:#fff;"><input type="checkbox" id="col_swtot" checked onchange="applyColVis()"> סה"כ תיקופים</label>
                <label style="font-size:13px; color:#fff;"><input type="checkbox" id="col_swavg" checked onchange="applyColVis()"> ממוצע תיקופים</label>
                <label style="font-size:13px; color:#fff;"><input type="checkbox" id="col_gender" onchange="applyColVis()"> מגדר</label>
                <label style="font-size:13px; color:#fff;"><input type="checkbox" id="col_bday" checked onchange="applyColVis()"> יום הולדת</label>
                <label style="font-size:13px; color:#fff;"><input type="checkbox" id="col_msg" checked onchange="applyColVis()"> הודעה פרטית</label>
                <label style="font-size:13px; color:#fff;"><input type="checkbox" id="col_card" checked onchange="applyColVis()"> מס' כרטיס</label>
                <label style="font-size:13px; color:#fff;"><input type="checkbox" id="col_idnum" onchange="applyColVis()"> ת"ז</label>
                <label style="font-size:13px; color:#fff;"><input type="checkbox" id="col_serial" checked onchange="applyColVis()"> מס' סידורי</label>
                <label style="font-size:13px; color:#fff;"><input type="checkbox" id="col_photo" onchange="applyColVis()"> תמונה</label>
            </div>

            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; flex-wrap:wrap; gap:8px; color:#fff;">
                <div id="s_status" style="font-size:13px; font-weight:bold; opacity:0.8;">טוען...</div>
                <div id="s_selected" style="font-size:13px;">לא נבחר תלמיד</div>
            </div>

            <div class="stu-table-wrap">
                <div class="table-scroll" style="max-height:68vh;">
                    <table id="s_table">
                        <thead>
                            <tr>
                                <th onclick="sortBy('first_name')" style="cursor:pointer;"><span id="sh_first_name">שם פרטי</span></th>
                                <th onclick="sortBy('last_name')" style="cursor:pointer;"><span id="sh_last_name">שם משפחה</span></th>
                                <th class="col_class" onclick="sortBy('class_name')" style="cursor:pointer; width:70px;"><span id="sh_class_name">כיתה</span></th>
                                <th class="col_points" onclick="sortBy('points')" style="cursor:pointer; width:70px;"><span id="sh_points">נקודות</span></th>
                                <th class="col_upd" style="width:110px;">עדכון אחרון</th>
                                <th class="col_swipe" onclick="sortBy('last_swiped_at')" style="cursor:pointer; width:110px;"><span id="sh_last_swiped_at">תיקוף אחרון</span></th>
                                <th class="col_swtot" style="width:70px;">סה"כ תיקופים</th>
                                <th class="col_swavg" style="width:80px;">ממוצע תיקופים</th>
                                <th class="col_gender" style="width:50px;">מגדר</th>
                                <th class="col_bday" style="width:100px;">יום הולדת</th>
                                <th class="col_msg" onclick="sortBy('private_message')" style="cursor:pointer;"><span id="sh_private_message">הודעה פרטית</span></th>
                                <th class="col_card" style="width:110px;">מס' כרטיס</th>
                                <th class="col_idnum" style="width:110px;">ת"ז</th>
                                <th class="col_serial" onclick="sortBy('serial_number')" style="cursor:pointer; width:80px;"><span id="sh_serial_number">מס' סידורי</span></th>
                                <th class="col_photo" style="width:70px;">תמונה</th>
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
                <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:10px;">
                  <div class="form-group"><label>מגדר</label><select id="m_gender" class="form-input"><option value="">—</option><option value="M">בן</option><option value="F">בת</option></select></div>
                  <div class="form-group"><label>יום (עברי)</label><select id="m_hb_day" class="form-input"><option value="">—</option></select></div>
                  <div class="form-group"><label>חודש (עברי)</label><select id="m_hb_month" class="form-input"><option value="">—</option><option value="7">תשרי</option><option value="8">חשון</option><option value="9">כסלו</option><option value="10">טבת</option><option value="11">שבט</option><option value="12">אדר</option><option value="13">אדר ב'</option><option value="1">ניסן</option><option value="2">אייר</option><option value="3">סיון</option><option value="4">תמוז</option><option value="5">אב</option><option value="6">אלול</option></select></div>
                  <div class="form-group"><label>שנה (עברי)</label><input type="number" id="m_hb_year" class="form-input" placeholder="לדוג' 5786"></div>
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
            let _sortCol = null, _sortDir = 1;  // null = server order (serial, class, name)
            const rowsEl = document.getElementById('s_rows');
            const statusEl = document.getElementById('s_status');
            const searchEl = document.getElementById('s_search');
            const selectedEl = document.getElementById('s_selected');
            const btnEdit = document.getElementById('s_edit');
            const btnDelete = document.getElementById('s_delete');
            const btnQP = document.getElementById('s_qpoints');
            const modal = document.getElementById('s_modal');
            const qpModal = document.getElementById('qp_modal');

            function toggleColPanel() {
                const p = document.getElementById('col_panel');
                p.style.display = p.style.display === 'none' ? 'flex' : 'none';
            }
            function applyColVis() {
                const map = {col_class:'col_class',col_points:'col_points',col_upd:'col_upd',col_swipe:'col_swipe',col_swtot:'col_swtot',col_swavg:'col_swavg',col_gender:'col_gender',col_bday:'col_bday',col_msg:'col_msg',col_card:'col_card',col_idnum:'col_idnum',col_serial:'col_serial',col_photo:'col_photo'};
                for (const [cbId, cls] of Object.entries(map)) {
                    const cb = document.getElementById(cbId);
                    if (!cb) continue;
                    const show = cb.checked;
                    document.querySelectorAll('.'+cls).forEach(el => el.style.display = show ? '' : 'none');
                }
            }
            function sortBy(col) {
                if (_sortCol === col) _sortDir = -_sortDir;
                else { _sortCol = col; _sortDir = 1; }
                // Update header arrows
                ['first_name','last_name','class_name','points','last_swiped_at','private_message','serial_number'].forEach(c => {
                    const el = document.getElementById('sh_'+c);
                    if (el) el.textContent = el.textContent.replace(/ [▲▼]$/,'');
                });
                const hel = document.getElementById('sh_'+col);
                if (hel) hel.textContent = hel.textContent + (_sortDir===1?' ▲':' ▼');
                renderRows();
            }
            function renderRows() {
                if (!_allStudents || !_allStudents.length) { rowsEl.innerHTML=''; return; }
                const clsF = document.getElementById('s_class_filter').value;
                const pool = clsF ? _allStudents.filter(s => String(s.class_name||'') === clsF) : _allStudents;
                const sorted = _sortCol ? [...pool].sort((a,b) => {
                    let va = a[_sortCol], vb = b[_sortCol];
                    if (va == null) va = ''; if (vb == null) vb = '';
                    if (_sortCol === 'serial_number' || _sortCol === 'swipe_total' || _sortCol === 'swipe_avg') return _sortDir * ((parseFloat(va)||0) - (parseFloat(vb)||0));
                    if (typeof va === 'number' && typeof vb === 'number') return _sortDir*(va-vb);
                    return _sortDir * String(va).localeCompare(String(vb), 'he');
                }) : pool;
                rowsEl.innerHTML = sorted.map((s,i) => `
                    <tr data-id="${s.id}" onclick="setSelected(${s.id})" class="${selectedId == s.id ? 'selected' : ''}">
                        <td style="font-weight:700;">${esc(s.first_name)}</td>
                        <td>${esc(s.last_name)}</td>
                        <td class="col_class" style="text-align:center;">${esc(s.class_name)}</td>
                        <td class="col_points stu-points" title="לחץ פעמיים לעריכה" ondblclick="editPoints(event, ${s.id}, ${s.points})">${s.points}</td>
                        <td class="col_upd stu-small" style="text-align:center;">${esc(s.last_update || '')}</td>
                        <td class="col_swipe stu-small" style="direction:ltr; text-align:right;">${fmtDate(s.last_swiped_at)}</td>
                        <td class="col_swtot stu-small" style="text-align:center;">${s.swipe_total || 0}</td>
                        <td class="col_swavg stu-small" style="text-align:center;">${s.swipe_avg || 0}</td>
                        <td class="col_gender stu-small" style="text-align:center;">${esc(s.gender || '')}</td>
                        <td class="col_bday stu-small" style="text-align:center;">${fmtBday(s)}</td>
                        <td class="col_msg stu-small stu-points" title="לחץ פעמיים לעריכה" ondblclick="editMsg(event, ${s.id})">${esc(stripMsg(s.private_message))}</td>
                        <td class="col_card stu-num">${esc(s.card_number)}</td>
                        <td class="col_idnum stu-num">${esc(s.id_number)}</td>
                        <td class="col_serial stu-num" style="text-align:center;">${esc(s.serial_number)}</td>
                        <td class="col_photo" style="text-align:center;">${s.photo_number ? '🖼' : '-'}</td>
                    </tr>
                `).join('');
                applyColVis();
            }
            
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
            const mHbYear = document.getElementById('m_hb_year');
            const bulkModal = document.getElementById('bulk_modal');
            // Populate hebrew days 1-30
            for(let i=1;i<=30;i++){const o=document.createElement('option');o.value=i;o.textContent=i;mHbDay.appendChild(o);}

            function esc(s) {
                return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
            }
            function stripMsg(t) {
                return String(t || '').replace(/\\*[^*]*\\*/g, '').replace(/\\s{2,}/g, ' ').trim();
            }
            function fmtDate(d) {
                if (!d) return '-';
                // last_swiped_at arrives from stations already in Israel local time
                // — display as-is (no timezone conversion).
                try {
                    const s = String(d).replace('T', ' ').substring(0, 19);
                    const m = s.match(/^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})/);
                    if (m) return `${parseInt(m[3])}.${parseInt(m[2])} ${m[4]}:${m[5]}`;
                    return s.substring(0, 16);
                } catch(e) { return d; }
            }
            const hMonths = {1:'ניסן',2:'אייר',3:'סיון',4:'תמוז',5:'אב',6:'אלול',7:'תשרי',8:'חשון',9:'כסלו',10:'טבת',11:'שבט',12:'אדר',13:"אדר ב'"};
            function numToHebLetters(n) {
                n = parseInt(n) || 0;
                if (n <= 0) return '';
                const ones = ['', 'א', 'ב', 'ג', 'ד', 'ה', 'ו', 'ז', 'ח', 'ט'];
                const tens = ['', 'י', 'כ', 'ל', 'מ', 'נ', 'ס', 'ע', 'פ', 'צ'];
                const hundreds = ['', 'ק', 'ר', 'ש', 'ת'];
                let parts = [];
                while (n >= 400) { parts.push('ת'); n -= 400; }
                if (n >= 100) { parts.push(hundreds[Math.floor(n / 100)]); n %= 100; }
                if (n === 15) { parts.push('ט', 'ו'); n = 0; }
                else if (n === 16) { parts.push('ט', 'ז'); n = 0; }
                if (n >= 10) { parts.push(tens[Math.floor(n / 10)]); n %= 10; }
                if (n > 0) parts.push(ones[n]);
                let raw = parts.join('');
                if (!raw) return '';
                if (raw.length === 1) return raw + "'";
                return raw.slice(0, -1) + '"' + raw.slice(-1);
            }
            function fmtBday(s) {
                if (!s.hebrew_birth_day && !s.hebrew_birth_month) return '-';
                let d = numToHebLetters(s.hebrew_birth_day) || '?';
                let m = hMonths[s.hebrew_birth_month] || '?';
                let out = d + ' ' + m;
                if (s.hebrew_birth_year) {
                    out += ' ' + (numToHebLetters(parseInt(s.hebrew_birth_year) % 1000) || s.hebrew_birth_year);
                }
                return out;
            }

            function setSelected(id) {
                selectedId = id;
                const on = (selectedId !== null);
                btnEdit.disabled = !on;
                btnDelete.disabled = !on;
                btnQP.disabled = !on;
                const stu = _allStudents.find(x => x.id == id);
                const stuName = stu ? (stu.first_name + ' ' + stu.last_name).trim() : 'תלמיד';
                selectedEl.textContent = on ? 'נבחר: ' + stuName : 'לא נבחר תלמיד';
                
                document.querySelectorAll('#s_rows tr').forEach(tr => {
                    tr.classList.toggle('selected', tr.dataset.id == id);
                });
            }

            async function load() {
                statusEl.textContent = 'מרענן...';
                // Keep the existing table visible while fetching — no flicker
                try {
                    const q = encodeURIComponent(searchEl.value);
                    const resp = await fetch('/api/students?q=' + q, {credentials: 'include'});
                    const data = await resp.json();

                    if (!data.items || data.items.length === 0) {
                        rowsEl.innerHTML = '<tr><td colspan="10" style="padding:20px; text-align:center;">לא נמצאו תלמידים</td></tr>';
                        statusEl.textContent = '0 תלמידים';
                        return;
                    }
                    
                    _allStudents = data.items;
                    statusEl.textContent = data.items.length + ' תלמידים';

                    // Populate class filter (keep current selection if still exists)
                    const cf = document.getElementById('s_class_filter');
                    const curVal = cf.value;
                    const classes = [...new Set(_allStudents.map(s => String(s.class_name||'').trim()).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'he'));
                    cf.innerHTML = '<option value="">כל הכיתות</option>' + classes.map(c => '<option value="'+esc(c)+'"'+(c===curVal?' selected':'')+'>'+esc(c)+'</option>').join('');

                    renderRows();
                    
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

            function editPoints(event, id, current) {
                event.stopPropagation();
                const cell = event.currentTarget;
                if (cell.querySelector('input')) return;
                const inp = document.createElement('input');
                inp.type = 'number';
                inp.value = current;
                inp.style.width = '80px';
                inp.style.fontSize = '16px';
                inp.style.textAlign = 'center';
                inp.style.padding = '4px';
                inp.style.border = '1px solid #2ecc71';
                inp.style.borderRadius = '6px';
                inp.style.color = '#1f2d3a';
                inp.style.background = '#fff';
                cell.innerHTML = '';
                cell.appendChild(inp);
                inp.focus();
                inp.select();
                let moved = false;
                function finish(moveNext) {
                    if (moved) return;
                    moved = true;
                    const val = parseInt(inp.value || 0);
                    if (isNaN(val) || val < 0) { cell.textContent = current; return; }
                    if (val === current) {
                        cell.textContent = current;
                        if (moveNext) openNextPoints(id);
                        return;
                    }
                    submitInlinePoints(id, val, cell, moveNext);
                }
                inp.addEventListener('blur', function(){ finish(false); });
                inp.addEventListener('keydown', function(e) {
                    if (e.key === 'Enter') { e.preventDefault(); finish(true); }
                    if (e.key === 'Escape') { e.preventDefault(); moved = true; cell.textContent = current; }
                });
            }

            function openNextPoints(currentId) {
                // Find next visible row after currentId and open its points cell for editing
                const rows = Array.from(document.querySelectorAll('#s_rows tr'));
                const idx = rows.findIndex(tr => String(tr.dataset.id) === String(currentId));
                const next = (idx >= 0 && idx + 1 < rows.length) ? rows[idx + 1] : rows[0];
                if (!next) return;
                const nid = parseInt(next.dataset.id);
                const stu = _allStudents.find(s => s.id === nid);
                const cell = next.querySelector('.col_points');
                if (cell && stu) {
                    const fake = {stopPropagation(){}, currentTarget: cell};
                    editPoints(fake, nid, stu.points);
                    next.scrollIntoView({block:'nearest'});
                }
            }

            async function submitInlinePoints(id, newPoints, cell, moveNext) {
                cell.textContent = '...';
                try {
                    const resp = await fetch('/api/students/quick-points', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        credentials: 'include',
                        body: JSON.stringify({student_id: id, delta: newPoints, mode: 'set', reason: 'עדכון נקודות מהטבלה'})
                    });
                    if (!resp.ok) throw new Error('HTTP ' + resp.status);
                    const data = await resp.json();
                    if (data.ok) {
                        const stu = _allStudents.find(s => s.id === id);
                        if (stu) { stu.points = data.new_points; stu.last_update = 'היום'; }
                        cell.textContent = data.new_points;
                        if (moveNext) openNextPoints(id);
                    } else {
                        throw new Error(data.detail || 'error');
                    }
                } catch(e) {
                    alert('שגיאה בעדכון נקודות: ' + e);
                    renderRows();
                }
            }

            function editMsg(event, id) {
                event.stopPropagation();
                const cell = event.currentTarget;
                if (cell.querySelector('input')) return;
                const stu = _allStudents.find(s => s.id === id);
                if (!stu) return;
                const inp = document.createElement('input');
                inp.type = 'text';
                inp.value = stu.private_message || '';
                inp.style.width = '100%';
                inp.style.fontSize = '13px';
                inp.style.padding = '4px';
                inp.style.border = '1px solid #3498db';
                inp.style.borderRadius = '6px';
                inp.style.color = '#1f2d3a';
                inp.style.background = '#fff';
                cell.innerHTML = '';
                cell.appendChild(inp);
                inp.focus();
                inp.select();
                function finish() {
                    const val = inp.value.trim();
                    if (val === (stu.private_message || '')) { renderRows(); return; }
                    submitInlineMsg(id, val, cell);
                }
                inp.addEventListener('blur', finish);
                inp.addEventListener('keydown', function(e) {
                    if (e.key === 'Enter') { e.preventDefault(); finish(); }
                    if (e.key === 'Escape') { e.preventDefault(); renderRows(); }
                });
            }

            async function submitInlineMsg(id, msg, cell) {
                cell.textContent = '...';
                try {
                    const resp = await fetch('/api/students/update-message', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        credentials: 'include',
                        body: JSON.stringify({student_id: id, private_message: msg})
                    });
                    if (!resp.ok) throw new Error('HTTP ' + resp.status);
                    const data = await resp.json();
                    if (data.ok) {
                        const stu = _allStudents.find(s => s.id === id);
                        if (stu) stu.private_message = msg;
                        renderRows();
                    } else {
                        throw new Error(data.detail || 'error');
                    }
                } catch(e) {
                    alert('שגיאה בעדכון הודעה: ' + e);
                    renderRows();
                }
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
                mHbYear.value = '';
                openModal();
            }

            async function openEdit() {
                if (!selectedId) return;
                document.getElementById('s_modal_title').textContent = 'עריכת תלמיד ' + selectedId;
                
                try {
                    const resp = await fetch('/api/students/' + selectedId, {credentials: 'include'});
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
                    mHbYear.value = s.hebrew_birth_year || '';
                    
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
                    hebrew_birth_month: mHbMonth.value ? parseInt(mHbMonth.value) : null,
                    hebrew_birth_year: mHbYear.value ? parseInt(mHbYear.value) : null
                };
                
                try {
                    const resp = await fetch('/api/students/save', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        credentials: 'include',
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
                        credentials: 'include',
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
                        credentials: 'include',
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
                    const r = await fetch('/api/students/bulk-quick-update',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'include',body:JSON.stringify(body)});
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
    
    teacher = web_current_teacher(request) or {}
    is_admin = (int(teacher.get('is_admin') or 0) == 1)
    teacher_id = int(teacher.get('id') or 0)
    
    conn = tenant_db_connection(tenant_id)
    try:
        cur = conn.cursor()
        
        # Non-admin teachers: only see students from their classes
        allowed_classes = None
        if not is_admin and teacher_id > 0:
            try:
                cur.execute(sql_placeholder('SELECT class_name FROM teacher_classes WHERE teacher_id = ?'), (teacher_id,))
                tc_rows = cur.fetchall() or []
                allowed_classes = []
                for tcr in tc_rows:
                    cn = tcr['class_name'] if isinstance(tcr, dict) else tcr[0]
                    if cn:
                        allowed_classes.append(str(cn).strip())
            except Exception:
                allowed_classes = None
        
        q_str = str(q or '').strip()
        # Select only columns that actually exist — schema varies between tenants/versions
        _wanted_cols = ['id', 'first_name', 'last_name', 'class_name', 'points', 'private_message',
                        'card_number', 'id_number', 'is_free_fix_blocked', 'last_swiped_at',
                        'hebrew_birth_day', 'hebrew_birth_month', 'hebrew_birth_year', 'gender',
                        'serial_number', 'photo_number', 'total_swipes', 'updated_at']
        try:
            _existing = set(table_columns(conn, 'students'))
            _sel_cols = [c for c in _wanted_cols if c in _existing]
            if not _sel_cols:
                _sel_cols = ['id', 'first_name', 'last_name', 'points']
        except Exception:
            _sel_cols = _wanted_cols
        sql = "SELECT " + ", ".join(_sel_cols) + " FROM students"
        params = []
        where_parts = []

        if q_str:
            where_parts.append("(first_name LIKE ? OR last_name LIKE ? OR card_number LIKE ? OR class_name LIKE ? OR id_number LIKE ?)")
            p = f"%{q_str}%"
            params = [p, p, p, p, p]

        if allowed_classes is not None and len(allowed_classes) > 0:
            placeholders = ','.join(['?' for _ in allowed_classes])
            where_parts.append(f"class_name IN ({placeholders})")
            params.extend(allowed_classes)
        elif allowed_classes is not None and len(allowed_classes) == 0:
            # Teacher has no assigned classes — show nothing
            return {'items': []}

        if where_parts:
            sql += " WHERE " + " AND ".join(where_parts)

        cur.execute(sql_placeholder(sql), params)
        rows = cur.fetchall() or []
        items = []
        for r in rows:
            d = dict(r) if isinstance(r, dict) else {k: r[k] for k in r.keys()} if hasattr(r, 'keys') else {
                'id': r[0], 'first_name': r[1], 'last_name': r[2], 'class_name': r[3],
                'points': r[4], 'private_message': r[5], 'card_number': r[6], 'id_number': r[7],
                'is_free_fix_blocked': r[8] if len(r) > 8 else 0
            }
            # Normalize serial_number for cross-DB sorting (text in PG, may be numeric)
            try:
                d['_sort_sn'] = int(d.get('serial_number') or 0)
            except Exception:
                d['_sort_sn'] = 0
            items.append(d)

        # Enrich: swipe totals + last manual update (matches desktop app columns)
        try:
            sids = [int(d['id']) for d in items if d.get('id')]

            total_days = 0
            try:
                cur.execute(sql_placeholder("SELECT value FROM settings WHERE key = 'total_school_days' LIMIT 1"))
                rr = cur.fetchone()
                if rr:
                    total_days = int((rr['value'] if isinstance(rr, dict) else rr[0]) or 0)
            except Exception:
                total_days = 0
            if total_days <= 0:
                try:
                    if USE_POSTGRES:
                        cur.execute("SELECT COUNT(DISTINCT DATE(swiped_at)) FROM swipe_log WHERE station_type='public' AND EXTRACT(DOW FROM swiped_at) != 6")
                    else:
                        cur.execute("SELECT COUNT(DISTINCT DATE(swiped_at)) FROM swipe_log WHERE station_type='public' AND strftime('%w', swiped_at) != '6'")
                    rr = cur.fetchone()
                    if rr:
                        total_days = int((list(rr.values())[0] if isinstance(rr, dict) else rr[0]) or 0)
                except Exception:
                    total_days = 0

            swipe_totals = {}
            if sids:
                try:
                    ph = ','.join(['?'] * len(sids))
                    cur.execute(sql_placeholder(
                        f"SELECT student_id, COUNT(*) AS c FROM swipe_log WHERE student_id IN ({ph}) GROUP BY student_id"
                    ), list(sids))
                    for r2 in (cur.fetchall() or []):
                        swipe_totals[int(r2['student_id'] if isinstance(r2, dict) else r2[0])] = int((r2['c'] if isinstance(r2, dict) else r2[1]) or 0)
                except Exception:
                    pass

            last_updates = {}
            if sids:
                try:
                    pl_cols = set(table_columns(conn, 'points_log'))
                    delta_col = 'delta' if 'delta' in pl_cols else ('points' if 'points' in pl_cols else ('points_change' if 'points_change' in pl_cols else None))
                    if delta_col:
                        ph = ','.join(['?'] * len(sids))
                        if 'action_type' in pl_cols:
                            act = "'מנהל','מורה','עדכון מהיר','ביטול/שחזור','quick_update','web','sync'"
                            act_where = f" AND action_type IN ({act})"
                        else:
                            act_where = ''
                        cur.execute(sql_placeholder(f'''
                            SELECT student_id, created_at, {delta_col} AS delta FROM points_log
                            WHERE student_id IN ({ph}){act_where}
                              AND id IN (SELECT MAX(id) FROM points_log
                                         WHERE student_id IN ({ph}){act_where}
                                         GROUP BY student_id)
                        '''), list(sids) + list(sids))
                        for r2 in (cur.fetchall() or []):
                            sid2 = int(r2['student_id'] if isinstance(r2, dict) else r2[0])
                            last_updates[sid2] = {
                                'created_at': str(r2['created_at'] if isinstance(r2, dict) else r2[1] or ''),
                                'delta': int((r2['delta'] if isinstance(r2, dict) else r2[2]) or 0),
                            }
                except Exception:
                    last_updates = {}

            for d in items:
                tot = int(d.get('total_swipes') or 0) or swipe_totals.get(d.get('id'), 0)
                d['swipe_total'] = tot
                d['swipe_avg'] = round(tot / total_days, 2) if (total_days > 0 and tot > 0) else 0
                u = last_updates.get(d.get('id'))
                d['last_update'] = _fmt_rel_update(u['created_at'], u['delta']) if u else ''
        except Exception:
            pass

        # Sort exactly like the desktop app: null/empty serials first, then serial,
        # then class, last_name, first_name
        items.sort(key=lambda s: (
            0 if (s.get('serial_number') or '0') in ('', '0') else 1,
            s['_sort_sn'],
            str(s.get('class_name') or ''),
            str(s.get('last_name') or ''),
            str(s.get('first_name') or '')
        ))
        for s in items:
            s.pop('_sort_sn', None)

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

@router.post("/api/students/update-message")
def api_student_update_message(request: Request, payload: Dict[str, Any] = Body(...)):
    guard = web_require_teacher(request)
    if guard: raise HTTPException(status_code=401, detail="Unauthorized")

    tenant_id = web_tenant_from_cookie(request)
    if not tenant_id: raise HTTPException(status_code=400, detail="Missing tenant")

    sid = int(payload.get('student_id') or 0)
    msg = str(payload.get('private_message') or '').strip()
    if sid <= 0:
        raise HTTPException(status_code=400, detail="Invalid student_id")

    conn = tenant_db_connection(tenant_id)
    try:
        cur = conn.cursor()
        cur.execute(sql_placeholder("UPDATE students SET private_message = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?"), (msg, sid))
        conn.commit()

        record_sync_event(
            tenant_id=tenant_id,
            station_id='web',
            entity_type='student',
            entity_id=str(sid),
            action_type='update',
            payload={'private_message': msg}
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
    mode = str(payload.get('mode') or 'add').strip().lower()
    reason = str(payload.get('reason') or '').strip()
    if sid <= 0:
        raise HTTPException(status_code=400, detail="Invalid student_id")
    if mode == 'set':
        if delta < 0:
            raise HTTPException(status_code=400, detail="Absolute points cannot be negative")
    elif delta == 0:
        raise HTTPException(status_code=400, detail="Invalid delta")

    conn = tenant_db_connection(tenant_id)
    try:
        cur = conn.cursor()
        cur.execute(sql_placeholder("SELECT id, points FROM students WHERE id = ? LIMIT 1"), (sid,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Student not found")
        old_points = int((row['points'] if isinstance(row, dict) else row[1]) or 0)
        new_points = delta if mode == 'set' else old_points + delta

        cur.execute(sql_placeholder("UPDATE students SET points = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?"), (new_points, sid))
        
        # Verify update succeeded
        if cur.rowcount == 0:
            raise HTTPException(status_code=500, detail="Failed to update student points")

        # Best-effort history log — adapts to the real points_log schema and uses a
        # SAVEPOINT so a schema mismatch can never abort the points UPDATE above.
        teacher = web_current_teacher(request) or {}
        insert_points_log(
            conn, sid, delta,
            old_points=old_points, new_points=new_points,
            reason=reason or 'עדכון מהיר מהאתר',
            actor_name=str(teacher.get('name') or 'web'),
            action_type='quick_update',
        )

        conn.commit()

        record_sync_event(
            tenant_id=tenant_id,
            station_id='web',
            entity_type='student_points',
            entity_id=str(sid),
            action_type='update',
            payload={
                'old_points': int(old_points),
                'new_points': int(new_points),
                'reason': reason or 'עדכון מהיר מהאתר',
                'added_by': 'web',
                'log_action_type': 'עדכון מהיר'
            }
        )

        return {'ok': True, 'new_points': new_points}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        try: conn.close()
        except: pass
