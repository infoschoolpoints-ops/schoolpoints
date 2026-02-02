"""Final working solution: use legacy structure, replace logo data only."""
import argparse
import time
from PIL import Image


def parse_hex_file(path):
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


def encode_logo_data(img_path):
    """Encode image to GS * data format (just the pixel data, no header)."""
    X_BYTES = 44
    Y_SLICES = 10
    WIDTH = X_BYTES * 8
    HEIGHT = Y_SLICES * 8
    
    img = Image.open(img_path).convert('L')
    w, h = img.size
    
    scale = min(WIDTH / w, HEIGHT / h)
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))
    img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    
    canvas = Image.new('L', (WIDTH, HEIGHT), 255)
    paste_x = (WIDTH - new_w) // 2
    paste_y = (HEIGHT - new_h) // 2
    canvas.paste(img, (paste_x, paste_y))
    
    canvas = canvas.point(lambda p: 0 if p < 128 else 255, mode='1')
    canvas.save('debug_final_logo.png')
    
    px = canvas.load()
    data = bytearray()
    for y in range(HEIGHT):
        for byte_x in range(X_BYTES):
            b = 0
            for bit in range(8):
                x = byte_x * 8 + bit
                if px[x, y] == 0:
                    b |= (0x80 >> bit)
            data.append(b)
    
    return bytes(data)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--printer', required=True)
    ap.add_argument('--logo', required=True)
    ap.add_argument('--legacy-file', default=r"C:\Users\עמדת קופה\Documents\Install\TOOLS\Printer Test-eng0816\חשבונית עברית.txt")
    ap.add_argument('--logo-only', action='store_true', help='Print only logo, skip receipt text')
    args = ap.parse_args()
    
    import win32print
    
    print("Loading legacy file structure...")
    legacy = bytearray(parse_hex_file(args.legacy_file))
    print(f"Legacy file: {len(legacy)} bytes")
    
    # Find GS * position
    gs_pos = legacy.find(b'\x1d\x2a')
    if gs_pos < 0:
        print("ERROR: GS * not found in legacy file")
        return 1
    
    x, y = legacy[gs_pos+2], legacy[gs_pos+3]
    data_start = gs_pos + 4
    data_len = x * y * 8
    data_end = data_start + data_len
    
    print(f"GS * at byte {gs_pos}, x={x}, y={y}")
    print(f"Logo data: bytes {data_start}-{data_end} ({data_len} bytes)")
    
    # Encode our logo
    print("Encoding your logo...")
    our_data = encode_logo_data(args.logo)
    print(f"Encoded: {len(our_data)} bytes")
    print("Saved debug image: debug_final_logo.png")
    
    if len(our_data) != data_len:
        print(f"ERROR: Size mismatch - expected {data_len}, got {len(our_data)}")
        return 1
    
    # Replace logo data in legacy structure
    legacy[data_start:data_end] = our_data
    print("Replaced logo data in legacy structure")
    
    if args.logo_only:
        # Extract minimal payload: init + GS * + GS / + cut
        # Find first GS /
        gs_slash_pos = legacy.find(b'\x1d\x2f')
        if gs_slash_pos < 0:
            print("ERROR: GS / not found")
            return 1
        
        # Build minimal: ESC @ + GS * + GS / + feeds + cut
        payload = bytearray()
        payload.extend(b'\x1b\x40')  # init
        payload.extend(legacy[gs_pos:data_end])  # GS * with our logo
        payload.extend(b'\x1d\x2f\x01')  # GS / 1
        payload.extend(b'\x0a' * 5)  # feeds
        payload.extend(b'\x1d\x56\x31')  # cut
        
        print(f"Logo-only payload: {len(payload)} bytes")
    else:
        # Use full legacy structure with replaced logo
        payload = bytes(legacy)
        print(f"Full receipt payload: {len(payload)} bytes")
    
    # Send to printer
    print(f"Sending to {args.printer}...")
    h = None
    try:
        t0 = time.perf_counter()
        h = win32print.OpenPrinter(args.printer)
        job_id = win32print.StartDocPrinter(h, 1, ('LogoFinal', None, 'RAW'))
        win32print.StartPagePrinter(h)
        written = win32print.WritePrinter(h, payload)
        win32print.EndPagePrinter(h)
        win32print.EndDocPrinter(h)
        t1 = time.perf_counter()
        print(f"OK: wrote {written} bytes in {t1-t0:.3f}s")
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
