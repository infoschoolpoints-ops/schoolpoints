import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

from .config import (
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, 
    SMTP_FROM, CONTACT_EMAIL_TO
)
from .utils import safe_int

logger = logging.getLogger("schoolpoints.email")

def send_email(to_email: str, subject: str, body_html: str) -> bool:
    """Send a generic email using configured SMTP server."""
    if not SMTP_HOST or not SMTP_USER or not SMTP_PASSWORD:
        logger.warning(f"[EMAIL] SKIP: No SMTP config. To={to_email}, Subject={subject}")
        return False
        
    try:
        msg = MIMEMultipart()
        msg['From'] = SMTP_FROM or SMTP_USER
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body_html, 'html'))
        
        server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        logger.error(f"[EMAIL] Failed to send email: {e}")
        return False

def send_contact_email(name: str, email: str, subject: str, message: str) -> bool:
    if not CONTACT_EMAIL_TO:
        logger.warning("[EMAIL] No contact email configured")
        return False
        
    body = f"""
    <div dir="ltr">
        <b>Name:</b> {name}<br>
        <b>Email:</b> {email}<br>
        <b>Subject:</b> {subject}<br>
        <hr>
        <b>Message:</b><br>
        <pre>{message}</pre>
    </div>
    """
    return send_email(CONTACT_EMAIL_TO, f"Contact Form: {subject} (from {name})", body)
