#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Receipt image generator for thermal printer
Creates beautiful receipts as images with Hebrew text and decorative elements
"""

import os
import re
from PIL import Image, ImageDraw, ImageFont

_FONT_CACHE = None
_SYMBOL_FONT_CACHE = None
_LOGO_CACHE = {}


def _get_fonts():
    global _FONT_CACHE, _SYMBOL_FONT_CACHE
    if _FONT_CACHE is not None:
        return _FONT_CACHE, _SYMBOL_FONT_CACHE

    # Try to load Hebrew font (bold version preferred)
    font_paths = [
        ('C:/Windows/Fonts/arialbd.ttf', 'C:/Windows/Fonts/arial.ttf'),
        ('C:/Windows/Fonts/tahomabd.ttf', 'C:/Windows/Fonts/tahoma.ttf'),
    ]

    # Font for symbols (supports Unicode symbols like stars, bullets, arrows)
    symbol_font_paths = [
        'C:/Windows/Fonts/seguisym.ttf',
        'C:/Windows/Fonts/segoeui.ttf',
        'C:/Windows/Fonts/arial.ttf',
    ]

    font_large_bold = None
    font_large = None
    font_medium_bold = None
    font_medium = None
    font_small = None

    for bold_path, regular_path in font_paths:
        try:
            if os.path.exists(bold_path):
                font_large_bold = ImageFont.truetype(bold_path, 56)
                font_medium_bold = ImageFont.truetype(bold_path, 36)
            if os.path.exists(regular_path):
                font_large = ImageFont.truetype(regular_path, 48)
                font_medium = ImageFont.truetype(regular_path, 32)
                font_small = ImageFont.truetype(regular_path, 26)
                break
        except Exception:
            pass

    if not font_large:
        font_large_bold = font_large = ImageFont.load_default()
        font_medium_bold = font_medium = ImageFont.load_default()
        font_small = ImageFont.load_default()

    font_symbols = None
    for symbol_path in symbol_font_paths:
        try:
            if os.path.exists(symbol_path):
                font_symbols = ImageFont.truetype(symbol_path, 26)
                break
        except Exception:
            pass
    if not font_symbols:
        font_symbols = font_small

    _FONT_CACHE = (font_large_bold, font_large, font_medium_bold, font_medium, font_small)
    _SYMBOL_FONT_CACHE = font_symbols
    return _FONT_CACHE, _SYMBOL_FONT_CACHE


def _get_cached_logo(logo_path: str, *, max_width: int = 460):
    if not logo_path:
        return None
    try:
        p = str(logo_path).strip()
    except Exception:
        return None
    if not p or (not os.path.exists(p)):
        return None
    try:
        mtime = os.path.getmtime(p)
    except Exception:
        mtime = None
    key = (p, mtime, int(max_width))
    if key in _LOGO_CACHE:
        return _LOGO_CACHE.get(key)
    try:
        with Image.open(p) as logo:
            logo.load()
            if logo.size[0] > max_width:
                ratio = max_width / logo.size[0]
                new_size = (max_width, int(logo.size[1] * ratio))
                logo = logo.resize(new_size, Image.Resampling.LANCZOS)
            logo = logo.convert('1')
            out = logo.copy()
    except Exception:
        out = None
    _LOGO_CACHE[key] = out
    return out


def reverse_hebrew_for_image(text):
    """Reverse Hebrew text for image rendering"""
    # Reverse word order AND letters in each word
    words = text.split()
    reversed_words = []
    for word in reversed(words):
        # Check if word contains Hebrew
        if re.search(r'[\u0590-\u05FF]', word):
            reversed_words.append(word[::-1])
        else:
            reversed_words.append(word)
    return ' '.join(reversed_words)


def create_receipt_image(receipt_data: dict, logo_path: str = None, closing_message: str = None) -> Image.Image:
    """
    Create beautiful receipt as image with Hebrew text
    
    Args:
        receipt_data: Dictionary with receipt information:
            - student_name: str
            - class_name: str
            - items: list of dicts with 'name' and 'price'
            - total: float
            - balance_before: float (optional)
            - balance_after: float (optional)
        logo_path: Path to logo image file (optional)
        closing_message: Custom closing message from config (optional)
    
    Returns:
        PIL Image object
    """
    
    # Receipt dimensions (576 pixels = 80mm at 203 DPI)
    width = 576
    height = 1600  # Will be trimmed later
    
    # Create white background
    img = Image.new('RGB', (width, height), 'white')
    draw = ImageDraw.Draw(img)

    (font_large_bold, font_large, font_medium_bold, font_medium, font_small), font_symbols = _get_fonts()
    
    y = 30  # Current Y position
    
    # Add logo if provided (reload each time to avoid cache)
    if logo_path:
        try:
            if os.path.exists(logo_path):
                logo = _get_cached_logo(logo_path, max_width=460)
                if logo is not None:
                    logo_x = (width - logo.size[0]) // 2
                    img.paste(logo, (logo_x, y))
                    y += logo.size[1] + 20
        except Exception as e:
            print(f"Logo load error: {e}")
            pass
    
    # Decorative top border with stars
    star_line = "★ " * 20
    bbox = draw.textbbox((0, 0), star_line, font=font_symbols)
    text_width = bbox[2] - bbox[0]
    x = (width - text_width) // 2
    draw.text((x, y), star_line, fill='black', font=font_symbols)
    y += 40
    
    # Header - "קבלה"
    text = reverse_hebrew_for_image("קבלה")
    bbox = draw.textbbox((0, 0), text, font=font_large_bold)
    text_width = bbox[2] - bbox[0]
    x = (width - text_width) // 2
    draw.text((x, y), text, fill='black', font=font_large_bold)
    y += 70
    
    # Double line
    draw.line([(40, y), (width-40, y)], fill='black', width=3)
    y += 5
    draw.line([(40, y), (width-40, y)], fill='black', width=1)
    y += 25
    
    # Student info section header
    text = reverse_hebrew_for_image("פרטי תלמיד")
    bbox = draw.textbbox((0, 0), text, font=font_medium_bold)
    text_width = bbox[2] - bbox[0]
    x = width - text_width - 50
    draw.text((x, y), text, fill='black', font=font_medium_bold)
    y += 45
    
    # Student info
    from datetime import datetime
    now = datetime.now()
    time_str = now.strftime("%H:%M")
    
    # Hebrew date
    hebrew_date = ""
    greg_date = now.strftime('%Y-%m-%d')
    try:
        from jewish_calendar import hebrew_date_from_gregorian_str
        hebrew_date = str(hebrew_date_from_gregorian_str(greg_date) or '').strip()
    except Exception as e:
        print(f"[RECEIPT] jewish_calendar error: {e}")
        hebrew_date = ''
    
    texts = []
    if receipt_data.get('student_name'):
        texts.append(reverse_hebrew_for_image(f"שם: {receipt_data['student_name']}"))
    if receipt_data.get('class_name'):
        texts.append(reverse_hebrew_for_image(f"כיתה: {receipt_data['class_name']}"))
    # Date line (Hebrew only)
    if hebrew_date:
        texts.append(reverse_hebrew_for_image(f"תאריך: {hebrew_date}"))
    texts.append(reverse_hebrew_for_image(f"שעה: {time_str}"))
    
    for text in texts:
        bbox = draw.textbbox((0, 0), text, font=font_small)
        text_width = bbox[2] - bbox[0]
        x = width - text_width - 70
        draw.text((x, y), text, fill='black', font=font_small)
        y += 35
    
    y += 15
    
    # Decorative separator
    for i in range(3):
        draw.line([(60 + i*10, y), (width-60 - i*10, y)], fill='black', width=1)
        y += 3
    y += 15
    
    # Items header
    text = reverse_hebrew_for_image("פריטים שנרכשו")
    bbox = draw.textbbox((0, 0), text, font=font_medium_bold)
    text_width = bbox[2] - bbox[0]
    x = (width - text_width) // 2
    draw.text((x, y), text, fill='black', font=font_medium_bold)
    y += 45
    
    # Items
    items = receipt_data.get('items', [])
    for item in items:
        item_name = str(item.get('name', ''))
        item_price = float(item.get('price', 0))
        
        # Item name (right-aligned, reversed)
        reversed_name = reverse_hebrew_for_image(item_name)
        bbox = draw.textbbox((0, 0), reversed_name, font=font_small)
        text_width = bbox[2] - bbox[0]
        x = width - text_width - 50
        draw.text((x, y), reversed_name, fill='black', font=font_small)
        
        # Bullet point (to the right of item name)
        draw.text((width - 30, y), "●", fill='black', font=font_symbols)
        
        # Price (left-aligned)
        price_text = reverse_hebrew_for_image(f'{int(item_price)} נקודות')
        draw.text((50, y), price_text, fill='black', font=font_small)
        y += 38
    
    y += 15
    
    # Decorative separator before total
    draw.line([(40, y), (width-40, y)], fill='black', width=3)
    y += 5
    draw.line([(40, y), (width-40, y)], fill='black', width=1)
    y += 30
    
    # Total
    text = reverse_hebrew_for_image('סה"כ לתשלום')
    bbox = draw.textbbox((0, 0), text, font=font_medium_bold)
    text_width = bbox[2] - bbox[0]
    x = (width - text_width) // 2
    draw.text((x, y), text, fill='black', font=font_medium_bold)
    y += 50
    
    total = float(receipt_data.get('total', 0))
    text = reverse_hebrew_for_image(f'{int(total)} נקודות')
    bbox = draw.textbbox((0, 0), text, font=font_large_bold)
    text_width = bbox[2] - bbox[0]
    x = (width - text_width) // 2
    draw.text((x, y), text, fill='black', font=font_large_bold)
    y += 70
    
    # Balance info (if provided)
    if receipt_data.get('balance_before') is not None or receipt_data.get('balance_after') is not None:
        # Decorative separator
        draw.line([(40, y), (width-40, y)], fill='black', width=3)
        y += 5
        draw.line([(40, y), (width-40, y)], fill='black', width=1)
        y += 25
        
        # Balance header
        text = reverse_hebrew_for_image("יתרות")
        bbox = draw.textbbox((0, 0), text, font=font_medium_bold)
        text_width = bbox[2] - bbox[0]
        x = width - text_width - 50
        draw.text((x, y), text, fill='black', font=font_medium_bold)
        y += 40
        
        texts = []
        if receipt_data.get('balance_before') is not None:
            bal_before = float(receipt_data['balance_before'])
            texts.append(reverse_hebrew_for_image(f"יתרה לפני: {int(bal_before)} נקודות"))
        if receipt_data.get('balance_after') is not None:
            bal_after = float(receipt_data['balance_after'])
            texts.append(reverse_hebrew_for_image(f"יתרה אחרי: {int(bal_after)} נקודות"))
        
        for text in texts:
            bbox = draw.textbbox((0, 0), text, font=font_small)
            text_width = bbox[2] - bbox[0]
            x = width - text_width - 50
            draw.text((x, y), text, fill='black', font=font_small)
            # Bullet point (to the right of text)
            draw.text((width - 30, y), "▸", fill='black', font=font_symbols)
            y += 38
        
        y += 25
    
    # Decorative bottom border with stars
    star_line = "★ " * 20
    bbox = draw.textbbox((0, 0), star_line, font=font_symbols)
    text_width = bbox[2] - bbox[0]
    x = (width - text_width) // 2
    draw.text((x, y), star_line, fill='black', font=font_symbols)
    y += 40
    
    # Footer - use closing message from config or default
    if closing_message:
        # Use custom closing message from config
        text = reverse_hebrew_for_image(closing_message)
        bbox = draw.textbbox((0, 0), text, font=font_large_bold)
        text_width = bbox[2] - bbox[0]
        x = (width - text_width) // 2
        draw.text((x, y), text, fill='black', font=font_large_bold)
        y += 55
    else:
        # Default closing message
        text = reverse_hebrew_for_image("תודה רבה!")
        bbox = draw.textbbox((0, 0), text, font=font_large_bold)
        text_width = bbox[2] - bbox[0]
        x = (width - text_width) // 2
        draw.text((x, y), text, fill='black', font=font_large_bold)
        y += 55
        
        text = reverse_hebrew_for_image("נתראה בקרוב ❤")
        bbox = draw.textbbox((0, 0), text, font=font_medium)
        text_width = bbox[2] - bbox[0]
        x = (width - text_width) // 2
        draw.text((x, y), text, fill='black', font=font_medium)
        y += 50
    
    # Trim image to actual height
    img = img.crop((0, 0, width, y + 20))
    
    # Convert to black and white
    img = img.convert('1')
    
    return img
