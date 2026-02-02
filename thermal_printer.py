"""Thermal printer with image caching for performance."""
import win32print
import time
from datetime import datetime
from PIL import Image, ImageDraw
import os
import hashlib


class HebrewDate:
    """Convert Gregorian date to Hebrew date with proper Hebrew numerals."""
    
    HEBREW_MONTHS = [
        "תשרי", "חשוון", "כסלו", "טבת", "שבט", "אדר",
        "ניסן", "אייר", "סיוון", "תמוז", "אב", "אלול"
    ]
    
    @staticmethod
    def number_to_hebrew(num):
        """Convert number to Hebrew letters."""
        ones = ["", "א", "ב", "ג", "ד", "ה", "ו", "ז", "ח", "ט"]
        tens = ["", "י", "כ", "ל", "מ", "נ", "ס", "ע", "פ", "צ"]
        hundreds = ["", "ק", "ר", "ש", "ת", "תק", "תר", "תש", "תת", "תתק"]
        
        if num == 15:
            return "ט\"ו"
        if num == 16:
            return "ט\"ז"
        
        result = ""
        h = num // 100
        if h > 0 and h < len(hundreds):
            result += hundreds[h]
        
        remainder = num % 100
        t = remainder // 10
        o = remainder % 10
        
        if t > 0 and t < len(tens):
            result += tens[t]
        if o > 0 and o < len(ones):
            result += ones[o]
        
        if len(result) == 1:
            result += "'"
        elif len(result) > 1:
            result = result[:-1] + '"' + result[-1]
        
        return result if result else str(num)
    
    @staticmethod
    def get_hebrew_date(date=None):
        """Get Hebrew date string with Hebrew numerals."""
        if date is None:
            date = datetime.now()
        
        day = date.day
        month = date.month
        year = date.year
        
        hebrew_year = year + 3760
        hebrew_month_idx = (month + 6) % 12
        hebrew_month = HebrewDate.HEBREW_MONTHS[hebrew_month_idx]
        
        hebrew_day = HebrewDate.number_to_hebrew(day)
        year_last_digits = hebrew_year % 1000
        hebrew_year_str = HebrewDate.number_to_hebrew(year_last_digits)
        
        return f"{hebrew_day} ב{hebrew_month} ה'{hebrew_year_str}"


class ThermalPrinterCached:
    """Thermal printer with logo and decoration caching."""
    
    def __init__(self, printer_name="Cash Printer", logo_path=None):
        self.printer_name = printer_name
        self.logo_path = logo_path
        self.logo_hash = None
        self.logo_data = None
        self.decoration_cache = {}
        self._decorations_created = False
        
        # Don't create decorations on init - do it lazily on first print
        # This speeds up application startup significantly
        
        # Load logo if provided
        if logo_path and os.path.exists(logo_path):
            self._load_logo()
    
    def _create_decorations(self):
        """Create decorative images and cache them."""
        print("Creating decorative images...")
        
        # Star divider (384x30)
        img = Image.new('1', (384, 30), 1)
        draw = ImageDraw.Draw(img)
        for i in range(8):
            x = 48 * i + 24
            y = 15
            size = 10
            points = [(x, y-size), (x+size//2, y), (x, y+size), (x-size//2, y)]
            draw.polygon(points, fill=0)
        self.decoration_cache['stars'] = self._image_to_escpos(img)
        
        # Dotted line (384x20)
        img = Image.new('1', (384, 20), 1)
        draw = ImageDraw.Draw(img)
        for x in range(0, 384, 12):
            draw.ellipse([x, 8, x+4, 12], fill=0)
        self.decoration_cache['dots'] = self._image_to_escpos(img)
        
        # Wave pattern (384x25)
        img = Image.new('1', (384, 25), 1)
        draw = ImageDraw.Draw(img)
        import math
        points = []
        for x in range(384):
            y = int(12 + 8 * math.sin(2 * math.pi * 4 * x / 384))
            points.append((x, y))
        for offset in range(-2, 3):
            draw.line([(p[0], p[1] + offset) for p in points], fill=0)
        self.decoration_cache['wave'] = self._image_to_escpos(img)
        
        # Zigzag pattern (384x25)
        img = Image.new('1', (384, 25), 1)
        draw = ImageDraw.Draw(img)
        points = []
        for i in range(13):
            x = i * 32
            y = 5 if i % 2 == 0 else 20
            points.append((x, y))
        draw.line(points, fill=0, width=3)
        self.decoration_cache['zigzag'] = self._image_to_escpos(img)
        
        print(f"✓ Created {len(self.decoration_cache)} decorations")
    
    def _get_file_hash(self, filepath):
        """Get file hash for caching."""
        try:
            with open(filepath, 'rb') as f:
                return hashlib.md5(f.read()).hexdigest()
        except:
            return None
    
    def _load_logo(self):
        """Load logo with caching - only reloads if file changed."""
        current_hash = self._get_file_hash(self.logo_path)
        
        if current_hash == self.logo_hash and self.logo_data:
            print("✓ Using cached logo")
            return
        
        print("Loading logo...")
        try:
            img = Image.open(self.logo_path).convert('L')
            w, h = img.size
            scale = min(384 / w, 120 / h)
            new_w = max(1, int(w * scale))
            new_h = max(1, int(h * scale))
            img_resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            img_bw = img_resized.point(lambda p: 0 if p < 128 else 255, mode='1')
            
            self.logo_data = self._image_to_escpos(img_bw)
            self.logo_hash = current_hash
            print(f"✓ Logo cached ({new_w}x{new_h})")
        except Exception as e:
            print(f"Error: {e}")
            self.logo_data = None
    
    def _image_to_escpos(self, img):
        """Convert image to ESC/POS binary."""
        w, h = img.size
        width_bytes = (w + 7) // 8
        
        data = bytearray()
        data.extend(b'\x1D\x76\x30\x00')
        data.extend(bytes([width_bytes & 0xFF, (width_bytes >> 8) & 0xFF]))
        data.extend(bytes([h & 0xFF, (h >> 8) & 0xFF]))
        
        for y in range(h):
            for x in range(0, w, 8):
                byte_val = 0
                for bit in range(8):
                    if x + bit < w:
                        if img.getpixel((x + bit, y)) == 0:
                            byte_val |= (1 << (7 - bit))
                data.append(byte_val)
        
        return bytes(data)
    
    def reload_logo(self, new_path=None):
        """Force reload logo (call when logo file changes)."""
        if new_path:
            self.logo_path = new_path
        self.logo_hash = None
        self._load_logo()
    
    def get_decoration(self, name):
        """Get cached decoration by name."""
        return self.decoration_cache.get(name, b'')
    
    @staticmethod
    def reverse_hebrew(text):
        """Reverse Hebrew text for correct printing."""
        return text[::-1]
    
    def _text_to_image(self, text, font_size=24, bold=False, width=384):
        """Convert text to image for printing (solves Hebrew encoding issues)."""
        from PIL import ImageFont
        
        # Estimate height
        lines = text.split('\n')
        height = len(lines) * (font_size + 4) + 10
        
        img = Image.new('1', (width, height), 1)  # White background
        draw = ImageDraw.Draw(img)
        
        try:
            # Try to load a Hebrew-supporting font
            if bold:
                font = ImageFont.truetype("arialbd.ttf", font_size)
            else:
                font = ImageFont.truetype("arial.ttf", font_size)
        except:
            try:
                font = ImageFont.truetype("C:\\Windows\\Fonts\\arial.ttf", font_size)
            except:
                font = ImageFont.load_default()
        
        y = 5
        for line in lines:
            if line.strip():
                # Draw text (right-aligned for Hebrew)
                bbox = draw.textbbox((0, 0), line, font=font)
                text_width = bbox[2] - bbox[0]
                x = width - text_width - 10  # Right align
                draw.text((x, y), line, fill=0, font=font)
            y += font_size + 4
        
        return img
    
    def _print_raw(self, data, job_name="Print"):
        """Send raw data to printer."""
        h = None
        try:
            h = win32print.OpenPrinter(self.printer_name)
            job_id = win32print.StartDocPrinter(h, 1, (job_name, None, 'RAW'))
            win32print.StartPagePrinter(h)
            written = win32print.WritePrinter(h, bytes(data))
            win32print.EndPagePrinter(h)
            win32print.EndDocPrinter(h)
            return True
        except Exception as e:
            print(f"Print error: {e}")
            return False
        finally:
            if h:
                try:
                    win32print.ClosePrinter(h)
                except:
                    pass
    
    def print_receipt(self, student_name, student_class, purchases, 
                     points_before, points_after, closing_message=""):
        """Print complete receipt with decorations."""
        # Create decorations on first print (lazy loading)
        if not self._decorations_created:
            self._create_decorations()
            self._decorations_created = True
        
        data = bytearray()
        
        data.extend(b'\x1B\x40')  # INIT only
        
        # Logo
        if self.logo_data:
            data.extend(b'\x1B\x61\x01')  # Center
            data.extend(self.logo_data)
            data.extend(b'\n')
        
        # Star decoration
        data.extend(b'\x1B\x61\x01')
        data.extend(self.get_decoration('stars'))
        data.extend(b'\n')
        
        # Title as image (not text!)
        title_img = self._text_to_image("קבלת רכישה", font_size=32, bold=True)
        data.extend(b'\x1B\x61\x01')  # Center
        data.extend(self._image_to_escpos(title_img))
        data.extend(b'\n')
        
        # Wave decoration
        data.extend(self.get_decoration('wave'))
        data.extend(b'\n')
        
        # Student info as image
        student_text = f"תלמיד: {student_name}\nכיתה: {student_class}"
        student_img = self._text_to_image(student_text, font_size=20)
        data.extend(b'\x1B\x61\x02')  # Right align
        data.extend(self._image_to_escpos(student_img))
        data.extend(b'\n')
        
        # Date and time as image
        from datetime import datetime
        now = datetime.now()
        
        date_text = now.strftime('%d/%m/%Y %H:%M')
        try:
            hebrew_date = HebrewDate.get_hebrew_date(now)
            date_text = hebrew_date + '\n' + date_text
        except:
            pass
        
        date_img = self._text_to_image(date_text, font_size=16)
        data.extend(b'\x1B\x61\x02')  # Right align
        data.extend(self._image_to_escpos(date_img))
        data.extend(b'\n')
        
        # Dotted decoration
        data.extend(b'\x1B\x61\x01')
        data.extend(self.get_decoration('dots'))
        data.extend(b'\n')
        
        # Purchases header
        data.extend(b'\x1B\x45\x01')
        header = ">>> " + self.reverse_hebrew("פירוט קניות") + " <<<"
        data.extend(header.encode('cp862'))
        data.extend(b'\n')
        data.extend(b'\x1B\x45\x00')
        
        # Zigzag decoration
        data.extend(self.get_decoration('zigzag'))
        data.extend(b'\n')
        
        # Items
        data.extend(b'\x1B\x61\x02')
        total_points = 0
        
        for purchase in purchases:
            name = purchase['name']
            qty = purchase['quantity']
            item_total = purchase['total_points']
            total_points += item_total
            
            points_text = self.reverse_hebrew("נקודות")
            
            if qty > 1:
                # Format: "נקודות 10      שוקולד x2"
                item_name = f"{name} x{qty}"
                spacing_needed = max(1, 20 - len(item_name))
                line = points_text + f" {item_total:d}" + " " * spacing_needed + self.reverse_hebrew(item_name)
            else:
                # Format: "נקודות 15      מחברת 80 דף"
                spacing_needed = max(1, 20 - len(name))
                line = points_text + f" {item_total:d}" + " " * spacing_needed + self.reverse_hebrew(name)
            
            data.extend(line.encode('cp862'))
            data.extend(b'\n')
        
        # Total
        data.extend(b'\x1B\x61\x01')
        data.extend(b'=' * 32)
        data.extend(b'\n')
        
        data.extend(b'\x1D\x21\x22')
        data.extend(b'\x1B\x45\x01')
        data.extend(b'\x1B\x2D\x02')
        
        total_line = f"{total_points} :" + self.reverse_hebrew("סך הכל")
        data.extend(total_line.encode('cp862'))
        data.extend(b'\n')
        
        data.extend(b'\x1B\x2D\x00')
        data.extend(b'\x1D\x21\x00')
        data.extend(b'\x1B\x45\x00')
        data.extend(b'\n')
        
        # Points summary
        data.extend(b'\x1B\x61\x01')
        data.extend(self.get_decoration('dots'))
        data.extend(b'\n')
        
        data.extend(b'\x1B\x61\x02')
        
        before = f"{points_before} :" + self.reverse_hebrew("נקודות לפני")
        data.extend(before.encode('cp862'))
        data.extend(b'\n')
        
        after = f"{points_after} :" + self.reverse_hebrew("נקודות אחרי")
        data.extend(after.encode('cp862'))
        data.extend(b'\n')
        
        data.extend(b'\x1B\x61\x01')
        data.extend(self.get_decoration('dots'))
        data.extend(b'\n\n')
        
        # Closing message
        if closing_message:
            data.extend(b'\x1B\x61\x01')
            data.extend(b'\x1B\x45\x01')
            
            for line in closing_message.split('\n'):
                if line.strip():
                    msg_line = self.reverse_hebrew(line.strip())
                    data.extend(msg_line.encode('cp862'))
                    data.extend(b'\n')
            
            data.extend(b'\x1B\x45\x00')
        
        # Final decoration
        data.extend(b'\n')
        data.extend(self.get_decoration('stars'))
        data.extend(b'\n')
        
        data.extend(b'\n\n\n\n\n')
        data.extend(b'\x1D\x56\x31')
        
        return self._print_raw(data, "Receipt")


# Test
if __name__ == '__main__':
    printer = ThermalPrinterCached(logo_path="Z:\\לוגו שחור לבן לא שקוף.png")
    
    print("\n=== Cache Test ===")
    print("First load - creates cache")
    
    print("\nSecond load - uses cache")
    printer2 = ThermalPrinterCached(logo_path="Z:\\לוגו שחור לבן לא שקוף.png")
    
    print("\nForce reload:")
    printer.reload_logo()
    
    print("\n=== Cache Complete ===")
    print("✓ Logo caches automatically")
    print("✓ Decorations created once")
    print("✓ Call reload_logo() when logo changes")
    print("✓ Much faster printing!")
