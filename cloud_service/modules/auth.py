import hashlib
import hmac
import secrets
import urllib.parse
from typing import Optional, Dict, Any
from fastapi import Request, Response
from fastapi.responses import RedirectResponse

from .db import get_db_connection, sql_placeholder
from .config import MASTER_PASSWORD_HASH

def pbkdf2_hash(password: str) -> str:
    """Hash password using PBKDF2."""
    return hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        b'schoolpoints_salt_2024',
        100000
    ).hex()

def master_token_valid(token: str, tenant_id: str) -> bool:
    """Check if the master token is valid for the given tenant."""
    if not token or not tenant_id:
        return False
    # token format: tenant_id:hash
    parts = token.split(':')
    if len(parts) != 2:
        return False
    tid, h = parts
    if tid != tenant_id:
        return False
    
    # Re-compute hash
    expected = hmac.new(
        MASTER_PASSWORD_HASH.encode('utf-8'),
        tenant_id.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(h, expected)

def web_tenant_from_cookie(request: Request) -> str:
    """Get tenant_id from cookie."""
    return str(request.cookies.get('web_tenant') or '').strip()

def web_teacher_from_cookie(request: Request) -> int:
    """Get teacher_id from cookie."""
    try:
        return int(request.cookies.get('web_teacher') or 0)
    except Exception:
        return 0

def web_require_tenant(request: Request) -> Optional[Response]:
    """Guard: Require tenant cookie. Redirect to signin if missing."""
    tid = web_tenant_from_cookie(request)
    if not tid:
        return RedirectResponse(url='/web/signin', status_code=302)
    return None

def web_next_from_request(request: Request, default: str = '/web/admin') -> str:
    """Get 'next' url from query param or default."""
    nxt = str(request.query_params.get('next') or '').strip()
    if not nxt or not nxt.startswith('/'):
        return default
    return nxt

def safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default

def web_master_ok(request: Request) -> bool:
    tenant_id = web_tenant_from_cookie(request)
    if not tenant_id:
        return False
    try:
        token = str(request.cookies.get('web_master') or '').strip()
    except Exception:
        token = ''
    return master_token_valid(token, tenant_id)

def web_current_teacher(request: Request) -> Optional[Dict[str, Any]]:
    from .db import tenant_db_connection, sql_placeholder
    tenant_id = web_tenant_from_cookie(request)
    if not tenant_id:
        return None
    tid = web_teacher_from_cookie(request)
    if tid <= 0:
        return None
    
    try:
        conn = tenant_db_connection(tenant_id)
        try:
            cur = conn.cursor()
            # Handle different columns if necessary, but generally we want name and is_admin
            cur.execute(
                sql_placeholder('SELECT id, name, is_admin, can_edit_student_card, can_edit_student_photo FROM teachers WHERE id = ? LIMIT 1'),
                (tid,)
            )
            row = cur.fetchone()
            if not row:
                return None
            
            if isinstance(row, dict):
                return dict(row)
            
            # Fallback for tuple cursor
            # columns: id, name, is_admin, can_edit_student_card, can_edit_student_photo
            return {
                'id': row[0],
                'name': row[1],
                'is_admin': row[2],
                'can_edit_student_card': row[3] if len(row) > 3 else 0,
                'can_edit_student_photo': row[4] if len(row) > 4 else 0,
            }
        finally:
            conn.close()
    except Exception:
        return None

def web_require_admin_teacher(request: Request) -> Optional[Response]:
    t = web_current_teacher(request)
    if not t:
        # Check master
        if web_master_ok(request):
            return None
        return RedirectResponse(url='/web/teacher-login', status_code=302)
    
    if int(t.get('is_admin') or 0) == 1:
        return None
    
    # Not admin
    return Response("Access Denied: Admin only", status_code=403)

def web_require_teacher(request: Request) -> Optional[Response]:
    t = web_current_teacher(request)
    if t:
        return None
    if web_master_ok(request):
        return None
    return RedirectResponse(url='/web/teacher-login', status_code=302)
