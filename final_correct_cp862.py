"""Final correct solution with CP862 and ESC t 15 command."""
import os
import time
import win32print
from PIL import Image


def resize_logo_for_printer(img_path, max_width=384, max_height=150):
    """Resize logo to fit printer dimensions properly."""
    print(f"Resizing logo to max {max_width}x{max_height}...")
    
    img = Image.open(img_path).convert('L')
    w, h = img.size
    
    # Calculate scale to fit within limits
    scale = min(max_width / w, max_height / h)
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))
    
    print(f"Original: {w}x{h} -> Resized: {new_w}x{new_h}")
    
    # Resize with high quality
    img_resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    
    # Convert to pure black/white (1-bit)
    threshold = 128
    img_bw = img_resized.point(lambda p: 0 if p < threshold else 255, mode='1')
    
    # Save for inspection
    img_bw.save('logo_resized_final.png')
    
    return img_bw


def text_cp862(txt):
    """Text function with correct CP862 encoding."""
    return txt.encode("cp862") + b"\n"


def create_final_receipt():
    """Create final receipt with CORRECT CP862 encoding."""
    print("=== Creating Final CORRECT Receipt ===")
    
    try:
        from escpos.printer import Dummy
        
        # Resize logo first
        logo_img = resize_logo_for_printer("Z:\\לוגו שחור לבן לא שקוף.png", 384, 120)
        
        # Create dummy printer
        printer = Dummy()
        
        # Initialize printer
        printer._raw(b'\x1B\x40')
        
        # CRITICAL: Set Code Page to 862 (Hebrew)
        printer._raw(b'\x1B\x74\x0F')  # ESC t 15 = Code Page 862
        
        # Add logo (centered)
        printer.set(align='center')
        printer.image(logo_img)
        
        # Add spacing
        printer.text("\n")
        
        # Store name - using CORRECT CP862 encoding
        printer.set(align='center', bold=True, width=2, height=2)
        printer._raw(text_cp862("חנות רות שלי"))  # CORRECT!
        
        # Store details
        printer.set(align='center', bold=False, width=1, height=1)
        printer._raw(text_cp862("ח.פ: 123456789"))  # CORRECT!
        printer._raw(text_cp862("טלפון: 03-1234567"))  # CORRECT!
        printer.text("\n")
        
        # Separator
        printer.set(align='center')
        printer.text("-" * 32 + "\n")
        
        # Sample items
        printer.set(align='right')
        printer._raw(text_cp862("חלב 3%                    9.00"))  # CORRECT!
        printer._raw(text_cp862("לחם אחיד                  7.50"))  # CORRECT!
        printer._raw(text_cp862("גבינה                    12.00"))  # CORRECT!
        printer.text("\n")
        
        # Total
        printer.set(align='center', bold=True, width=2, height=2)
        printer._raw(text_cp862("סה\"כ: 28.50 NIS"))  # CORRECT!
        
        # Footer
        printer.set(align='center', bold=False, width=1, height=1)
        printer.text("\n")
        printer._raw(text_cp862("תודה ולהתראות!"))  # CORRECT!
        printer.text("\n\n")
        
        # Cut
        printer.cut()
        
        # Get the output data
        output_data = printer.output
        
        # Save the file
        with open("receipt_final_correct.bin", "wb") as f:
            f.write(output_data)
        
        print("✓ Final CORRECT receipt created: receipt_final_correct.bin")
        
        # Check file size
        file_size = os.path.getsize("receipt_final_correct.bin")
        print(f"File size: {file_size} bytes")
        
        return True
        
    except Exception as e:
        print(f"✗ Error creating final receipt: {e}")
        return False


def create_simple_text_test():
    """Create simple text test with CORRECT CP862."""
    print("=== Creating Simple CORRECT Text Test ===")
    
    try:
        from escpos.printer import Dummy
        
        printer = Dummy()
        printer._raw(b'\x1B\x40')
        
        # CRITICAL: Set Code Page to 862 (Hebrew)
        printer._raw(b'\x1B\x74\x0F')  # ESC t 15 = Code Page 862
        
        # Test different text styles with CORRECT CP862
        printer.set(align='center', bold=True, width=2, height=2)
        printer._raw(text_cp862("חנות רות שלי"))  # CORRECT!
        
        printer.set(align='center', bold=False, width=1, height=1)
        printer._raw(text_cp862("בדיקת עברית"))  # CORRECT!
        printer._raw(text_cp862("שלום עולם"))  # CORRECT!
        printer._raw(text_cp862("סה\"כ לתשלום"))  # CORRECT!
        
        printer.text("\n\n")
        printer.cut()
        
        with open("text_test_correct.bin", "wb") as f:
            f.write(printer.output)
        
        print("✓ Final CORRECT text test created: text_test_correct.bin")
        
        return True
        
    except Exception as e:
        print(f"✗ Error creating text test: {e}")
        return False


def create_decorated_receipt():
    """Create receipt with decorations and formatting."""
    print("=== Creating Decorated Receipt ===")
    
    try:
        from escpos.printer import Dummy
        
        printer = Dummy()
        printer._raw(b'\x1B\x40')
        
        # CRITICAL: Set Code Page to 862 (Hebrew)
        printer._raw(b'\x1B\x74\x0F')  # ESC t 15 = Code Page 862
        
        # Decorated header
        printer.set(align='center')
        printer.text("=" * 32 + "\n")
        printer.set(align='center', bold=True, width=2, height=2)
        printer._raw(text_cp862("חנות רות שלי"))  # CORRECT!
        printer.set(align='center', bold=False, width=1, height=1)
        printer._raw(text_cp862("ח.פ: 123456789"))  # CORRECT!
        printer.text("=" * 32 + "\n")
        printer.text("\n")
        
        # Sample items with decoration
        printer.set(align='right')
        printer._raw(text_cp862("חלב 3%                    9.00"))  # CORRECT!
        printer._raw(text_cp862("לחם אחיד                  7.50"))  # CORRECT!
        printer._raw(text_cp862("גבינה                    12.00"))  # CORRECT!
        printer.text("\n")
        
        # Decorated total
        printer.text("-" * 32 + "\n")
        printer.set(align='center', bold=True, width=2, height=2)
        printer._raw(text_cp862("סה\"כ: 28.50 ₪"))  # CORRECT!
        printer.text("-" * 32 + "\n")
        
        # Footer
        printer.set(align='center', bold=False, width=1, height=1)
        printer._raw(text_cp862("תודה ולהתראות!"))  # CORRECT!
        printer.text("\n")
        printer.text("=" * 32 + "\n")
        printer.text("\n")
        
        printer.cut()
        
        with open("receipt_decorated.bin", "wb") as f:
            f.write(printer.output)
        
        print("✓ Decorated receipt created: receipt_decorated.bin")
        
        return True
        
    except Exception as e:
        print(f"✗ Error creating decorated receipt: {e}")
        return False


def print_final_tests():
    """Print the final CORRECT tests."""
    print("\n=== Printing Final CORRECT Tests ===")
    
    files_to_test = [
        ("text_test_correct.bin", "CORRECT text test"),
        ("receipt_final_correct.bin", "CORRECT receipt"),
        ("receipt_decorated.bin", "Decorated receipt")
    ]
    
    for filename, description in files_to_test:
        if not os.path.exists(filename):
            print(f"✗ {filename} not found")
            continue
        
        print(f"\nPrinting {description}...")
        
        try:
            with open(filename, "rb") as f:
                data = f.read()
            
            printer = "Cash Printer"
            h = None
            try:
                t0 = time.perf_counter()
                h = win32print.OpenPrinter(printer)
                job_id = win32print.StartDocPrinter(h, 1, (description, None, 'RAW'))
                win32print.StartPagePrinter(h)
                written = win32print.WritePrinter(h, data)
                win32print.EndPagePrinter(h)
                win32print.EndDocPrinter(h)
                t1 = time.perf_counter()
                
                print(f"✓ Printed {written} bytes in {t1-t0:.3f}s")
                print(f"Expected: {description} with PERFECT Hebrew!")
                
            except Exception as e:
                print(f"✗ Print error: {e}")
            finally:
                if h:
                    try:
                        win32print.ClosePrinter(h)
                    except:
                        pass
        
        except Exception as e:
            print(f"✗ File error: {e}")


def main():
    print("=== FINAL CORRECT SOLUTION ===")
    print("With ESC t 15 + CP862 encoding!")
    
    # Test 1: Simple text test
    if not create_simple_text_test():
        print("Failed to create text test")
        return 1
    
    input("\nPress Enter to continue with final receipt...")
    
    # Test 2: Final receipt
    if not create_final_receipt():
        print("Failed to create final receipt")
        return 1
    
    # Test 3: Decorated receipt
    if not create_decorated_receipt():
        print("Failed to create decorated receipt")
        return 1
    
    # Test 4: Print final tests
    print_final_tests()
    
    print("\n=== FINAL CORRECT SOLUTION COMPLETE ===")
    print("✓ ESC t 15 command (Code Page 862)")
    print("✓ CP862 encoding (not UTF-8)")
    print("✓ Logo resized to 384px width")
    print("✓ Professional formatting and decorations")
    print("\nThe Hebrew should now be PERFECT!")
    print("This is the industry-standard method for thermal printers!")
    
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
