import os
import secrets
import datetime
import re
from typing import Optional, List
from fastapi import Request

from .config import ROOT_DIR

def read_text_file(path: str) -> str:
    if not path or not os.path.isfile(path):
        return ""
    for enc in ("utf-8", "utf-8-sig", "cp1255", "windows-1255", "latin-1"):
        try:
            with open(path, 'r', encoding=enc) as f:
                return f.read()
        except Exception:
            continue
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()
    except Exception:
        return ""

def random_pair_code() -> str:
    # short human-friendly code (no ambiguous chars)
    alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    try:
        return ''.join(secrets.choice(alphabet) for _ in range(8))
    except Exception:
        return secrets.token_hex(4).upper()

def public_base_url(request: Request) -> str:
    try:
        proto = str(request.headers.get('x-forwarded-proto') or '').strip() or str(getattr(request.url, 'scheme', '') or '').strip() or 'https'
    except Exception:
        proto = 'https'
    try:
        host = str(request.headers.get('x-forwarded-host') or '').strip() or str(request.headers.get('host') or '').strip()
    except Exception:
        host = ''
    if not host:
        try:
            host = str(request.url.netloc or '').strip()
        except Exception:
            host = ''
    host = host.strip()
    if not host:
        return str(request.base_url).rstrip('/')
    return f"{proto}://{host}".rstrip('/')

def weekday_he(dt: datetime.date) -> str:
    m = {0: 'ב', 1: 'ג', 2: 'ד', 3: 'ה', 4: 'ו', 5: 'ש', 6: 'א'}
    return m.get(dt.weekday(), '')

def parse_days_of_week(s: Optional[str]) -> set:
    try:
        raw = str(s or '').strip()
    except Exception:
        raw = ''
    if not raw:
        return set()
    raw = raw.replace(';', ',').replace('\u05f3', ',').replace('\u05f4', ',')
    parts = [p.strip() for p in raw.split(',')]
    out = set()
    for p in parts:
        if not p:
            continue
        p1 = p[0]
        if p1 in ('א', 'ב', 'ג', 'ד', 'ה', 'ו', 'ש'):
            out.add(p1)
    return out

def time_to_minutes(t: Optional[str]) -> Optional[int]:
    try:
        s = str(t or '').strip()
        if not s:
            return None
        s = s.replace('.', ':')
        parts = s.split(':')
        if len(parts) != 2:
            return None
        hh = int(parts[0])
        mm = int(parts[1])
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            return None
        return hh * 60 + mm
    except Exception:
        return None

def guide_image_sort_key(name: str) -> tuple:
    stem = os.path.splitext(name)[0]
    if stem.isdigit():
        return (0, int(stem))
    return (1, stem.lower())

def replace_guide_base64_images(html_text: str) -> str:
    images_dir = os.path.join(ROOT_DIR, 'תמונות', 'להוראות')
    if not os.path.isdir(images_dir):
        return html_text

    icon_names = ['admin.png', 'public.png', 'cashier.png', 'installer.png']
    replacements: List[str] = []
    for icon in icon_names:
        icon_path = os.path.join(images_dir, icon)
        if os.path.isfile(icon_path):
            replacements.append(f'/web/assets/guide_images/{icon}')
        else:
            fallback = os.path.join(ROOT_DIR, 'icons', icon)
            if os.path.isfile(fallback):
                replacements.append(f'/web/assets/icons/{icon}')

    other_files: List[str] = []
    for name in os.listdir(images_dir):
        if name in icon_names:
            continue
        ext = os.path.splitext(name)[1].lower()
        if ext in ('.png', '.jpg', '.jpeg', '.gif', '.webp'):
            other_files.append(name)
    other_files.sort(key=guide_image_sort_key)
    replacements.extend(f'/web/assets/guide_images/{name}' for name in other_files)
    if not replacements:
        return html_text

    pattern = re.compile(r'(<img[^>]+src=["\"])(data:image[^"\"]+)(["\"][^>]*>)', re.IGNORECASE)
    index = 0

    def repl(match: re.Match) -> str:
        nonlocal index
        if index >= len(replacements):
            return match.group(0)
        new_src = replacements[index]
        index += 1
        return f"{match.group(1)}{new_src}{match.group(3)}"

    return pattern.sub(repl, html_text)
