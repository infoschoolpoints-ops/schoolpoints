from fastapi import APIRouter, Request, Form, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from ..ui import public_web_shell
from ..db import get_db_connection, sql_placeholder
from ..email import send_contact_email, send_email
from ..antispam import honeypot_html, form_token_html, captcha_html, screen_submission

router = APIRouter()

def save_contact_message(name: str, email: str, subject: str, message: str) -> None:
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        # Ensure table exists - though usually migrations handle this,
        # for simplicity in this module we'll assume it exists or fail gracefully
        # In a real app we'd have a startup migration check.
        try:
            cur.execute(
                sql_placeholder('INSERT INTO contact_messages (name, email, subject, message) VALUES (?, ?, ?, ?)'),
                (name, email, subject, message)
            )
            conn.commit()
        except Exception:
            pass # Table might not exist yet
    finally:
        try:
            conn.close()
        except Exception:
            pass

@router.get('/web/contact', response_class=HTMLResponse)
def web_contact() -> str:
    body = """
<style>
  .contact-wrap { max-width: 1000px; margin: 0 auto; padding: 20px; }
  .contact-hero { text-align: center; margin-bottom: 40px; }
  .contact-hero h2 { 
    font-size: 48px; 
    margin: 0 0 16px; 
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    font-weight: 700;
  }
  .contact-hero p { 
    font-size: 20px; 
    margin: 0; 
    opacity: 0.9; 
    line-height: 1.6;
  }
  .contact-card {
    background: var(--glass-bg);
    backdrop-filter: blur(24px);
    -webkit-backdrop-filter: blur(24px);
    border: 1px solid var(--glass-border);
    border-radius: 24px;
    padding: 48px;
    box-shadow: 0 20px 60px rgba(0,0,0,0.1);
    transition: transform 0.3s ease, box-shadow 0.3s ease;
  }
  .contact-card:hover {
    transform: translateY(-5px);
    box-shadow: 0 25px 70px rgba(0,0,0,0.15);
  }
  .contact-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 32px; }
  .contact-full { grid-column: 1 / -1; }
  .form-group { margin-bottom: 24px; }
  .form-group label {
    display: block;
    margin-bottom: 8px;
    font-size: 16px;
    font-weight: 600;
    color: var(--text-primary);
  }
  .form-input {
    width: 100%;
    padding: 16px 20px;
    font-size: 16px;
    border: 2px solid var(--glass-border);
    border-radius: 12px;
    background: rgba(255,255,255,0.05);
    transition: all 0.3s ease;
  }
  .form-input:focus {
    border-color: #667eea;
    background: rgba(255,255,255,0.08);
    outline: none;
    box-shadow: 0 0 0 3px rgba(102,126,234,0.1);
  }
  textarea.form-input {
    min-height: 160px;
    resize: vertical;
    font-family: inherit;
  }
  .contact-actions {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-top: 40px;
    gap: 20px;
  }
  .btn-glass {
    padding: 16px 32px;
    font-size: 16px;
    font-weight: 600;
    border-radius: 12px;
    transition: all 0.3s ease;
  }
  .btn-primary {
    padding: 16px 48px;
    font-size: 18px;
    font-weight: 700;
    border-radius: 12px;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    border: none;
    transition: all 0.3s ease;
  }
  .btn-primary:hover {
    transform: translateY(-2px);
    box-shadow: 0 10px 30px rgba(102,126,234,0.3);
  }
  .contact-info {
    margin-top: 48px;
    padding: 32px;
    background: rgba(255,255,255,0.03);
    border-radius: 16px;
    text-align: center;
  }
  .contact-info h3 {
    font-size: 24px;
    margin-bottom: 16px;
  }
  .contact-info p {
    font-size: 16px;
    opacity: 0.8;
    margin: 8px 0;
  }
  @media (max-width: 768px) {
    .contact-grid { grid-template-columns: 1fr; gap: 24px; }
    .contact-card { padding: 32px 24px; }
    .contact-hero h2 { font-size: 36px; }
    .contact-hero p { font-size: 18px; }
    .contact-actions { flex-direction: column; }
    .btn-primary { width: 100%; }
  }
</style>

<div class="contact-wrap">
  <div class="contact-hero">
    <h2>צור קשר</h2>
    <p>נשמח לשמוע מכם ולעזור בכל שאלה.<br>הצוות שלנו זמין לתמיכה.</p>
  </div>

  <form method="post" action="/web/contact">
    __ANTISPAM__
    <div class="contact-card">
      <div class="contact-grid">
        <div class="form-group">
          <label>שם מלא</label>
          <input name="name" class="form-input reg-input" required placeholder="הכנס שם ושם משפחה" />
        </div>
        <div class="form-group">
          <label>אימייל</label>
          <input name="email" type="email" class="form-input reg-input" required placeholder="name@example.com" style="direction:ltr; text-align:left;" />
        </div>
        <div class="form-group contact-full">
          <label>נושא הפנייה</label>
          <input name="subject" class="form-input reg-input" placeholder="לדוגמה: שאלה טכנית, בקשת הצעה, תמיכה..." />
        </div>
        <div class="form-group contact-full">
          <label>תוכן ההודעה</label>
          <textarea name="message" class="form-input reg-input" required placeholder="כתוב כאן את הודעתך בפירוט כדי שנוכל לעזור לך בצורה הטובה ביותר..."></textarea>
        </div>
      </div>

      <div class="form-group contact-full">__CAPTCHA__</div>

      <div class="contact-actions">
        <a class="btn-glass" href="/web">ביטול וחזרה</a>
        <button class="btn-primary" type="submit">שליחת הודעה</button>
      </div>
    </div>
  </form>

  <div class="contact-info">
    <h3>דרכים נוספות ליצירת קשר</h3>
    <p>📧 אימייל: <a href="mailto:info@schoolpoints.co.il" style="color:inherit;">info@schoolpoints.co.il</a></p>
  </div>
</div>
"""
    return public_web_shell('צור קשר', body.replace('__ANTISPAM__', honeypot_html() + form_token_html()).replace('__CAPTCHA__', captcha_html()))

@router.post('/web/contact', response_class=HTMLResponse)
def web_contact_submit(
    request: Request,
    name: str = Form(default=''),
    email: str = Form(default=''),
    subject: str = Form(default=''),
    message: str = Form(default=''),
    company_url: str = Form(default=''),
    _ft: str = Form(default=''),
    _cap: str = Form(default=''),
    _cap_ans: str = Form(default=''),
) -> Response:
    name = str(name or '').strip()
    email = str(email or '').strip()
    subject = str(subject or '').strip()
    message = str(message or '').strip()
    
    if not name or not email or not message:
        body = "<h2>צור קשר</h2><p>חסרים פרטים.</p><div class=\"actionbar\"><a class=\"gray\" href=\"/web/contact\">חזרה</a></div>"
        return HTMLResponse(public_web_shell('צור קשר', body), status_code=400)

    # --- Anti-spam screening ---
    _spam = screen_submission(
        request, {'company_url': company_url, '_ft': _ft,
                  '_cap': _cap, '_cap_ans': _cap_ans}, kind='contact',
        max_hits=5, window_sec=3600, require_token=True, require_captcha=True,
        check_email=True, email_value=email,
    )
    if _spam == 'honeypot':
        # Tarpit: pretend success, silently drop (false-positive risk ~0)
        body = "<h2>תודה!</h2><p>ההודעה נשלחה בהצלחה.</p><div class=\"actionbar\"><a class=\"blue\" href=\"/web\">דף הבית</a></div>"
        return HTMLResponse(public_web_shell('צור קשר', body), status_code=200)
    if _spam == 'captcha':
        body = "<h2>צור קשר</h2><p>תשובת האימות שגויה. חזרו ונסו שוב.</p><div class=\"actionbar\"><a class=\"gray\" href=\"/web/contact\">חזרה</a></div>"
        return HTMLResponse(public_web_shell('צור קשר', body), status_code=400)
    if _spam == 'rate_limit':
        body = "<h2>צור קשר</h2><p>נשלחו יותר מדי הודעות מכתובת זו. נסו שוב בעוד כשעה.</p><div class=\"actionbar\"><a class=\"gray\" href=\"/web\">דף הבית</a></div>"
        return HTMLResponse(public_web_shell('צור קשר', body), status_code=429)
    if _spam:
        body = "<h2>צור קשר</h2><p>לא ניתן לשלוח את ההודעה כעת. רעננו את הדף ונסו שוב.</p><div class=\"actionbar\"><a class=\"gray\" href=\"/web/contact\">חזרה</a></div>"
        return HTMLResponse(public_web_shell('צור קשר', body), status_code=400)
    
    # Save to DB
    save_contact_message(name, email, subject, message)
        
    # Send Email
    email_sent = send_contact_email(name, email, subject, message)
    
    if not email_sent:
        body = "<h2>קיבלנו את ההודעה</h2><p>ההודעה נשמרה במערכת, אך שליחת אימייל נכשלה (בדוק הגדרות SMTP בשרת).</p><div class=\"actionbar\"><a class=\"blue\" href=\"/web\">דף הבית</a><a class=\"gray\" href=\"/web/contact\">שליחה נוספת</a></div>"
        return HTMLResponse(public_web_shell('צור קשר', body), status_code=200)

    body = "<h2>תודה!</h2><p>ההודעה נשלחה בהצלחה.</p><div class=\"actionbar\"><a class=\"blue\" href=\"/web\">דף הבית</a><a class=\"gray\" href=\"/web/guide\">מדריך</a></div>"
    return HTMLResponse(public_web_shell('צור קשר', body), status_code=200)


_CALLBACK_DEST = 'info.schoolpoints@gmail.com'

def _callback_form_html(error: str = '') -> str:
    err = f'<div style="background:rgba(231,76,60,.15);border:1px solid rgba(231,76,60,.5);border-radius:10px;padding:11px 15px;margin-bottom:16px;color:#ff6b6b;">{error}</div>' if error else ''
    return f"""<style>
.cbw{{max-width:740px;margin:0 auto;padding:16px;}}
.cbw h2{{text-align:center;font-size:36px;font-weight:900;background:linear-gradient(135deg,#f7971e,#ffd200);-webkit-background-clip:text;-webkit-text-fill-color:transparent;margin:0 0 6px;}}
.cbw .sub{{text-align:center;font-size:16px;opacity:.8;margin-bottom:26px;line-height:1.6;}}
.cbcard{{background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.12);border-radius:18px;padding:28px 24px;}}
.cbgrid{{display:grid;grid-template-columns:1fr 1fr;gap:12px 20px;}}
.cbfull{{grid-column:1/-1;}}
.fl label{{display:block;font-size:13.5px;font-weight:600;margin-bottom:4px;opacity:.88;}}
.fl input,.fl textarea,.fl select{{width:100%;padding:10px 13px;font-size:15px;border:1.5px solid rgba(255,255,255,0.14);border-radius:9px;background:rgba(255,255,255,0.06);color:inherit;box-sizing:border-box;transition:border-color .2s;font-family:inherit;}}
.fl input:focus,.fl textarea:focus{{outline:none;border-color:#ffd200;background:rgba(255,255,255,0.09);}}
.fl textarea{{min-height:72px;resize:vertical;}}
.opt-box{{background:rgba(255,255,255,0.03);border:1px dashed rgba(255,255,255,0.15);border-radius:11px;padding:12px 15px;margin:4px 0;}}
.opt-toggle{{display:flex;align-items:center;gap:9px;cursor:pointer;font-size:15px;font-weight:600;}}
.opt-toggle input{{width:17px;height:17px;margin:0;cursor:pointer;}}
.opt-fields{{display:none;margin-top:13px;}}
.rg{{display:flex;gap:14px;flex-wrap:wrap;margin-top:4px;}}
.rg label{{display:flex;align-items:center;gap:6px;font-weight:500;font-size:15px;cursor:pointer;}}
.rg input[type=radio]{{width:auto;}}
.cb-req{{color:#ffd200;}}
@media(max-width:580px){{.cbgrid{{grid-template-columns:1fr;}}}}
</style>
<div class="cbw">
<h2>דווקא מעניין אותי!</h2>
<p class="sub">מלאו את הפרטים ונחזור אליכם בהקדם עם כל המידע.</p>
{err}
<form method="post" action="/web/callback">
{honeypot_html()}{form_token_html()}
<div class="cbcard">
<div class="cbgrid">
<div class="fl cbfull"><label>שם בית הספר / המוסד <span class="cb-req">*</span></label><input name="school_name" required placeholder='לדוגמה: בי"ס אורט רמת גן' /></div>
<div class="fl"><label>שם איש קשר <span class="cb-req">*</span></label><input name="contact_name" required placeholder="שם מלא" /></div>
<div class="fl"><label>מס' טלפון <span class="cb-req">*</span></label><input name="contact_phone" type="tel" required placeholder="05X-XXXXXXX" /></div>
<div class="fl cbfull"><label>דוא"ל</label><input name="contact_email" type="email" placeholder="name@school.edu" style="direction:ltr;text-align:left;" /></div>
<div class="fl cbfull">
  <div class="opt-box">
    <label class="opt-toggle"><input type="checkbox" name="extra_contact" id="extra_cb" onchange="document.getElementById('extra_fields').style.display=this.checked?'grid':'none'"> איש קשר נוסף</label>
    <div class="opt-fields cbgrid" id="extra_fields">
      <div class="fl"><label>שם איש קשר נוסף</label><input name="extra_name" placeholder="שם מלא" /></div>
      <div class="fl"><label>מס' טלפון</label><input name="extra_phone" type="tel" placeholder="05X-XXXXXXX" /></div>
      <div class="fl cbfull"><label>דוא"ל</label><input name="extra_email" type="email" placeholder="name@school.edu" style="direction:ltr;text-align:left;" /></div>
    </div>
  </div>
</div>
<div class="fl"><label>מס' תלמידים בבית הספר</label><input name="num_students" type="number" placeholder="לדוגמה: 450" /></div>
<div class="fl"><label>מס' כיתות</label><input name="num_classes" type="number" placeholder="לדוגמה: 18" /></div>
<div class="fl cbfull"><label>מעוניינים בתוכנה</label>
<div class="rg">
<label><input type="radio" name="software_type" value="מקומית" checked> מקומית</label>
<label><input type="radio" name="software_type" value="היברידית"> היברידית</label>
<label><input type="radio" name="software_type" value="מקוונת"> מקוונת</label>
</div></div>
</div>
{captcha_html()}
<div style="margin-top:22px;text-align:center;">
<button type="submit" style="padding:14px 52px;font-size:18px;font-weight:800;border-radius:12px;background:linear-gradient(135deg,#f7971e,#ffd200);border:none;color:#1a1a2e;cursor:pointer;transition:opacity .2s;">שלח פנייה</button>
</div>
</div>
</form>
</div>"""

@router.get('/web/callback', response_class=HTMLResponse)
def web_callback() -> str:
    return public_web_shell('תחזרו אלי', _callback_form_html())

@router.post('/web/callback', response_class=HTMLResponse)
def web_callback_submit(
    request: Request,
    school_name: str = Form(default=''),
    contact_name: str = Form(default=''),
    contact_phone: str = Form(default=''),
    contact_email: str = Form(default=''),
    extra_contact: str = Form(default=''),
    extra_name: str = Form(default=''),
    extra_phone: str = Form(default=''),
    extra_email: str = Form(default=''),
    num_students: str = Form(default=''),
    num_classes: str = Form(default=''),
    software_type: str = Form(default=''),
    company_url: str = Form(default=''),
    _ft: str = Form(default=''),
    _cap: str = Form(default=''),
    _cap_ans: str = Form(default=''),
) -> Response:
    school_name = str(school_name or '').strip()
    contact_name = str(contact_name or '').strip()
    contact_phone = str(contact_phone or '').strip()
    contact_email = str(contact_email or '').strip()
    if not school_name or not contact_name or not contact_phone:
        return HTMLResponse(public_web_shell('תחזרו אלי', _callback_form_html('נא למלא את כל השדות החובה')), status_code=400)

    # --- Anti-spam screening (email optional here, so skip email check) ---
    _spam = screen_submission(
        request, {'company_url': company_url, '_ft': _ft,
                  '_cap': _cap, '_cap_ans': _cap_ans}, kind='callback',
        max_hits=5, window_sec=3600, require_token=True, require_captcha=True,
        check_email=False,
    )
    if _spam == 'honeypot':
        ok = '<div style="text-align:center;padding:40px 20px;"><div style="font-size:52px;margin-bottom:16px;">✅</div><h2 style="font-size:28px;font-weight:900;">קיבלנו את הפנייה!</h2><a href="/web" class="btn-glass primary" style="padding:14px 36px;font-size:17px;">חזרה לדף הבית</a></div>'
        return HTMLResponse(public_web_shell('תחזרו אלי', ok), status_code=200)
    if _spam == 'captcha':
        return HTMLResponse(public_web_shell('תחזרו אלי', _callback_form_html('תשובת האימות שגויה. נסו שוב.')), status_code=400)
    if _spam == 'rate_limit':
        return HTMLResponse(public_web_shell('תחזרו אלי', _callback_form_html('נשלחו יותר מדי פניות מכתובת זו. נסו שוב בעוד כשעה.')), status_code=429)
    if _spam:
        return HTMLResponse(public_web_shell('תחזרו אלי', _callback_form_html('לא ניתן לשלוח כעת. רעננו את הדף ונסו שוב.')), status_code=400)
    lines = [
        f'<b>בית הספר:</b> {school_name}',
        f'<b>איש קשר:</b> {contact_name} | טלפון: {contact_phone}' + (f' | דוא"ל: {contact_email}' if contact_email else ''),
    ]
    if extra_contact == 'on' and extra_name:
        lines.append(f'<b>איש קשר נוסף:</b> {extra_name} | {extra_phone} | {extra_email}')
    lines += [
        f'<b>מס\' תלמידים:</b> {num_students or "לא צוין"}',
        f'<b>מס\' כיתות:</b> {num_classes or "לא צוין"}',
        f'<b>סוג תוכנה:</b> {software_type or "לא צוין"}',
    ]
    body_html = '<div dir="rtl" style="line-height:2;">' + '<br>'.join(lines) + '</div>'
    subject = f'פנייה חדשה ממוסד: {school_name}'
    send_email(_CALLBACK_DEST, subject, body_html)
    if contact_email:
        copy_body = '<div dir="rtl"><p>קיבלנו את פנייתך ונשתדל לחזור אליך בהקדם!</p><hr>' + body_html + '</div>'
        send_email(contact_email, 'קיבלנו את פנייתך - SchoolPoints', copy_body)
    ok = '<div style="text-align:center;padding:40px 20px;"><div style="font-size:52px;margin-bottom:16px;">✅</div><h2 style="font-size:28px;font-weight:900;">קיבלנו את הפנייה!</h2><p style="font-size:17px;opacity:.85;max-width:480px;margin:0 auto 28px;line-height:1.7;">נשתדל לחזור אליך בהקדם האפשרי.</p><a href="/web" class="btn-glass primary" style="padding:14px 36px;font-size:17px;">חזרה לדף הבית</a></div>'
    return HTMLResponse(public_web_shell('תחזרו אלי', ok), status_code=200)
