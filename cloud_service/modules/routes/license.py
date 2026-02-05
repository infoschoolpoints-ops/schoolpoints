from fastapi import APIRouter, HTTPException, Body
from typing import Dict, Any
import datetime

from ..models import LicenseFetchPayload
from ..db import get_db_connection, sql_placeholder, ensure_tenant_db_exists
from ..auth import check_password_hash

router = APIRouter()

@router.post('/api/license/fetch')
def api_license_fetch(payload: LicenseFetchPayload) -> Dict[str, Any]:
    tenant_id = str(payload.tenant_id or '').strip()
    api_key = str(payload.api_key or '').strip()
    password = str(payload.password or '').strip()
    
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Missing tenant_id")

    # If api_key provided, verify it. If password provided, verify it.
    # Logic: try to find institution by tenant_id.
    
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql_placeholder('SELECT api_key, password_hash, name FROM institutions WHERE tenant_id = ? LIMIT 1'), (tenant_id,))
        row = cur.fetchone()
        
        if not row:
            raise HTTPException(status_code=404, detail="Institution not found")
            
        real_api_key = row['api_key'] if isinstance(row, dict) else row[0]
        real_pw_hash = row['password_hash'] if isinstance(row, dict) else row[1]
        inst_name = row['name'] if isinstance(row, dict) else row[2]
        
        authenticated = False
        if api_key and api_key == real_api_key:
            authenticated = True
        elif password and check_password_hash(password, real_pw_hash):
            authenticated = True
            
        if not authenticated:
            raise HTTPException(status_code=401, detail="Invalid credentials")
            
        # Success. Return license info.
        # In a real app, check subscription status, expiration, etc.
        # For now, return active basic license.
        
        return {
            'ok': True,
            'license': {
                'tenant_id': tenant_id,
                'name': inst_name,
                'plan': 'basic',
                'status': 'active',
                'expires_at': '2099-12-31',
                'api_key': real_api_key  # Send back API key if authenticated by password, so client can store it
            }
        }
    finally:
        try: conn.close()
        except: pass
