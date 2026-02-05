from fastapi import APIRouter, Request, HTTPException, Body, Query
from fastapi.responses import HTMLResponse
from typing import Dict, Any

from ..utils import public_web_shell
from ..registration_logic import approve_pending_registration
from ..db import get_db_connection, sql_placeholder, ensure_pending_registrations_table

router = APIRouter()

@router.get('/web/payment/mock', response_class=HTMLResponse)
def web_payment_mock(request: Request, reg_email: str = Query(default=''), plan: str = Query(default='')) -> str:
    # Mock payment page to simulate successful payment
    if not reg_email:
        return "Mock Payment Page"
        
    amount = 50 if plan == 'basic' else (100 if plan == 'extended' else 200)
    
    body = f"""
    <div style="max-width:500px; margin:40px auto; text-align:center; background:#fff; padding:30px; border-radius:15px; box-shadow:0 10px 30px rgba(0,0,0,0.1);">
      <h2 style="color:#2c3e50;">תשלום מאובטח (סימולציה)</h2>
      <div style="font-size:18px; margin:20px 0;">
        <div><b>לקוח:</b> {reg_email}</div>
        <div><b>מסלול:</b> {plan.upper()}</div>
        <div style="font-size:24px; font-weight:bold; color:#27ae60; margin-top:10px;">סכום לתשלום: ₪{amount}</div>
      </div>
      
      <div style="background:#f8f9fa; padding:15px; border-radius:8px; margin-bottom:20px; text-align:left; direction:ltr;">
        <div>💳 Card Number: 4242 4242 4242 4242</div>
        <div>📅 Expiry: 12/30</div>
        <div>🔒 CVC: 123</div>
      </div>
      
      <button onclick="processPayment()" style="width:100%; padding:15px; background:#2ecc71; color:white; border:none; border-radius:8px; font-size:18px; font-weight:bold; cursor:pointer;">שלם עכשיו</button>
      
      <script>
        async function processPayment() {{
            const btn = document.querySelector('button');
            btn.disabled = true;
            btn.textContent = 'מעבד תשלום...';
            
            await new Promise(r => setTimeout(r, 1500));
            
            // Call webhook simulation
            try {{
                const resp = await fetch('/api/payment/webhook/mock', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ email: '{reg_email}', status: 'success' }})
                }});
                const data = await resp.json();
                if (data.ok) {{
                    document.body.innerHTML = '<h2 style="color:#27ae60">התשלום עבר בהצלחה!</h2><p>פרטי ההתחברות נשלחו למייל שלך.</p><a href="/web/signin" style="display:inline-block; margin-top:20px; padding:10px 20px; background:#3498db; color:white; text-decoration:none; border-radius:6px;">מעבר להתחברות</a>';
                }} else {{
                    alert('שגיאה: ' + (data.detail || 'unknown'));
                    btn.disabled = false;
                    btn.textContent = 'שלם עכשיו';
                }}
            }} catch (e) {{
                alert('שגיאה בתקשורת');
                btn.disabled = false;
                btn.textContent = 'שלם עכשיו';
            }}
        }}
      </script>
    </div>
    """
    return public_web_shell("תשלום", body, request=request)

@router.post('/api/payment/webhook/mock')
def api_payment_webhook_mock(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Mock webhook for payment success."""
    email = str(payload.get('email') or '').strip()
    status = str(payload.get('status') or '').strip()
    
    if status != 'success':
         return {'ok': False, 'detail': 'Status not success'}
         
    # ensure_pending_registrations_table() # Assuming done by register module or db init
    # But safe to ensure here or assume register flow ran it.
    
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            sql_placeholder("SELECT id FROM pending_registrations WHERE email = ? AND payment_status != 'completed' ORDER BY id DESC LIMIT 1"),
            (email,)
        )
        row = cur.fetchone()
        if not row:
             return {'ok': True, 'processed': False, 'detail': 'No pending registration found'}
             
        reg_id = row['id'] if isinstance(row, dict) else row[0]
    finally:
        try: conn.close()
        except: pass

    # Delegate to core logic
    return approve_pending_registration(reg_id)

@router.post('/api/payment/webhook/mock/legacy')
def api_payment_webhook_mock_legacy(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Legacy endpoint forwarding."""
    return api_payment_webhook_mock(payload)
