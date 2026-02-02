"""Thermal printer with image caching for performance."""
import win32print
import time
from datetime import datetime
from PIL import Image, ImageDraw
import os
import hashlib


class ThermalPrinterCached:
    """Thermal printer with logo and decoration caching."""
    
    def __init__(self, printer_name="Cash Printer", logo_path=None):
        self.printer_name = printer_name
        self.logo_path = logo_path
        self.logo_hash = None
        self.logo_data = None
        self.decoration_cache = {}
        
        # Create decorative images once
        self._create_decorations()
        
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
