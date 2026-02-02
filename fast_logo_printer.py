"""Fast logo printer with rich text formatting."""
import time
import win32print
from PIL import Image, ImageFilter, ImageDraw, ImageFont


def parse_hex_file(path):
    """Parse hex file and return raw bytes."""
    data = bytearray()
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            for tok in line.strip().split():
                if len(tok) == 2:
                    try:
                        data.append(int(tok, 16))
                    except ValueError:
                        pass
    return bytes(data)


def encode_logo_optimized(img_path):
    """Encode logo with the discovered correct method."""
    X_BYTES = 44
    Y_SLICES = 10
    WIDTH = 352
    HEIGHT = 80
    
    img = Image.open(img_path).convert('L')
    w, h = img.size
    
    # Scale to fit with good density
    scale = min(WIDTH / w, HEIGHT / h) * 0.75
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))
    img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    
    # Apply slight blur
    img = img.filter(ImageFilter.SMOOTH)
    
    # Center on canvas
    canvas = Image.new('L', (WIDTH, HEIGHT), 255)
    paste_x = (WIDTH - new_w) // 2
    paste_y = (HEIGHT - new_h) // 2
    canvas.paste(img, (paste_x, paste_y))
    
    # High threshold for sparsity
    canvas = canvas.point(lambda p: 0 if p < 170 else 255, mode='1')
    canvas.save('fast_logo_preview.png')
    
    px = canvas.load()
    
    # Encode image data (row-major, MSB-first)
    image_data = bytearray()
    for y in range(HEIGHT):
        for byte_x in range(X_BYTES):
            b = 0
            for bit in range(8):
                x = byte_x * 8 + bit
                if px[x, y] == 0:
                    b |= (0x80 >> bit)
            image_data.append(b)
    
    # Create the full logo data structure with padding
    logo_data = bytearray()
    
    # Add 517 bytes of zeros (like ALL4SHOP)
    logo_data.extend([0x00] * 517)
    
    # Add our image data
    logo_data.extend(image_data)
    
    # Fill remaining space with zeros
    while len(logo_data) < 3520:
        logo_data.append(0x00)
    
    # Trim to exactly 3520 bytes
    logo_data = logo_data[:3520]
    
    return bytes(logo_data)


def hebrew_to_cp862(text):
    """Convert Hebrew text to CP862 encoding."""
    cp862_map = {
        'א': 0x80, 'ב': 0x81, 'ג': 0x82, 'ד': 0x83, 'ה': 0x84,
        'ו': 0x85, 'ז': 0x86, 'ח': 0x87, 'ט': 0x88, 'י': 0x89,
        'ך': 0x8A, 'כ': 0x8B, 'ל': 0x8C, 'ם': 0x8D, 'מ': 0x8E,
        'ן': 0x8F, 'נ': 0x90, 'ס': 0x91, 'ע': 0x92, 'ף': 0x93,
        'פ': 0x94, 'ץ': 0x95, 'צ': 0x96, 'ק': 0x97, 'ר': 0x98,
        'ש': 0x99, 'ת': 0x9A, ' ': 0x20, '\n': 0x0A,
        '0': 0x30, '1': 0x31, '2': 0x32, '3': 0x33, '4': 0x34,
        '5': 0x35, '6': 0x36, '7': 0x37, '8': 0x38, '9': 0x39,
        ':': 0x3A, '.': 0x2E, '-': 0x2D, '/': 0x2F, '₪': 0xA4
    }
    
    bytes_list = []
    for char in text:
        if char in cp862_map:
            bytes_list.append(cp862_map[char])
        elif char.isdigit() or char in '.-/:':
            bytes_list.append(ord(char))
        elif char == '\n':
            bytes_list.append(0x0A)
        # Skip unsupported characters
    
    return bytes_list


def create_receipt_with_logo(logo_path, store_name, items, total, date=""):
    """Create a complete receipt with logo and formatted text."""
    commands = bytearray()
    
    # Initialize printer
    commands.extend(b'\x1b\x40')
    
    # Add logo
    if logo_path:
        logo_data = encode_logo_optimized(logo_path)
        
        # GS * command
        commands.extend(b'\x1d\x2a\x2c\x0a')  # GS * 44 10
        commands.extend(logo_data)
        
        # Print the logo
        commands.extend(b'\x1d\x2f\x01')
        commands.extend(b'\x0a\x0a')
    
    # Store name - large and bold
    commands.extend(b'\x1b\x21\x08')  # Bold
    commands.extend(b'\x1b\x21\x30')  # Large
    commands.extend(hebrew_to_cp862(store_name))
    commands.extend(b'\x0a')
    
    # Reset formatting
    commands.extend(b'\x1b\x21\x00')
    
    # Date
    if date:
        commands.extend(hebrew_to_cp862(f"תאריך: {date}"))
        commands.extend(b'\x0a')
    
    # Separator line
    commands.extend(b'\x0a')
    commands.extend(b'-' * 30)
    commands.extend(b'\x0a\x0a')
    
    # Items
    for item in items:
        name = item.get('name', '')
        quantity = item.get('quantity', 1)
        price = item.get('price', 0)
        
        # Item name and quantity
        item_text = f"{name} x{quantity}"
        commands.extend(hebrew_to_cp862(item_text))
        commands.extend(b'\x0a')
        
        # Price (right-aligned approximation)
        price_text = f"{' ' * (25 - len(item_text))}{price:.2f}₪"
        commands.extend(hebrew_to_cp862(price_text))
        commands.extend(b'\x0a')
    
    # Separator line
    commands.extend(b'\x0a')
    commands.extend(b'-' * 30)
    commands.extend(b'\x0a\x0a')
    
    # Total - bold
    commands.extend(b'\x1b\x21\x08')  # Bold
    total_text = f"סך הכל: {total:.2f}₪"
    commands.extend(hebrew_to_cp862(total_text))
    commands.extend(b'\x0a')
    
    # Reset formatting
    commands.extend(b'\x1b\x21\x00')
    
    # Thank you message
    commands.extend(b'\x0a\x0a')
    commands.extend(hebrew_to_cp862("תודה ולהתראות!"))
    commands.extend(b'\x0a\x0a\x0a')
    
    # Cut paper
    commands.extend(b'\x1d\x56\x31')
    
    return bytes(commands)


def print_fast_receipt():
    """Print a fast test receipt."""
    print("=== Fast Logo Printer Test ===")
    
    # Sample receipt data
    store_name = "חנות רות שלי"
    date = "20/01/2026"
    items = [
        {"name": "מוצר א", "quantity": 2, "price": 15.50},
        {"name": "מוצר ב", "quantity": 1, "price": 32.00},
        {"name": "מוצר ג", "quantity": 3, "price": 8.75},
    ]
    total = sum(item["quantity"] * item["price"] for item in items)
    
    # Create receipt
    receipt_data = create_receipt_with_logo(
        r"Z:\לוגו שחור לבן לא שקוף.png",
        store_name,
        items,
        total,
        date
    )
    
    print(f"Receipt data: {len(receipt_data)} bytes")
    
    # Print
    printer = "Cash Printer"
    h = None
    try:
        t0 = time.perf_counter()
        h = win32print.OpenPrinter(printer)
        job_id = win32print.StartDocPrinter(h, 1, ('FastReceipt', None, 'RAW'))
        win32print.StartPagePrinter(h)
        written = win32print.WritePrinter(h, receipt_data)
        win32print.EndPagePrinter(h)
        win32print.EndDocPrinter(h)
        t1 = time.perf_counter()
        print(f"Printed: {written} bytes in {t1-t0:.3f}s")
        print("Expected: Complete receipt with logo and formatted text")
        return True
    except Exception as e:
        print(f"ERROR: {e}")
        return False
    finally:
        if h:
            try:
                win32print.ClosePrinter(h)
            except:
                pass


def print_logo_only():
    """Print just the logo for testing."""
    print("\n=== Logo Only Test ===")
    
    logo_data = encode_logo_optimized(r"Z:\לוגו שחור לבן לא שקוף.png")
    
    # Build simple logo print
    commands = bytearray()
    commands.extend(b'\x1b\x40')  # Initialize
    commands.extend(b'\x1d\x2a\x2c\x0a')  # GS * 44 10
    commands.extend(logo_data)
    commands.extend(b'\x1d\x2f\x01')  # Print logo
    commands.extend(b'\x0a\x0a\x0a')  # Feed
    commands.extend(b'\x1d\x56\x31')  # Cut
    
    print(f"Logo data: {len(logo_data)} bytes")
    
    # Print
    printer = "Cash Printer"
    h = None
    try:
        t0 = time.perf_counter()
        h = win32print.OpenPrinter(printer)
        job_id = win32print.StartDocPrinter(h, 1, ('LogoOnly', None, 'RAW'))
        win32print.StartPagePrinter(h)
        written = win32print.WritePrinter(h, bytes(commands))
        win32print.EndPagePrinter(h)
        win32print.EndDocPrinter(h)
        t1 = time.perf_counter()
        print(f"Printed: {written} bytes in {t1-t0:.3f}s")
        print("Expected: Logo only")
        return True
    except Exception as e:
        print(f"ERROR: {e}")
        return False
    finally:
        if h:
            try:
                win32print.ClosePrinter(h)
            except:
                pass


def main():
    print("=== Fast Logo Printer with Rich Text ===")
    
    # Test 1: Logo only
    print("1. Testing logo only...")
    print_logo_only()
    
    input("\nPress Enter to continue with full receipt...")
    
    # Test 2: Full receipt
    print("\n2. Testing full receipt with rich text...")
    print_fast_receipt()
    
    print("\n=== Test Complete ===")
    print("Check both printouts:")
    print("1. Logo only - should show your logo clearly")
    print("2. Full receipt - should show complete formatted receipt")
    
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
