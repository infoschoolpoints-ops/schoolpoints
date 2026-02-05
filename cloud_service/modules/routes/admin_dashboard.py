from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..ui import basic_web_shell
from ..auth import web_require_teacher, web_current_teacher, web_master_ok
from ..auth import safe_int

router = APIRouter()

@router.get("/web/admin", response_class=HTMLResponse)
def web_admin(request: Request):
    guard = web_require_teacher(request)
    if guard:
        return guard
    
    teacher = web_current_teacher(request)
    if not teacher:
        if web_master_ok(request):
            teacher = {'id': 0, 'name': 'מנהל על', 'is_admin': 1}
        else:
            return RedirectResponse(url="/web/teacher-login", status_code=302)
        
    is_admin = bool(safe_int(teacher.get('is_admin'), 0) == 1)
    
    tiles_html = ""
    
    # Students (Everyone)
    tiles_html += """
    <a href="/web/students" class="tile blue">
      <div class="icon">🎓</div>
      <div class="label">תלמידים</div>
    </a>
    """
    
    if is_admin:
        tiles_html += """
        <a href="/web/teachers" class="tile red">
          <div class="icon">👥</div>
          <div class="label">מורים</div>
        </a>
        <a href="/web/classes" class="tile orange">
          <div class="icon">🏫</div>
          <div class="label">כיתות</div>
        </a>
        <a href="/web/import" class="tile dark">
          <div class="icon">📥</div>
          <div class="label">ייבוא</div>
        </a>
        <a href="/web/reports" class="tile cyan">
          <div class="icon">📤</div>
          <div class="label">ייצוא</div>
        </a>
        <a href="/web/upgrades" class="tile orange">
          <div class="icon">🎁</div>
          <div class="label">שדרוגים</div>
        </a>
        <a href="/web/messages" class="tile purple">
          <div class="icon">💬</div>
          <div class="label">הודעות כלליות</div>
        </a>
        <a href="/web/special-bonus" class="tile pink">
          <div class="icon">✨</div>
          <div class="label">בונוס מיוחד</div>
        </a>
        <a href="/web/time-bonus" class="tile teal">
          <div class="icon">⏱️</div>
          <div class="label">בונוס זמנים</div>
        </a>
        <a href="/web/system-settings" class="tile gray">
          <div class="icon">⚙️</div>
          <div class="label">הגדרות מערכת</div>
        </a>
        <a href="/web/display-settings" class="tile gray">
          <div class="icon">🖥️</div>
          <div class="label">הגדרות תצוגה</div>
        </a>
        <a href="/web/purchases" class="tile indigo">
          <div class="icon">🛒</div>
          <div class="label">קניות</div>
        </a>
        <a href="/web/holidays" class="tile green">
          <div class="icon">📅</div>
          <div class="label">חגים</div>
        </a>
        <a href="/web/max-points" class="tile red">
          <div class="icon">📉</div>
          <div class="label">מגבלת ניקוד</div>
        </a>
        <a href="/web/anti-spam" class="tile orange">
          <div class="icon">🛡️</div>
          <div class="label">אנטי-ספאם</div>
        </a>
        <a href="/web/quiet-mode" class="tile teal">
          <div class="icon">🌙</div>
          <div class="label">מצב שקט</div>
        </a>
        <a href="/web/settings" class="tile dark">
          <div class="icon">🏢</div>
          <div class="label">הגדרות עמדת ניהול</div>
        </a>
        """
    
    # Personal Area (Everyone)
    tiles_html += """
    <a href="/web/personal" class="tile dark">
      <div class="icon">👤</div>
      <div class="label">אזור אישי</div>
    </a>
    """

    body = f"""
    <style>
      .dashboard-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 16px; padding: 10px 0; }}
      .tile {{ display: flex; flex-direction: column; align-items: center; justify-content: center; height: 120px; border-radius: 16px; text-decoration: none; color: white; transition: transform 0.2s, box-shadow 0.2s; box-shadow: 0 4px 10px rgba(0,0,0,0.15); position:relative; overflow:hidden; }}
      .tile:hover {{ transform: translateY(-4px); box-shadow: 0 8px 20px rgba(0,0,0,0.25); }}
      .tile .icon {{ font-size: 42px; margin-bottom: 8px; text-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
      .tile .label {{ font-weight: 700; font-size: 16px; text-shadow: 0 1px 2px rgba(0,0,0,0.2); text-align:center; padding:0 8px; }}
      
      .tile.blue {{ background: linear-gradient(135deg, #3498db, #2980b9); }}
      .tile.red {{ background: linear-gradient(135deg, #e74c3c, #c0392b); }}
      .tile.purple {{ background: linear-gradient(135deg, #9b59b6, #8e44ad); }}
      .tile.orange {{ background: linear-gradient(135deg, #e67e22, #d35400); }}
      .tile.yellow {{ background: linear-gradient(135deg, #f1c40f, #f39c12); }}
      .tile.green {{ background: linear-gradient(135deg, #2ecc71, #27ae60); }}
      .tile.teal {{ background: linear-gradient(135deg, #1abc9c, #16a085); }}
      .tile.pink {{ background: linear-gradient(135deg, #e91e63, #c2185b); }}
      .tile.indigo {{ background: linear-gradient(135deg, #3f51b5, #303f9f); }}
      .tile.cyan {{ background: linear-gradient(135deg, #00bcd4, #0097a7); }}
      .tile.gray {{ background: linear-gradient(135deg, #95a5a6, #7f8c8d); }}
      .tile.dark {{ background: linear-gradient(135deg, #34495e, #2c3e50); }}
    </style>
    
    <div class="dashboard-grid">
      {tiles_html}
    </div>
    """
    return basic_web_shell("לוח בקרה", body, request=request)
