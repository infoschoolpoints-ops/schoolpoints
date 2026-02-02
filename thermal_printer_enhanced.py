"""Enhanced thermal printer with Hebrew dates, decorations, and better formatting."""
import win32print
import time
from datetime import datetime
from PIL import Image
import json
import os


class HebrewDate:
    """Convert Gregorian date to Hebrew date."""
    
    HEBREW_MONTHS = [
        "ניסן", "אייר", "סיוון", "תמוז", "אב", "אלול",
        "תשרי", "חשוון", "כסלו", "טבת", "שבט", "אדר"
    ]
    
    HEBREW_DAYS = [
        "", "א'", "ב'", "ג'", "ד'", "ה'", "ו'", "ז'", "ח'", "ט'",
        "י'", "י\"א", "י\"ב", "י\"ג", "י\"ד", "ט\"ו", "ט\"ז",
        "י\"ז", "י\"ח", "י\"ט", "כ'", "כ\"א", "כ\"ב", "כ\"ג",
        "כ\"ד", "כ\"ה", "כ\"ו", "כ\"ז", "כ\"ח", "כ\"ט", "ל'"
    ]
    
    @staticmethod
    def get_hebrew_date(date=None):
        """
        Get Hebrew date string.
        Note: This is a simplified version. For accurate Hebrew calendar,
        consider using the 'pyluach' library.
        """
        if date is None:
            date = datetime.now()
        
        # Simplified approximation - for production use pyluach
        # This is just for display purposes
        day = date.day
        month = date.month
        year = date.year
        
        # Approximate Hebrew year (5784 for 2024)
        hebrew_year = year + 3760
        
        # Get Hebrew month (approximate)
        hebrew_month_idx = (month + 6) % 12
        hebrew_month = HebrewDate.HEBREW_MONTHS[hebrew_month_idx]
        
        # Get Hebrew day
        hebrew_day = HebrewDate.HEBREW_DAYS[min(day, 30)]
        
        return f"{hebrew_day} {hebrew_month} {hebrew_year}"


class ThermalPrinter:
    """Enhanced thermal printer for receipts and vouchers."""
    
    # Decoration characters
    DECORATIONS = {
        'box_top': '┌' + '─' * 30 + '┐',
        'box_bottom': '└' + '─' * 30 + '┘',
        'box_middle': '├' + '─' * 30 + '┤',
        'double_line': '═' * 32,
        'single_line': '─' * 32,
        'thick_line': '━' * 32,
        'dotted_line': '·' * 32,
        'star_line': '★' * 16,
    }
    
    def __init__(self, printer_name="Cash Printer", logo_path=None):
        self.printer_name = printer_name
        self.logo_path = logo_path
        self.logo_data = None
        
        # Load logo if provided
        if logo_path and os.path.exists(logo_path):
            self._load_logo()
    
    def _load_logo(self):
        """Load and prepare logo for printing."""
        try:
            img = Image.open(self.logo_path).convert('L')
            w, h = img.size
            scale = min(384 / w, 120 / h)
            new_w = max(1, int(w * scale))
            new_h = max(1, int(h * scale))
            img_resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            img_bw = img_resized.point(lambda p: 0 if p < 128 else 255, mode='1')
            
            width_bytes = (new_w + 7) // 8
            
            logo_data = bytearray()
            logo_data.extend(b'\x1D\x76\x30\x00')
            logo_data.extend(bytes([width_bytes & 0xFF, (width_bytes >> 8) & 0xFF]))
            logo_data.extend(bytes([new_h & 0xFF, (new_h >> 8) & 0xFF]))
            
            for y in range(new_h):
                for x in range(0, new_w, 8):
                    byte_val = 0
                    for bit in range(8):
                        if x + bit < new_w:
                            pixel = img_bw.getpixel((x + bit, y))
                            if pixel == 0:
                                byte_val |= (1 << (7 - bit))
                    logo_data.append(byte_val)
            
            self.logo_data = bytes(logo_data)
            
        except Exception as e:
            print(f"Error loading logo: {e}")
            self.logo_data = None
    
    @staticmethod
    def reverse_hebrew(text):
        """Reverse Hebrew text for correct printing."""
        return text[::-1]
    
    def _print_raw(self, data, job_name="Print"):
        """Send raw data to printer."""
        h = None
        try:
            t0 = time.perf_counter()
            h = win32print.OpenPrinter(self.printer_name)
            job_id = win32print.StartDocPrinter(h, 1, (job_name, None, 'RAW'))
            win32print.StartPagePrinter(h)
            written = win32print.WritePrinter(h, bytes(data))
            win32print.EndPagePrinter(h)
            win32print.EndDocPrinter(h)
            t1 = time.perf_counter()
            
            print(f"✓ Printed {written} bytes in {t1-t0:.3f}s")
            return True
            
        except Exception as e:
            print(f"✗ Print error: {e}")
            return False
        finally:
            if h:
                try:
                    win32print.ClosePrinter(h)
                except:
                    pass
    
    def print_receipt(self, student_name, student_class, purchases, 
                     points_before, points_after, closing_message=""):
        """Print a complete receipt with decorations."""
        data = bytearray()
        
        # Initialize
        data.extend(b'\x1B\x40')
        data.extend(b'\x1B\x74\x08')
        
        # Logo
        if self.logo_data:
            data.extend(b'\x1B\x61\x01')
            data.extend(self.logo_data)
            data.extend(b'\n')
        
        # Decorative top
        data.extend(b'\x1B\x61\x01')
        data.extend(self.DECORATIONS['double_line'].encode('cp862', errors='ignore'))
        data.extend(b'\n')
        
        # Title with "font" effect (using double width/height)
        data.extend(b'\x1D\x21\x33')  # Extra large (width x4, height x4)
        data.extend(b'\x1B\x45\x01')
        title = self.reverse_hebrew("קבלה")
        data.extend(title.encode('cp862'))
        data.extend(b'\n')
        
        data.extend(b'\x1D\x21\x00')
        data.extend(b'\x1B\x45\x00')
        
        # Decorative separator
        data.extend(self.DECORATIONS['double_line'].encode('cp862', errors='ignore'))
        data.extend(b'\n\n')
        
        # Student info
        data.extend(b'\x1B\x61\x02')
        data.extend(b'\x1D\x21\x11')
        
        student_line = self.reverse_hebrew(f"תלמיד: {student_name}")
        data.extend(student_line.encode('cp862'))
        data.extend(b'\n')
        
        class_line = self.reverse_hebrew(f"כיתה: {student_class}")
        data.extend(class_line.encode('cp862'))
        data.extend(b'\n')
        
        data.extend(b'\x1D\x21\x00')
        data.extend(b'\n')
        
        # Date and time with Hebrew date
        now = datetime.now()
        gregorian_date = now.strftime("%d/%m/%Y")
        hebrew_date = HebrewDate.get_hebrew_date(now)
        time_str = now.strftime("%H:%M:%S")
        
        date_line = f"{gregorian_date} :" + self.reverse_hebrew("תאריך")
        data.extend(date_line.encode('cp862'))
        data.extend(b'\n')
        
        hebrew_date_line = self.reverse_hebrew(hebrew_date)
        data.extend(hebrew_date_line.encode('cp862'))
        data.extend(b'\n')
        
        time_line = f"{time_str} :" + self.reverse_hebrew("שעה")
        data.extend(time_line.encode('cp862'))
        data.extend(b'\n\n')
        
        # Purchases section
        data.extend(b'\x1B\x61\x01')
        data.extend(self.DECORATIONS['thick_line'].encode('cp862', errors='ignore'))
        data.extend(b'\n')
        
        data.extend(b'\x1B\x45\x01')
        header = self.reverse_hebrew("פירוט קניות")
        data.extend(header.encode('cp862'))
        data.extend(b'\n')
        data.extend(b'\x1B\x45\x00')
        
        data.extend(self.DECORATIONS['single_line'].encode('cp862', errors='ignore'))
        data.extend(b'\n')
        
        # Purchase items - right align items, left align prices
        total_points = 0
        for purchase in purchases:
            name = purchase['name']
            qty = purchase['quantity']
            points_each = purchase['points_each']
            item_total = purchase['total_points']
            total_points += item_total
            
            # Right aligned item name
            data.extend(b'\x1B\x61\x02')
            if qty > 1:
                item_name = f"{self.reverse_hebrew(name)} x{qty}"
            else:
                item_name = self.reverse_hebrew(name)
            data.extend(item_name.encode('cp862'))
            data.extend(b'\n')
            
            # Left aligned price with "נקודות"
            data.extend(b'\x1B\x61\x00')
            price_line = f"  {item_total} " + self.reverse_hebrew("נקודות")
            data.extend(price_line.encode('cp862'))
            data.extend(b'\n')
        
        # Total separator
        data.extend(b'\x1B\x61\x01')
        data.extend(self.DECORATIONS['thick_line'].encode('cp862', errors='ignore'))
        data.extend(b'\n')
        
        # Total points
        data.extend(b'\x1D\x21\x22')
        data.extend(b'\x1B\x45\x01')
        
        total_line = f"{total_points} :" + self.reverse_hebrew("סך הכל")
        data.extend(total_line.encode('cp862'))
        data.extend(b'\n')
        
        data.extend(b'\x1D\x21\x00')
        data.extend(b'\x1B\x45\x00')
        data.extend(b'\n')
        
        # Points before/after with decoration
        data.extend(self.DECORATIONS['dotted_line'].encode('cp862', errors='ignore'))
        data.extend(b'\n')
        
        data.extend(b'\x1B\x61\x02')
        
        before_line = f"{points_before} :" + self.reverse_hebrew("נקודות לפני")
        data.extend(before_line.encode('cp862'))
        data.extend(b'\n')
        
        after_line = f"{points_after} :" + self.reverse_hebrew("נקודות אחרי")
        data.extend(after_line.encode('cp862'))
        data.extend(b'\n')
        
        data.extend(self.DECORATIONS['dotted_line'].encode('cp862', errors='ignore'))
        data.extend(b'\n')
        
        # Closing message
        if closing_message:
            data.extend(b'\n')
            data.extend(b'\x1B\x61\x01')
            data.extend(b'\x1B\x45\x01')
            
            for line in closing_message.split('\n'):
                if line.strip():
                    msg_line = self.reverse_hebrew(line.strip())
                    data.extend(msg_line.encode('cp862'))
                    data.extend(b'\n')
            
            data.extend(b'\x1B\x45\x00')
        
        # Decorative bottom
        data.extend(b'\n')
        data.extend(b'\x1B\x61\x01')
        data.extend(self.DECORATIONS['double_line'].encode('cp862', errors='ignore'))
        data.extend(b'\n')
        
        data.extend(b'\n\n\n\n\n')
        data.extend(b'\x1D\x56\x31')
        
        return self._print_raw(data, "Receipt")
    
    def print_voucher(self, student_name, student_class, product_name, 
                     variation="", points_cost=0, challenge_time=""):
        """Print a voucher for product/challenge with decorations."""
        data = bytearray()
        
        # Initialize
        data.extend(b'\x1B\x40')
        data.extend(b'\x1B\x74\x08')
        
        # Logo
        if self.logo_data:
            data.extend(b'\x1B\x61\x01')
            data.extend(self.logo_data)
            data.extend(b'\n')
        
        # Decorative top
        data.extend(b'\x1B\x61\x01')
        data.extend(self.DECORATIONS['star_line'].encode('cp862', errors='ignore'))
        data.extend(b'\n')
        
        # Title with large font
        data.extend(b'\x1D\x21\x33')
        data.extend(b'\x1B\x45\x01')
        title = self.reverse_hebrew("שובר")
        data.extend(title.encode('cp862'))
        data.extend(b'\n')
        
        data.extend(b'\x1D\x21\x00')
        data.extend(b'\x1B\x45\x00')
        
        data.extend(self.DECORATIONS['star_line'].encode('cp862', errors='ignore'))
        data.extend(b'\n\n')
        
        # Student info
        data.extend(b'\x1B\x61\x02')
        data.extend(b'\x1D\x21\x11')
        
        student_line = self.reverse_hebrew(f"תלמיד: {student_name}")
        data.extend(student_line.encode('cp862'))
        data.extend(b'\n')
        
        class_line = self.reverse_hebrew(f"כיתה: {student_class}")
        data.extend(class_line.encode('cp862'))
        data.extend(b'\n')
        
        data.extend(b'\x1D\x21\x00')
        data.extend(b'\n')
        
        # Separator
        data.extend(b'\x1B\x61\x01')
        data.extend(self.DECORATIONS['thick_line'].encode('cp862', errors='ignore'))
        data.extend(b'\n\n')
        
        # Product/Challenge name
        data.extend(b'\x1D\x21\x22')
        data.extend(b'\x1B\x45\x01')
        
        product_line = self.reverse_hebrew(product_name)
        data.extend(product_line.encode('cp862'))
        data.extend(b'\n')
        
        # Variation
        if variation:
            data.extend(b'\x1D\x21\x11')
            var_line = self.reverse_hebrew(f"({variation})")
            data.extend(var_line.encode('cp862'))
            data.extend(b'\n')
        
        data.extend(b'\x1D\x21\x00')
        data.extend(b'\x1B\x45\x00')
        data.extend(b'\n')
        
        # Separator
        data.extend(self.DECORATIONS['single_line'].encode('cp862', errors='ignore'))
        data.extend(b'\n\n')
        
        # Points cost
        data.extend(b'\x1D\x21\x11')
        data.extend(b'\x1B\x45\x01')
        
        points_line = f"{points_cost} :" + self.reverse_hebrew("נקודות")
        data.extend(points_line.encode('cp862'))
        data.extend(b'\n')
        
        data.extend(b'\x1D\x21\x00')
        data.extend(b'\x1B\x45\x00')
        data.extend(b'\n')
        
        # Date and time with Hebrew date
        data.extend(b'\x1B\x61\x02')
        
        now = datetime.now()
        gregorian_date = now.strftime("%d/%m/%Y")
        hebrew_date = HebrewDate.get_hebrew_date(now)
        time_str = now.strftime("%H:%M:%S")
        
        date_line = f"{gregorian_date} :" + self.reverse_hebrew("תאריך ביצוע")
        data.extend(date_line.encode('cp862'))
        data.extend(b'\n')
        
        hebrew_date_line = self.reverse_hebrew(hebrew_date)
        data.extend(hebrew_date_line.encode('cp862'))
        data.extend(b'\n')
        
        time_line = f"{time_str} :" + self.reverse_hebrew("שעה")
        data.extend(time_line.encode('cp862'))
        data.extend(b'\n')
        
        # Challenge time if provided
        if challenge_time:
            data.extend(b'\n')
            time_line = self.reverse_hebrew(f"זמן אתגר: {challenge_time}")
            data.extend(time_line.encode('cp862'))
            data.extend(b'\n')
        
        # Decorative bottom
        data.extend(b'\n')
        data.extend(b'\x1B\x61\x01')
        data.extend(self.DECORATIONS['star_line'].encode('cp862', errors='ignore'))
        data.extend(b'\n')
        
        data.extend(b'\n\n\n\n\n')
        data.extend(b'\x1D\x56\x31')
        
        return self._print_raw(data, "Voucher")


def test_printer():
    """Test the enhanced printer."""
    printer = ThermalPrinter(logo_path="Z:\\לוגו שחור לבן לא שקוף.png")
    
    print("=== Test 1: Enhanced Receipt ===")
    purchases = [
        {"name": "שוקולד מריר", "quantity": 2, "points_each": 5, "total_points": 10},
        {"name": "מחברת 80 דף", "quantity": 1, "points_each": 15, "total_points": 15},
        {"name": "עט כחול", "quantity": 3, "points_each": 3, "total_points": 9},
        {"name": "מחק לבן", "quantity": 1, "points_each": 2, "total_points": 2},
    ]
    
    printer.print_receipt(
        student_name="דוד כהן",
        student_class="ה'1",
        purchases=purchases,
        points_before=100,
        points_after=64,
        closing_message="תודה רבה על הקנייה!\nנתראה בקרוב\nהצלחה!"
    )
    
    input("\nPress Enter for voucher test...")
    
    print("\n=== Test 2: Enhanced Voucher ===")
    printer.print_voucher(
        student_name="דוד כהן",
        student_class="ה'1",
        product_name="אתגר מתמטיקה",
        variation="רמה קשה - משוואות",
        points_cost=50,
        challenge_time="30 דקות"
    )
    
    print("\n=== Enhanced Tests Complete ===")


if __name__ == '__main__':
    test_printer()
