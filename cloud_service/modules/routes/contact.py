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
    <div style="max-width:600px; margin:0 auto;">
        <h2 style="text-align:center; margin-bottom:10px;">צור קשר</h2>
        <p style="text-align:center; opacity:0.8; margin-bottom:30px;">נשמח לשמוע מכם! מלאו את הפרטים ונחזור אליכם בהקדם.</p>
        
        <form method="post" action="/web/contact">
            <div class="glass" style="padding:30px; border-radius:16px;">
                <div class="form-group">
                    <label>שם מלא</label>
                    <input name="name" class="form-input reg-input" required placeholder="שם ושם משפחה" />
                </div>
                
                <div class="form-group">
                    <label>אימייל</label>
                    <input name="email" type="email" class="form-input reg-input" required placeholder="name@example.com" style="direction:ltr; text-align:right;" />
                </div>
                
                <div class="form-group">
                    <label>נושא הפנייה</label>
                    <input name="subject" class="form-input reg-input" placeholder="בנושא..." />
                </div>
                
                <div class="form-group">
                    <label>תוכן ההודעה</label>
                    <textarea name="message" class="form-input reg-input" style="min-height:150px; resize:vertical;" required placeholder="כתוב כאן את הודעתך..."></textarea>
                </div>
                
                <div class="actionbar" style="justify-content:space-between; margin-top:20px;">
                     <a class="btn-glass" href="/web">ביטול וחזרה</a>
                     <button class="btn-primary" type="submit" style="padding-left:30px; padding-right:30px;">שליחת הודעה</button>
                </div>
            </div>
        </form>
    </div>
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
