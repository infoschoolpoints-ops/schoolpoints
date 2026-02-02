"""Print logo using exact legacy HebrewReceipt format (GS * 44 10).

This replicates the working format from חשבונית עברית.txt:
- GS * with x=44 (352 dots), y=10 (80 dots)
- Row-major data: 80 rows × 44 bytes = 3520 bytes
- Each byte = 8 horizontal dots, MSB = leftmost
"""
import argparse
import time


def encode_logo_legacy(img, lsb_first=False, ordering='row'):
    """Encode image to GS * format matching legacy HebrewReceipt."""
    try:
        from PIL import Image
    except ImportError as e:
        raise RuntimeError('Pillow required: pip install pillow') from e

    # Legacy format: 44 bytes wide (352 dots), 10 slices tall (80 dots)
    X_BYTES = 44
    Y_SLICES = 10
    WIDTH = X_BYTES * 8   # 352 dots
    HEIGHT = Y_SLICES * 8  # 80 dots

    # Convert and resize
    im = img.convert('L')
    w, h = im.size

    # Resize to fit within 352x80, maintaining aspect ratio
    scale = min(WIDTH / w, HEIGHT / h)
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))
    im = im.resize((new_w, new_h), Image.Resampling.LANCZOS)

    # Create a white canvas of exact size and paste centered
    canvas = Image.new('L', (WIDTH, HEIGHT), 255)
    paste_x = (WIDTH - new_w) // 2
    paste_y = (HEIGHT - new_h) // 2
    canvas.paste(im, (paste_x, paste_y))

    # Convert to 1-bit (black/white)
    canvas = canvas.point(lambda p: 0 if p < 128 else 255, mode='1')
    
    # Save debug image to see what we're encoding
    try:
        canvas.save('debug_encoded_logo.png')
        print(f"DEBUG: Saved encoded image to debug_encoded_logo.png")
    except:
        pass

    px = canvas.load()
    data = bytearray(X_BYTES * Y_SLICES * 8)  # 3520 bytes
    idx = 0

    if ordering == 'row':
        # Row-major: for each row, for each horizontal byte
        for y in range(HEIGHT):
            for byte_x in range(X_BYTES):
                b = 0
                for bit in range(8):
                    x = byte_x * 8 + bit
                    if px[x, y] == 0:
                        if lsb_first:
                            b |= (1 << bit)
                        else:
                            b |= (0x80 >> bit)
                data[idx] = b
                idx += 1
    elif ordering == 'slice':
        # Slice-major: for each slice, for each horizontal byte, 8 vertical bits
        for slice_y in range(Y_SLICES):
            base_y = slice_y * 8
            for byte_x in range(X_BYTES):
                for row_in_slice in range(8):
                    y = base_y + row_in_slice
                    b = 0
                    for bit in range(8):
                        x = byte_x * 8 + bit
                        if px[x, y] == 0:
                            if lsb_first:
                                b |= (1 << bit)
                            else:
                                b |= (0x80 >> bit)
                    data[idx] = b
                    idx += 1
    elif ordering == 'column':
        # Column-major: for each slice, for each horizontal byte, pack 8 vertical dots
        for slice_y in range(Y_SLICES):
            base_y = slice_y * 8
            for byte_x in range(X_BYTES):
                for bit_x in range(8):
                    x = byte_x * 8 + bit_x
                    b = 0
                    for bit_y in range(8):
                        y = base_y + bit_y
                        if px[x, y] == 0:
                            if lsb_first:
                                b |= (1 << bit_y)
                            else:
                                b |= (0x80 >> bit_y)
                    data[idx] = b
                    idx += 1

    # Build GS * command
    GS = b'\x1d'
    define = GS + b'*' + bytes([X_BYTES, Y_SLICES]) + bytes(data)
    return define


def create_test_pattern():
    """Create a simple test pattern image for debugging."""
    try:
        from PIL import Image
    except ImportError:
        return None
    
    WIDTH = 352
    HEIGHT = 80
    img = Image.new('L', (WIDTH, HEIGHT), 255)
    px = img.load()
    
    # Draw a simple pattern: filled rectangle in center
    for y in range(20, 60):
        for x in range(100, 252):
            px[x, y] = 0  # black
    
    # Draw diagonal line
    for i in range(80):
        if i < WIDTH:
            px[i, i] = 0
            px[i + 50, i] = 0 if i + 50 < WIDTH else px[i, i]
    
    return img


def main():
    ap = argparse.ArgumentParser(description='Print logo in legacy HebrewReceipt format')
    ap.add_argument('--printer', required=True)
    ap.add_argument('--logo', required=True)
    ap.add_argument('--no-init', action='store_true', help='Skip ESC @ init')
    ap.add_argument('--scale', type=int, choices=[0, 1, 2, 3], default=1,
                    help='GS / m parameter: 0=normal, 1=double-width, 2=double-height, 3=quadruple')
    ap.add_argument('--lsb', action='store_true', help='Use LSB-first bit order (instead of MSB-first)')
    ap.add_argument('--ordering', choices=['row', 'slice', 'column'], default='row', help='Byte ordering format')
    ap.add_argument('--test-pattern', action='store_true', help='Print a diagonal test pattern instead of logo')
    ap.add_argument('--wait', action='store_true')
    args = ap.parse_args()

    try:
        import win32print
    except ImportError:
        print('ERROR: pywin32 required')
        return 2

    try:
        from PIL import Image
    except ImportError:
        print('ERROR: Pillow required')
        return 2

    if args.test_pattern:
        img = create_test_pattern()
        if img is None:
            print('ERROR: Cannot create test pattern')
            return 2
        print('Using test pattern instead of logo')
    else:
        try:
            img = Image.open(args.logo)
        except Exception as e:
            print(f'ERROR: Cannot open logo: {e}')
            return 2

    ESC = b'\x1b'
    GS = b'\x1d'
    INIT = ESC + b'@'
    ALIGN_CENTER = ESC + b'a\x01'
    PRINT_DOWNLOADED = GS + b'/' + bytes([args.scale])

    try:
        define = encode_logo_legacy(img, lsb_first=args.lsb, ordering=args.ordering)
        print(f'Ordering: {args.ordering}, LSB: {args.lsb}')
    except Exception as e:
        print(f'ERROR: Encoding failed: {e}')
        return 2

    payload = bytearray()
    if not args.no_init:
        payload += INIT
    # Note: Legacy file has NO commands between ESC @ and GS *
    payload += define
    payload += ALIGN_CENTER  # Align AFTER define, before print
    payload += PRINT_DOWNLOADED
    payload += b'\n\n\n'

    print(f'Payload size: {len(payload)} bytes')
    print(f'GS * data size: {len(define) - 4} bytes (expected 3520)')

    h = None
    try:
        t0 = time.perf_counter()
        h = win32print.OpenPrinter(args.printer)
        job_id = win32print.StartDocPrinter(h, 1, ('LegacyLogoTest', None, 'RAW'))
        win32print.StartPagePrinter(h)
        written = win32print.WritePrinter(h, bytes(payload))
        win32print.EndPagePrinter(h)
        win32print.EndDocPrinter(h)
        t_send = time.perf_counter() - t0

        print(f'OK: wrote {written} bytes')
        print(f'SendTime: {t_send:.3f}s')

        if args.wait:
            # Simple wait for job completion
            time.sleep(0.5)
            deadline = time.time() + 30
            while time.time() < deadline:
                try:
                    h2 = win32print.OpenPrinter(args.printer)
                    jobs = win32print.EnumJobs(h2, 0, 100, 1)
                    win32print.ClosePrinter(h2)
                    if not any(j.get('JobId') == job_id for j in jobs):
                        break
                except:
                    break
                time.sleep(0.2)
            print(f'TotalTime: {time.perf_counter() - t0:.3f}s')

        return 0
    except Exception as e:
        print(f'ERROR: Print failed: {e}')
        return 2
    finally:
        if h:
            try:
                win32print.ClosePrinter(h)
            except:
                pass


if __name__ == '__main__':
    raise SystemExit(main())
