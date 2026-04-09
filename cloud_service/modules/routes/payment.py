"""Payment module — uPay integration infrastructure.

Flow:
  1. User registers → pending_registrations row created
  2. /web/payment?reg_email=...&plan=... shows payment page
  3. In MOCK mode: simulates payment → calls internal webhook
  4. In LIVE mode (once uPay API docs arrive):
     a. Server creates a uPay payment link via API
     b. User is redirected to uPay hosted page
     c. uPay calls /api/payment/webhook/upay (IPN) on success
     d. We approve the pending registration
"""
import json
import logging
import os
from fastapi import APIRouter, Request, HTTPException, Body, Query, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from typing import Dict, Any, Optional

from ..ui import public_web_shell
from ..registration_logic import approve_pending_registration
from ..db import get_db_connection, sql_placeholder
from ..config import USE_POSTGRES

logger = logging.getLogger("schoolpoints.payment")
router = APIRouter()

# ---------------------------------------------------------------------------
# uPay configuration (from environment variables)
# ---------------------------------------------------------------------------
UPAY_API_KEY = os.environ.get('UPAY_API_KEY', '').strip()
UPAY_API_SECRET = os.environ.get('UPAY_API_SECRET', '').strip()
UPAY_TERMINAL_ID = os.environ.get('UPAY_TERMINAL_ID', '').strip()
UPAY_API_URL = os.environ.get('UPAY_API_URL', 'https://pay.upay.co.il/api').strip()
UPAY_LIVE = bool(UPAY_API_KEY and UPAY_API_SECRET and UPAY_TERMINAL_ID)


def _get_plan_details(plan_key: str) -> Dict[str, Any]:
    """Load plan from plan_config table."""
    from ..admin_db import ensure_admin_tables
    ensure_admin_tables()
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql_placeholder('SELECT * FROM plan_config WHERE plan_key = ? LIMIT 1'), (plan_key,))
        row = cur.fetchone()
        if not row:
            return {}
        if isinstance(row, dict):
            return dict(row)
        if hasattr(row, 'keys'):
            return {k: row[k] for k in row.keys()}
        return {}
    except Exception:
        return {}
    finally:
        try: conn.close()
        except: pass


def _create_upay_payment(*, amount: int, description: str, email: str, order_id: str, success_url: str, cancel_url: str, ipn_url: str) -> Optional[str]:
    """Create a uPay payment and return the redirect URL.
    
    TODO: Implement when uPay API documentation is received.
    Expected flow:
      POST {UPAY_API_URL}/create-payment
      Headers: Authorization: Bearer {UPAY_API_KEY}
      Body: {
        terminal_id, api_secret, amount, currency: 'ILS',
        description, customer_email, order_id,
        success_url, cancel_url, ipn_url
      }
      Response: { url: 'https://pay.upay.co.il/pay/...' }
    """
    if not UPAY_LIVE:
        return None
    # Placeholder — will be replaced with actual HTTP call
    logger.warning("[UPAY] create_upay_payment called but real implementation pending API docs")
    return None


# ---------------------------------------------------------------------------
# Payment page — auto-selects mock or uPay based on config
# ---------------------------------------------------------------------------
@router.get('/web/payment', response_class=HTMLResponse)
@router.get('/web/payment/mock', response_class=HTMLResponse)
def web_payment_page(request: Request, reg_email: str = Query(default=''), plan: str = Query(default='')) -> str:
    if not reg_email:
        return public_web_shell("תשלום", "<h2>חסר מייל הרשמה</h2><a href='/web/register'>חזרה להרשמה</a>", request=request)

    plan_data = _get_plan_details(plan)
    plan_name = plan_data.get('display_name') or plan.upper()
    price_monthly = int(plan_data.get('price_monthly') or 0)
    duration = int(plan_data.get('duration_months') or 1)
    total = price_monthly * duration

    if total <= 0:
        # Free plan or missing — auto-approve
        return _auto_approve_free(reg_email, plan, request)

    # If uPay is configured, redirect to uPay hosted payment
    if UPAY_LIVE:
        base_url = str(request.base_url).rstrip('/')
        order_id = f"reg_{reg_email}_{plan}"
        pay_url = _create_upay_payment(
            amount=total,
            description=f'SchoolPoints - {plan_name}',
            email=reg_email,
            order_id=order_id,
            success_url=f'{base_url}/web/payment/success?email={reg_email}',
            cancel_url=f'{base_url}/web/payment?reg_email={reg_email}&plan={plan}',
            ipn_url=f'{base_url}/api/payment/webhook/upay',
        )
        if pay_url:
            return RedirectResponse(url=pay_url, status_code=302)
        # Fallback to mock if uPay call failed
        logger.warning("[PAYMENT] uPay create failed, falling back to mock")

    # Mock payment page
    price_line = f'₪{price_monthly}/חודש × {duration} חודשים = <b>₪{total}</b>' if duration > 1 else f'<b>₪{total}</b>'

    body = f"""
    <div style="max-width:500px; margin:40px auto; text-align:center; background:#fff; padding:30px; border-radius:15px; box-shadow:0 10px 30px rgba(0,0,0,0.1);">
      <h2 style="color:#2c3e50;">תשלום מאובטח</h2>
      <div style="font-size:14px;color:#e67e22;margin-bottom:16px;background:#fff8e1;padding:8px;border-radius:8px;">סימולציה — סליקה אמיתית תופעל בקרוב</div>
      <div style="font-size:18px; margin:20px 0;">
        <div><b>לקוח:</b> {reg_email}</div>
        <div><b>מסלול:</b> {plan_name}</div>
        <div style="font-size:22px; color:#27ae60; margin-top:10px;">{price_line}</div>
      </div>
      
      <div style="background:#f8f9fa; padding:15px; border-radius:8px; margin-bottom:20px; text-align:left; direction:ltr;">
        <div>💳 Card Number: 4242 4242 4242 4242</div>
        <div>📅 Expiry: 12/30 &nbsp; 🔒 CVC: 123</div>
      </div>
      
      <button id="payBtn" onclick="processPayment()" style="width:100%; padding:15px; background:#2ecc71; color:white; border:none; border-radius:8px; font-size:18px; font-weight:bold; cursor:pointer;">שלם ₪{total}</button>
      
      <script>
        async function processPayment() {{
            const btn = document.getElementById('payBtn');
            btn.disabled = true;
            btn.textContent = 'מעבד תשלום...';
            await new Promise(r => setTimeout(r, 1500));
            try {{
                const resp = await fetch('/api/payment/webhook/mock', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ email: '{reg_email}', status: 'success', amount: {total}, plan: '{plan}' }})
                }});
                const data = await resp.json();
                if (data.ok) {{
                    window.location.href = '/web/payment/success?email={reg_email}';
                }} else {{
                    alert('שגיאה: ' + (data.detail || 'unknown'));
                    btn.disabled = false;
                    btn.textContent = 'שלם ₪{total}';
                }}
            }} catch (e) {{
                alert('שגיאה בתקשורת');
                btn.disabled = false;
                btn.textContent = 'שלם ₪{total}';
            }}
        }}
      </script>
    </div>
    """
    return public_web_shell("תשלום", body, request=request)


@router.get('/web/payment/success', response_class=HTMLResponse)
def web_payment_success(request: Request, email: str = Query(default='')) -> str:
    body = f"""
    <div style="text-align:center; padding:40px 20px;">
      <div style="font-size:64px; margin-bottom:16px;">✅</div>
      <h2 style="color:#2ecc71;">התשלום עבר בהצלחה!</h2>
      <p style="opacity:.8;">פרטי ההתחברות נשלחו למייל <b>{email}</b></p>
      <a href="/web/signin" class="btn-glass primary" style="margin-top:20px; padding:14px 28px; font-size:16px;">מעבר להתחברות</a>
    </div>
    """
    return public_web_shell("תשלום הצליח", body, request=request)


def _auto_approve_free(email: str, plan: str, request: Request):
    """Auto-approve a free/trial registration."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            sql_placeholder("SELECT id FROM pending_registrations WHERE email = ? AND payment_status != 'completed' ORDER BY id DESC LIMIT 1"),
            (email,)
        )
        row = cur.fetchone()
        if row:
            reg_id = row['id'] if isinstance(row, dict) else row[0]
            approve_pending_registration(reg_id)
    except Exception:
        pass
    finally:
        try: conn.close()
        except: pass
    return RedirectResponse(url=f'/web/payment/success?email={email}', status_code=302)


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------
@router.post('/api/payment/webhook/mock')
def api_payment_webhook_mock(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Mock webhook for payment success (used in dev/testing)."""
    email = str(payload.get('email') or '').strip()
    status = str(payload.get('status') or '').strip()
    
    if status != 'success':
         return {'ok': False, 'detail': 'Status not success'}
    
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

    return approve_pending_registration(reg_id)


@router.post('/api/payment/webhook/upay')
async def api_payment_webhook_upay(request: Request) -> Dict[str, Any]:
    """uPay IPN (Instant Payment Notification) webhook.
    
    TODO: Parse actual uPay IPN format once API docs are received.
    Expected fields: order_id, transaction_id, status, amount, signature.
    Must verify signature using UPAY_API_SECRET before approving.
    """
    try:
        body = await request.body()
        payload = json.loads(body.decode('utf-8', errors='ignore'))
    except Exception:
        # Try form data
        try:
            form = await request.form()
            payload = dict(form)
        except Exception:
            logger.error("[UPAY-IPN] Could not parse request body")
            return {'ok': False, 'detail': 'Invalid payload'}

    logger.info(f"[UPAY-IPN] Received: {json.dumps(payload, ensure_ascii=False, default=str)[:500]}")

    # TODO: Verify signature
    # expected_sig = hmac.new(UPAY_API_SECRET.encode(), ...).hexdigest()
    # if not hmac.compare_digest(payload.get('signature',''), expected_sig):
    #     return {'ok': False, 'detail': 'Invalid signature'}

    status = str(payload.get('status') or payload.get('Status') or '').strip().lower()
    order_id = str(payload.get('order_id') or payload.get('OrderId') or '').strip()

    if status not in ('success', 'approved', 'completed', '1'):
        logger.info(f"[UPAY-IPN] Non-success status: {status}")
        return {'ok': True, 'processed': False, 'detail': f'Status: {status}'}

    # Extract email from order_id (format: reg_{email}_{plan})
    email = ''
    if order_id.startswith('reg_'):
        parts = order_id.split('_', 2)
        if len(parts) >= 2:
            email = parts[1]

    if not email:
        email = str(payload.get('email') or payload.get('Email') or payload.get('customer_email') or '').strip()

    if not email:
        logger.warning(f"[UPAY-IPN] Could not extract email from order_id={order_id}")
        return {'ok': False, 'detail': 'Missing email'}

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            sql_placeholder("SELECT id FROM pending_registrations WHERE email = ? AND payment_status != 'completed' ORDER BY id DESC LIMIT 1"),
            (email,)
        )
        row = cur.fetchone()
        if not row:
            logger.info(f"[UPAY-IPN] No pending registration for {email}")
            return {'ok': True, 'processed': False, 'detail': 'No pending registration'}
        reg_id = row['id'] if isinstance(row, dict) else row[0]
    finally:
        try: conn.close()
        except: pass

    result = approve_pending_registration(reg_id)
    logger.info(f"[UPAY-IPN] Approved registration {reg_id} for {email}: {result}")
    return result


@router.post('/api/payment/webhook/mock/legacy')
def api_payment_webhook_mock_legacy(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Legacy endpoint forwarding."""
    return api_payment_webhook_mock(payload)
