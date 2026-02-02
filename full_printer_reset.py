"""Full printer reset sequence."""
import time
import win32print


def main():
    printer = "Cash Printer"
    
    print(f"Performing FULL RESET of {printer}...")
    
    # Aggressive reset sequence
    reset_commands = [
        b'\x1b\x40',          # ESC @ - Initialize
        b'\x1b\x40',          # ESC @ - Initialize again
        b'\x1b\x40',          # ESC @ - Initialize third time
        b'\x1b\x40',          # ESC @ - Initialize fourth time
        b'\x0a' * 20,         # 20 line feeds to clear buffer
        b'\x1d\x56\x30',      # GS V 0 - Full cut
        b'\x0a' * 5,          # 5 more line feeds
        b'\x1b\x40',          # ESC @ - Initialize once more
    ]
    
    h = None
    try:
        h = win32print.OpenPrinter(printer)
        
        for i, cmd in enumerate(reset_commands):
            print(f"Sending reset command {i+1}/{len(reset_commands)}...")
            try:
                job_id = win32print.StartDocPrinter(h, 1, (f'FullReset{i+1}', None, 'RAW'))
                win32print.StartPagePrinter(h)
                written = win32print.WritePrinter(h, cmd)
                win32print.EndPagePrinter(h)
                win32print.EndDocPrinter(h)
                time.sleep(1)  # Longer delay
                print(f"  Sent {written} bytes")
            except Exception as e:
                print(f"  Error: {e}")
                time.sleep(2)  # Wait longer on error
        
        print("\nFull reset complete!")
        print("Wait 10 seconds before trying to print...")
        time.sleep(10)
        
        # Test with simple text
        print("\nTesting with simple text...")
        test_cmd = b'Hello World\x0a' * 3
        job_id = win32print.StartDocPrinter(h, 1, ('TestPrint', None, 'RAW'))
        win32print.StartPagePrinter(h)
        written = win32print.WritePrinter(h, test_cmd)
        win32print.EndPagePrinter(h)
        win32print.EndDocPrinter(h)
        print(f"Test print sent: {written} bytes")
        
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
