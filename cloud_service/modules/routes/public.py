from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, Response, FileResponse
from ..ui import public_web_shell, basic_web_shell
from ..utils import read_text_file, replace_guide_base64_images
from ..config import ROOT_DIR
import os
import re

router = APIRouter()

@router.get('/web/assets/{asset_path:path}', include_in_schema=False)
def web_assets(asset_path: str) -> Response:
    rel = str(asset_path or '').replace('\\', '/').lstrip('/')
    if not rel or '..' in rel:
        raise HTTPException(status_code=404, detail='Not found')

    rel_l = rel.lower()
    base = ROOT_DIR
    if rel_l.startswith('icons/'):
        base = os.path.join(ROOT_DIR, 'icons')
        rel = rel[len('icons/'):]
    elif rel_l.startswith('guide_images/'):
        base = os.path.join(ROOT_DIR, 'תמונות', 'להוראות')
        rel = rel[len('guide_images/'):]
    elif rel_l.startswith('equipment_required_files/'):
        base = os.path.join(ROOT_DIR, 'equipment_required_files')
        rel = rel[len('equipment_required_files/'):]
    
    full_path = os.path.join(base, rel)
    if not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail='Not found')
    return FileResponse(full_path)

@router.get('/', include_in_schema=False)
def root() -> Response:
    return RedirectResponse(url="/web", status_code=302)

@router.get('/admin', include_in_schema=False)
def admin_redirect() -> Response:
    return RedirectResponse(url="/admin/login", status_code=302)

_HOME_CARDS = """
<div style="margin-top:50px;text-align:center;position:relative;z-index:5;">
  <h2 style="font-size:32px;font-weight:900;margin-bottom:8px;background:linear-gradient(135deg,#2ecc71,#00cec9);-webkit-background-clip:text;-webkit-text-fill-color:transparent;">למה SchoolPoints?</h2>
  <p style="font-size:16px;opacity:.8;max-width:620px;margin:0 auto 30px;line-height:1.7;">הפלטפורמה שהופכת כל מבצע חינוכי לחוויה מרגשת &mdash; כרטיסים חכמים, מעקב בזמן אמת ותגמול שמניע להצטיינות.</p>
</div>
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:20px;max-width:1100px;margin:0 auto;position:relative;z-index:5;">
  <div class="glass" style="padding:26px;border-radius:20px;text-align:center;">
    <div style="font-size:44px;margin-bottom:12px;">🏆</div>
    <div style="font-weight:900;font-size:20px;margin-bottom:10px;color:#fff;">הצטיינות והתמדה</div>
    <div style="font-size:15px;opacity:.8;line-height:1.6;">תלמידים צוברים נקודות על הישגים, הגעה בזמן והתנהגות מצטיינת. תחרות חיובית שמעלה מוטיבציה!</div>
  </div>
  <div class="glass" style="padding:26px;border-radius:20px;text-align:center;">
    <div style="font-size:44px;margin-bottom:12px;">💳</div>
    <div style="font-weight:900;font-size:20px;margin-bottom:10px;color:#fff;">כרטיס אישי חכם</div>
    <div style="font-size:15px;opacity:.8;line-height:1.6;">לכל תלמיד כרטיס מהודר ואישי &mdash; לא עוד ניירות שנאבדות! העברה מהירה בעמדה, יתרה מעודכנת תמיד.</div>
  </div>
  <div class="glass" style="padding:26px;border-radius:20px;text-align:center;">
    <div style="font-size:44px;margin-bottom:12px;">📊</div>
    <div style="font-weight:900;font-size:20px;margin-bottom:10px;color:#fff;">מעקב והתקדמות</div>
    <div style="font-size:15px;opacity:.8;line-height:1.6;">הצוות החינוכי עוקב אחר מצב כל תלמיד בלוח בקרה אחד. דוחות, גרפים ותובנות לשיפור מתמיד.</div>
  </div>
  <div class="glass" style="padding:26px;border-radius:20px;text-align:center;">
    <div style="font-size:44px;margin-bottom:12px;">🎁</div>
    <div style="font-weight:900;font-size:20px;margin-bottom:10px;color:#fff;">תגמול נאה ושמחה</div>
    <div style="font-size:15px;opacity:.8;line-height:1.6;">אווירת מבצע מרגשת! תלמידים מממשים נקודות לפרסים, חוויות וקניות &mdash; שמחה וסיפוק אמיתיים.</div>
  </div>
  <div class="glass" style="padding:26px;border-radius:20px;text-align:center;">
    <div style="font-size:44px;margin-bottom:12px;">👥</div>
    <div style="font-weight:900;font-size:20px;margin-bottom:10px;color:#fff;">מעקב צוותי</div>
    <div style="font-size:15px;opacity:.8;line-height:1.6;">מחנכים ורכזים רואים את ההתקדמות של כל תלמיד ותלמידה, מזהים מי צריך חיזוק ומי בדרך להצטיינות.</div>
  </div>
  <div class="glass" style="padding:26px;border-radius:20px;text-align:center;">
    <div style="font-size:44px;margin-bottom:12px;">🚀</div>
    <div style="font-weight:900;font-size:20px;margin-bottom:10px;color:#fff;">פשוט להתחיל</div>
    <div style="font-size:15px;opacity:.8;line-height:1.6;">התקנה מהירה, ייבוא תלמידים מאקסל, הדפסת כרטיסים ותוך דקות &mdash; המבצע באוויר!</div>
  </div>
</div>
"""

@router.get('/web', response_class=HTMLResponse)
@router.get('/web/', response_class=HTMLResponse)
def web_home() -> str:
    # Use some guide images for the montage
    montage_images = ['01.png', '02.png', '03.png', '04.png']
    
    body = f"""
    <style>
      .hero-section {{
        text-align: center;
        padding: 40px 20px;
        position: relative;
        overflow: hidden;
      }}
      
      .hero-title {{
        font-size: 56px;
        font-weight: 900;
        margin-bottom: 16px;
        background: linear-gradient(135deg, #ffffff 0%, #a5b1c2 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        text-shadow: 0 10px 30px rgba(0,0,0,0.3);
      }}
      
      .hero-subtitle {{
        font-size: 20px;
        opacity: 0.9;
        max-width: 700px;
        margin: 0 auto 40px;
        line-height: 1.6;
        color: #dfe6e9;
      }}
      
      .montage-container {{
        position: relative;
        height: 300px;
        margin: 40px auto;
        max-width: 1000px;
        perspective: 1000px;
        pointer-events: none;
      }}
      
      .montage-card {{
        position: absolute;
        border-radius: 12px;
        box-shadow: 0 15px 35px rgba(0,0,0,0.4);
        border: 1px solid rgba(255,255,255,0.2);
        transition: transform 0.5s ease;
        background: rgba(255,255,255,0.1);
        backdrop-filter: blur(5px);
        overflow: hidden;
      }}
      
      .montage-card img {{
        width: 100%;
        height: auto;
        display: block;
        opacity: 0.9;
      }}
      
      /* Floating Animation */
      @keyframes float {{
        0% {{ transform: translateY(0px) rotate(var(--rot)); }}
        50% {{ transform: translateY(-10px) rotate(var(--rot)); }}
        100% {{ transform: translateY(0px) rotate(var(--rot)); }}
      }}
      
      .card-1 {{ top: 10px; left: 10%; width: 220px; transform: rotate(-6deg); --rot: -6deg; animation: float 6s ease-in-out infinite; z-index: 2; }}
      .card-2 {{ top: 40px; right: 10%; width: 240px; transform: rotate(5deg); --rot: 5deg; animation: float 7s ease-in-out infinite 1s; z-index: 2; }}
      .card-3 {{ top: 80px; left: 35%; width: 300px; transform: rotate(0deg); --rot: 0deg; animation: float 8s ease-in-out infinite 0.5s; z-index: 3; box-shadow: 0 20px 50px rgba(0,0,0,0.6); }}
      
      .stars {{
        position: absolute;
        top: 0; left: 0; right: 0; bottom: 0;
        pointer-events: none;
        z-index: 0;
      }}
      .star {{
        position: absolute;
        background: white;
        border-radius: 50%;
        animation: twinkle var(--dur) ease-in-out infinite;
        opacity: var(--op);
      }}
      @keyframes twinkle {{
        0%, 100% {{ opacity: var(--op); transform: scale(1); }}
        50% {{ opacity: 0; transform: scale(0.5); }}
      }}

    </style>

    <div class="hero-section">
        <!-- Stars Background -->
        <div class="stars">
            {''.join([f'<div class="star" style="top:{x*7}%; left:{y*13}%; width:{s}px; height:{s}px; --dur:{d}s; --op:{o};"></div>' for x,y,s,d,o in [(1,5,2,3,0.8), (8,2,3,4,0.6), (2,8,2,5,0.9), (6,6,3,3,0.7), (3,3,2,6,0.5), (7,9,2,4,0.8)]])}
        </div>

        <h1 class="hero-title">תוכנת הנקודות</h1>
        <p class="hero-subtitle">
            המערכת המתקדמת לניהול נקודות, תלמידים ורכישות במוסדות חינוך.<br/>
            סנכרון מלא לענן, עיצוב חדשני וחווית משתמש מושלמת.
        </p>
      
        <div class="actionbar" style="justify-content:center; gap:20px; margin-bottom:40px; position:relative; z-index:10;">
            <a class="btn-glass primary" href="/web/signin" style="padding:16px 32px; font-size:18px;">כניסה למערכת</a>
            <a class="btn-glass" href="/web/register" style="padding:16px 32px; font-size:18px;">הרשמה למוסד</a>
        </div>
        
        <div class="actionbar" style="justify-content:center; gap:16px; margin-bottom:20px; position:relative; z-index:10;">
            <a href="/web/guide" style="color:rgba(255,255,255,0.8); font-weight:700; display:flex; align-items:center; gap:6px; font-size:16px;">
                <span style="font-size:20px;">📚</span> מדריך למשתמש
            </a>
            <span style="opacity:0.3;">|</span>
            <a href="/web/contact" style="color:rgba(255,255,255,0.8); font-weight:700; display:flex; align-items:center; gap:6px; font-size:16px;">
                <span style="font-size:20px;">✉️</span> צור קשר
            </a>
            <span style="opacity:0.3;">|</span>
             <a href="/web/download" style="color:rgba(255,255,255,0.8); font-weight:700; display:flex; align-items:center; gap:6px; font-size:16px;">
                <span style="font-size:20px;">⬇️</span> הורדה
            </a>
        </div>

        <div class="montage-container">
            <div class="montage-card card-1"><img src="/web/assets/guide_images/02.png" alt="Screen 1"></div>
            <div class="montage-card card-2"><img src="/web/assets/guide_images/06.png" alt="Screen 2"></div>
            <div class="montage-card card-3"><img src="/web/assets/guide_images/01.png" alt="Screen 3"></div>
        </div>

        """ + _HOME_CARDS + """

    <div style="max-width:900px;margin:40px auto 10px;position:relative;z-index:5;padding:0 16px;">
      <a href="/web/callback" style="text-decoration:none;display:block;">
        <div style="background:linear-gradient(135deg,#f7971e 0%,#ffd200 100%);border-radius:22px;padding:36px 40px;text-align:center;box-shadow:0 12px 40px rgba(247,151,30,.35);transition:transform .25s,box-shadow .25s;" onmouseover="this.style.transform='translateY(-4px)';this.style.boxShadow='0 20px 54px rgba(247,151,30,.5)'" onmouseout="this.style.transform='';this.style.boxShadow='0 12px 40px rgba(247,151,30,.35)'">
          <div style="font-size:42px;margin-bottom:10px;">📞</div>
          <div style="font-size:30px;font-weight:900;color:#1a1a2e;margin-bottom:8px;">דווקא מעניין אותי! תחזרו אלי</div>
          <div style="font-size:17px;color:#2d2d2d;opacity:.85;max-width:560px;margin:0 auto;">מלאו פרטים קצרים ונחזור אליכם עם הצעה מותאמת לבית ספרכם</div>
          <div style="margin-top:18px;display:inline-block;background:#1a1a2e;color:#ffd200;font-weight:800;font-size:16px;padding:11px 34px;border-radius:10px;letter-spacing:.3px;">מלאו טופס פנייה &rsaquo;</div>
        </div>
      </a>
    </div>

    </div>
    """
    return public_web_shell('תוכנת הנקודות', body)

@router.get('/web/equipment-required', response_class=HTMLResponse)
def web_equipment_required(request: Request) -> str:
    html_content = ""
    for fname in ('equipment_required.html', 'equipment-required.html'):
        path = os.path.join(ROOT_DIR, fname)
        html_content = read_text_file(path)
        if html_content:
            break

    _logged_in = False
    try:
        from ..auth import web_current_teacher, web_tenant_from_cookie, web_master_ok
        if web_current_teacher(request) or web_tenant_from_cookie(request) or web_master_ok(request):
            _logged_in = True
    except Exception:
        pass

    _back_btn = '<div style="margin-bottom:20px;"><a href="/web/guide" class="btn-glass primary">← חזרה למדריך</a></div>'
    _back_btn_bottom = '<div style="margin-top:28px;text-align:center;"><a href="/web/guide" class="btn-glass primary">← חזרה למדריך</a></div>'

    if not html_content:
        body = "<h2>ציוד נדרש</h2><p>דף הציוד הנדרש עדיין לא זמין.</p><div class=\"actionbar\"><a class=\"gray\" href=\"/web/guide\">חזרה למדריך</a></div>"
        if _logged_in:
            return basic_web_shell('ציוד נדרש', body, request=request)
        return public_web_shell('ציוד נדרש', body, request=request)

    import re as _re2
    html_content = html_content.replace('src="guide_images/', 'src="/web/assets/guide_images/')
    html_content = html_content.replace('src="images/', 'src="/web/assets/guide_images/')
    html_content = html_content.replace('href="guide_index.html"', 'href="/web/guide"')
    inner = html_content
    body_match2 = _re2.search(r'<body[^>]*>(.*)</body>', inner, _re2.DOTALL | _re2.IGNORECASE)
    if body_match2:
        inner = body_match2.group(1)
    style_parts2 = _re2.findall(r'(<style[^>]*>.*?</style>)', html_content, _re2.DOTALL | _re2.IGNORECASE)
    style_block2 = '\n'.join(style_parts2) if style_parts2 else ''
    wrapped2 = style_block2 + '<div style="max-width:100%;overflow-x:auto;">' + inner + '</div>'

    if _logged_in:
        full_body2 = _back_btn + wrapped2 + _back_btn_bottom
        return basic_web_shell('ציוד נדרש', full_body2, request=request)
    return public_web_shell('ציוד נדרש', wrapped2, request=request)


@router.get('/web/guide', response_class=HTMLResponse)
def web_guide(request: Request) -> str:
    html_content = ""
    for name in ('guide_user_embedded.html', 'guide_user.html', 'guide_index.html'):
        path = os.path.join(ROOT_DIR, name)
        html_content = read_text_file(path)
        if html_content:
            break

    # Detect if user is logged in (teacher session or institution session)
    _logged_in = False
    try:
        from ..auth import web_current_teacher, web_tenant_from_cookie, web_master_ok
        if web_current_teacher(request) or web_tenant_from_cookie(request) or web_master_ok(request):
            _logged_in = True
    except Exception:
        pass

    _back_btn = '<div style="margin-bottom:20px;"><a href="/web/admin" class="btn-glass primary">← חזרה ללוח הבקרה</a></div>'
    _back_btn_bottom = '<div style="margin-top:28px;text-align:center;"><a href="/web/admin" class="btn-glass primary">← חזרה ללוח הבקרה</a></div>'

    if not html_content:
        body = "<h2>מדריך</h2><p>המדריך עדיין לא זמין.</p><div class=\"actionbar\"><a class=\"gray\" href=\"/web\">חזרה</a></div>"
        if _logged_in:
            return basic_web_shell('מדריך', body, request=request)
        return public_web_shell('מדריך', body, request=request)

    # Fix image/link paths
    html_content = html_content.replace('src="guide_images/', 'src="/web/assets/guide_images/')
    html_content = html_content.replace('src="images/', 'src="/web/assets/guide_images/')
    html_content = html_content.replace('href="equipment_required.html"', 'href="/web/equipment-required"')
    # Strip any existing <html>/<head>/<body> tags to embed in shell
    import re as _re
    inner = html_content
    # Extract body content if full HTML doc
    body_match = _re.search(r'<body[^>]*>(.*)</body>', inner, _re.DOTALL | _re.IGNORECASE)
    if body_match:
        inner = body_match.group(1)
    # Extract inline styles from head to preserve them
    style_parts = _re.findall(r'(<style[^>]*>.*?</style>)', html_content, _re.DOTALL | _re.IGNORECASE)
    style_block = '\n'.join(style_parts) if style_parts else ''
    wrapped = style_block + '<div style="max-width:100%;overflow-x:auto;">' + inner + '</div>'

    if _logged_in:
        full_body = _back_btn + wrapped + _back_btn_bottom
        return basic_web_shell('\u05de\u05d3\u05e8\u05d9\u05da', full_body, request=request)
    return public_web_shell('\u05de\u05d3\u05e8\u05d9\u05da', wrapped, request=request)

@router.get('/web/pricing', response_class=HTMLResponse)
def web_pricing() -> str:
    import json as _json
    from ..admin_db import ensure_admin_tables, get_all_plans
    ensure_admin_tables()
    plans = [p for p in get_all_plans()
             if int(p.get('is_active') or 0) == 1
             and int(p.get('is_visible') if p.get('is_visible') is not None else 1) == 1]

    cards_html = ""
    for p in plans:
        pk = p.get('plan_key', '')
        name = p.get('display_name', '')
        price = int(p.get('price_monthly') or 0)
        dur = int(p.get('duration_months') or 1)
        total = price * dur
        desc = p.get('description', '')
        featured = int(p.get('is_featured') or 0)
        feats_raw = p.get('features_json', '[]')
        try:
            feats = _json.loads(feats_raw) if isinstance(feats_raw, str) else feats_raw
        except Exception:
            feats = []
        feat_html = ''.join(f'<li>{f}</li>' for f in feats if f)

        featured_cls = ' featured' if featured else ''
        badge = '<div style="position:absolute; top:12px; left:-30px; transform:rotate(-45deg); background:#e74c3c; color:white; padding:5px 40px; font-size:12px; font-weight:bold; box-shadow:0 2px 5px rgba(0,0,0,0.2);">מומלץ</div>' if featured else ''

        if dur > 1:
            price_html = f'<div class="pricing-price">₪{price}<span>/חודש</span></div><div style="font-size:16px;margin-top:-14px;margin-bottom:16px;opacity:.85;">סה״כ ל-{dur} חודשים: <b style="color:#2ecc71;">₪{total}</b></div>'
        else:
            price_html = f'<div class="pricing-price">₪{price}<span>/חודש</span></div>'

        cards_html += f'''
        <div class="pricing-card{featured_cls}">
          {badge}
          <div class="pricing-title">{name}</div>
          {price_html}
          <div style="font-size:13px;opacity:.7;margin-bottom:14px;">{desc}</div>
          <ul class="pricing-features">{feat_html}</ul>
          <a href="/web/register?plan={pk}" class="pricing-btn">בחר מסלול</a>
        </div>
        '''

    if not cards_html:
        cards_html = '<div style="text-align:center;opacity:.7;padding:40px;">אין מסלולים זמינים כרגע.</div>'

    body = f"""
    <style>
      .pricing-container {{ display: flex; flex-wrap: wrap; justify-content: center; gap: 20px; margin-top: 30px; }}
      .pricing-card {{ flex: 1; min-width: 280px; max-width: 360px; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); border-radius: 16px; padding: 24px; text-align: center; transition: transform 0.3s, box-shadow 0.3s; position: relative; overflow: hidden; }}
      .pricing-card:hover {{ transform: translateY(-5px); box-shadow: 0 10px 30px rgba(0,0,0,0.3); border-color: rgba(255,255,255,0.2); }}
      .pricing-card.featured {{ background: linear-gradient(145deg, rgba(46, 204, 113, 0.1), rgba(39, 174, 96, 0.15)); border: 1px solid rgba(46, 204, 113, 0.4); transform: scale(1.05); z-index: 1; }}
      .pricing-card.featured:hover {{ transform: scale(1.05) translateY(-5px); }}
      .pricing-title {{ font-size: 24px; font-weight: 900; margin-bottom: 10px; color: #fff; }}
      .pricing-price {{ font-size: 36px; font-weight: 800; margin-bottom: 20px; color: #2ecc71; }}
      .pricing-price span {{ font-size: 16px; font-weight: 400; opacity: 0.7; }}
      .pricing-features {{ text-align: right; margin-bottom: 24px; list-style: none; padding: 0; }}
      .pricing-features li {{ margin-bottom: 10px; padding-right: 20px; position: relative; font-size: 14px; opacity: 0.9; }}
      .pricing-features li::before {{ content: "✓"; position: absolute; right: 0; color: #2ecc71; font-weight: bold; }}
      .pricing-btn {{ display: inline-block; width: 100%; padding: 12px; background: rgba(255,255,255,0.1); color: #fff; border-radius: 10px; font-weight: 700; text-decoration: none; transition: background 0.2s; box-sizing: border-box; }}
      .pricing-btn:hover {{ background: rgba(255,255,255,0.2); }}
      .featured .pricing-btn {{ background: #2ecc71; border: none; }}
      .featured .pricing-btn:hover {{ background: #27ae60; }}
    </style>

    <div style="text-align:center;">
      <h2 style="margin-bottom:10px;">חבילות ומחירים</h2>
      <p style="opacity:0.7;">בחר את המסלול המתאים למוסד שלך</p>
    </div>

    <div class="pricing-container">
      {cards_html}
    </div>

    <div style="text-align:center; margin-top:40px; font-size:14px; opacity:0.6;">
      * המחירים כוללים מע"מ. ניתן לבטל בכל עת.
    </div>
    """
    return public_web_shell("מחירון", body)

@router.get('/web/terms', response_class=HTMLResponse)
def web_terms(request: Request) -> Response:
    body = """
    <div style="line-height:1.9;">
      <h3 style="margin-top:0;">תקנון ותנאי שימוש</h3>
      <div style="opacity:.9;">המסמך נכתב בלשון זכר מטעמי נוחות בלבד ומתייחס לשני המינים.</div>
      <hr style="border:0;border-top:1px solid rgba(255,255,255,0.18); margin:14px 0;" />
      <h4>שימוש במערכת</h4>
      <div>
        המערכת מיועדת לניהול נקודות/תמריצים במוסדות חינוך. המשתמש אחראי לוודא התאמה לצרכי המוסד, לרבות הגדרות,
        הרשאות, תהליכי עבודה, וגיבוי נתונים.
      </div>
      <h4>אחריות והגבלת אחריות</h4>
      <div>
        השירות והתוכנה מסופקים "כמות שהם" (AS IS) וללא התחייבות לזמינות רציפה, לאי-תקלות או להתאמה למטרה מסוימת.
        לא תהיה אחריות לכל נזק עקיף, תוצאתי, אובדן נתונים, אובדן רווחים או פגיעה תפעולית הנובעים מהשימוש במערכת או
        מהסתמכות עליה.
      </div>
      <h4>תמיכה טכנית</h4>
      <div>
        תמיכה טכנית, אם ניתנת, הינה מאמץ סביר בלבד ואינה חלק מהתחייבות חוזית לזמני תגובה/פתרון. ייתכנו תקלות,
        השבתות מתוכננות, או שינויים במערכת ללא הודעה מוקדמת.
      </div>
      <h4>שמירת מידע</h4>
      <div>
        המשתמש אחראי לשמירת סיסמאות, הרשאות וגיבויים. מומלץ להגדיר נהלי עבודה פנימיים ולבצע בדיקות תקופתיות.
      </div>
      <div class="actionbar" style="margin-top:18px;">
        <a class="gray" href="/web/register">חזרה להרשמה</a>
      </div>
    </div>
    """
    return HTMLResponse(public_web_shell('תקנון', body, request=request))

@router.get('/web/download', response_class=HTMLResponse)
def web_download() -> str:
    download_url = "https://drive.google.com/drive/folders/1jM8CpSPbO0avrmNLA3MBcCPXpdC0JGxc?usp=sharing"
    body = f"""
    <div style="text-align:center;">
      <div style="font-size:22px;font-weight:900;">הורדת התוכנה</div>
      <div style="margin-top:10px;line-height:1.8;">ההתקנה נמצאת בתיקיית Google Drive.</div>
      <div class="actionbar" style="justify-content:center;">
        <a class="green" href="{download_url}" target="_blank" rel="noopener">להורדה</a>
        <a class="blue" href="/web/guide">מדריך</a>
        <a class="gray" href="/web">חזרה</a>
      </div>
    </div>
    """
    return public_web_shell("הורדה", body)

@router.get("/web/equipment-required", response_class=HTMLResponse)
def web_equipment_required(request: Request) -> str:
    path = os.path.join(ROOT_DIR, 'equipment_required.html')
    html_content = read_text_file(path)
    if not html_content:
        body = "<h2>רשימת ציוד נדרש</h2><p>העמוד עדיין לא זמין.</p>"
        return public_web_shell("רשימת ציוד נדרש", body)
    
    # Fix image paths
    html_content = html_content.replace('src="equipment_required_files/', 'src="/web/assets/equipment_required_files/')
    html_content = html_content.replace("src='equipment_required_files/", "src='/web/assets/equipment_required_files/")
    # Strip any existing <html>/<head>/<body> tags to embed in shell
    import re as _re
    inner = html_content
    body_match = _re.search(r'<body[^>]*>(.*)</body>', inner, _re.DOTALL | _re.IGNORECASE)
    if body_match:
        inner = body_match.group(1)
    style_parts = _re.findall(r'(<style[^>]*>.*?</style>)', html_content, _re.DOTALL | _re.IGNORECASE)
    style_block = '\n'.join(style_parts) if style_parts else ''
    wrapped = style_block + '<div style="max-width:100%;overflow-x:auto;">' + inner + '</div>'
    return public_web_shell('\u05e6\u05d9\u05d5\u05d3 \u05e0\u05d3\u05e8\u05e9', wrapped, request=request)
