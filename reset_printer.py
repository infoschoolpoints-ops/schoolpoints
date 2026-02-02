"""Reset printer completely."""
import time
import win32print


def main():
    printer = "Cash Printer"
    
    print(f"Resetting {printer}...")
    
    # Full reset sequence
    reset_commands = [
        b'\x1b\x40',          # ESC @ - Initialize
        b'\x1b\x40',          # ESC @ - Initialize again
        b'\x1b\x40',          # ESC @ - Initialize third time
        b'\x0a' * 10,         # 10 line feeds
        b'\x1d\x56\x30',      # GS V 0 - Full cut
    ]
    
    h = None
    try:
        h = win32print.OpenPrinter(printer)
        
        for i, cmd in enumerate(reset_commands):
            print(f"Sending reset command {i+1}/{len(reset_commands)}...")
            job_id = win32print.StartDocPrinter(h, 1, (f'Reset{i+1}', None, 'RAW'))
            win32print.StartPagePrinter(h)
            written = win32print.WritePrinter(h, cmd)
            win32print.EndPagePrinter(h)
            win32print.EndDocPrinter(h)
            time.sleep(0.5)
        
        print("Printer reset complete!")
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
