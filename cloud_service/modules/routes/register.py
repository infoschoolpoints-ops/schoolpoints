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
<div style="max-width:600px; margin:0 auto;">
    <h2 style="text-align:center; margin-bottom:10px;">הרשמה למוסד חדש</h2>
    <p style="text-align:center; opacity:0.8; margin-bottom:30px;">הצטרפו למאות תלמידים שכבר נהנים מניהול נקודות מתקדם.</p>
    
    <form id="regForm" onsubmit="submitRegister(event)">
        <div class="glass" style="padding:24px; border-radius:16px;">
            <h3 style="margin-top:0; border-bottom:1px solid rgba(255,255,255,0.1); padding-bottom:10px;">פרטי המוסד</h3>
            
            <div class="form-group">
                <label>שם המוסד</label>
                <input name="institution_name" class="form-input reg-input" required placeholder="לדוגמה: תלמוד תורה חכמת שלמה" />
            </div>
            
            <div class="form-group">
                <label>קוד מוסד (ספרות בלבד)</label>
                <input name="institution_code" class="form-input reg-input" required pattern="[0-9]+" placeholder="12345" style="direction:ltr; text-align:left;" />
                <div style="font-size:12px; opacity:0.6; margin-top:4px;">זהו המזהה הייחודי שלכם במערכת (Tenant ID).</div>
            </div>
            
            <div class="form-group">
                <label>סיסמת ניהול ראשית</label>
                <input name="password" type="password" class="form-input reg-input" required placeholder="סיסמה חזקה לניהול המערכת" />
            </div>

            <h3 style="margin-top:30px; border-bottom:1px solid rgba(255,255,255,0.1); padding-bottom:10px;">בחירת מסלול</h3>
            <div style="display:flex; flex-direction:column; gap:12px; margin-bottom:20px;">
                <label style="display:flex; align-items:center; gap:10px; cursor:pointer; padding:12px; border:1px solid rgba(255,255,255,0.1); border-radius:10px; transition:background 0.2s;">
                    <input type="radio" name="plan" value="basic" checked style="margin:0;">
                    <div>
                        <strong>Basic</strong> – עד 100 תלמידים
                    </div>
                </label>
                <label style="display:flex; align-items:center; gap:10px; cursor:pointer; padding:12px; border:1px solid rgba(255,255,255,0.1); border-radius:10px; transition:background 0.2s;">
                    <input type="radio" name="plan" value="extended" style="margin:0;">
                    <div>
                        <strong>Extended</strong> – עד 300 תלמידים
                    </div>
                </label>
                <label style="display:flex; align-items:center; gap:10px; cursor:pointer; padding:12px; border:1px solid rgba(255,255,255,0.1); border-radius:10px; transition:background 0.2s;">
                    <input type="radio" name="plan" value="unlimited" style="margin:0;">
                    <div>
                        <strong>Unlimited</strong> – ללא הגבלה
                    </div>
                </label>
            </div>

            <h3 style="margin-top:30px; border-bottom:1px solid rgba(255,255,255,0.1); padding-bottom:10px;">איש קשר</h3>
            
            <div class="form-group">
                <label>שם מלא</label>
                <input name="contact_name" class="form-input reg-input" required />
            </div>
            
            <div class="form-group">
                <label>אימייל</label>
                <input name="email" type="email" class="form-input reg-input" required style="direction:ltr; text-align:left;" />
            </div>
            
            <div class="form-group">
                <label>טלפון</label>
                <input name="phone" class="form-input reg-input" style="direction:ltr; text-align:left;" />
            </div>

            <div class="form-group" style="margin-top:20px; display:flex; gap:10px; align-items:center;">
                <input type="checkbox" id="terms" name="terms" required style="width:20px; height:20px;" />
                <label for="terms" style="margin:0; font-weight:400;">קראתי ואני מאשר את <a href="/web/terms" target="_blank" style="text-decoration:underline;">התקנון ותנאי השימוש</a></label>
            </div>

            <div style="margin-top:30px; text-align:center;">
                <button type="submit" class="btn-primary" style="width:100%; font-size:18px; padding:16px;">הרשמה ותשלום</button>
            </div>
        </form>
    </div>

    <script>
    async function submitRegister(e) {
        e.preventDefault();
        const btn = e.target.querySelector('button');
        const originalText = btn.innerText;
        btn.disabled = true;
        btn.innerText = 'מעבד...';

        const formData = new FormData(e.target);
        const data = Object.fromEntries(formData.entries());
        data.terms = !!document.getElementById('terms').checked;
        
        // Get selected plan from radio buttons
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
</div>
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
