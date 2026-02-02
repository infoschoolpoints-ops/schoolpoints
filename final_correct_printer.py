"""Final correct printer with reversed Hebrew and fixed cut."""
import win32print
import time


def reverse_hebrew_text(text):
    """Reverse Hebrew text for correct printing."""
    return text[::-1]


def print_final_correct():
    """Print with correct Hebrew direction and timing."""
    print("=== Final Correct Printer ===")
    
    data = bytearray()

    # ===== אתחול =====
    data += b"\x1B\x40"          # Init
    data += b"\x1B\x74\x0F"      # Code Page 862 (Hebrew)

    # ===== כותרת מעוצבת =====
    data += b"\x1B\x61\x01"      # Center
    data += b"\x1D\x21\x22"      # Double width + height
    data += b"\x1B\x45\x01"      # Bold ON
    
    # REVERSE the Hebrew text!
    title = reverse_hebrew_text("החנות שלי")
    data += (title + "\n").encode("cp862")

    # ===== חזרה לרגיל =====
    data += b"\x1D\x21\x00"
    data += b"\x1B\x45\x00"

    receipt = reverse_hebrew_text("חשבונית מס")
    data += (receipt + "\n").encode("cp862")
    data += "\n".encode("cp862")

    # ===== עיטור =====
    data += "==============================\n".encode("cp862")

    # ===== גוף =====
    data += b"\x1B\x61\x02"      # Right align
    
    date = reverse_hebrew_text("תאריך: 21/01/2026")
    data += (date + "\n").encode("cp862")
    
    receipt_num = reverse_hebrew_text("מספר קבלה: 000123")
    data += (receipt_num + "\n").encode("cp862")

    data += "------------------------------\n".encode("cp862")

    milk = reverse_hebrew_text("חלב 3%        9.00 NIS")
    data += (milk + "\n").encode("cp862")
    
    bread = reverse_hebrew_text("לחם אחיד      7.50 NIS")
    data += (bread + "\n").encode("cp862")
    
    cheese = reverse_hebrew_text("גבינה         12.00 NIS")
    data += (cheese + "\n").encode("cp862")

    data += "------------------------------\n".encode("cp862")

    # ===== סה\"כ מודגש =====
    data += b"\x1D\x21\x11"      # Large
    data += b"\x1B\x45\x01"      # Bold
    
    total = reverse_hebrew_text("סה\"כ לתשלום: 28.50 NIS")
    data += (total + "\n").encode("cp862")

    # ===== סיום =====
    data += b"\x1D\x21\x00"
    data += b"\x1B\x45\x00"
    data += b"\x1B\x61\x01"      # Center

    data += "\n".encode("cp862")
    data += "\n".encode("cp862")  # Extra spacing before cut
    
    thanks = reverse_hebrew_text("*** תודה ולהתראות ***")
    data += (thanks + "\n").encode("cp862")
    
    data += "\n".encode("cp862")  # More spacing before cut
    data += "\n".encode("cp862")  # Even more spacing

    # ===== חיתוך =====
    data += b"\x1D\x56\x31"
    
    # Print
    printer = "Cash Printer"
    h = None
    try:
        t0 = time.perf_counter()
        h = win32print.OpenPrinter(printer)
        job_id = win32print.StartDocPrinter(h, 1, ('FinalCorrect', None, 'RAW'))
        win32print.StartPagePrinter(h)
        written = win32print.WritePrinter(h, bytes(data))
        win32print.EndPagePrinter(h)
        win32print.EndDocPrinter(h)
        t1 = time.perf_counter()
        
        print(f"✓ Printed {written} bytes in {t1-t0:.3f}s")
        print("Final correct - Hebrew should be RIGHT direction!")
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
    """Print with logo and correct Hebrew."""
    print("\n=== Logo + Correct Hebrew ===")
    
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
        printer._raw(b'\x1B\x74\x0F')  # CP862
        
        # Add logo
        printer.set(align='center')
        printer.image(img_bw)
        
        # Add spacing
        printer.text("\n")
        
        # Add REVERSED Hebrew
        printer.set(align='center', bold=True, width=2, height=2)
        
        title = reverse_hebrew_text("חנות רות שלי")
        printer._raw((title + "\n").encode('cp862'))
        
        printer.set(align='center', bold=False, width=1, height=1)
        
        total = reverse_hebrew_text("סה\"כ: 50 נקודות")
        printer._raw((total + "\n").encode('cp862'))
        
        # Add spacing before cut
        printer.text("\n\n\n")
        
        printer.cut()
        
        # Print
        printer_name = "Cash Printer"
        h = None
        try:
            t0 = time.perf_counter()
            h = win32print.OpenPrinter(printer_name)
            job_id = win32print.StartDocPrinter(h, 1, ('LogoCorrect', None, 'RAW'))
            win32print.StartPagePrinter(h)
            written = win32print.WritePrinter(h, printer.output)
            win32print.EndPagePrinter(h)
            win32print.EndDocPrinter(h)
            t1 = time.perf_counter()
            
            print(f"✓ Printed {written} bytes in {t1-t0:.3f}s")
            print("Logo + Correct Hebrew!")
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
    print("=== FINAL CORRECT PRINTER ===")
    print("With reversed Hebrew and proper spacing!")
    
    # Test 1: Final correct receipt
    if not print_final_correct():
        print("Final receipt failed")
        return 1
    
    input("\nPress Enter to test with logo...")
    
    # Test 2: Logo + correct Hebrew
    if not print_with_logo():
        print("Logo test failed")
        return 1
    
    print("\n=== FINAL SOLUTION COMPLETE ===")
    print("✓ Hebrew text reversed for correct direction")
    print("✓ Proper spacing before cut")
    print("✓ Logo + Hebrew working")
    print("\nThis should be PERFECT!")
    
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
