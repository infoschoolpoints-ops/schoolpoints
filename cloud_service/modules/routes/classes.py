from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse
from typing import Dict, Any, List
import json

from ..ui import basic_web_shell
from ..auth import web_require_teacher, web_tenant_from_cookie
from ..db import tenant_db_connection, sql_placeholder, integrity_errors
from ..config import USE_POSTGRES

router = APIRouter()

@router.get("/api/classes")
def api_classes(request: Request) -> Dict[str, Any]:
    guard = web_require_teacher(request)
    if guard:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    tenant_id = web_tenant_from_cookie(request)
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Missing tenant")
        
    conn = tenant_db_connection(tenant_id)
    try:
        cur = conn.cursor()
        # Fetch distinct classes from students
        cur.execute("SELECT DISTINCT class_name FROM students WHERE class_name IS NOT NULL AND class_name != '' ORDER BY class_name")
        rows = cur.fetchall() or []
        classes = []
        for r in rows:
            name = r['class_name'] if isinstance(r, dict) else r[0]
            if name:
                classes.append(str(name).strip())
        return {'items': classes}
    finally:
        try: conn.close()
        except: pass

@router.get("/web/classes", response_class=HTMLResponse)
def web_classes(request: Request):
    guard = web_require_teacher(request)
    if guard:
        return guard
        
    html_content = """
    <div style="max-width:800px; margin:0 auto; padding:20px;">
        <h2 style="margin-bottom:20px;">ניהול כיתות</h2>
        <div class="card" style="padding:20px; background:#fff; border-radius:12px; border:1px solid #eee;">
            <p style="color:#666; margin-bottom:20px;">כאן ניתן לראות את רשימת הכיתות הפעילות, לשנות שמות או למחוק כיתות (ריקון שדה הכיתה לתלמידים).</p>
            
            <div style="margin-bottom:15px; display:flex; justify-content:space-between; align-items:center;">
                <button class="gray" onclick="loadClasses()">🔄 רענן רשימה</button>
                <div style="font-size:14px; color:#888;">* שינוי שם כיתה יעדכן את כל התלמידים בכיתה זו</div>
            </div>

            <table style="width:100%; border-collapse:collapse; font-size:14px;">
                <thead>
                    <tr style="background:#f8f9fa; border-bottom:2px solid #eee;">
                        <th style="padding:12px; text-align:right;">שם הכיתה</th>
                        <th style="padding:12px; text-align:right;">מספר תלמידים</th>
                        <th style="padding:12px; text-align:right;">פעולות</th>
                    </tr>
                </thead>
                <tbody id="classes-list">
                    <tr><td colspan="3" style="text-align:center; padding:20px;">טוען...</td></tr>
                </tbody>
            </table>
        </div>
    </div>

    <script>
        async function loadClasses() {
            const list = document.getElementById('classes-list');
            list.innerHTML = '<tr><td colspan="3" style="text-align:center; padding:20px;">טוען...</td></tr>';
            try {
                // We don't have a dedicated API for class stats yet, let's assume we can fetch stats or just list
                // For now, minimal list via api/classes
                const resp = await fetch('/api/classes');
                const data = await resp.json();
                
                if (!data.items || data.items.length === 0) {
                    list.innerHTML = '<tr><td colspan="3" style="text-align:center; padding:20px;">אין כיתות פעילות</td></tr>';
                    return;
                }
                
                let html = '';
                for (const cls of data.items) {
                    html += `
                    <tr style="border-bottom:1px solid #eee;">
                        <td style="padding:12px;"><b>${cls}</b></td>
                        <td style="padding:12px;">-</td>
                        <td style="padding:12px;">
                            <button class="blue" style="padding:4px 10px; font-size:12px;" onclick="renameClass('${cls}')">✏️ שנה שם</button>
                        </td>
                    </tr>
                    `;
                }
                list.innerHTML = html;
            } catch (e) {
                list.innerHTML = `<tr><td colspan="3" style="text-align:center; color:red;">שגיאה בטעינה: ${e.message}</td></tr>`;
            }
        }
        
        function renameClass(oldName) {
            const newName = prompt('שם חדש לכיתה ' + oldName + ':', oldName);
            if (newName && newName !== oldName) {
                // Implement rename logic via API if exists
                alert('פונקציונליות בבנייה');
            }
        }

        loadClasses();
    </script>
    """
    return basic_web_shell("ניהול כיתות", html_content, request=request)
