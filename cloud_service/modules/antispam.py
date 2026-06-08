"""Lightweight, dependency-free anti-spam helpers for public web forms.

Provides four complementary defenses (use together for best effect):

1. Honeypot field  - a hidden input that humans never see but naive bots fill.
2. Signed form token - embedded on the GET page and verified on POST. Blocks
   bots that POST directly to the API endpoint without ever loading the form.
3. IP rate limiting - in-memory sliding window per client IP.
4. Disposable / malformed email detection.

Everything is stdlib-only so it works on any deployment (SQLite or Postgres).
The rate-limit store is per-process; with a single worker this is sufficient.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import secrets
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("schoolpoints.antispam")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# Hidden field name. Looks plausible to a bot but is NOT an autocomplete token,
# so browser autofill will not populate it for real users.
HONEYPOT_FIELD = "company_url"

# Secret for signing form tokens. Prefer an env-provided secret so tokens stay
# valid across restarts; otherwise generate a per-process random secret.
_SECRET = (
    str(os.getenv("ANTISPAM_SECRET") or "").strip()
    or str(os.getenv("MASTER_LOGIN_SECRET") or "").strip()
    or secrets.token_hex(32)
).encode("utf-8")

# Token validity window (seconds). Reject if the form was submitted suspiciously
# fast (bot) or far too late (stale / replayed page).
TOKEN_MIN_AGE = 2
TOKEN_MAX_AGE = 6 * 60 * 60  # 6 hours

# Disposable / throwaway email domains commonly abused by spam bots.
_DISPOSABLE_DOMAINS = {
    "mailinator.com", "guerrillamail.com", "guerrillamailblock.com",
    "10minutemail.com", "tempmail.com", "temp-mail.org", "tempr.email",
    "yopmail.com", "trashmail.com", "throwawaymail.com", "getnada.com",
    "maildrop.cc", "dispostable.com", "fakeinbox.com", "sharklasers.com",
    "spam4.me", "grr.la", "mailnesia.com", "moakt.com", "mohmal.com",
    "emailondeck.com", "discard.email", "mailcatch.com", "tmpmail.org",
    "tmpmail.net", "fakemail.net", "byom.de", "spambog.com", "mvrht.net",
    "33mail.com", "anonbox.net", "mintemail.com", "mytemp.email",
}

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")

# ---------------------------------------------------------------------------
# In-memory rate-limit store
# ---------------------------------------------------------------------------

_LOCK = threading.Lock()
_HITS: Dict[str, list] = {}


def _cleanup(now: float, window_sec: int) -> None:
    dead = [k for k, v in _HITS.items() if not v or (now - max(v)) > window_sec]
    for k in dead:
        _HITS.pop(k, None)


def get_client_ip(request: Any) -> str:
    """Best-effort client IP, honoring common proxy headers."""
    try:
        xff = request.headers.get("x-forwarded-for") or ""
        if xff:
            return xff.split(",")[0].strip()
        xri = request.headers.get("x-real-ip") or ""
        if xri:
            return xri.strip()
        return request.client.host if getattr(request, "client", None) else ""
    except Exception:
        return ""


def rate_limited(ip: str, key: str = "default", max_hits: int = 5,
                 window_sec: int = 3600) -> bool:
    """Return True if this IP exceeded ``max_hits`` within ``window_sec``.

    A successful (non-limited) call counts as a hit.
    """
    if not ip:
        return False
    now = time.time()
    bucket = f"{key}:{ip}"
    with _LOCK:
        hits = [t for t in _HITS.get(bucket, []) if now - t < window_sec]
        if len(hits) >= max_hits:
            _HITS[bucket] = hits
            return True
        hits.append(now)
        _HITS[bucket] = hits
        if len(_HITS) > 5000:
            _cleanup(now, window_sec)
    return False


# ---------------------------------------------------------------------------
# Honeypot
# ---------------------------------------------------------------------------

def honeypot_triggered(value: Any) -> bool:
    """True when the hidden honeypot field was filled (i.e. a bot)."""
    try:
        return bool(value is not None and str(value).strip())
    except Exception:
        return False


def honeypot_html() -> str:
    """Hidden honeypot input markup. Visually removed + excluded from tab order
    and from autocomplete so real users never interact with it."""
    return (
        '<div aria-hidden="true" '
        'style="position:absolute;left:-9999px;top:-9999px;width:1px;height:1px;'
        'overflow:hidden;opacity:0;">'
        f'<label>Leave this field empty</label>'
        f'<input type="text" name="{HONEYPOT_FIELD}" tabindex="-1" '
        'autocomplete="off" value="" />'
        '</div>'
    )


# ---------------------------------------------------------------------------
# Signed form token
# ---------------------------------------------------------------------------

def make_form_token(ts: Optional[int] = None) -> str:
    ts = int(ts if ts is not None else time.time())
    sig = hmac.new(_SECRET, str(ts).encode("utf-8"), hashlib.sha256).hexdigest()[:24]
    return f"{ts}.{sig}"


def verify_form_token(token: Any, min_age: int = TOKEN_MIN_AGE,
                      max_age: int = TOKEN_MAX_AGE) -> bool:
    try:
        token = str(token or "").strip()
        if "." not in token:
            return False
        ts_s, sig = token.split(".", 1)
        ts = int(ts_s)
        expected = hmac.new(_SECRET, str(ts).encode("utf-8"), hashlib.sha256).hexdigest()[:24]
        if not hmac.compare_digest(sig, expected):
            return False
        age = time.time() - ts
        return min_age <= age <= max_age
    except Exception:
        return False


def form_token_html(field_name: str = "_ft") -> str:
    return f'<input type="hidden" name="{field_name}" value="{make_form_token()}" />'


# ---------------------------------------------------------------------------
# Simple math CAPTCHA (stateless, HMAC-signed answer)
# ---------------------------------------------------------------------------

CAPTCHA_MAX_AGE = 30 * 60  # 30 minutes


def make_captcha() -> tuple:
    """Return (question_text, token). The token binds the correct answer via
    HMAC so verification needs no server-side session storage."""
    a = secrets.randbelow(9) + 1
    b = secrets.randbelow(9) + 1
    answer = a + b
    ts = int(time.time())
    sig = hmac.new(_SECRET, f"{ts}:{answer}".encode("utf-8"), hashlib.sha256).hexdigest()[:16]
    return f"{a} + {b}", f"{ts}.{sig}"


def verify_captcha(token: Any, answer: Any, max_age: int = CAPTCHA_MAX_AGE) -> bool:
    try:
        token = str(token or "").strip()
        ans = int(str(answer or "").strip())
        if "." not in token:
            return False
        ts_s, sig = token.split(".", 1)
        ts = int(ts_s)
        if not (0 <= time.time() - ts <= max_age):
            return False
        expected = hmac.new(_SECRET, f"{ts}:{ans}".encode("utf-8"), hashlib.sha256).hexdigest()[:16]
        return hmac.compare_digest(sig, expected)
    except Exception:
        return False


def captcha_html() -> str:
    """Self-contained, inline-styled CAPTCHA block that looks consistent in any
    of the public forms (registration / contact / callback)."""
    question, token = make_captcha()
    return (
        '<div style="margin:18px 0;padding:14px 16px;border:1px solid rgba(255,255,255,.2);'
        'border-radius:12px;background:rgba(255,255,255,.05);">'
        '<label style="display:block;font-weight:600;margin-bottom:8px;font-size:15px;">'
        f'\U0001F512 \u05d0\u05d9\u05de\u05d5\u05ea \u05d0\u05e0\u05d5\u05e9\u05d9: \u05db\u05de\u05d4 \u05d6\u05d4 '
        f'<b>{question}</b>? <span style="color:#e74c3c;">*</span></label>'
        '<input name="_cap_ans" required inputmode="numeric" autocomplete="off" '
        'placeholder="\u05d4\u05e7\u05dc\u05d9\u05d3\u05d5 \u05d0\u05ea \u05d4\u05ea\u05d5\u05e6\u05d0\u05d4" '
        'style="width:100%;padding:12px 14px;font-size:15px;border:1.5px solid rgba(255,255,255,.22);'
        'border-radius:9px;background:rgba(255,255,255,.06);color:inherit;box-sizing:border-box;" />'
        f'<input type="hidden" name="_cap" value="{token}" />'
        '</div>'
    )


# ---------------------------------------------------------------------------
# Email heuristics
# ---------------------------------------------------------------------------

def email_looks_invalid(email: str) -> bool:
    """True for malformed addresses or known disposable domains."""
    e = str(email or "").strip().lower()
    if not e or len(e) > 254 or not _EMAIL_RE.match(e):
        return True
    domain = e.rsplit("@", 1)[-1]
    if domain in _DISPOSABLE_DOMAINS:
        return True
    return False


# ---------------------------------------------------------------------------
# Combined check
# ---------------------------------------------------------------------------

def screen_submission(request: Any, payload: Dict[str, Any], *,
                      kind: str = "form",
                      max_hits: int = 5,
                      window_sec: int = 3600,
                      require_token: bool = True,
                      require_captcha: bool = False,
                      check_email: bool = False,
                      email_value: str = "") -> Optional[str]:
    """Run all anti-spam checks against a submission.

    Returns ``None`` if the submission looks legitimate, otherwise a short
    reason code string (for logging). Callers decide how to respond.
    """
    ip = get_client_ip(request)

    if honeypot_triggered(payload.get(HONEYPOT_FIELD)):
        logger.warning("antispam[%s]: honeypot triggered ip=%s", kind, ip)
        return "honeypot"

    if require_token and not verify_form_token(payload.get("_ft")):
        logger.warning("antispam[%s]: bad/missing form token ip=%s", kind, ip)
        return "token"

    if require_captcha and not verify_captcha(payload.get("_cap"), payload.get("_cap_ans")):
        logger.warning("antispam[%s]: captcha failed ip=%s", kind, ip)
        return "captcha"

    if check_email and email_looks_invalid(email_value):
        logger.warning("antispam[%s]: invalid/disposable email ip=%s", kind, ip)
        return "email"

    if rate_limited(ip, key=kind, max_hits=max_hits, window_sec=window_sec):
        logger.warning("antispam[%s]: rate limited ip=%s", kind, ip)
        return "rate_limit"

    return None
