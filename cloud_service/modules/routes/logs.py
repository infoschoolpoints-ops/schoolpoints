from fastapi import APIRouter, Request, HTTPException, Query
from fastapi.responses import HTMLResponse
from typing import Dict, Any, List
import json

from ..ui import basic_web_shell
from ..auth import web_require_admin_teacher, web_tenant_from_cookie
from ..db import tenant_db_connection, sql_placeholder

router = APIRouter()

@router.get('/api/logs')
def api_logs_list(
    request: Request,
    q: str = Query(default=''),
    limit: int = Query(default=50, le=1000),
    offset: int = Query(default=0)
) -> Dict[str, Any]:
    guard = web_require_admin_teacher(request)
    if guard:
        raise HTTPException(status_code=401, detail='not authorized')
    
    tenant_id = web_tenant_from_cookie(request)
    conn = tenant_db_connection(tenant_id)
    try:
        cur = conn.cursor()
        
        sql = """
            SELECT l.id, l.created_at, l.student_id, l.delta, l.reason, l.actor_name, l.action_type,
                   s.first_name, s.last_name, s.class_name
              FROM points_log l
              LEFT JOIN students s ON l.student_id = s.id
        """
        
        where_clauses = []
        params = []
        
        if q:
            term = f"%{q.strip()}%"
            where_clauses.append("(s.first_name LIKE ? OR s.last_name LIKE ? OR s.class_name LIKE ? OR l.actor_name LIKE ? OR l.reason LIKE ?)")
            params.extend([term, term, term, term, term])
            
        if where_clauses:
            sql += " WHERE " + " AND ".join(where_clauses)
            
        sql += " ORDER BY l.id DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        
        cur.execute(sql_placeholder(sql), params)
        rows = []
        for r in cur.fetchall():
            rows.append(dict(r) if isinstance(r, dict) else {k: r[k] for k in r.keys()})
            
        return {'items': rows}
    finally:
        try: conn.close()
        except: pass

@router.get("/web/logs", response_class=HTMLResponse)
def web_logs(request: Request):
    guard = web_require_admin_teacher(request)
    if guard: return guard
    
    html_content = """
    <style>
      .tabs { display: flex; gap: 10px; border-bottom: 1px solid #ddd; margin-bottom: 20px; }
      .tab { padding: 10px 20px; cursor: pointer; border-bottom: 3px solid transparent; font-weight: bold; color: #666; }
      .tab.active { border-bottom-color: #3498db; color: #3498db; }
      .tab-content { display: none; }
      .tab-content.active { display: block; }
      .log-table { width: 100%; border-collapse: collapse; font-size: 13px; }
      .log-table th { background: #f8f9fa; text-align: right; padding: 10px; border-bottom: 2px solid #eee; position: sticky; top: 0; }
      .log-table td { padding: 8px 10px; border-bottom: 1px solid #f1f1f1; }
      .log-table tr:hover { background: #fdfdfd; }
      .pos { color: green; font-weight: bold; }
      .neg { color: red; font-weight: bold; }
    </style>

    <div class="tabs">
      <div class="tab active" onclick="switchTab('view')">📜 צפייה בלוגים</div>
      <div class="tab" onclick="switchTab('settings')">⚙️ הגדרות</div>
    </div>

    <div id="tab-view" class="tab-content active">
      <div style="display:flex; gap:10px; margin-bottom:15px;">
        <input id="search-box" style="padding:8px; border:1px solid #ddd; border-radius:6px; width:250px;" placeholder="חיפוש (שם, כיתה, סיבה...)" onkeyup="debounceLoad()">
        <button class="blue" onclick="loadLogsView()">🔍 חפש</button>
      </div>
      
      <div class="card" style="padding:0; overflow:auto; max-height:calc(100vh - 250px);">
        <table class="log-table">
          <thead>
            <tr>
              <th>תאריך</th>
              <th>תלמיד</th>
              <th>כיתה</th>
              <th>שינוי</th>
              <th>סיבה</th>
              <th>בוצע ע"י</th>
            </tr>
          </thead>
          <tbody id="logs-body">
            <tr><td colspan="6" style="text-align:center; padding:20px;">טוען...</td></tr>
          </tbody>
        </table>
        <div style="padding:10px; text-align:center;">
            <button class="gray" id="btn-more" onclick="loadMore()" style="display:none; width:100%;">טען עוד...</button>
        </div>
      </div>
    </div>

    <div id="tab-settings" class="tab-content">
        <div class="card" style="padding:20px; background:#fff; border-radius:10px; border:1px solid #eee; max-width:500px;">
          <h3 style="margin-top:0;">שמירת היסטוריה</h3>
          <div style="margin-bottom:15px;">
            <label style="display:block; margin-bottom:5px; font-weight:600;">מספר ימים לשמירת לוגים</label>
            <input type="number" id="log-retention" style="width:100%; padding:10px; border:1px solid #ddd; border-radius:6px; box-sizing:border-box;">
            <div style="font-size:12px; color:#666; margin-top:5px;">לוגים ישנים יותר יימחקו אוטומטית ע"י המערכת.</div>
          </div>
          <div>
            <button class="green" onclick="saveLogsSettings()" style="padding:10px 20px; border-radius:6px; border:none; background:#2ecc71; color:white; font-weight:bold; cursor:pointer;">שמירה</button>
          </div>
        </div>
    </div>

    <script>
      let offset = 0;
      let limit = 50;
      let isLoading = false;
      let searchTimer = null;

      function switchTab(tab) {
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
        document.querySelector(`.tab[onclick="switchTab('${tab}')"]`).classList.add('active');
        document.getElementById('tab-' + tab).classList.add('active');
      }

      function debounceLoad() {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(() => {
            offset = 0;
            loadLogsView();
        }, 500);
      }

      async function loadLogsView(append = false) {
        if (isLoading) return;
        isLoading = true;
        
        const q = document.getElementById('search-box').value;
        if (!append) {
            offset = 0;
            document.getElementById('logs-body').innerHTML = '<tr><td colspan="6" style="text-align:center; padding:20px;">טוען...</td></tr>';
            document.getElementById('btn-more').style.display = 'none';
        }

        try {
            const res = await fetch(`/api/logs?q=${encodeURIComponent(q)}&limit=${limit}&offset=${offset}`);
            const data = await res.json();
            const rows = data.items || [];
            
            const html = rows.map(r => {
                let dt = r.created_at;
                try { dt = new Date(r.created_at).toLocaleString('he-IL'); } catch(e) {}
                const cls = r.delta > 0 ? 'pos' : (r.delta < 0 ? 'neg' : '');
                const sign = r.delta > 0 ? '+' : '';
                return `
                    <tr>
                        <td style="direction:ltr; text-align:right;">${dt}</td>
                        <td>${esc(r.first_name)} ${esc(r.last_name)}</td>
                        <td>${esc(r.class_name)}</td>
                        <td class="${cls}" style="direction:ltr; text-align:right;">${sign}${r.delta}</td>
                        <td>${esc(r.reason)}</td>
                        <td>${esc(r.actor_name)}</td>
                    </tr>
                `;
            }).join('');

            const tbody = document.getElementById('logs-body');
            if (!append) tbody.innerHTML = '';
            
            if (rows.length === 0 && !append) {
                tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; padding:20px; color:#999;">אין נתונים</td></tr>';
            } else {
                if (!append) tbody.innerHTML = html;
                else tbody.insertAdjacentHTML('beforeend', html);
            }

            if (rows.length >= limit) {
                document.getElementById('btn-more').style.display = 'block';
                offset += limit;
            } else {
                document.getElementById('btn-more').style.display = 'none';
            }

        } catch(e) {
            console.error(e);
            if (!append) document.getElementById('logs-body').innerHTML = '<tr><td colspan="6" style="text-align:center; color:red;">שגיאה</td></tr>';
        } finally {
            isLoading = false;
        }
      }

      function loadMore() {
        loadLogsView(true);
      }

      async function loadLogsSettings() {
        try {
          const res = await fetch('/api/settings/log_settings');
          const data = await res.json();
          document.getElementById('log-retention').value = data.retention_days || 30;
        } catch(e) {}
      }

      async function saveLogsSettings() {
        const days = parseInt(document.getElementById('log-retention').value) || 30;
        await fetch('/api/settings/save', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ key: 'log_settings', value: { retention_days: days } })
        });
        alert('נשמר בהצלחה');
      }

      function esc(s) {
        return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
      }

      loadLogsView();
      loadLogsSettings();
    </script>
    """
    return basic_web_shell("לוגים", html_content, request=request)
