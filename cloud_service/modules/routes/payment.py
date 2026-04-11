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
PAYME_SELLER_ID = os.environ.get('PAYME_SELLER_ID', '').strip()
PAYME_API_KEY = os.environ.get('PAYME_API_KEY', '').strip()
PAYME_TEST_MODE = os.environ.get('PAYME_TEST_MODE', '1').strip() == '1'
PAYME_API_URL = 'https://preprod.paymeservice.com/api' if PAYME_TEST_MODE else 'https://ng.payme.io/api'
PAYME_LIVE = bool(PAYME_SELLER_ID and PAYME_API_KEY)


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


def _payme_generate_sale(*, buyer_key: str, amount: float, product_name: str,
                          sale_callback_url: str, sale_return_url: str,
                          seller_payme_id: str = '') -> Dict[str, Any]:
    """Call PayMe generate-sale API to charge a tokenized card.
    
    Returns dict with payme_sale_id, payme_transaction_id on success.
    """
    if not PAYME_LIVE:
        return {'ok': False, 'error': 'PayMe not configured'}

    payload = {
        'seller_payme_id': seller_payme_id or PAYME_SELLER_ID,
        'sale_price': amount,
        'currency': 'ILS',
        'product_name': product_name,
        'sale_callback_url': sale_callback_url,
        'sale_return_url': sale_return_url,
        'buyer_key': buyer_key,
        'language': 'he',
    }
    data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    url = f'{PAYME_API_URL}/generate-sale'
    req = urllib.request.Request(url, data=data, headers={
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode('utf-8', errors='ignore')
        result = json.loads(body)
        logger.info(f"[PAYME] generate-sale response: {body[:500]}")
        if result.get('status_code') == 0 or result.get('payme_status') == 'success':
            return {'ok': True, **result}
        return {'ok': False, 'error': result.get('status_error_details') or body[:200], **result}
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

    if PAYME_LIVE:
        # --- PayMe Hosted Fields ---
        test_mode_js = 'true' if PAYME_TEST_MODE else 'false'
        body = f"""
        <style>
          .pay-wrap {{ max-width:480px; margin:30px auto; }}
          .pay-card {{ background:rgba(255,255,255,.06); border:1px solid rgba(255,255,255,.15); border-radius:16px; padding:28px; backdrop-filter:blur(10px); }}
          .pay-summary {{ text-align:center; margin-bottom:24px; }}
          .pay-summary h2 {{ margin:0 0 8px; font-size:22px; }}
          .pay-total {{ font-size:28px; font-weight:800; color:#2ecc71; margin:12px 0; }}
          .pay-field {{ margin-bottom:16px; }}
          .pay-field label {{ display:block; font-size:13px; opacity:.8; margin-bottom:6px; }}
          .pay-field-box {{ background:rgba(255,255,255,.08); border:1px solid rgba(255,255,255,.2); border-radius:8px; padding:12px; min-height:42px; transition: border-color .2s; }}
          .pay-field-box.focused {{ border-color:#667eea; }}
          .pay-row {{ display:flex; gap:12px; }}
          .pay-row .pay-field {{ flex:1; }}
          #payBtn {{ width:100%; padding:14px; background:linear-gradient(135deg,#667eea,#764ba2); color:#fff; border:none; border-radius:10px; font-size:18px; font-weight:700; cursor:pointer; transition: opacity .2s; }}
          #payBtn:disabled {{ opacity:.6; cursor:not-allowed; }}
          #payMsg {{ text-align:center; margin-top:12px; font-size:14px; min-height:20px; }}
          .pay-secure {{ text-align:center; font-size:12px; opacity:.5; margin-top:16px; }}
        </style>
        <div class="pay-wrap"><div class="pay-card">
          <div class="pay-summary">
            <h2>תשלום מאובטח</h2>
            <div style="opacity:.7;">{safe_plan_name} — {safe_email}</div>
            <div class="pay-total">{price_line}</div>
          </div>
          <div class="pay-field">
            <label>מספר כרטיס</label>
            <div class="pay-field-box" id="card-number-container"></div>
          </div>
          <div class="pay-row">
            <div class="pay-field">
              <label>תוקף</label>
              <div class="pay-field-box" id="card-expiry-container"></div>
            </div>
            <div class="pay-field">
              <label>CVV</label>
              <div class="pay-field-box" id="card-cvc-container"></div>
            </div>
          </div>
          <button id="payBtn" disabled>שלם ₪{total}</button>
          <div id="payMsg"></div>
          <div class="pay-secure">🔒 מאובטח ע"י PayMe — PCI Level 1</div>
        </div></div>

        <script src="https://cdn.paymeservice.com/hf/v1/paymeFields.js"></script>
        <script>
        (function() {{
          var apiKey = '{html_mod.escape(PAYME_API_KEY)}';
          var testMode = {test_mode_js};
          var btn = document.getElementById('payBtn');
          var msg = document.getElementById('payMsg');
          var instance = null;

          PayMe.create(apiKey, {{ testMode: testMode, language: 'he' }})
            .then(function(inst) {{
              instance = inst;
              var fields = inst.hostedFields();
              var cardNumber = fields.create('cardNumber');
              var expiry = fields.create('cardExpiration');
              var cvc = fields.create('cvc');

              cardNumber.mount('#card-number-container');
              expiry.mount('#card-expiry-container');
              cvc.mount('#card-cvc-container');

              // Focus styling
              ['card-number-container','card-expiry-container','card-cvc-container'].forEach(function(id){{
                var el = document.getElementById(id);
                el.addEventListener('focus', function(){{ el.classList.add('focused'); }}, true);
                el.addEventListener('blur', function(){{ el.classList.remove('focused'); }}, true);
              }});

              btn.disabled = false;
            }})
            .catch(function(err) {{
              msg.textContent = 'שגיאה באתחול טופס התשלום: ' + (err.message || err);
              msg.style.color = '#e74c3c';
            }});

          btn.addEventListener('click', function() {{
            btn.disabled = true;
            btn.textContent = 'מעבד תשלום...';
            msg.textContent = '';
            msg.style.color = '';

            var saleData = {{
              payerFirstName: 'Customer',
              payerLastName: '',
              payerEmail: '{safe_email}',
              payerPhone: '',
              total: {{
                label: '{safe_plan_name}',
                amount: {{
                  currency: 'ILS',
                  value: '{total}.00'
                }}
              }}
            }};

            instance.tokenize(saleData)
              .then(function(result) {{
                // Send token to our backend
                return fetch('/api/payment/charge', {{
                  method: 'POST',
                  headers: {{ 'Content-Type': 'application/json' }},
                  body: JSON.stringify({{
                    buyer_key: result.token,
                    email: '{safe_email}',
                    plan: '{safe_plan}',
                    amount: {total}
                  }})
                }});
              }})
              .then(function(resp) {{ return resp.json(); }})
              .then(function(data) {{
                if (data.ok) {{
                  window.location.href = '/web/payment/success?email={safe_email}';
                }} else {{
                  msg.textContent = data.error || data.detail || 'שגיאה בתשלום';
                  msg.style.color = '#e74c3c';
                  btn.disabled = false;
                  btn.textContent = 'שלם ₪{total}';
                }}
              }})
              .catch(function(err) {{
                var errMsg = '';
                if (err.validationError) {{
                  var errs = err.errors || {{}};
                  errMsg = Object.values(errs).join(', ') || 'נא למלא את כל השדות';
                }} else {{
                  errMsg = err.message || err.error || 'שגיאה בתשלום';
                }}
                msg.textContent = errMsg;
                msg.style.color = '#e74c3c';
                btn.disabled = false;
                btn.textContent = 'שלם ₪{total}';
              }});
          }});
        }})();
        </script>
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
                    if(d.ok){{ window.location.href='/web/payment/success?email={safe_email}'; }}
                    else {{ alert('שגיאה: '+(d.detail||'unknown')); btn.disabled=false; btn.textContent='שלם ₪{total}'; }}
                }} catch(e){{ alert('שגיאה בתקשורת'); btn.disabled=false; btn.textContent='שלם ₪{total}'; }}
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
# Backend charge endpoint — receives token from frontend, calls PayMe API
# ---------------------------------------------------------------------------
@router.post('/api/payment/charge')
def api_payment_charge(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Receive buyer_key from PayMe Hosted Fields tokenization, call generate-sale."""
    buyer_key = str(payload.get('buyer_key') or '').strip()
    email = str(payload.get('email') or '').strip()
    plan = str(payload.get('plan') or '').strip()
    amount = int(payload.get('amount') or 0)

    if not buyer_key or not email or amount <= 0:
        return {'ok': False, 'error': 'חסרים פרטים'}

    if not PAYME_LIVE:
        return {'ok': False, 'error': 'שרת התשלומים לא מוגדר'}

    plan_data = _get_plan_details(plan)
    plan_name = plan_data.get('display_name') or plan

    # Build callback URLs
    sale_callback_url = ''  # IPN — PayMe will POST to this
    sale_return_url = ''    # Redirect after payment (not used in hosted fields flow)

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
        _approve_by_email(email)
        return {'ok': True, 'sale_id': ref}
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
