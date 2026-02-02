"""Encode user logo using Method 7 (Interleaved rows) - the correct one!"""
import time
from PIL import Image


def encode_logo_interleaved(img_path):
    """Encode logo using interleaved rows method."""
    X_BYTES = 44
    Y_SLICES = 10
    WIDTH = 352
    HEIGHT = 80
    
    img = Image.open(img_path).convert('L')
    w, h = img.size
    
    # Scale to fit
    scale = min(WIDTH / w, HEIGHT / h)
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))
    img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    
    canvas = Image.new('L', (WIDTH, HEIGHT), 255)
    paste_x = (WIDTH - new_w) // 2
    paste_y = (HEIGHT - new_h) // 2
    canvas.paste(img, (paste_x, paste_y))
    
    # Convert to 1-bit
    canvas = canvas.point(lambda p: 0 if p < 128 else 255, mode='1')
    canvas.save('user_logo_method7.png')
    
    px = canvas.load()
    data = bytearray()
    
    # EVEN ROWS FIRST
    for y in range(0, HEIGHT, 2):
        for byte_x in range(X_BYTES):
            b = 0
            for bit in range(8):
                x = byte_x * 8 + bit
                if px[x, y] == 0:
                    b |= (0x80 >> bit)
            data.append(b)
    
    # THEN ODD ROWS
    for y in range(1, HEIGHT, 2):
        for byte_x in range(X_BYTES):
            b = 0
            for bit in range(8):
                x = byte_x * 8 + bit
                if px[x, y] == 0:
                    b |= (0x80 >> bit)
            data.append(b)
    
    return bytes(data)


def main():
    import win32print
    
    print("=== Encoding logo with Method 7 (Interleaved rows) ===")
    
    logo_data = encode_logo_interleaved(r"Z:\לוגו שחור לבן לא שקוף.png")
    print(f"Encoded: {len(logo_data)} bytes")
    
    # Build GS * command
    gs_star = bytearray([0x1D, 0x2A, 44, 10])  # x=44, y=10
    gs_star.extend(logo_data)
    
    # Build payload
    payload = bytearray()
    payload.extend(b'\x1b\x40')        # ESC @ - init
    payload.extend(gs_star)            # GS * - define
    payload.extend(b'\x1d\x2f\x01')    # GS / 1 - print
    payload.extend(b'\x0a' * 5)        # feeds
    payload.extend(b'\x1d\x56\x31')    # cut
    
    print(f"Total payload: {len(payload)} bytes")
    
    # Send to printer
    printer = "Cash Printer"
    print(f"Sending to {printer}...")
    
    h = None
    try:
        t0 = time.perf_counter()
        h = win32print.OpenPrinter(printer)
        job_id = win32print.StartDocPrinter(h, 1, ('Method7Logo', None, 'RAW'))
        win32print.StartPagePrinter(h)
        written = win32print.WritePrinter(h, bytes(payload))
        win32print.EndPagePrinter(h)
        win32print.EndDocPrinter(h)
        t1 = time.perf_counter()
        print(f"OK: wrote {written} bytes in {t1-t0:.3f}s")
        print("\nSUCCESS! Logo printed with Method 7 encoding!")
        return 0
    except Exception as e:
        print(f"ERROR: {e}")
        return 1
    finally:
        if h:
            try:
                win32print.ClosePrinter(h)
            except:
                pass


if __name__ == '__main__':
    raise SystemExit(main())
