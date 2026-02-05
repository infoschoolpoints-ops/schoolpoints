import secrets
import html
import os
import logging
from typing import Dict, Any, Optional

from .db import get_db_connection, sql_placeholder, ensure_tenant_db_exists, generate_numeric_tenant_id, tenant_db_connection
from .email import send_email
from .config import REGISTRATION_NOTIFY_EMAIL

logger = logging.getLogger("schoolpoints.registration")

def approve_pending_registration(reg_id: int) -> Dict[str, Any]:
    """Approve a pending registration: create tenant, send email, mark completed."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            sql_placeholder("SELECT id, institution_name, institution_code, contact_name, plan, password_hash, email, payment_status, phone FROM pending_registrations WHERE id = ? LIMIT 1"),
            (reg_id,)
        )
        row = cur.fetchone()
        if not row:
            return {'ok': False, 'detail': 'Registration not found'}
        
        if isinstance(row, dict):
             r = row
        else:
             # Fallback for tuple row factory
             r = {
                 'id': row[0],
                 'institution_name': row[1],
                 'institution_code': row[2],
                 'contact_name': row[3],
                 'plan': row[4],
                 'password_hash': row[5],
                 'email': row[6],
                 'payment_status': row[7],
                 'phone': row[8]
             }
             
        if r['payment_status'] == 'completed':
            return {'ok': True, 'already_completed': True}

        inst_name = r['institution_name']
        inst_code = str(r.get('institution_code') or '').strip()
        contact = r['contact_name']
        email = r['email']
        pwd_hash = r['password_hash']
        
        # 1. Use chosen institution code as Tenant ID if available, else generate numeric
        tenant_id = inst_code
        if not tenant_id:
            tenant_id = generate_numeric_tenant_id(conn)

        # Check collision
        try:
            cur.execute(sql_placeholder('SELECT 1 FROM institutions WHERE tenant_id = ? LIMIT 1'), (str(tenant_id),))
            if cur.fetchone():
                return {'ok': False, 'detail': 'Tenant ID already exists'}
        except Exception:
            pass
        
        # 2. Create Institution
        api_key = secrets.token_urlsafe(24)
        
        try:
            # Check columns in institutions table to avoid errors if schema differs
            # Assuming standard schema from db.py
            cur.execute(
                sql_placeholder("INSERT INTO institutions (tenant_id, name, api_key, password_hash, contact_name, email, phone, plan) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"),
                (tenant_id, inst_name, api_key, pwd_hash, contact, email, r.get('phone'), r.get('plan'))
            )
        except Exception as e:
            # Fallback if columns missing?
            logger.error(f"Error inserting institution: {e}")
            try:
                cur.execute(
                    sql_placeholder("INSERT INTO institutions (tenant_id, name, api_key, password_hash) VALUES (?, ?, ?, ?)"),
                    (tenant_id, inst_name, api_key, pwd_hash)
                )
            except Exception as e2:
                return {'ok': False, 'detail': f'DB Insert failed: {e2}'}

        # Create Tenant DB
        try:
            ensure_tenant_db_exists(str(tenant_id))
        except Exception as e:
            try: conn.rollback()
            except: pass
            return {'ok': False, 'detail': f'Tenant DB creation failed: {e}'}
        
        # 3. Update pending registration
        cur.execute(
            sql_placeholder("UPDATE pending_registrations SET payment_status = 'completed', payment_id = ? WHERE id = ?"),
            (f"MANUAL_{secrets.token_hex(4)}", reg_id)
        )
        conn.commit()

        # Initialize Tenant DB tables if needed? 
        # ensure_tenant_db_exists handles table creation for both SQLite and Postgres in db.py now.
        
        download_url = "https://schoolpoints.co.il/web/download"
        
        body = f"""
        <div dir="rtl" style="font-family:Arial, sans-serif; line-height:1.6; color:#333;">
            <h2 style="color:#2ecc71;">ברוכים הבאים ל-SchoolPoints!</h2>
            <p>שלום {contact},</p>
            <p>תודה שנרשמת למערכת SchoolPoints. ההרשמה עברה בהצלחה והחשבון שלך מוכן.</p>
            
            <div style="background:#f9f9f9; padding:15px; border-radius:10px; border:1px solid #ddd; margin:20px 0;">
                <h3 style="margin-top:0;">פרטי המוסד שלך:</h3>
                <div><b>שם המוסד:</b> {inst_name}</div>
                <div><b>מזהה מוסד (Tenant ID):</b> <span style="font-family:monospace; background:#eee; padding:2px 5px;">{tenant_id}</span></div>
                <div><b>סיסמת ניהול:</b> (כפי שבחרת בהרשמה)</div>
            </div>
            
            <p>
                <b>להורדת התוכנה והתקנה ראשונית:</b><br/>
                <a href="{download_url}">לחץ כאן להורדה</a>
            </p>
            
            <p>
                במסך ההגדרות בתוכנה, הזן את מזהה המוסד שלך ({tenant_id}) כדי להתחבר לענן.
                המערכת תזהה את הרישיון שלך באופן אוטומטי ותפעיל את התוכנה.
            </p>
            
            <hr style="border:0; border-top:1px solid #eee; margin:20px 0;">
            <div style="font-size:12px; color:#888;">
                הודעה זו נשלחה אוטומטית ממערכת SchoolPoints Cloud.
            </div>
        </div>
        """
        
        email_sent = send_email(email, "ברוכים הבאים ל-SchoolPoints - פרטי התחברות", body)

        if REGISTRATION_NOTIFY_EMAIL:
            try:
                admin_body = f"""
                <div dir="rtl" style="font-family:Arial, sans-serif; line-height:1.6;">
                  <h3>נוצר מוסד חדש</h3>
                  <div><b>מוסד:</b> {html.escape(str(inst_name or ''))}</div>
                  <div><b>Tenant ID:</b> {html.escape(str(tenant_id or ''))}</div>
                  <div><b>איש קשר:</b> {html.escape(str(contact or ''))}</div>
                  <div><b>אימייל:</b> {html.escape(str(email or ''))}</div>
                  <div><b>מסלול:</b> {html.escape(str(r.get('plan') or ''))}</div>
                </div>
                """
                send_email(REGISTRATION_NOTIFY_EMAIL, 'SchoolPoints: מוסד חדש נוצר', admin_body)
            except Exception:
                pass
        
        return {
            'ok': True,
            'tenant_id': tenant_id,
            'email_sent': email_sent
        }
    except Exception as e:
        logger.error(f"Approve error: {e}")
        return {'ok': False, 'detail': str(e)}
    finally:
        try: conn.close()
        except: pass
