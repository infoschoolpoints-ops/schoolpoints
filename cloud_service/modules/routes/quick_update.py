"""Quick Update routes."""
from fastapi import APIRouter, Request, HTTPException, Body
from fastapi.responses import HTMLResponse
from typing import Dict, Any
from ..ui import basic_web_shell
from ..auth import web_require_teacher, web_tenant_from_cookie, web_current_teacher
from ..db import tenant_db_connection, sql_placeholder
from ..config import USE_POSTGRES
from ..sync_logic import record_sync_event

router = APIRouter()


@router.post("/api/students/bulk-quick-update")
def api_bulk_qu(request: Request, payload: Dict[str, Any] = Body(...)):
    guard = web_require_teacher(request)
    if guard:
        raise HTTPException(status_code=401)
    tid = web_tenant_from_cookie(request)
    if not tid:
        raise HTTPException(status_code=400)
    mode = str(payload.get('mode') or '')
    op = str(payload.get('operation') or 'add')
    pts = int(payload.get('points') or 0)
    cn = payload.get('class_names') or []
    si = payload.get('student_ids') or []
    sf = int(payload.get('serial_from') or 0)
    st2 = int(payload.get('serial_to') or 0)
    if op not in ('add', 'subtract', 'set'):
        op = 'add'
    teacher = web_current_teacher(request) or {}
    ia = int(teacher.get('is_admin') or 0) == 1
    conn = tenant_db_connection(tid)
    try:
        cur = conn.cursor()
        ids = _collect(cur, mode, cn, si, sf, st2, ia)
        if not ids:
            return {'ok': True, 'updated': 0}
        rsn = _reason(op, pts)
        upd = 0
        for s in ids:
            cur.execute(sql_placeholder("SELECT points FROM students WHERE id=?"), (s,))
            row = cur.fetchone()
            if not row:
                continue
            old = int((row['points'] if isinstance(row, dict) else row[0]) or 0)
            nw = _calc(op, old, pts)
            cur.execute(sql_placeholder("UPDATE students SET points=?, updated_at=CURRENT_TIMESTAMP WHERE id=?"), (nw, s))
            _log(cur, s, old, nw, rsn)
            record_sync_event(
                tenant_id=tid, station_id='web',
                entity_type='student_points', entity_id=str(s),
                action_type='update',
                payload={'student_id': s, 'old_points': old, 'new_points': nw, 'delta': nw - old, 'reason': rsn}
            )
            upd += 1
        conn.commit()
        return {'ok': True, 'updated': upd}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        try:
            conn.close()
        except:
            pass


def _collect(cur, mode, cn, si, sf, st2, ia):
    ids = []
    if mode == 'class' and cn:
        ph = ','.join(['?' for _ in cn])
        cur.execute(sql_placeholder(f"SELECT id FROM students WHERE class_name IN ({ph})"), tuple(cn))
        ids = [int((r['id'] if isinstance(r, dict) else r[0])) for r in (cur.fetchall() or [])]
    elif mode == 'students' and si:
        ids = [int(x) for x in si if int(x) > 0]
    elif mode == 'serial_range' and sf > 0 and st2 >= sf:
        cur.execute(sql_placeholder("SELECT id FROM students WHERE serial_number>=? AND serial_number<=?"), (sf, st2))
        ids = [int((r['id'] if isinstance(r, dict) else r[0])) for r in (cur.fetchall() or [])]
    elif mode == 'all_school' and ia:
        cur.execute("SELECT id FROM students")
        ids = [int((r['id'] if isinstance(r, dict) else r[0])) for r in (cur.fetchall() or [])]
    return ids


def _reason(op, pts):
    if op == 'add':
        return '\u05e2\u05d3\u05db\u05d5\u05df \u05de\u05d4\u05d9\u05e8 +' + str(pts)
    elif op == 'subtract':
        return '\u05e2\u05d3\u05db\u05d5\u05df \u05de\u05d4\u05d9\u05e8 -' + str(abs(pts))
    return '\u05e2\u05d3\u05db\u05d5\u05df \u05de\u05d4\u05d9\u05e8 = ' + str(max(0, pts))


def _calc(op, old, pts):
    if op == 'add':
        return old + pts
    elif op == 'subtract':
        return max(0, old - abs(pts))
    return max(0, pts)


def _log(cur, sid, old, nw, rsn):
    try:
        if USE_POSTGRES:
            cur.execute(
                "INSERT INTO points_log(student_id,old_points,new_points,delta,reason,actor_name,action_type,created_at)"
                " VALUES(%s,%s,%s,%s,%s,%s,%s,CURRENT_TIMESTAMP)",
                (sid, old, nw, nw - old, rsn, 'web', 'quick_update'))
        else:
            cur.execute(
                "INSERT INTO points_log(student_id,old_points,new_points,delta,reason,actor_name,action_type,created_at)"
                " VALUES(?,?,?,?,?,?,?,datetime('now'))",
                (sid, old, nw, nw - old, rsn, 'web', 'quick_update'))
    except Exception:
        pass


@router.get("/web/quick-update", response_class=HTMLResponse)
def web_quick_update(request: Request):
    guard = web_require_teacher(request)
    if guard:
        return guard
    teacher = web_current_teacher(request) or {}
    ia = int(teacher.get('is_admin') or 0) == 1
    ao = '<option value="all_school">\u05db\u05dc \u05d1\u05d9\u05ea \u05d4\u05e1\u05e4\u05e8</option>' if ia else ''
    return basic_web_shell("\u05e2\u05d3\u05db\u05d5\u05df \u05de\u05d4\u05d9\u05e8", _page(ao), request=request)


def _page(ao):
    return (
        '<div style="max-width:800px;margin:0 auto;">'
        '<h2 style="margin-bottom:20px;">&#9889; \u05e2\u05d3\u05db\u05d5\u05df \u05de\u05d4\u05d9\u05e8</h2>'
        '<div class="card" style="padding:20px;margin-bottom:20px;">'
        '<div style="display:flex;gap:15px;flex-wrap:wrap;align-items:flex-end;margin-bottom:16px;">'
        '<div style="flex:1;min-width:120px;">'
        '<label style="display:block;margin-bottom:4px;font-weight:600;">\u05e0\u05e7\u05d5\u05d3\u05d5\u05ea</label>'
        '<input type="number" id="qu-pts" class="form-input" value="1" min="0" style="font-size:18px;text-align:center;">'
        '</div>'
        '<div style="flex:1;min-width:160px;">'
        '<label style="display:block;margin-bottom:4px;font-weight:600;">\u05e4\u05e2\u05d5\u05dc\u05d4</label>'
        '<select id="qu-op" class="form-input">'
        '<option value="add">\u05d4\u05d5\u05e1\u05e4\u05d4 (+)</option>'
        '<option value="subtract">\u05d7\u05d9\u05e1\u05d5\u05e8 (-)</option>'
        '<option value="set">\u05de\u05d5\u05d7\u05dc\u05d8 (=)</option>'
        '</select></div></div>'
        '<div style="margin-bottom:16px;">'
        '<label style="display:block;margin-bottom:4px;font-weight:600;">\u05e1\u05d5\u05d2 \u05e2\u05d3\u05db\u05d5\u05df</label>'
        '<select id="qu-mode" class="form-input" onchange="modeChanged()">'
        '<option value="class">\u05dc\u05e4\u05d9 \u05db\u05d9\u05ea\u05d4</option>'
        '<option value="students">\u05ea\u05dc\u05de\u05d9\u05d3\u05d9\u05dd \u05e0\u05d1\u05d7\u05e8\u05d9\u05dd</option>'
        '<option value="serial_range">\u05d8\u05d5\u05d5\u05d7 \u05de\u05e1\u05f3 \u05e1\u05d9\u05d3\u05d5\u05e8\u05d9</option>'
        + ao +
        '</select></div>'
        + _sections() + _script()
        + '</div></div>'
    )


def _sections():
    return (
        '<div id="sec-class" style="margin-bottom:16px;">'
        '<label style="display:block;margin-bottom:4px;font-weight:600;">\u05d1\u05d7\u05e8 \u05db\u05d9\u05ea\u05d5\u05ea</label>'
        '<div id="cls-list" style="display:flex;flex-wrap:wrap;gap:8px;margin-top:6px;"></div></div>'
        '<div id="sec-students" style="margin-bottom:16px;display:none;">'
        '<label style="display:block;margin-bottom:4px;font-weight:600;">\u05d1\u05d7\u05e8 \u05ea\u05dc\u05de\u05d9\u05d3\u05d9\u05dd</label>'
        '<input type="text" id="stu-search" class="form-input" placeholder="\u05d7\u05d9\u05e4\u05d5\u05e9..." onkeyup="filterStu()" style="margin-bottom:8px;">'
        '<div id="stu-list" style="max-height:250px;overflow-y:auto;border:1px solid #ddd;border-radius:6px;padding:6px;"></div>'
        '<div style="margin-top:4px;font-size:12px;"><span id="stu-cnt">0</span> \u05e0\u05d1\u05d7\u05e8\u05d5 | '
        '<a href="#" onclick="togStu(true);return false;">\u05d1\u05d7\u05e8 \u05d4\u05db\u05dc</a> | '
        '<a href="#" onclick="togStu(false);return false;">\u05e0\u05e7\u05d4</a></div></div>'
        '<div id="sec-serial" style="margin-bottom:16px;display:none;">'
        '<div style="display:flex;gap:10px;">'
        '<div><label style="display:block;margin-bottom:4px;font-weight:600;">\u05de-</label>'
        '<input type="number" id="qu-sf" class="form-input" min="1"></div>'
        '<div><label style="display:block;margin-bottom:4px;font-weight:600;">\u05e2\u05d3</label>'
        '<input type="number" id="qu-st" class="form-input" min="1"></div></div></div>'
        '<div id="sec-all" style="margin-bottom:16px;display:none;padding:12px;background:#fff3cd;border-radius:8px;border:1px solid #ffc107;color:#856404;">'
        '<strong>&#9888;&#65039;</strong> \u05d4\u05e2\u05d3\u05db\u05d5\u05df \u05d9\u05d7\u05d5\u05dc \u05e2\u05dc \u05db\u05dc \u05ea\u05dc\u05de\u05d9\u05d3\u05d9 \u05d1\u05d9\u05ea \u05d4\u05e1\u05e4\u05e8!</div>'
        '<button class="green" onclick="doUpdate()" style="width:100%;font-size:16px;padding:14px;">&#9889; \u05d1\u05e6\u05e2 \u05e2\u05d3\u05db\u05d5\u05df</button>'
        '<div id="qu-result" style="margin-top:12px;text-align:center;font-weight:bold;display:none;"></div>'
    )


def _script():
    return """<script>
let allStu=[],selIds=new Set();
async function loadData(){
  try{const r=await fetch('/api/students');const d=await r.json();allStu=d.items||[];renderStu();}catch(e){}
  try{const r=await fetch('/api/classes');const d=await r.json();renderCls(d.items||[]);}catch(e){}
}
function renderCls(cls){
  const el=document.getElementById('cls-list');
  el.innerHTML=cls.map(c=>'<label style="display:flex;align-items:center;gap:4px;padding:6px 10px;background:#eef;border-radius:6px;cursor:pointer;"><input type="checkbox" class="cls-cb" value="'+esc(c)+'" checked> '+esc(c)+'</label>').join('');
}
function renderStu(){
  const q=(document.getElementById('stu-search').value||'').trim().toLowerCase();
  const el=document.getElementById('stu-list');let html='';
  allStu.forEach(s=>{
    const nm=((s.first_name||'')+' '+(s.last_name||'')+' '+(s.class_name||'')).toLowerCase();
    if(q&&nm.indexOf(q)<0)return;
    const chk=selIds.has(s.id)?'checked':'';
    html+='<label style="display:flex;align-items:center;gap:6px;padding:4px 6px;border-bottom:1px solid #f0f0f0;cursor:pointer;"><input type="checkbox" onchange="togOne('+s.id+',this.checked)" '+chk+'> '+esc(s.first_name)+' '+esc(s.last_name)+' <span style="color:#888;font-size:12px;">('+esc(s.class_name)+')</span></label>';
  });
  el.innerHTML=html||'<div style="padding:12px;text-align:center;color:#999;">---</div>';
  document.getElementById('stu-cnt').textContent=selIds.size;
}
function filterStu(){renderStu();}
function togOne(id,on){if(on)selIds.add(id);else selIds.delete(id);document.getElementById('stu-cnt').textContent=selIds.size;}
function togStu(on){allStu.forEach(s=>{if(on)selIds.add(s.id);else selIds.delete(s.id);});renderStu();}
function modeChanged(){
  const m=document.getElementById('qu-mode').value;
  document.getElementById('sec-class').style.display=m=='class'?'':'none';
  document.getElementById('sec-students').style.display=m=='students'?'':'none';
  document.getElementById('sec-serial').style.display=m=='serial_range'?'':'none';
  document.getElementById('sec-all').style.display=m=='all_school'?'':'none';
}
async function doUpdate(){
  const pts=parseInt(document.getElementById('qu-pts').value)||0;
  const op=document.getElementById('qu-op').value;
  const mode=document.getElementById('qu-mode').value;
  if(pts<=0&&op!='set'){alert('\\u05d9\\u05e9 \\u05dc\\u05d4\\u05d6\\u05d9\\u05df \\u05e0\\u05e7\\u05d5\\u05d3\\u05d5\\u05ea');return;}
  let body={mode:mode,operation:op,points:pts};
  if(mode=='class'){
    const cbs=document.querySelectorAll('.cls-cb:checked');
    body.class_names=[...cbs].map(c=>c.value);
    if(!body.class_names.length){alert('\\u05d1\\u05d7\\u05e8 \\u05db\\u05d9\\u05ea\\u05d4');return;}
  }else if(mode=='students'){
    body.student_ids=[...selIds];
    if(!body.student_ids.length){alert('\\u05d1\\u05d7\\u05e8 \\u05ea\\u05dc\\u05de\\u05d9\\u05d3\\u05d9\\u05dd');return;}
  }else if(mode=='serial_range'){
    body.serial_from=parseInt(document.getElementById('qu-sf').value)||0;
    body.serial_to=parseInt(document.getElementById('qu-st').value)||0;
    if(body.serial_from<=0||body.serial_to<body.serial_from){alert('\\u05d8\\u05d5\\u05d5\\u05d7 \\u05dc\\u05d0 \\u05ea\\u05e7\\u05d9\\u05df');return;}
  }
  if(mode=='all_school'&&!confirm('\\u05e2\\u05d3\\u05db\\u05d5\\u05df \\u05dc\\u05db\\u05dc \\u05d1\\u05d9\\u05ea \\u05d4\\u05e1\\u05e4\\u05e8?'))return;
  if(op=='set'&&!confirm('\\u05e4\\u05e2\\u05d5\\u05dc\\u05d4 \\u05de\\u05d5\\u05d7\\u05dc\\u05d8\\u05ea - \\u05ea\\u05e7\\u05d1\\u05e2 \\u05e0\\u05e7\\u05d5\\u05d3\\u05d5\\u05ea. \\u05d1\\u05d8\\u05d5\\u05d7?'))return;
  const res=document.getElementById('qu-result');
  res.style.display='block';res.style.color='#888';res.textContent='\\u05de\\u05e2\\u05d3\\u05db\\u05df...';
  try{
    const r=await fetch('/api/students/bulk-quick-update',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const d=await r.json();
    if(d.ok){res.style.color='#27ae60';res.textContent='\\u2713 \\u05e2\\u05d5\\u05d3\\u05db\\u05e0\\u05d5 '+d.updated+' \\u05ea\\u05dc\\u05de\\u05d9\\u05d3\\u05d9\\u05dd';loadData();}
    else{res.style.color='#e74c3c';res.textContent=(d.detail||'error');}
  }catch(e){res.style.color='#e74c3c';res.textContent=''+e;}
}
function esc(s){return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
loadData();
</script>"""
