#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Voucher image generator for thermal printer
Creates simple vouchers (not full receipts) with item details
"""

import os
import re
from PIL import Image, ImageDraw, ImageFont


def reverse_hebrew_for_image(text):
    """Reverse Hebrew text for image rendering"""
    words = text.split()
    reversed_words = []
    for word in reversed(words):
        if re.search(r'[\u0590-\u05FF]', word):
            reversed_words.append(word[::-1])
        else:
            reversed_words.append(word)
    return ' '.join(reversed_words)


def create_voucher_image(voucher_data: dict, logo_path: str = None) -> Image.Image:
    """
    Create simple voucher image (not full receipt)
    
    Args:
        voucher_data: Dictionary with voucher information:
            - student_name: str
            - class_name: str
            - item_name: str (single item)
            - qty: int
            - price: float
            - slot_text: str (for scheduled services)
            - duration_minutes: int (for scheduled services)
        logo_path: Path to logo image file (optional)
    
    Returns:
        PIL Image object
    """
    
    # Voucher dimensions (smaller than receipt)
    width = 576
    height = 1000
    
    # Create white background
    img = Image.new('RGB', (width, height), 'white')
    draw = ImageDraw.Draw(img)
    
    # Load fonts
    font_paths = [
        ('C:/Windows/Fonts/arialbd.ttf', 'C:/Windows/Fonts/arial.ttf'),
        ('C:/Windows/Fonts/tahomabd.ttf', 'C:/Windows/Fonts/tahoma.ttf'),
    ]
    
    font_extra_large_bold = None
    font_large_bold = None
    font_medium_bold = None
    font_medium = None
    font_small = None
    
    for bold_path, regular_path in font_paths:
        try:
            if os.path.exists(bold_path):
                font_extra_large_bold = ImageFont.truetype(bold_path, 60)
                font_large_bold = ImageFont.truetype(bold_path, 48)
                font_medium_bold = ImageFont.truetype(bold_path, 32)
            if os.path.exists(regular_path):
                font_medium = ImageFont.truetype(regular_path, 28)
                font_small = ImageFont.truetype(regular_path, 24)
                break
        except:
            pass
    
    if not font_extra_large_bold:
        font_extra_large_bold = font_large_bold = font_medium_bold = font_medium = font_small = ImageFont.load_default()
    
    y = 30
    
    # Add small logo if provided
    if logo_path and os.path.exists(logo_path):
        try:
            with Image.open(logo_path) as logo:
                logo.load()
                max_width = 300
                if logo.size[0] > max_width:
                    ratio = max_width / logo.size[0]
                    new_size = (max_width, int(logo.size[1] * ratio))
                    logo = logo.resize(new_size, Image.Resampling.LANCZOS)
                logo = logo.convert('1')
                
                logo_x = (width - logo.size[0]) // 2
                img.paste(logo, (logo_x, y))
                y += logo.size[1] + 20
        except:
            pass
    
    # Header - "שובר"
    text = reverse_hebrew_for_image("שובר")
    bbox = draw.textbbox((0, 0), text, font=font_large_bold)
    text_width = bbox[2] - bbox[0]
    x = (width - text_width) // 2
    draw.text((x, y), text, fill='black', font=font_large_bold)
    y += 60
    
    # Line separator
    draw.line([(40, y), (width-40, y)], fill='black', width=2)
    y += 25
    
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
        print(f"[VOUCHER] jewish_calendar error: {e}")
        hebrew_date = ''
    
    texts = []
    if voucher_data.get('student_name'):
        texts.append(reverse_hebrew_for_image(f"תלמיד: {voucher_data['student_name']}"))
    if voucher_data.get('class_name'):
        texts.append(reverse_hebrew_for_image(f"כיתה: {voucher_data['class_name']}"))
    # Date line (Hebrew only)
    if hebrew_date:
        texts.append(reverse_hebrew_for_image(f"תאריך: {hebrew_date}"))
    texts.append(reverse_hebrew_for_image(f"שעה: {time_str}"))
    
    for text in texts:
        bbox = draw.textbbox((0, 0), text, font=font_small)
        text_width = bbox[2] - bbox[0]
        x = width - text_width - 50
        draw.text((x, y), text, fill='black', font=font_small)
        y += 32
    
    y += 20
    
    # Line separator
    draw.line([(40, y), (width-40, y)], fill='black', width=2)
    y += 30
    
    # Item name (centered, bold)
    item_name = voucher_data.get('item_name', '')
    if item_name:
        text = reverse_hebrew_for_image(item_name)
        # Use extra large font for item name
        bbox = draw.textbbox((0, 0), text, font=font_extra_large_bold)
        text_width = bbox[2] - bbox[0]
        x = (width - text_width) // 2
        draw.text((x, y), text, fill='black', font=font_extra_large_bold)
        y += 70  # More space for larger font
    
    # Quantity (if > 1)
    qty = voucher_data.get('qty', 1)
    if qty > 1:
        text = reverse_hebrew_for_image(f"כמות: {qty}")
        bbox = draw.textbbox((0, 0), text, font=font_medium)
        text_width = bbox[2] - bbox[0]
        x = (width - text_width) // 2
        draw.text((x, y), text, fill='black', font=font_medium)
        y += 40
    
    # Price
    price = voucher_data.get('price', 0)
    if price > 0:
        text = reverse_hebrew_for_image(f"{int(price)} נקודות")
        bbox = draw.textbbox((0, 0), text, font=font_medium)
        text_width = bbox[2] - bbox[0]
        x = (width - text_width) // 2
        draw.text((x, y), text, fill='black', font=font_medium)
        y += 40
    
    # Slot info (for scheduled services) - convert to Hebrew date if possible
    slot_text = voucher_data.get('slot_text', '')
    if slot_text:
        y += 10
        draw.line([(40, y), (width-40, y)], fill='black', width=1)
        y += 20
        
        # Try to convert slot date to Hebrew (Hebrew-only)
        slot_display = slot_text
        try:
            # Check if slot_text contains a date in format YYYY-MM-DD or DD/MM/YYYY
            import re
            date_match = re.search(r'(\d{4})-(\d{2})-(\d{2})', slot_text)
            if not date_match:
                date_match = re.search(r'(\d{2})/(\d{2})/(\d{4})', slot_text)
                if date_match:
                    # Convert DD/MM/YYYY to YYYY-MM-DD
                    d, m, y = date_match.groups()
                    greg_date = f"{y}-{m}-{d}"
                else:
                    greg_date = None
            else:
                greg_date = date_match.group(0)
            
            if greg_date:
                from jewish_calendar import hebrew_date_from_gregorian_str
                heb_date = hebrew_date_from_gregorian_str(greg_date)
                if heb_date:
                    # Replace Gregorian date with Hebrew date in slot_text
                    slot_display = slot_text.replace(date_match.group(0), heb_date)
                else:
                    # Remove Gregorian date if we can't convert
                    try:
                        slot_display = slot_text.replace(date_match.group(0), '').strip()
                        slot_display = re.sub(r'\s{2,}', ' ', slot_display).strip()
                    except Exception:
                        slot_display = slot_text
        except:
            pass
        
        text = reverse_hebrew_for_image(f"מועד: {slot_display}")
        bbox = draw.textbbox((0, 0), text, font=font_medium)
        text_width = bbox[2] - bbox[0]
        x = (width - text_width) // 2
        draw.text((x, y), text, fill='black', font=font_medium)
        y += 40
    
    duration = voucher_data.get('duration_minutes', 0)
    if duration > 0:
        text = reverse_hebrew_for_image(f"משך: {duration} דקות")
        bbox = draw.textbbox((0, 0), text, font=font_medium)
        text_width = bbox[2] - bbox[0]
        x = (width - text_width) // 2
        draw.text((x, y), text, fill='black', font=font_medium)
        y += 40
    
    y += 20
    
    # Bottom line
    draw.line([(40, y), (width-40, y)], fill='black', width=2)
    y += 30
    
    # Trim image to actual height
    img = img.crop((0, 0, width, y + 20))
    
    # Convert to black and white
    img = img.convert('1')
    
    return img
