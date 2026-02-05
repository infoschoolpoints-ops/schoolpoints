from fastapi import APIRouter, Request, Body, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from typing import Dict, Any
import datetime
import secrets
import re
import logging

from ..db import get_db_connection, sql_placeholder, integrity_errors, ensure_pending_registrations_table
from ..config import USE_POSTGRES
from ..auth import pbkdf2_hash
from ..utils import random_pair_code
from ..ui import public_web_shell

router = APIRouter()
logger = logging.getLogger("schoolpoints.register")

@router.get('/web/register', response_class=HTMLResponse)
def web_register(request: Request) -> str:
    body = """
<style>
  .register-wrap { max-width: 800px; margin: 0 auto; padding: 20px; }
  .register-hero { text-align: center; margin-bottom: 40px; }
  .register-hero h2 { 
    font-size: 48px; 
    margin: 0 0 16px; 
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    font-weight: 700;
  }
  .register-hero p { 
    font-size: 20px; 
    margin: 0; 
    opacity: 0.9; 
    line-height: 1.6;
  }
  .register-card {
    background: var(--glass-bg);
    backdrop-filter: blur(24px);
    -webkit-backdrop-filter: blur(24px);
    border: 1px solid var(--glass-border);
    border-radius: 24px;
    padding: 48px;
    box-shadow: 0 20px 60px rgba(0,0,0,0.1);
    transition: transform 0.3s ease, box-shadow 0.3s ease;
  }
  .register-card:hover {
    transform: translateY(-5px);
    box-shadow: 0 25px 70px rgba(0,0,0,0.15);
  }
  .section-title {
    font-size: 24px;
    font-weight: 700;
    margin: 30px 0 20px;
    padding-bottom: 10px;
    border-bottom: 1px solid rgba(255,255,255,0.1);
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .section-title:first-child { margin-top: 0; }
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
  .plan-grid { 
    display: grid; 
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); 
    gap: 16px; 
    margin-bottom: 20px; 
  }
  .plan-option {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 20px;
    border: 2px solid var(--glass-border);
    border-radius: 16px;
    background: rgba(255,255,255,0.03);
    cursor: pointer;
    transition: all 0.3s ease;
  }
  .plan-option:hover {
    border-color: rgba(102,126,234,0.5);
    background: rgba(255,255,255,0.06);
  }
  .plan-option.selected {
    border-color: #667eea;
    background: rgba(102,126,234,0.1);
  }
  .plan-option input[type="radio"] { 
    width: 20px; 
    height: 20px; 
    margin: 0; 
  }
  .plan-details {
    flex: 1;
  }
  .plan-name {
    font-size: 18px;
    font-weight: 700;
    color: #fff;
    margin-bottom: 4px;
  }
  .plan-desc {
    font-size: 14px;
    opacity: 0.7;
  }
  .plan-price {
    font-size: 16px;
    font-weight: 600;
    color: #2ecc71;
  }
  .checkbox-group {
    display: flex;
    align-items: flex-start;
    gap: 12px;
    margin: 24px 0;
  }
  .checkbox-group input[type="checkbox"] {
    width: 20px;
    height: 20px;
    margin-top: 2px;
  }
  .checkbox-group label {
    margin: 0;
    font-weight: 400;
    line-height: 1.6;
  }
  .checkbox-group a {
    color: #667eea;
    text-decoration: none;
    font-weight: 600;
  }
  .checkbox-group a:hover { text-decoration: underline; }
  .submit-section {
    margin-top: 40px;
    text-align: center;
  }
  .btn-primary {
    padding: 18px 48px;
    font-size: 20px;
    font-weight: 700;
    border-radius: 12px;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    border: none;
    color: white;
    cursor: pointer;
    transition: all 0.3s ease;
    width: 100%;
    max-width: 400px;
  }
  .btn-primary:hover {
    transform: translateY(-2px);
    box-shadow: 0 10px 30px rgba(102,126,234,0.3);
  }
  .btn-primary:disabled {
    opacity: 0.6;
    cursor: not-allowed;
    transform: none;
  }
  .pricing-link {
    margin-top: 20px;
    font-size: 16px;
    opacity: 0.8;
  }
  .pricing-link a {
    color: #667eea;
    text-decoration: none;
    font-weight: 600;
  }
  .pricing-link a:hover { text-decoration: underline; }
  .help-text {
    font-size: 12px;
    opacity: 0.6;
    margin-top: 4px;
  }
  @media (max-width: 768px) {
    .register-card { padding: 32px 24px; }
    .register-hero h2 { font-size: 36px; }
    .register-hero p { font-size: 18px; }
    .plan-grid { grid-template-columns: 1fr; }
  }
</style>

<div class="register-wrap">
  <div class="register-hero">
    <h2>הרשמה למוסד חדש</h2>
    <p>הצטרפו למאות מוסדות חינוך שכבר נהנים ממערכת ניהול הנקודות המתקדמת בישראל</p>
  </div>

  <form id="regForm" onsubmit="submitRegister(event)">
    <div class="register-card">
      <div class="section-title">
        <span>🏫</span> פרטי המוסד
      </div>
      
      <div class="form-group">
        <label>שם המוסד</label>
        <input name="institution_name" class="form-input reg-input" required placeholder="לדוגמה: תלמוד תורה חכמת שלמה" />
      </div>
      
      <div class="form-group">
        <label>קוד מוסד (Tenant ID)</label>
        <input name="institution_code" class="form-input reg-input" required pattern="[0-9]+" placeholder="מספר ספרות בלבד" style="direction:ltr; text-align:left;" />
        <div class="help-text">זהו המזהה הייחודי שלכם במערכת</div>
      </div>
      
      <div class="form-group">
        <label>סיסמת ניהול ראשית</label>
        <input name="password" type="password" class="form-input reg-input" required placeholder="סיסמה חזקה לניהול המערכת" />
      </div>

      <div class="section-title">
        <span>💎</span> בחירת מסלול
      </div>
      
      <div class="plan-grid">
        <label class="plan-option">
          <input type="radio" name="plan" value="basic" checked>
          <div class="plan-details">
            <div class="plan-name">Basic</div>
            <div class="plan-desc">עד 100 תלמיד</div>
          </div>
          <div class="plan-price">₪50/חודש</div>
        </label>
        
        <label class="plan-option">
          <input type="radio" name="plan" value="extended">
          <div class="plan-details">
            <div class="plan-name">Extended</div>
            <div class="plan-desc">עד 300 תלמיד</div>
          </div>
          <div class="plan-price">₪120/חודש</div>
        </label>
        
        <label class="plan-option">
          <input type="radio" name="plan" value="unlimited">
          <div class="plan-details">
            <div class="plan-name">Unlimited</div>
            <div class="plan-desc">ללא הגבלה</div>
          </div>
          <div class="plan-price">₪200/חודש</div>
        </label>
      </div>

      <div class="section-title">
        <span>👤</span> איש קשר
      </div>
      
      <div class="form-group">
        <label>שם מלא</label>
        <input name="contact_name" class="form-input reg-input" required placeholder="שם פרטי ושם משפחה" />
      </div>
      
      <div class="form-group">
        <label>אימייל</label>
        <input name="email" type="email" class="form-input reg-input" required placeholder="name@example.com" style="direction:ltr; text-align:left;" />
      </div>
      
      <div class="form-group">
        <label>טלפון</label>
        <input name="phone" class="form-input reg-input" placeholder="050-1234567" style="direction:ltr; text-align:left;" />
      </div>

      <div class="checkbox-group">
        <input type="checkbox" id="terms" name="terms" required>
        <label for="terms">קראתי ואני מאשר את <a href="/web/terms" target="_blank">התקנון ותנאי השימוש</a></label>
      </div>

      <div class="submit-section">
        <button type="submit" class="btn-primary" id="submitBtn">הרשמה והמשך לתשלום</button>
        <div class="pricing-link">
          <a href="/web/pricing" target="_blank">לצפייה בפירוט המחירים והיתרונות ></a>
        </div>
      </div>
    </div>
  </form>
</div>

<script>
// Handle plan selection visual feedback
document.querySelectorAll('.plan-option').forEach(option => {
  option.addEventListener('click', function() {
    document.querySelectorAll('.plan-option').forEach(o => o.classList.remove('selected'));
    this.classList.add('selected');
    this.querySelector('input[type="radio"]').checked = true;
  });
});

// Set initial selected state
document.querySelector('.plan-option input:checked').closest('.plan-option').classList.add('selected');

async function submitRegister(e) {
  e.preventDefault();
  const btn = document.getElementById('submitBtn');
  const originalText = btn.innerText;
  btn.disabled = true;
  btn.innerText = 'מעבד...';

  const formData = new FormData(e.target);
  const data = Object.fromEntries(formData.entries());
  data.terms = !!document.getElementById('terms').checked;
  
  // Get selected plan
  const selectedPlan = document.querySelector('input[name="plan"]:checked').value;
  data.plan = selectedPlan;

  try {
    const res = await fetch('/api/register', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(data)
    });
    const result = await res.json();
    
    if (res.ok && result.ok) {
      // Redirect to mock payment
      window.location.href = `/web/payment/mock?reg_email=${encodeURIComponent(data.email)}&plan=${selectedPlan}`;
    } else {
      alert('שגיאה בהרשמה: ' + (result.detail || result.message || 'Unknown error'));
      btn.disabled = false;
      btn.innerText = originalText;
    }
  } catch (err) {
    alert('שגיאה בתקשורת: ' + err);
    btn.disabled = false;
    btn.innerText = originalText;
  }
}
</script>
"""
"""
    return public_web_shell("הרשמה", body, request=request)

@router.post('/api/register')
def api_register(request: Request, payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    ensure_pending_registrations_table()
    
    inst_name = str(payload.get('institution_name') or '').strip()
    inst_code = str(payload.get('institution_code') or '').strip()
    contact = str(payload.get('contact_name') or '').strip()
    email = str(payload.get('email') or '').strip()
    phone = str(payload.get('phone') or '').strip()
    password = str(payload.get('password') or '').strip()
    plan = str(payload.get('plan') or 'basic').strip()
    terms_ok = payload.get('terms')
    
    if not inst_name or not email or not password:
        raise HTTPException(status_code=400, detail="Missing required fields")

    if not terms_ok:
        raise HTTPException(status_code=400, detail="Missing terms approval")

    if not inst_code:
        raise HTTPException(status_code=400, detail="Missing institution code")
        
    # Allow alphanumeric, but ensure it's url-safe-ish
    if not re.match(r'^[a-zA-Z0-9\-_]+$', inst_code):
        raise HTTPException(status_code=400, detail="Institution code must be alphanumeric (letters, numbers, -, _)")
        
    password_hash = pbkdf2_hash(password)
    
    conn = get_db_connection()
    try:
        cur = conn.cursor()

        cur.execute(sql_placeholder('SELECT 1 FROM institutions WHERE tenant_id = ? LIMIT 1'), (inst_code,))
        if cur.fetchone():
            raise HTTPException(status_code=409, detail='institution_code already exists')

        cur.execute(
            sql_placeholder(
                "SELECT 1 FROM pending_registrations WHERE institution_code = ? AND payment_status != 'completed' LIMIT 1"
            ),
            (inst_code,)
        )
        if cur.fetchone():
            raise HTTPException(status_code=409, detail='institution_code already pending')

        reg_id = None
        if USE_POSTGRES:
            cur.execute(
                sql_placeholder(
                    '''
                    INSERT INTO pending_registrations 
                    (institution_name, institution_code, contact_name, email, phone, password_hash, plan) 
                    VALUES (?, ?, ?, ?, ?, ?, ?) 
                    RETURNING id
                    '''
                ),
                (inst_name, inst_code, contact, email, phone, password_hash, plan)
            )
            row = cur.fetchone()
            if row:
                reg_id = row.get('id') if isinstance(row, dict) else row[0]
        else:
            cur.execute(
                sql_placeholder(
                    '''
                    INSERT INTO pending_registrations 
                    (institution_name, institution_code, contact_name, email, phone, password_hash, plan) 
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    '''
                ),
                (inst_name, inst_code, contact, email, phone, password_hash, plan)
            )
            reg_id = cur.lastrowid
        conn.commit()
        
        # In a real scenario, return payment URL
        return {
            'ok': True, 
            'reg_id': reg_id,
            'message': 'Registration pending payment',
            # 'payment_url': '...' 
        }
    finally:
        try:
            conn.close()
        except Exception:
            pass
