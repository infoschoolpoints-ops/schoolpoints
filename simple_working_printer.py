"""Simple working printer test with correct Hebrew."""
import win32print
import time


def print_simple_hebrew():
    """Print simple Hebrew text with correct encoding."""
    print("=== Simple Hebrew Test ===")
    
    # Create the command sequence
    data = bytearray()
    
    # Initialize printer
    data.extend(b'\x1B\x40')
    
    # Set Code Page to 862 (Hebrew) - CRITICAL!
    data.extend(b'\x1B\x74\x0F')
    
    # Set large text and center
    data.extend(b'\x1B\x21\x30')  # Large
    data.extend(b'\x1B\x61\x01')  # Center
    
    # Add Hebrew text using CP862
    hebrew_text = "חנות רות שלי"
    data.extend(hebrew_text.encode('cp862'))
    data.extend(b'\x0A')  # Newline
    
    # Normal text
    data.extend(b'\x1B\x21\x00')  # Normal
    data.extend(b'\x1B\x61\x01')  # Center
    
    hebrew_text2 = "בדיקת עברית"
    data.extend(hebrew_text2.encode('cp862'))
    data.extend(b'\x0A')
    
    hebrew_text3 = "סה\"כ: 50 נקודות"
    data.extend(hebrew_text3.encode('cp862'))
    data.extend(b'\x0A')
    
    # Add spacing and cut
    data.extend(b'\x0A\x0A\x0A')
    data.extend(b'\x1D\x56\x31')  # Cut
    
    # Print
    printer = "Cash Printer"
    h = None
    try:
        t0 = time.perf_counter()
        h = win32print.OpenPrinter(printer)
        job_id = win32print.StartDocPrinter(h, 1, ('SimpleHebrew', None, 'RAW'))
        win32print.StartPagePrinter(h)
        written = win32print.WritePrinter(h, bytes(data))
        win32print.EndPagePrinter(h)
        win32print.EndDocPrinter(h)
        t1 = time.perf_counter()
        
        print(f"✓ Printed {written} bytes in {t1-t0:.3f}s")
        print("Check the printer - Hebrew should be correct!")
        return True
        
    except Exception as e:
        print(f"✗ Print error: {e}")
        return False
    finally:
        if h:
            try:
                win32print.ClosePrinter(h)
            except:
                pass


def print_with_logo():
    """Print with logo using ESCPOS library."""
    print("\n=== Logo + Hebrew Test ===")
    
    try:
        from escpos.printer import Dummy
        from PIL import Image
        
        # Resize logo
        img = Image.open("Z:\\לוגו שחור לבן לא שקוף.png").convert('L')
        w, h = img.size
        scale = min(384 / w, 120 / h)
        new_w = max(1, int(w * scale))
        new_h = max(1, int(h * scale))
        img_resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        img_bw = img_resized.point(lambda p: 0 if p < 128 else 255, mode='1')
        
        # Create printer
        printer = Dummy()
        
        # Initialize
        printer._raw(b'\x1B\x40')
        
        # Set Code Page to 862 (Hebrew)
        printer._raw(b'\x1B\x74\x0F')
        
        # Add logo
        printer.set(align='center')
        printer.image(img_bw)
        
        # Add Hebrew
        printer.text("\n")
        printer.set(align='center', bold=True, width=2, height=2)
        
        hebrew_text = "חנות רות שלי"
        printer._raw(hebrew_text.encode('cp862') + b'\n')
        
        printer.set(align='center', bold=False, width=1, height=1)
        hebrew_text2 = "סה\"כ: 50 נקודות"
        printer._raw(hebrew_text2.encode('cp862') + b'\n')
        
        printer.text("\n\n")
        printer.cut()
        
        # Print
        printer_name = "Cash Printer"
        h = None
        try:
            t0 = time.perf_counter()
            h = win32print.OpenPrinter(printer_name)
            job_id = win32print.StartDocPrinter(h, 1, ('LogoHebrew', None, 'RAW'))
            win32print.StartPagePrinter(h)
            written = win32print.WritePrinter(h, printer.output)
            win32print.EndPagePrinter(h)
            win32print.EndDocPrinter(h)
            t1 = time.perf_counter()
            
            print(f"✓ Printed {written} bytes in {t1-t0:.3f}s")
            print("Check the printer - Logo + Hebrew should be perfect!")
            return True
            
        except Exception as e:
            print(f"✗ Print error: {e}")
            return False
        finally:
            if h:
                try:
                    win32print.ClosePrinter(h)
                except:
                    pass
    
    except Exception as e:
        print(f"✗ Error: {e}")
        return False


def main():
    print("=== SIMPLE WORKING PRINTER ===")
    print("Test 1: Hebrew text only")
    print("Test 2: Logo + Hebrew")
    
    # Test 1
    if not print_simple_hebrew():
        print("Failed text test")
        return 1
    
    input("\nPress Enter to test with logo...")
    
    # Test 2
    if not print_with_logo():
        print("Failed logo test")
        return 1
    
    print("\n=== BOTH TESTS COMPLETE ===")
    print("If you see correct Hebrew - we solved it!")
    
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
