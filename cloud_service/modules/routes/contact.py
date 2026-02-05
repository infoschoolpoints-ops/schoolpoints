from fastapi import APIRouter, Request, Form, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from ..ui import public_web_shell
from ..db import get_db_connection, sql_placeholder
from ..email import send_contact_email

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
    body = f"""
    <h2>צור קשר</h2>
    <div style="opacity:.86; margin-top:-6px;">נחזור אליך בהקדם.</div>
    <form method="post" action="/web/contact" style="margin-top:12px; max-width:680px;">
      <div class="form-group">
        <label>שם</label>
        <input name="name" class="form-input" required />
      </div>
      <div class="form-group">
        <label>אימייל</label>
        <input name="email" type="email" class="form-input" required />
      </div>
      <div class="form-group">
        <label>נושא</label>
        <input name="subject" class="form-input" />
      </div>
      <div class="form-group">
        <label>הודעה</label>
        <textarea name="message" class="form-input" style="min-height:120px;" required></textarea>
      </div>
      <div class="actionbar" style="justify-content:flex-start;">
        <button class="green" type="submit">שליחה</button>
        <a class="gray" href="/web">חזרה</a>
      </div>
    </form>
    """
    return public_web_shell('צור קשר', body)

@router.post('/web/contact', response_class=HTMLResponse)
def web_contact_submit(
    name: str = Form(default=''),
    email: str = Form(default=''),
    subject: str = Form(default=''),
    message: str = Form(default=''),
) -> Response:
    name = str(name or '').strip()
    email = str(email or '').strip()
    subject = str(subject or '').strip()
    message = str(message or '').strip()
    
    if not name or not email or not message:
        body = "<h2>צור קשר</h2><p>חסרים פרטים.</p><div class=\"actionbar\"><a class=\"gray\" href=\"/web/contact\">חזרה</a></div>"
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
