from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, Response, FileResponse
from ..ui import public_web_shell
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

@router.get('/web', response_class=HTMLResponse)
@router.get('/web/', response_class=HTMLResponse)
def web_home() -> str:
    body = f"""
    <div style="text-align:center;">
      <h1 style="font-size:42px; font-weight:900; margin-bottom:10px; background: -webkit-linear-gradient(45deg, #00cec9, #6c5ce7); -webkit-background-clip: text; -webkit-text-fill-color: transparent;">SchoolPoints Cloud</h1>
      <p style="font-size:18px; opacity:0.8; max-width:600px; margin:0 auto 30px;">
        מערכת ניהול נקודות מתקדמת למוסדות חינוך. סנכרון מלא בין עמדות הקצה לענן, ניהול תלמידים, מורים, בונוסים וקניות.
      </p>
      
      <div class="actionbar" style="justify-content:center; gap:16px;">
        <a class="btn-glass primary" href="/web/signin" style="padding:14px 28px; font-size:16px;">כניסה למערכת</a>
        <a class="btn-glass" href="/web/register" style="padding:14px 28px; font-size:16px;">הרשמה למוסד</a>
      </div>

      <div style="margin-top:50px; display:grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap:20px; max-width:1000px; margin-left:auto; margin-right:auto;">
        <div class="glass" style="padding:24px; border-radius:16px; text-align:center;">
          <div style="font-size:32px; margin-bottom:10px;">☁️</div>
          <div style="font-weight:800; font-size:18px; margin-bottom:8px;">ענן היברידי</div>
          <div style="font-size:14px; opacity:0.7;">הנתונים מסונכרנים בזמן אמת בין כל העמדות במוסד לבין הענן.</div>
        </div>
        <div class="glass" style="padding:24px; border-radius:16px; text-align:center;">
          <div style="font-size:32px; margin-bottom:10px;">🎓</div>
          <div style="font-weight:800; font-size:18px; margin-bottom:8px;">תלמידים</div>
          <div style="font-size:14px; opacity:0.7;">מעקב נקודות, רכישות ובונוסים אישי לכל תלמיד.</div>
        </div>
        <div class="glass" style="padding:24px; border-radius:16px; text-align:center;">
          <div style="font-size:32px; margin-bottom:10px;">🛡️</div>
          <div style="font-weight:800; font-size:18px; margin-bottom:8px;">אבטחה</div>
          <div style="font-size:14px; opacity:0.7;">גיבוי נתונים יומי והגנה מתקדמת על המידע.</div>
        </div>
      </div>
      
      <div style="margin-top:40px;">
        <a href="/web/download" style="color:var(--accent-blue); font-weight:700;">הורדת התוכנה למחשב &larr;</a>
      </div>
    </div>
    """
    return public_web_shell('SchoolPoints', body)

@router.get('/web/guide', response_class=HTMLResponse)
def web_guide(request: Request) -> str:
    html_content = ""
    for name in ('guide_user_embedded.html', 'guide_user.html', 'guide_index.html'):
        path = os.path.join(ROOT_DIR, name)
        html_content = read_text_file(path)
        if html_content:
            break

    if not html_content:
        body = "<h2>מדריך</h2><p>המדריך עדיין לא זמין.</p><div class=\"actionbar\"><a class=\"gray\" href=\"/web\">חזרה</a></div>"
        return public_web_shell('מדריך', body, request=request)

    html_content = str(html_content)
    html_content = html_content.replace('file:///C:/ProgramData/SchoolPoints/equipment_required.html', '/web/equipment-required')
    html_content = html_content.replace('file:///C:/%D7%9E%D7%99%D7%A6%D7%93/SchoolPoints/equipment_required.html', '/web/equipment-required')
    html_content = html_content.replace('equipment_required.html', '/web/equipment-required')
    html_content = replace_guide_base64_images(html_content)

    return html_content

@router.get('/web/pricing', response_class=HTMLResponse)
def web_pricing() -> str:
    body = """
    <style>
      .pricing-container { display: flex; flex-wrap: wrap; justify-content: center; gap: 20px; margin-top: 30px; }
      .pricing-card { flex: 1; min-width: 280px; max-width: 320px; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); border-radius: 16px; padding: 24px; text-align: center; transition: transform 0.3s, box-shadow 0.3s; position: relative; overflow: hidden; }
      .pricing-card:hover { transform: translateY(-5px); box-shadow: 0 10px 30px rgba(0,0,0,0.3); border-color: rgba(255,255,255,0.2); }
      .pricing-card.featured { background: linear-gradient(145deg, rgba(46, 204, 113, 0.1), rgba(39, 174, 96, 0.15)); border: 1px solid rgba(46, 204, 113, 0.4); transform: scale(1.05); z-index: 1; }
      .pricing-card.featured:hover { transform: scale(1.05) translateY(-5px); }
      .pricing-title { font-size: 24px; font-weight: 900; margin-bottom: 10px; color: #fff; }
      .pricing-price { font-size: 36px; font-weight: 800; margin-bottom: 20px; color: #2ecc71; }
      .pricing-price span { font-size: 16px; font-weight: 400; opacity: 0.7; }
      .pricing-features { text-align: right; margin-bottom: 24px; list-style: none; padding: 0; }
      .pricing-features li { margin-bottom: 10px; padding-right: 20px; position: relative; font-size: 14px; opacity: 0.9; }
      .pricing-features li::before { content: "✓"; position: absolute; right: 0; color: #2ecc71; font-weight: bold; }
      .pricing-btn { display: inline-block; width: 100%; padding: 12px; background: rgba(255,255,255,0.1); color: #fff; border-radius: 10px; font-weight: 700; text-decoration: none; transition: background 0.2s; box-sizing: border-box; }
      .pricing-btn:hover { background: rgba(255,255,255,0.2); }
      .featured .pricing-btn { background: #2ecc71; border: none; }
      .featured .pricing-btn:hover { background: #27ae60; }
    </style>

    <div style="text-align:center;">
      <h2 style="margin-bottom:10px;">חבילות ומחירים</h2>
      <p style="opacity:0.7;">בחר את המסלול המתאים למוסד שלך</p>
    </div>

    <div class="pricing-container">
      <div class="pricing-card">
        <div class="pricing-title">Basic</div>
        <div class="pricing-price">₪50<span>/חודש</span></div>
        <ul class="pricing-features">
          <li>עד 2 עמדות (מחשבים)</li>
          <li>סנכרון ענן מלא</li>
          <li>ניהול תלמידים ונקודות</li>
          <li>ללא מודול חנות</li>
          <li>תמיכה במייל</li>
        </ul>
        <a href="/web/register?plan=basic" class="pricing-btn">בחר מסלול</a>
      </div>

      <div class="pricing-card featured">
        <div style="position:absolute; top:12px; left:-30px; transform:rotate(-45deg); background:#e74c3c; color:white; padding:5px 40px; font-size:12px; font-weight:bold; box-shadow:0 2px 5px rgba(0,0,0,0.2);">מומלץ</div>
        <div class="pricing-title">Extended</div>
        <div class="pricing-price">₪100<span>/חודש</span></div>
        <ul class="pricing-features">
          <li>עד 5 עמדות</li>
          <li>סנכרון ענן מלא</li>
          <li>כל הפיצ'רים של Basic</li>
          <li>מודול חנות וקניות</li>
          <li>דוחות מתקדמים</li>
          <li>גיבוי היסטוריה ל-3 שנים</li>
        </ul>
        <a href="/web/register?plan=extended" class="pricing-btn">בחר מסלול</a>
      </div>

      <div class="pricing-card">
        <div class="pricing-title">Unlimited</div>
        <div class="pricing-price">₪200<span>/חודש</span></div>
        <ul class="pricing-features">
          <li>ללא הגבלת עמדות</li>
          <li>כל הפיצ'רים של Extended</li>
          <li>מודול קיוסק (Cashier)</li>
          <li>תמיכה טלפונית</li>
          <li>API פתוח לאינטגרציות</li>
          <li>דומיין אישי (אופציונלי)</li>
        </ul>
        <a href="/web/register?plan=unlimited" class="pricing-btn">בחר מסלול</a>
      </div>
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
    
    # Extract body content
    body_content = html_content
    m = re.search(r'<body[^>]*>(.*?)</body>', html_content, re.DOTALL | re.IGNORECASE)
    if m:
        body_content = m.group(1)
        
    # Fix relative paths
    body_content = body_content.replace('src="equipment_required_files/', 'src="/web/assets/equipment_required_files/')
    body_content = body_content.replace("src='equipment_required_files/", "src='/web/assets/equipment_required_files/")
    
    return public_web_shell("רשימת ציוד נדרש", body_content, request=request)
