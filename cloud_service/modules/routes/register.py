from fastapi import APIRouter, Request, Body, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from typing import Dict, Any
import datetime
import secrets
import re
import logging

from ..db import get_db_connection, sql_placeholder, integrity_errors
from ..config import USE_POSTGRES
from ..auth import pbkdf2_hash
from ..utils import random_pair_code

router = APIRouter()
logger = logging.getLogger("schoolpoints.register")

def ensure_pending_registrations_table() -> None:
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        try:
            if USE_POSTGRES:
                cur.execute(
                    '''
                    CREATE TABLE IF NOT EXISTS pending_registrations (
                        id BIGSERIAL PRIMARY KEY,
                        institution_name TEXT NOT NULL,
                        institution_code TEXT,
                        contact_name TEXT,
                        email TEXT NOT NULL,
                        phone TEXT,
                        password_hash TEXT,
                        plan TEXT,
                        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        payment_status TEXT DEFAULT 'pending',
                        payment_id TEXT
                    )
                    '''
                )
            else:
                cur.execute(
                    '''
                    CREATE TABLE IF NOT EXISTS pending_registrations (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        institution_name TEXT NOT NULL,
                        institution_code TEXT,
                        contact_name TEXT,
                        email TEXT NOT NULL,
                        phone TEXT,
                        password_hash TEXT,
                        plan TEXT,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                        payment_status TEXT DEFAULT 'pending',
                        payment_id TEXT
                    )
                    '''
                )
        except Exception:
            pass

        try:
            if USE_POSTGRES:
                cur.execute('ALTER TABLE pending_registrations ADD COLUMN IF NOT EXISTS institution_code TEXT')
            else:
                cur.execute('ALTER TABLE pending_registrations ADD COLUMN institution_code TEXT')
        except Exception:
            pass
        conn.commit()
    finally:
        try: conn.close()
        except: pass

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
