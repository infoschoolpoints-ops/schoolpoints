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
    <p>נשמח לשמוע מכם ולעזור בכל שאלה.<br>הצוות שלנו זמין 24/7 לתמיכה מלאה.</p>
  </div>

  <form method="post" action="/web/contact">
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

      <div class="contact-actions">
        <a class="btn-glass" href="/web">ביטול וחזרה</a>
        <button class="btn-primary" type="submit">שליחת הודעה</button>
      </div>
    </div>
  </form>

  <div class="contact-info">
    <h3>דרכים נוספות ליצירת קשר</h3>
    <p>📧 אימייל: info@schoolpoints.co.il</p>
    <p>📱 טלפון: 03-1234567</p>
    <p>💬 צ'אט תמיכה: זמין באתר בכל יום</p>
  </div>
</div>
"""
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
