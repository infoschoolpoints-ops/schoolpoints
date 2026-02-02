"""Use the exact legacy file structure, just replace the logo data."""
import argparse
import time


def parse_hex_file(path):
    """Parse hex file and return raw bytes."""
    data = bytearray()
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            tokens = line.split()
            for tok in tokens:
                tok = tok.strip()
                if len(tok) == 2:
                    try:
                        data.append(int(tok, 16))
                    except ValueError:
                        pass
    return bytes(data)


def encode_image_to_gs_data(img):
    """Encode image to GS * data (just the pixel data, no header)."""
    from PIL import Image
    
    X_BYTES = 44
    Y_SLICES = 10
    WIDTH = X_BYTES * 8
    HEIGHT = Y_SLICES * 8
    
    im = img.convert('L')
    w, h = im.size
    
    scale = min(WIDTH / w, HEIGHT / h)
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))
    im = im.resize((new_w, new_h), Image.Resampling.LANCZOS)
    
    canvas = Image.new('L', (WIDTH, HEIGHT), 255)
    paste_x = (WIDTH - new_w) // 2
    paste_y = (HEIGHT - new_h) // 2
    canvas.paste(im, (paste_x, paste_y))
    
    canvas = canvas.point(lambda p: 0 if p < 128 else 255, mode='1')
    
    px = canvas.load()
    data = bytearray(X_BYTES * Y_SLICES * 8)
    idx = 0
    for y in range(HEIGHT):
        for byte_x in range(X_BYTES):
            b = 0
            for bit in range(8):
                x = byte_x * 8 + bit
                if px[x, y] == 0:
                    b |= (0x80 >> bit)
            data[idx] = b
            idx += 1
    
    return bytes(data)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--printer', required=True)
    ap.add_argument('--logo', required=True)
    ap.add_argument('--legacy-file', required=True)
    ap.add_argument('--use-legacy-logo', action='store_true', help='Use original legacy logo (no replacement)')
    args = ap.parse_args()
    
    import win32print
    from PIL import Image
    
    # Load legacy file
    print("Loading legacy file...")
    legacy = bytearray(parse_hex_file(args.legacy_file))
    print(f"Legacy file size: {len(legacy)} bytes")
    
    # Find GS * position
    gs_pos = bytes(legacy).find(b'\x1d\x2a')
    if gs_pos < 0:
        print("ERROR: GS * not found")
        return 1
    
    x = legacy[gs_pos + 2]
    y = legacy[gs_pos + 3]
    data_len = x * y * 8
    data_start = gs_pos + 4
    data_end = data_start + data_len
    
    print(f"GS * at {gs_pos}, x={x}, y={y}, data: {data_start}-{data_end}")
    
    if not args.use_legacy_logo:
        # Load and encode user's logo
        print("Encoding user's logo...")
        img = Image.open(args.logo)
        new_data = encode_image_to_gs_data(img)
        
        if len(new_data) != data_len:
            print(f"ERROR: Size mismatch - expected {data_len}, got {len(new_data)}")
            return 1
        
        # Replace logo data in legacy payload
        print("Replacing logo data in legacy structure...")
        legacy[data_start:data_end] = new_data
    else:
        print("Using original legacy logo (no replacement)")
    
    # Send to printer
    print(f"Sending {len(legacy)} bytes to printer...")
    h = None
    try:
        t0 = time.perf_counter()
        h = win32print.OpenPrinter(args.printer)
        job_id = win32print.StartDocPrinter(h, 1, ('LegacyWrapperTest', None, 'RAW'))
        win32print.StartPagePrinter(h)
        written = win32print.WritePrinter(h, bytes(legacy))
        win32print.EndPagePrinter(h)
        win32print.EndDocPrinter(h)
        t1 = time.perf_counter()
        print(f"OK: wrote {written} bytes in {t1-t0:.3f}s")
        return 0
    except Exception as e:
        print(f"ERROR: {e}")
        return 2
    finally:
        if h:
            try:
                win32print.ClosePrinter(h)
            except:
                pass


if __name__ == '__main__':
    raise SystemExit(main())
