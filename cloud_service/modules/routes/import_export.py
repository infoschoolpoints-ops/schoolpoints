from fastapi import APIRouter, Request, HTTPException, UploadFile, File, Form, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from typing import Dict, Any
import io
import csv
import traceback

from ..ui import basic_web_shell
from ..auth import web_require_admin_teacher, web_tenant_from_cookie, web_current_teacher
from ..db import tenant_db_connection, sql_placeholder
from ..sync_logic import record_sync_event

router = APIRouter()

@router.get("/web/import", response_class=HTMLResponse)
def web_import(request: Request):
    guard = web_require_admin_teacher(request)
    if guard: return guard
    
    html_content = """
    <div class="card" style="padding:24px; max-width:600px; margin:0 auto; background:#fff; border-radius:12px; box-shadow:0 2px 10px rgba(0,0,0,0.05);">
        <h2 style="margin-top:0;">ייבוא תלמידים מאקסל</h2>
        <p style="color:#666; line-height:1.5;">ניתן לייבא תלמידים, לעדכן פרטים ולטעון נקודות באמצעות קובץ Excel.<br>
        הקובץ צריך להכיל עמודות כמו: <b>שם משפחה, שם פרטי, כיתה, מס' כרטיס, מס' נקודות, ת"ז</b>.</p>
        
        <div style="margin:20px 0; padding:15px; background:#f8f9fa; border-radius:8px;">
            <a href="/web/export/download" target="_blank" style="text-decoration:none; display:flex; align-items:center; gap:10px; color:#2980b9; font-weight:bold;">
                <span>⬇️</span> הורד תבנית / רשימה קיימת
            </a>
        </div>
        
        <div style="margin-bottom:20px;">
            <label style="display:block; margin-bottom:10px; font-weight:bold;">בחר קובץ Excel (.xlsx)</label>
            <input type="file" id="import-file" accept=".xlsx" style="padding:10px; border:1px solid #ddd; width:100%; box-sizing:border-box; border-radius:6px;">
        </div>
        
        <div style="margin-bottom:25px;">
            <label class="ck" style="display:flex; align-items:center; gap:10px; cursor:pointer; user-select:none;">
                <input type="checkbox" id="clear-existing" style="width:18px; height:18px;">
                <span style="color:#c0392b; font-weight:bold;">⚠️ מחק את כל התלמידים הקיימים לפני הייבוא</span>
            </label>
        </div>

        <button class="green" onclick="doImport()" id="btn-import" style="width:100%; padding:12px; font-size:16px; font-weight:bold; border-radius:8px; border:none; background:#2ecc71; color:white; cursor:pointer;">ביצוע ייבוא</button>
        
        <div id="import-status" style="margin-top:20px; white-space:pre-wrap; font-size:14px; line-height:1.5;"></div>
    </div>

    <script>
        async function doImport() {
            const fileInput = document.getElementById('import-file');
            const clearExisting = document.getElementById('clear-existing').checked;
            const btn = document.getElementById('btn-import');
            const status = document.getElementById('import-status');
            
            if (!fileInput.files[0]) {
                alert('נא לבחור קובץ');
                return;
            }
            
            if (clearExisting && !confirm('האם אתה בטוח שברצונך למחוק את כל הנתונים הקיימים? פעולה זו אינה הפיכה!')) {
                return;
            }

            const formData = new FormData();
            formData.append('file', fileInput.files[0]);
            formData.append('clear_existing', clearExisting ? 'true' : 'false');
            
            btn.disabled = true;
            btn.style.opacity = '0.7';
            btn.textContent = 'מייבא...';
            status.innerHTML = '<div style="color:#2980b9;">⏳ מבצע ייבוא, נא להמתין...</div>';
            
            try {
                const res = await fetch('/api/import/upload', {
                    method: 'POST',
                    body: formData
                });
                const data = await res.json();
                
                if (res.ok) {
                    status.innerHTML = `<div style="color:#27ae60; font-weight:bold;">✅ הייבוא הושלם בהצלחה!</div>` +
                                       `<div>תלמידים שנוצרו/עודכנו: ${data.imported_count}</div>` +
                                       (data.errors && data.errors.length ? `<div style="color:#e74c3c; margin-top:10px;"><b>שגיאות/אזהרות:</b><br>${data.errors.join('<br>')}</div>` : '');
                } else {
                    status.innerHTML = `<div style="color:#e74c3c;">❌ שגיאה: ${data.detail || 'Unknown error'}</div>`;
                }
            } catch (e) {
                status.innerHTML = `<div style="color:#e74c3c;">❌ שגיאה בתקשורת: ${e}</div>`;
            } finally {
                btn.disabled = false;
                btn.style.opacity = '1';
                btn.textContent = 'ביצוע ייבוא';
            }
        }
    </script>
    """
    return basic_web_shell("ייבוא נתונים", html_content, request=request)

@router.post("/api/import/upload")
async def api_import_upload(request: Request, file: UploadFile = File(...), clear_existing: str = Form(default='false')) -> Dict[str, Any]:
    guard = web_require_admin_teacher(request)
    if guard: raise HTTPException(status_code=401, detail='not authorized')
    
    tenant_id = web_tenant_from_cookie(request)
    if not tenant_id: raise HTTPException(status_code=400, detail='missing tenant')

    try:
        import pandas as pd
    except ImportError:
        raise HTTPException(status_code=500, detail='pandas not installed')

    contents = await file.read()
    try:
        df = pd.read_excel(io.BytesIO(contents), dtype={'מס\' כרטיס': str, 'ת"ז': str, 'מס\' סידורי': str})
    except Exception as e:
        raise HTTPException(status_code=400, detail=f'Invalid Excel file: {e}')

    conn = tenant_db_connection(tenant_id)
    imported_count = 0
    errors = []
    
    try:
        cur = conn.cursor()
        
        # Check if clear_existing is requested
        if clear_existing.lower() == 'true':
            try:
                cur.execute('DELETE FROM students')
                # Also clean logs? Usually implies full reset. Let's try to clean logs too.
                try: cur.execute('DELETE FROM points_log')
                except: pass
                try: cur.execute('DELETE FROM points_history')
                except: pass
                conn.commit()
            except Exception as e:
                return {'ok': False, 'detail': f'Failed to clear tables: {e}'}

        # Pre-fetch existing students to minimize queries if not clearing
        existing_students = {} # key: (first_name, last_name) -> dict
        if clear_existing.lower() != 'true':
            cur.execute('SELECT id, first_name, last_name, points, card_number, serial_number, photo_number, private_message, id_number, class_name FROM students')
            for r in cur.fetchall():
                # Normalize key
                fn = str((r.get('first_name') if isinstance(r, dict) else r['first_name']) or '').strip()
                ln = str((r.get('last_name') if isinstance(r, dict) else r['last_name']) or '').strip()
                existing_students[(fn, ln)] = dict(r) if isinstance(r, dict) else {k: r[k] for k in r.keys()}

        teacher = web_current_teacher(request) or {}
        teacher_name = str(teacher.get('name') or 'import')

        for index, row in df.iterrows():
            try:
                # Basic fields
                last_name = str(row.get('שם משפחה', '')).strip()
                first_name = str(row.get('שם פרטי', '')).strip()
                
                # Skip empty
                if not last_name or not first_name or last_name.lower() == 'nan' or first_name.lower() == 'nan':
                    continue

                # Optional fields
                id_number = str(row.get('ת"ז', '')).strip()
                if id_number.lower() == 'nan': id_number = ''
                
                class_name = str(row.get('כיתה', '')).strip()
                if class_name.lower() == 'nan': class_name = ''
                
                # Try both column names for photo
                photo_col = "נתיב תמונה" if "נתיב תמונה" in df.columns else "מס' תמונה"
                photo_number = str(row.get(photo_col, '')).strip()
                if photo_number.lower() == 'nan': photo_number = ''
                
                card_number = str(row.get("מס' כרטיס", '')).strip().lstrip("'")
                if card_number.lower() in ('nan', '', '0'): card_number = ''
                
                points = 0
                if "מס' נקודות" in df.columns and pd.notna(row.get("מס' נקודות")):
                    try: points = int(float(row.get("מס' נקודות")))
                    except: points = 0
                
                private_message = ''
                if "הודעה פרטית" in df.columns:
                    pm = row.get("הודעה פרטית")
                    if pd.notna(pm) and str(pm).lower() != 'nan':
                        private_message = str(pm).strip()

                # Serial number
                serial_number = ''
                serial_col = next((c for c in df.columns if 'סידורי' in str(c)), None)
                if serial_col:
                    val = row.get(serial_col)
                    if pd.notna(val) and str(val).lower() != 'nan':
                        try: serial_number = str(int(float(val)))
                        except: serial_number = str(val).strip()
                else:
                    if clear_existing.lower() == 'true':
                        serial_number = str(index + 1)

                key = (first_name, last_name)
                student = existing_students.get(key)
                
                if student:
                    # Update
                    sid = student['id']
                    updated_fields = []
                    params = []
                    
                    # Check changes
                    if serial_number and str(student.get('serial_number') or '') != serial_number:
                        updated_fields.append('serial_number = ?')
                        params.append(serial_number)
                    if card_number and str(student.get('card_number') or '') != card_number:
                        updated_fields.append('card_number = ?')
                        params.append(card_number)
                    if photo_number and str(student.get('photo_number') or '') != photo_number:
                        updated_fields.append('photo_number = ?')
                        params.append(photo_number)
                    if id_number and str(student.get('id_number') or '') != id_number:
                        updated_fields.append('id_number = ?')
                        params.append(id_number)
                    if class_name and str(student.get('class_name') or '') != class_name:
                        updated_fields.append('class_name = ?')
                        params.append(class_name)
                    if private_message != (student.get('private_message') or ''):
                        updated_fields.append('private_message = ?')
                        params.append(private_message)
                        
                    # Points update logic
                    current_points = int(student.get('points') or 0)
                    if points != current_points:
                        updated_fields.append('points = ?')
                        params.append(points)
                        # Log points change
                        delta = points - current_points
                        try:
                            cur.execute(
                                sql_placeholder('INSERT INTO points_log (student_id, old_points, new_points, delta, reason, actor_name, action_type) VALUES (?, ?, ?, ?, ?, ?, ?)'),
                                (sid, current_points, points, delta, "ייבוא מ-Excel", teacher_name, "import")
                            )
                            # Sync event for points
                            record_sync_event(
                                tenant_id=tenant_id,
                                station_id='web',
                                entity_type='student_points',
                                entity_id=str(sid),
                                action_type='update',
                                payload={'old_points': current_points, 'new_points': points, 'reason': 'ייבוא', 'added_by': teacher_name}
                            )
                        except: pass

                    if updated_fields:
                        updated_fields.append('updated_at = CURRENT_TIMESTAMP')
                        sql = f"UPDATE students SET {', '.join(updated_fields)} WHERE id = ?"
                        params.append(sid)
                        cur.execute(sql_placeholder(sql), params)
                        imported_count += 1

                else:
                    # Insert
                    cols = ['last_name', 'first_name', 'points']
                    vals = [last_name, first_name, points]
                    placeholders = ['?', '?', '?']
                    
                    if id_number:
                        cols.append('id_number'); vals.append(id_number); placeholders.append('?')
                    if class_name:
                        cols.append('class_name'); vals.append(class_name); placeholders.append('?')
                    if card_number:
                        cols.append('card_number'); vals.append(card_number); placeholders.append('?')
                    if photo_number:
                        cols.append('photo_number'); vals.append(photo_number); placeholders.append('?')
                    if serial_number:
                        cols.append('serial_number'); vals.append(serial_number); placeholders.append('?')
                    if private_message:
                        cols.append('private_message'); vals.append(private_message); placeholders.append('?')
                    
                    sql = f"INSERT INTO students ({', '.join(cols)}) VALUES ({', '.join(placeholders)})"
                    cur.execute(sql_placeholder(sql), vals)
                    new_sid = cur.lastrowid
                    imported_count += 1
                    
                    # Log initial points if > 0
                    if points > 0 and new_sid:
                        try:
                            cur.execute(
                                sql_placeholder('INSERT INTO points_log (student_id, old_points, new_points, delta, reason, actor_name, action_type) VALUES (?, ?, ?, ?, ?, ?, ?)'),
                                (new_sid, 0, points, points, "ייבוא מ-Excel", teacher_name, "import")
                            )
                            # Sync event
                            record_sync_event(
                                tenant_id=tenant_id,
                                station_id='web',
                                entity_type='student_points',
                                entity_id=str(new_sid),
                                action_type='update',
                                payload={'old_points': 0, 'new_points': points, 'reason': 'ייבוא', 'added_by': teacher_name}
                            )
                        except: pass

            except Exception as row_err:
                errors.append(f"שגיאה בשורה {index+2}: {row_err}")

        conn.commit()
        return {'ok': True, 'imported_count': imported_count, 'errors': errors}
        
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Import failed: {e}")
    finally:
        try: conn.close()
        except: pass

@router.get('/web/export/download')
def web_export_download(request: Request) -> Response:
    guard = web_require_admin_teacher(request)
    if guard: return guard
    
    tenant_id = web_tenant_from_cookie(request)
    if not tenant_id:
        return RedirectResponse(url='/web/signin', status_code=302)

    conn = tenant_db_connection(tenant_id)
    try:
        cur = conn.cursor()
        cur.execute(
            sql_placeholder(
                'SELECT serial_number, last_name, first_name, class_name, points, card_number '
                'FROM students '
                'ORDER BY class_name, last_name, first_name'
            )
        )
        rows = cur.fetchall() or []
    finally:
        try: conn.close()
        except: pass

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["מס' סידורי", 'שם משפחה', 'שם פרטי', 'כיתה', "מס' נקודות", "מס' כרטיס"])
    for r in rows:
        if isinstance(r, dict):
            d = r
        else:
            try: d = dict(r)
            except: d = {} # tuple fallback? if sqlite row factory is not dict
            
        w.writerow([
            d.get('serial_number') or '',
            d.get('last_name') or '',
            d.get('first_name') or '',
            d.get('class_name') or '',
            d.get('points') if d.get('points') is not None else '',
            d.get('card_number') or '',
        ])

    data = buf.getvalue().encode('utf-8-sig')
    return Response(
        content=data,
        media_type='text/csv; charset=utf-8',
        headers={'Content-Disposition': 'attachment; filename="students_export.csv"'}
    )
