"""Final solution based on friend's successful method."""
import time
import win32print
from PIL import Image, ImageFilter


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


def encode_logo_friend_method(img_path):
    """Encode logo using friend's successful method."""
    X_BYTES = 44
    Y_SLICES = 10
    WIDTH = 352
    HEIGHT = 80
    
    img = Image.open(img_path).convert('L')
    w, h = img.size
    
    # Scale to fit (like friend did)
    scale = min(WIDTH / w, HEIGHT / h) * 0.8  # Slightly larger than before
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))
    img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    
    # Apply blur to thicken lines
    img = img.filter(ImageFilter.SMOOTH)
    
    # Center on canvas
    canvas = Image.new('L', (WIDTH, HEIGHT), 255)
    paste_x = (WIDTH - new_w) // 2
    paste_y = (HEIGHT - new_h) // 2
    canvas.paste(img, (paste_x, paste_y))
    
    # Threshold for good density
    canvas = canvas.point(lambda p: 0 if p < 160 else 255, mode='1')
    canvas.save('friend_method_logo.png')
    
    px = canvas.load()
    
    # Try friend's method - maybe different bit ordering or structure
    # Method: Try column-major with different bit ordering
    
    # Method 1: Standard row-major MSB (our baseline)
    image_data1 = bytearray()
    for y in range(HEIGHT):
        for byte_x in range(X_BYTES):
            b = 0
            for bit in range(8):
                x = byte_x * 8 + bit
                if px[x, y] == 0:
                    b |= (0x80 >> bit)
            image_data1.append(b)
    
    # Method 2: Column-major MSB (like friend might have used)
    image_data2 = bytearray()
    for byte_x in range(X_BYTES):
        for y in range(HEIGHT):
            b = 0
            for bit in range(8):
                x = byte_x * 8 + bit
                if px[x, y] == 0:
                    b |= (0x80 >> bit)
            image_data2.append(b)
    
    # Method 3: Row-major LSB
    image_data3 = bytearray()
    for y in range(HEIGHT):
        for byte_x in range(X_BYTES):
            b = 0
            for bit in range(8):
                x = byte_x * 8 + bit
                if px[x, y] == 0:
                    b |= (0x01 << bit)
            image_data3.append(b)
    
    # Method 4: Column-major LSB
    image_data4 = bytearray()
    for byte_x in range(X_BYTES):
        for y in range(HEIGHT):
            b = 0
            for bit in range(8):
                x = byte_x * 8 + bit
                if px[x, y] == 0:
                    b |= (0x01 << bit)
            image_data4.append(b)
    
    # Return all methods for testing
    return [
        ("Row-major MSB", image_data1),
        ("Column-major MSB", image_data2),
        ("Row-major LSB", image_data3),
        ("Column-major LSB", image_data4)
    ]


def test_all_methods():
    """Test all encoding methods."""
    print("=== Testing All Friend Methods ===")
    
    methods = encode_logo_friend_method(r"Z:\לוגו שחור לבן לא שקוף.png")
    
    results = []
    
    for i, (name, image_data) in enumerate(methods):
        print(f"\n{i+1}. Testing {name}...")
        
        # Create logo data with padding
        logo_data = bytearray()
        logo_data.extend([0x00] * 517)  # Padding
        logo_data.extend(image_data)
        
        # Fill to 3520 bytes
        while len(logo_data) < 3520:
            logo_data.append(0x00)
        logo_data = logo_data[:3520]
        
        # Build print command
        gs_star = bytearray([0x1D, 0x2A, 44, 10])
        gs_star.extend(logo_data)
        
        payload = bytearray()
        payload.extend(b'\x1b\x40')
        payload.extend(gs_star)
        payload.extend(b'\x1d\x2f\x01')
        payload.extend(b'\x0a' * 5)
        payload.extend(b'\x1d\x56\x31')
        
        # Print
        printer = "Cash Printer"
        h = None
        try:
            t0 = time.perf_counter()
            h = win32print.OpenPrinter(printer)
            job_id = win32print.StartDocPrinter(h, 1, (f'FriendMethod{i+1}', None, 'RAW'))
            win32print.StartPagePrinter(h)
            written = win32print.WritePrinter(h, bytes(payload))
            win32print.EndPagePrinter(h)
            win32print.EndDocPrinter(h)
            t1 = time.perf_counter()
            
            non_zero = sum(1 for b in logo_data if b != 0)
            density = 100 * non_zero / len(logo_data)
            
            print(f"  Printed: {written} bytes in {t1-t0:.3f}s")
            print(f"  Density: {density:.1f}%")
            print(f"  Expected: Your logo with {name} encoding")
            
            results.append((name, True, density))
            
        except Exception as e:
            print(f"  ERROR: {e}")
            results.append((name, False, 0))
        finally:
            if h:
                try:
                    win32print.ClosePrinter(h)
                except:
                    pass
    
    print("\n=== Results Summary ===")
    for name, success, density in results:
        status = "✓" if success else "✗"
        print(f"{status} {name:20s}: {density:5.1f}% density")
    
    return results


def print_original_for_comparison():
    """Print original ALL4SHOP for comparison."""
    print("\n=== Printing Original ALL4SHOP ===")
    
    legacy_path = r"C:\Users\עמדת קופה\Documents\Install\TOOLS\Printer Test-eng0816\חשבונית עברית.txt"
    legacy = parse_hex_file(legacy_path)
    
    printer = "Cash Printer"
    h = None
    try:
        t0 = time.perf_counter()
        h = win32print.OpenPrinter(printer)
        job_id = win32print.StartDocPrinter(h, 1, ('OriginalALL4SHOP', None, 'RAW'))
        win32print.StartPagePrinter(h)
        written = win32print.WritePrinter(h, legacy)
        win32print.EndPagePrinter(h)
        win32print.EndDocPrinter(h)
        t1 = time.perf_counter()
        print(f"Printed: {written} bytes in {t1-t0:.3f}s")
        print("Expected: Original ALL4SHOP logo (for comparison)")
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
    print("=== Final Friend Method Test ===")
    print("Testing all 4 encoding methods based on friend's success")
    
    # Test all methods
    results = test_all_methods()
    
    input("\nPress Enter to print original ALL4SHOP for comparison...")
    
    # Print original
    print_original_for_comparison()
    
    print("\n=== Final Instructions ===")
    print("Compare all 5 printouts:")
    print("1. Row-major MSB - Standard method")
    print("2. Column-major MSB - Friend's possible method")
    print("3. Row-major LSB - Reversed bit order")
    print("4. Column-major LSB - Both reversed")
    print("5. Original ALL4SHOP - Reference")
    
    print("\nChoose the method that looks most like the original!")
    
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
