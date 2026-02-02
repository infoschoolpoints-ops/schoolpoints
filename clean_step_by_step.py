"""Clean step by step printer following friend's instructions exactly."""
import win32print
import time


def step_1_basic_english():
    """Step 1: Basic English to verify printer works."""
    print("=== Step 1: Basic English ===")
    
    data = bytearray()
    data += b"\x1B\x40"          # Init
    data += b"Hello World\n"
    data += b"Printer Test\n"
    data += b"123456789\n"
    data += b"\x0A\x0A\x0A"
    data += b"\x1D\x56\x31"      # Cut
    
    printer = "Cash Printer"
    h = None
    try:
        h = win32print.OpenPrinter(printer)
        job_id = win32print.StartDocPrinter(h, 1, ('Step1English', None, 'RAW'))
        win32print.StartPagePrinter(h)
        written = win32print.WritePrinter(h, bytes(data))
        win32print.EndPagePrinter(h)
        win32print.EndDocPrinter(h)
        print(f"✓ Step 1: {written} bytes")
        return True
    except Exception as e:
        print(f"✗ Step 1 error: {e}")
        return False
    finally:
        if h:
            try:
                win32print.ClosePrinter(h)
            except:
                pass


def step_2_basic_hebrew():
    """Step 2: Basic Hebrew with CP862."""
    print("\n=== Step 2: Basic Hebrew ===")
    
    data = bytearray()
    data += b"\x1B\x40"          # Init
    data += b"\x1B\x74\x0F"      # Code Page 862 (Hebrew)
    
    # Test simple Hebrew
    data += "שלום\n".encode("cp862")
    data += "עולם\n".encode("cp862")
    data += "חנות\n".encode("cp862")
    
    data += b"\x0A\x0A\x0A"
    data += b"\x1D\x56\x31"      # Cut
    
    printer = "Cash Printer"
    h = None
    try:
        h = win32print.OpenPrinter(printer)
        job_id = win32print.StartDocPrinter(h, 1, ('Step2Hebrew', None, 'RAW'))
        win32print.StartPagePrinter(h)
        written = win32print.WritePrinter(h, bytes(data))
        win32print.EndPagePrinter(h)
        win32print.EndDocPrinter(h)
        print(f"✓ Step 2: {written} bytes")
        return True
    except Exception as e:
        print(f"✗ Step 2 error: {e}")
        return False
    finally:
        if h:
            try:
                win32print.ClosePrinter(h)
            except:
                pass


def step_3_friend_exact_code():
    """Step 3: Friend's exact code without modifications."""
    print("\n=== Step 3: Friend's Exact Code ===")
    
    data = bytearray()

    # ===== אתחול =====
    data += b"\x1B\x40"          # Init
    data += b"\x1B\x74\x0F"      # Code Page 862 (Hebrew)

    # ===== כותרת מעוצבת =====
    data += b"\x1B\x61\x01"      # Center
    data += b"\x1D\x21\x22"      # Double width + height
    data += b"\x1B\x45\x01"      # Bold ON
    data += "החנות שלי\n".encode("cp862")

    # ===== חזרה לרגיל =====
    data += b"\x1D\x21\x00"
    data += b"\x1B\x45\x00"

    data += "חשבונית מס\n".encode("cp862")
    data += "\n".encode("cp862")

    # ===== עיטור =====
    data += "==============================\n".encode("cp862")

    # ===== גוף =====
    data += b"\x1B\x61\x02"      # Right align
    data += "תאריך: 21/01/2026\n".encode("cp862")
    data += "מספר קבלה: 000123\n".encode("cp862")

    data += "------------------------------\n".encode("cp862")

    data += "חלב 3%        9.00 NIS\n".encode("cp862")
    data += "לחם אחיד      7.50 NIS\n".encode("cp862")
    data += "גבינה         12.00 NIS\n".encode("cp862")

    data += "------------------------------\n".encode("cp862")

    # ===== סה\"כ מודגש =====
    data += b"\x1D\x21\x11"      # Large
    data += b"\x1B\x45\x01"      # Bold
    data += "סה\"כ לתשלום: 28.50 NIS\n".encode("cp862")

    # ===== סיום =====
    data += b"\x1D\x21\x00"
    data += b"\x1B\x45\x00"
    data += b"\x1B\x61\x01"      # Center

    data += "\n".encode("cp862")
    data += "*** תודה ולהתראות ***\n".encode("cp862")

    # ===== חיתוך =====
    data += b"\x1D\x56\x31"
    
    printer = "Cash Printer"
    h = None
    try:
        h = win32print.OpenPrinter(printer)
        job_id = win32print.StartDocPrinter(h, 1, ('Step3Friend', None, 'RAW'))
        win32print.StartPagePrinter(h)
        written = win32print.WritePrinter(h, bytes(data))
        win32print.EndPagePrinter(h)
        win32print.EndDocPrinter(h)
        print(f"✓ Step 3: {written} bytes")
        return True
    except Exception as e:
        print(f"✗ Step 3 error: {e}")
        return False
    finally:
        if h:
            try:
                win32print.ClosePrinter(h)
            except:
                pass


def step_4_test_logo():
    """Step 4: Test logo only."""
    print("\n=== Step 4: Logo Only ===")
    
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
        
        # Add logo only
        printer.set(align='center')
        printer.image(img_bw)
        
        # Add spacing
        printer.text("\n\n\n\n")
        
        printer.cut()
        
        # Print
        printer_name = "Cash Printer"
        h = None
        try:
            h = win32print.OpenPrinter(printer_name)
            job_id = win32print.StartDocPrinter(h, 1, ('Step4Logo', None, 'RAW'))
            win32print.StartPagePrinter(h)
            written = win32print.WritePrinter(h, printer.output)
            win32print.EndPagePrinter(h)
            win32print.EndDocPrinter(h)
            print(f"✓ Step 4: {written} bytes")
            return True
            
        except Exception as e:
            print(f"✗ Step 4 error: {e}")
            return False
        finally:
            if h:
                try:
                    win32print.ClosePrinter(h)
                except:
                    pass
    
    except Exception as e:
        print(f"✗ Step 4 error: {e}")
        return False


def step_5_logo_plus_simple_hebrew():
    """Step 5: Logo + simple Hebrew."""
    print("\n=== Step 5: Logo + Simple Hebrew ===")
    
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
        
        # Add simple Hebrew
        printer.set(align='center', bold=True, width=2, height=2)
        printer._raw("חנות רות שלי\n".encode('cp862'))
        
        printer.set(align='center', bold=False, width=1, height=1)
        printer._raw("סה\"כ: 50 נקודות\n".encode('cp862'))
        
        # Add spacing before cut
        printer.text("\n\n\n\n\n")
        
        printer.cut()
        
        # Print
        printer_name = "Cash Printer"
        h = None
        try:
            h = win32print.OpenPrinter(printer_name)
            job_id = win32print.StartDocPrinter(h, 1, ('Step5LogoHebrew', None, 'RAW'))
            win32print.StartPagePrinter(h)
            written = win32print.WritePrinter(h, printer.output)
            win32print.EndPagePrinter(h)
            win32print.EndDocPrinter(h)
            print(f"✓ Step 5: {written} bytes")
            return True
            
        except Exception as e:
            print(f"✗ Step 5 error: {e}")
            return False
        finally:
            if h:
                try:
                    win32print.ClosePrinter(h)
                except:
                    pass
    
    except Exception as e:
        print(f"✗ Step 5 error: {e}")
        return False


def main():
    print("=== CLEAN STEP BY STEP ===")
    print("Following friend's instructions exactly!")
    
    # Step 1: English
    if not step_1_basic_english():
        print("Step 1 failed")
        return 1
    
    input("\nPress Enter for Step 2...")
    
    # Step 2: Basic Hebrew
    if not step_2_basic_hebrew():
        print("Step 2 failed")
        return 1
    
    input("\nPress Enter for Step 3...")
    
    # Step 3: Friend's exact code
    if not step_3_friend_exact_code():
        print("Step 3 failed")
        return 1
    
    input("\nPress Enter for Step 4...")
    
    # Step 4: Logo only
    if not step_4_test_logo():
        print("Step 4 failed")
        return 1
    
    input("\nPress Enter for Step 5...")
    
    # Step 5: Logo + Hebrew
    if not step_5_logo_plus_simple_hebrew():
        print("Step 5 failed")
        return 1
    
    print("\n=== ALL STEPS COMPLETE ===")
    print("Check each printout:")
    print("1. English should work")
    print("2. Hebrew direction (reversed?)")
    print("3. Friend's code format")
    print("4. Logo quality")
    print("5. Logo + Hebrew combination")
    
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
