"""Payment module — PayMe integration.

Flow:
  1. User registers → pending_registrations row created
  2. /web/payment?reg_email=...&plan=... shows payment page with PayMe Hosted Fields
  3. Frontend: PayMe JS SDK collects card → tokenize → sends token to our backend
  4. Backend: POST to PayMe generate-sale API with the token
  5. PayMe IPN webhook confirms payment → we approve the pending registration

Environment variables needed:
  PAYME_SELLER_ID   — seller_payme_id from PayMe dashboard
  PAYME_API_KEY     — API key from PayMe dashboard (Settings → API)
  PAYME_TEST_MODE   — set to '1' for sandbox (default), '0' for production
"""
import json
import logging
import os
import secrets
import urllib.request
import urllib.parse
import html as html_mod
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
# PayMe configuration (from environment variables)
# ---------------------------------------------------------------------------
def _payme_config():
    """Read PayMe config dynamically so env var changes take effect without redeploy."""
    seller_id = os.environ.get('PAYME_SELLER_ID', '').strip()
    api_key = os.environ.get('PAYME_API_KEY', '').strip() or seller_id
    test_mode = os.environ.get('PAYME_TEST_MODE', '1').strip() == '1'
    api_url = 'https://preprod.paymeservice.com/api' if test_mode else 'https://ng.payme.io/api'
    return {
        'seller_id': seller_id,
        'api_key': api_key,
        'test_mode': test_mode,
        'api_url': api_url,
        'form_ready': bool(api_key),
        'charge_ready': bool(seller_id and api_key),
    }

# Module-level aliases (evaluated at import — kept for backward compat)
PAYME_SELLER_ID = os.environ.get('PAYME_SELLER_ID', '').strip()
PAYME_API_KEY = os.environ.get('PAYME_API_KEY', '').strip() or PAYME_SELLER_ID
PAYME_TEST_MODE = os.environ.get('PAYME_TEST_MODE', '1').strip() == '1'
PAYME_API_URL = 'https://preprod.paymeservice.com/api' if PAYME_TEST_MODE else 'https://ng.payme.io/api'
PAYME_FORM_READY = bool(PAYME_API_KEY)
PAYME_CHARGE_READY = bool(PAYME_SELLER_ID and PAYME_API_KEY)
PAYME_LIVE = PAYME_FORM_READY


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


def _payme_generate_sale(*, amount: float, product_name: str,
                          sale_callback_url: str, sale_return_url: str,
                          buyer_key: str = '',
                          payer_email: str = '',
                          payer_name: str = '',
                          seller_payme_id: str = '') -> Dict[str, Any]:
    """Call PayMe generate-sale API.
    
    Without buyer_key: returns sale_url for redirect to PayMe hosted payment page.
    With buyer_key: charges a tokenized card directly.
    Returns dict with sale_url or payme_sale_id on success.
    """
    cfg = _payme_config()
    if not cfg['form_ready']:
        return {'ok': False, 'error': 'PayMe not configured'}

    payload = {
        'seller_payme_id': seller_payme_id or cfg['seller_id'],
        'sale_price': int(amount * 100),  # PayMe expects agorot
        'currency': 'ILS',
        'product_name': product_name,
        'sale_callback_url': sale_callback_url,
        'sale_return_url': sale_return_url,
        'sale_type': 'J4',       # basic sale
        'installments': 1,
        'language': 'he',
    }
    if buyer_key:
        payload['buyer_key'] = buyer_key
    if payer_email:
        payload['payer_email'] = payer_email
    if payer_name:
        parts = payer_name.strip().split(' ', 1)
        payload['payer_first_name'] = parts[0]
        payload['payer_last_name'] = parts[1] if len(parts) > 1 else ''
    data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    url = f"{cfg['api_url']}/generate-sale"
    logger.info(f"[PAYME] calling url={url} test_mode={cfg['test_mode']} seller_id_prefix={cfg['seller_id'][:10]}")
    req = urllib.request.Request(url, data=data, headers={
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    })
    try:
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read().decode('utf-8', errors='ignore')
        except urllib.error.HTTPError as http_err:
            body = http_err.read().decode('utf-8', errors='ignore')
            logger.error(f"[PAYME] HTTP {http_err.code}: {body[:500]}")
        result = json.loads(body)
        logger.info(f"[PAYME] generate-sale response: {body[:500]}")
        if result.get('status_code') == 0 or result.get('payme_status') == 'success':
            return {'ok': True, **result}
        err = result.get('status_error_details') or result.get('payme_status') or body[:300]
        return {'ok': False, 'error': err, **result}
    except Exception as e:
        logger.error(f"[PAYME] generate-sale error: {e}")
        return {'ok': False, 'error': str(e)}


def _record_payment(*, tenant_id: str, email: str, plan: str, amount: int,
                     method: str, reference: str, status: str, raw_response: str = '') -> int:
    """Record a payment in institution_payments table. Returns payment id."""
    from ..admin_db import ensure_admin_tables
    ensure_admin_tables()
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql_placeholder(
            "INSERT INTO institution_payments (tenant_id, amount, payment_method, reference, notes, payment_date) "
            "VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)"),
            (tenant_id or email, amount, method, reference,
             json.dumps({'plan': plan, 'status': status, 'email': email, 'raw': raw_response[:1000]}, ensure_ascii=False)))
        conn.commit()
        # Get last id
        if USE_POSTGRES:
            cur.execute("SELECT lastval()")
        else:
            cur.execute("SELECT last_insert_rowid()")
        row = cur.fetchone()
        return int((row[0] if not isinstance(row, dict) else list(row.values())[0]) if row else 0)
    except Exception as e:
        logger.error(f"[PAYMENT] record error: {e}")
        return 0
    finally:
        try: conn.close()
        except: pass


# ---------------------------------------------------------------------------
# Payment page — PayMe Hosted Fields or Mock
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
        return _auto_approve_free(reg_email, plan, request)

    price_line = f'₪{price_monthly}/חודש × {duration} חודשים = <b>₪{total}</b>' if duration > 1 else f'<b>₪{total}</b>'
    safe_email = html_mod.escape(reg_email)
    safe_plan = html_mod.escape(plan)
    safe_plan_name = html_mod.escape(plan_name)

    cfg = _payme_config()
    if cfg['form_ready']:
        # --- PayMe Redirect Flow: generate sale_url server-side, redirect user ---
        base_url = str(request.base_url).rstrip('/')
        sale_callback_url = f'{base_url}/api/payment/webhook/payme'
        sale_return_url = f'{base_url}/web/payment/success?email={urllib.parse.quote(reg_email)}'
        # Try to get contact name from pending registration
        payer_name = ''
        try:
            _conn = get_db_connection()
            _cur = _conn.cursor()
            _cur.execute(sql_placeholder("SELECT contact_name FROM pending_registrations WHERE email=? ORDER BY id DESC LIMIT 1"), (reg_email,))
            _row = _cur.fetchone()
            if _row:
                payer_name = str((_row['contact_name'] if isinstance(_row, dict) else _row[0]) or '').strip()
            _conn.close()
        except Exception:
            pass
        sale_result = _payme_generate_sale(
            amount=float(total),
            product_name=f'SchoolPoints - {plan_name}',
            sale_callback_url=sale_callback_url,
            sale_return_url=sale_return_url,
            payer_email=reg_email,
            payer_name=payer_name,
        )
        if sale_result.get('ok') and sale_result.get('sale_url'):
            return RedirectResponse(url=sale_result['sale_url'], status_code=302)
        # Fallback: show error + retry button
        err_msg = html_mod.escape(sale_result.get('error') or 'שגיאה ביצירת עסקת תשלום')
        body = f"""
        <div style="max-width:500px;margin:40px auto;text-align:center;background:rgba(255,255,255,.06);padding:30px;border-radius:15px;border:1px solid rgba(255,255,255,.15);">
          <div style="font-size:48px;margin-bottom:16px;">⚠️</div>
          <h2>שגיאה ביצירת תשלום</h2>
          <p style="color:#e74c3c;">{err_msg}</p>
          <p style="opacity:.7;font-size:14px;">מסלול: {safe_plan_name} | סכום: ₪{total}</p>
          <a href="/web/payment?reg_email={safe_email}&plan={safe_plan}" style="display:inline-block;padding:12px 28px;background:#667eea;color:#fff;border-radius:8px;text-decoration:none;margin-top:12px;">נסה שוב</a>
          <br/><a href="/web/register" style="opacity:.5;font-size:13px;margin-top:12px;display:inline-block;">חזרה להרשמה</a>
        </div>
        """
    else:
        # --- Mock payment (no PayMe credentials) ---
        body = f"""
        <div style="max-width:500px; margin:40px auto; text-align:center; background:rgba(255,255,255,.06); padding:30px; border-radius:15px; border:1px solid rgba(255,255,255,.15);">
          <h2>תשלום מאובטח</h2>
          <div style="font-size:14px;color:#e67e22;margin-bottom:16px;background:rgba(255,200,50,.1);padding:8px;border-radius:8px;">מצב בדיקה — סליקה אמיתית תופעל בקרוב</div>
          <div style="font-size:18px; margin:20px 0;">
            <div><b>לקוח:</b> {safe_email}</div>
            <div><b>מסלול:</b> {safe_plan_name}</div>
            <div style="font-size:22px; color:#27ae60; margin-top:10px;">{price_line}</div>
          </div>
          <button id="payBtn" onclick="processPayment()" style="width:100%; padding:15px; background:#2ecc71; color:white; border:none; border-radius:8px; font-size:18px; font-weight:bold; cursor:pointer;">שלם ₪{total} (בדיקה)</button>
          <script>
            async function processPayment() {{
                var btn=document.getElementById('payBtn');
                btn.disabled=true; btn.textContent='מעבד תשלום...';
                await new Promise(r=>setTimeout(r,1500));
                try {{
                    var r=await fetch('/api/payment/webhook/mock',{{method:'POST',headers:{{'Content-Type':'application/json'}},
                        body:JSON.stringify({{email:'{safe_email}',status:'success',amount:{total},plan:'{safe_plan}'}})
                    }});
                    var d=await r.json();
                    if(d.ok){{ var u='/web/payment/success?email={safe_email}'; if(d.tenant_id) u+='&tenant_id='+encodeURIComponent(d.tenant_id); window.location.href=u; }}
                    else {{ alert('שגיאה: '+(d.detail||'unknown')); btn.disabled=false; btn.textContent='שלם ₪{total}'; }}
                }} catch(e){{ alert('שגיאה בתקשורת'); btn.disabled=false; btn.textContent='שלם ₪{total}'; }}
            }}
          </script>
        </div>
        """
    return public_web_shell('תשלום', body, request=request)


@router.get('/web/payment/success', response_class=HTMLResponse)
def web_payment_success(request: Request, email: str = Query(default=''), tenant_id: str = Query(default='')) -> str:
    safe_email = html_mod.escape(email)
    safe_tid = html_mod.escape(tenant_id)
    activate_link = f'/web/activate?tenant_id={safe_tid}' if tenant_id else '/web/activate'

    body = f"""
    <div style="text-align:center; padding:40px 20px; max-width:560px; margin:0 auto;">
      <div style="font-size:64px; margin-bottom:16px;">✅</div>
      <h2 style="color:#2ecc71;">התשלום עבר בהצלחה!</h2>
      <p style="opacity:.8;">פרטי ההתחברות נשלחו למייל <b>{safe_email}</b></p>

      <div style="background:rgba(255,255,255,.06); border:1px solid rgba(255,255,255,.15); border-radius:12px; padding:20px; margin:24px 0; text-align:right; line-height:1.9;">
        <div style="font-weight:700; font-size:16px; margin-bottom:8px; text-align:center;">השלב הבא — הפעלת התוכנה</div>
        <div>1. התקן והפעל את התוכנה במחשב</div>
        <div>2. פתח <b>⚙ הגדרות מערכת → רישום מערכת</b></div>
        <div>3. העתק את <b>קוד המערכת</b> המוצג שם</div>
        <div>4. לחץ על הכפתור למטה כדי לקבל קוד הפעלה</div>
      </div>

      <a href="{activate_link}" style="display:inline-block; padding:14px 32px; background:linear-gradient(135deg,#667eea,#764ba2); color:#fff; border-radius:10px; font-size:16px; font-weight:700; text-decoration:none; margin-bottom:12px;">הפעלת רישיון</a>
      <br/>
      <a href="/web/download" style="opacity:.6; font-size:14px;">להורדת התוכנה</a>
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
# Backend charge endpoint — receives token from frontend, calls PayMe API
# ---------------------------------------------------------------------------
@router.post('/api/payment/charge')
def api_payment_charge(request: Request, payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """Receive buyer_key from PayMe Hosted Fields tokenization, call generate-sale."""
    buyer_key = str(payload.get('buyer_key') or '').strip()
    email = str(payload.get('email') or '').strip()
    plan = str(payload.get('plan') or '').strip()
    amount = int(payload.get('amount') or 0)

    if not buyer_key or not email or amount <= 0:
        return {'ok': False, 'error': 'חסרים פרטים'}

    if not PAYME_CHARGE_READY:
        return {'ok': False, 'error': 'חשבון הסליקה בתהליך הפעלה — נסה שוב בעוד מספר ימים'}

    plan_data = _get_plan_details(plan)
    plan_name = plan_data.get('display_name') or plan

    # Build callback URLs
    base_url = str(request.base_url).rstrip('/')  # e.g. https://schoolpoints.co.il
    sale_callback_url = f'{base_url}/api/payment/webhook/payme'
    sale_return_url = f'{base_url}/web/payment/success?email={urllib.parse.quote(email)}'

    result = _payme_generate_sale(
        buyer_key=buyer_key,
        amount=float(amount),
        product_name=f'SchoolPoints - {plan_name}',
        sale_callback_url=sale_callback_url,
        sale_return_url=sale_return_url,
    )

    if result.get('ok'):
        # Payment succeeded — record and approve registration
        ref = str(result.get('payme_sale_id') or result.get('sale_id') or '')
        _record_payment(
            tenant_id='', email=email, plan=plan, amount=amount,
            method='payme', reference=ref, status='completed',
            raw_response=json.dumps(result, ensure_ascii=False, default=str)[:2000],
        )
        # Approve pending registration
        approve_result = _approve_by_email(email)
        tid = approve_result.get('tenant_id', '') if isinstance(approve_result, dict) else ''
        return {'ok': True, 'sale_id': ref, 'tenant_id': tid}
    else:
        error_msg = result.get('error') or 'התשלום נכשל'
        _record_payment(
            tenant_id='', email=email, plan=plan, amount=amount,
            method='payme', reference='', status='failed',
            raw_response=json.dumps(result, ensure_ascii=False, default=str)[:2000],
        )
        return {'ok': False, 'error': error_msg}


def _approve_by_email(email: str) -> Dict[str, Any]:
    """Find and approve a pending registration by email."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            sql_placeholder("SELECT id FROM pending_registrations WHERE email = ? AND payment_status != 'completed' ORDER BY id DESC LIMIT 1"),
            (email,)
        )
        row = cur.fetchone()
        if not row:
            logger.info(f"[PAYMENT] No pending registration for {email}")
            return {'ok': True, 'processed': False, 'detail': 'No pending registration'}
        reg_id = row['id'] if isinstance(row, dict) else row[0]
    finally:
        try: conn.close()
        except: pass
    result = approve_pending_registration(reg_id)
    logger.info(f"[PAYMENT] Approved registration {reg_id} for {email}: {result}")
    return result


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
    return _approve_by_email(email)


@router.post('/api/payment/webhook/payme')
async def api_payment_webhook_payme(request: Request) -> Dict[str, Any]:
    """PayMe IPN (Instant Payment Notification) webhook.
    
    PayMe sends a POST with sale details when a payment is completed.
    Fields: sale_status, sale_paid_amount, sale_payme_id, buyer_email, etc.
    """
    try:
        body = await request.body()
        payload = json.loads(body.decode('utf-8', errors='ignore'))
    except Exception:
        try:
            form = await request.form()
            payload = dict(form)
        except Exception:
            logger.error("[PAYME-IPN] Could not parse request body")
            return {'ok': False, 'detail': 'Invalid payload'}

    logger.info(f"[PAYME-IPN] Received: {json.dumps(payload, ensure_ascii=False, default=str)[:500]}")

    sale_status = str(payload.get('sale_status') or '').strip().lower()
    if sale_status not in ('completed', 'success', 'approved'):
        logger.info(f"[PAYME-IPN] Non-success status: {sale_status}")
        return {'ok': True, 'processed': False, 'detail': f'Status: {sale_status}'}

    email = str(payload.get('buyer_email') or payload.get('payer_email') or '').strip()
    sale_id = str(payload.get('sale_payme_id') or payload.get('payme_sale_id') or '').strip()
    amount = payload.get('sale_paid_amount') or payload.get('amount') or 0

    if email:
        _record_payment(
            tenant_id='', email=email, plan='', amount=int(float(amount or 0)),
            method='payme_ipn', reference=sale_id, status='completed',
            raw_response=json.dumps(payload, ensure_ascii=False, default=str)[:2000],
        )
        result = _approve_by_email(email)
        logger.info(f"[PAYME-IPN] Processed for {email}: {result}")
        return result

    logger.warning(f"[PAYME-IPN] No email in payload, sale_id={sale_id}")
    return {'ok': True, 'processed': False, 'detail': 'No email found'}


# Legacy endpoints for backward compatibility
@router.post('/api/payment/webhook/upay')
async def api_payment_webhook_upay(request: Request) -> Dict[str, Any]:
    """Legacy uPay webhook — forwards to PayMe handler."""
    return await api_payment_webhook_payme(request)

@router.post('/api/payment/webhook/mock/legacy')
def api_payment_webhook_mock_legacy(payload: Dict[str, Any]) -> Dict[str, Any]:
    return api_payment_webhook_mock(payload)
