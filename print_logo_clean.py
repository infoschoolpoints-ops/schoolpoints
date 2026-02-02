"""Clean minimal logo print - matching legacy structure exactly."""
import argparse
import time
from PIL import Image


def encode_logo_gs_star(img_path):
    """Encode image to GS * format (x=44, y=10)."""
    X_BYTES = 44
    Y_SLICES = 10
    WIDTH = X_BYTES * 8   # 352 dots
    HEIGHT = Y_SLICES * 8  # 80 dots
    
    img = Image.open(img_path).convert('L')
    w, h = img.size
    
    # Scale to fit
    scale = min(WIDTH / w, HEIGHT / h)
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))
    img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    
    # Center on canvas
    canvas = Image.new('L', (WIDTH, HEIGHT), 255)
    paste_x = (WIDTH - new_w) // 2
    paste_y = (HEIGHT - new_h) // 2
    canvas.paste(img, (paste_x, paste_y))
    
    # Convert to 1-bit
    canvas = canvas.point(lambda p: 0 if p < 128 else 255, mode='1')
    
    # Encode: row-major, MSB-first (matching legacy)
    px = canvas.load()
    data = bytearray()
    for y in range(HEIGHT):
        for byte_x in range(X_BYTES):
            b = 0
            for bit in range(8):
                x = byte_x * 8 + bit
                if px[x, y] == 0:  # black pixel
                    b |= (0x80 >> bit)
            data.append(b)
    
    # Build GS * command: 1D 2A x y data
    cmd = bytearray([0x1D, 0x2A, X_BYTES, Y_SLICES])
    cmd.extend(data)
    return bytes(cmd)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--printer', required=True)
    ap.add_argument('--logo', required=True)
    args = ap.parse_args()
    
    import win32print
    
    # Commands
    ESC_INIT = b'\x1b\x40'          # ESC @ - Initialize printer
    GS_CUT = b'\x1d\x56\x31'        # GS V 1 - Partial cut
    GS_PRINT_LOGO = b'\x1d\x2f\x01' # GS / 1 - Print downloaded bit image (normal)
    LF = b'\x0a'
    
    print("Encoding logo...")
    gs_star = encode_logo_gs_star(args.logo)
    print(f"GS * command: {len(gs_star)} bytes")
    
    # Build payload matching legacy structure:
    # 1. ESC @ (init)
    # 2. GS * (define logo)
    # 3. GS V (cut) - clears buffer, prepares for logo print
    # 4. GS / (print logo)
    # 5. Line feeds
    # 6. GS V (final cut)
    
    payload = bytearray()
    payload.extend(ESC_INIT)
    payload.extend(gs_star)
    payload.extend(LF * 3)
    payload.extend(GS_CUT)
    payload.extend(GS_PRINT_LOGO)
    payload.extend(LF * 5)
    payload.extend(GS_CUT)
    
    print(f"Total payload: {len(payload)} bytes")
    print(f"First 20 bytes: {payload[:20].hex(' ')}")
    
    # Send to printer
    print(f"Sending to {args.printer}...")
    h = None
    try:
        t0 = time.perf_counter()
        h = win32print.OpenPrinter(args.printer)
        job_id = win32print.StartDocPrinter(h, 1, ('LogoCleanTest', None, 'RAW'))
        win32print.StartPagePrinter(h)
        written = win32print.WritePrinter(h, bytes(payload))
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
