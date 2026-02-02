"""Send the exact legacy file bytes without any modification."""
import time


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


def main():
    import win32print
    
    legacy_path = r"C:\Users\עמדת קופה\Documents\Install\TOOLS\Printer Test-eng0816\חשבונית עברית.txt"
    printer = "Cash Printer"
    
    print("Loading EXACT legacy file...")
    legacy = parse_hex_file(legacy_path)
    print(f"Legacy file: {len(legacy)} bytes")
    
    print(f"First 20 bytes: {legacy[:20].hex(' ')}")
    
    print(f"Sending EXACT legacy to {printer}...")
    h = None
    try:
        t0 = time.perf_counter()
        h = win32print.OpenPrinter(printer)
        job_id = win32print.StartDocPrinter(h, 1, ('ExactLegacy', None, 'RAW'))
        win32print.StartPagePrinter(h)
        written = win32print.WritePrinter(h, legacy)
        win32print.EndPagePrinter(h)
        win32print.EndDocPrinter(h)
        t1 = time.perf_counter()
        print(f"OK: wrote {written} bytes in {t1-t0:.3f}s")
        print("\nExpected: Exact same as original working receipt")
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
