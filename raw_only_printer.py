"""Raw printer commands only - no ESCPOS library."""
import win32print
import time


def test_1_english():
    """Test 1: Simple English."""
    print("=== Test 1: English ===")
    
    data = bytearray()
    data.extend(b'\x1B\x40')  # Init
    data.extend(b'Hello World\n')
    data.extend(b'Test 123\n')
    data.extend(b'\n\n\n')
    data.extend(b'\x1D\x56\x31')  # Cut
    
    print_data(data, "Test1English")


def test_2_hebrew_simple():
    """Test 2: Simple Hebrew with CP862."""
    print("\n=== Test 2: Simple Hebrew ===")
    
    data = bytearray()
    data.extend(b'\x1B\x40')  # Init
    data.extend(b'\x1B\x74\x0F')  # CP862
    
    # Simple Hebrew words
    data.extend("שלום\n".encode('cp862'))
    data.extend("עולם\n".encode('cp862'))
    
    data.extend(b'\n\n\n')
    data.extend(b'\x1D\x56\x31')  # Cut
    
    print_data(data, "Test2Hebrew")


def test_3_hebrew_sentence():
    """Test 3: Hebrew sentence."""
    print("\n=== Test 3: Hebrew Sentence ===")
    
    data = bytearray()
    data.extend(b'\x1B\x40')  # Init
    data.extend(b'\x1B\x74\x0F')  # CP862
    
    # Full sentence
    data.extend("חנות רות שלי\n".encode('cp862'))
    
    data.extend(b'\n\n\n')
    data.extend(b'\x1D\x56\x31')  # Cut
    
    print_data(data, "Test3Sentence")


def test_4_formatted_hebrew():
    """Test 4: Formatted Hebrew."""
    print("\n=== Test 4: Formatted Hebrew ===")
    
    data = bytearray()
    data.extend(b'\x1B\x40')  # Init
    data.extend(b'\x1B\x74\x0F')  # CP862
    
    # Center and large
    data.extend(b'\x1B\x61\x01')  # Center
    data.extend(b'\x1D\x21\x11')  # Large
    
    data.extend("חנות רות שלי\n".encode('cp862'))
    
    # Back to normal
    data.extend(b'\x1D\x21\x00')
    data.extend(b'\x1B\x61\x00')  # Left
    
    data.extend(b'\n\n\n')
    data.extend(b'\x1D\x56\x31')  # Cut
    
    print_data(data, "Test4Formatted")


def test_5_compare_all4shop():
    """Test 5: Print original ALL4SHOP."""
    print("\n=== Test 5: Original ALL4SHOP ===")
    
    try:
        legacy_path = r"C:\Users\עמדת קופה\Documents\Install\TOOLS\Printer Test-eng0816\חשבונית עברית.txt"
        data = bytearray()
        with open(legacy_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                for tok in line.strip().split():
                    if len(tok) == 2:
                        try:
                            data.append(int(tok, 16))
                        except ValueError:
                            pass
        
        print_data(data, "Test5ALL4SHOP")
        
    except Exception as e:
        print(f"✗ Error loading ALL4SHOP: {e}")


def print_data(data, job_name):
    """Print data to printer."""
    printer = "Cash Printer"
    h = None
    try:
        t0 = time.perf_counter()
        h = win32print.OpenPrinter(printer)
        job_id = win32print.StartDocPrinter(h, 1, (job_name, None, 'RAW'))
        win32print.StartPagePrinter(h)
        written = win32print.WritePrinter(h, bytes(data))
        win32print.EndPagePrinter(h)
        win32print.EndDocPrinter(h)
        t1 = time.perf_counter()
        
        print(f"✓ Printed {written} bytes in {t1-t0:.3f}s")
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


def main():
    print("=== RAW PRINTER TESTS ===")
    print("No ESCPOS library - pure RAW commands only!")
    
    # Test 1
    test_1_english()
    input("\nCheck printout. Press Enter for Test 2...")
    
    # Test 2
    test_2_hebrew_simple()
    input("\nCheck printout. Press Enter for Test 3...")
    
    # Test 3
    test_3_hebrew_sentence()
    input("\nCheck printout. Press Enter for Test 4...")
    
    # Test 4
    test_4_formatted_hebrew()
    input("\nCheck printout. Press Enter for Test 5...")
    
    # Test 5
    test_5_compare_all4shop()
    
    print("\n=== ALL TESTS COMPLETE ===")
    print("Compare the printouts:")
    print("1. English - should work")
    print("2. Simple Hebrew - check direction")
    print("3. Hebrew sentence - check direction")
    print("4. Formatted Hebrew - check direction")
    print("5. ALL4SHOP - should be perfect")
    print("\nTell me EXACTLY what you see on each printout!")
    
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
