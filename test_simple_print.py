"""Test simple thermal printing to diagnose the issue."""
import win32print

def test_print_1():
    """Test 1: Absolute minimum - just text"""
    print("\n=== Test 1: Minimum (no ESC commands) ===")
    
    data = b"Hello World\n"
    data += b"Test 123\n"
    data += b"\n\n\n\n"
    
    h = win32print.OpenPrinter("Cash Printer")
    win32print.StartDocPrinter(h, 1, ("Test1", None, 'RAW'))
    win32print.StartPagePrinter(h)
    win32print.WritePrinter(h, data)
    win32print.EndPagePrinter(h)
    win32print.EndDocPrinter(h)
    win32print.ClosePrinter(h)
    print("✓ Sent")

def test_print_2():
    """Test 2: With INIT and CUT"""
    print("\n=== Test 2: With INIT and CUT ===")
    
    ESC = b'\x1b'
    GS = b'\x1d'
    
    data = ESC + b'@'  # INIT
    data += b"Hello World\n"
    data += b"Test 123\n"
    data += b"\n\n\n"
    data += GS + b'V\x31'  # CUT
    
    h = win32print.OpenPrinter("Cash Printer")
    win32print.StartDocPrinter(h, 1, ("Test2", None, 'RAW'))
    win32print.StartPagePrinter(h)
    win32print.WritePrinter(h, data)
    win32print.EndPagePrinter(h)
    win32print.EndDocPrinter(h)
    win32print.ClosePrinter(h)
    print("✓ Sent")

def test_print_3():
    """Test 3: Hebrew without reversal"""
    print("\n=== Test 3: Hebrew (no reversal) ===")
    
    ESC = b'\x1b'
    GS = b'\x1d'
    
    data = ESC + b'@'  # INIT
    data += ESC + b't\x0F'  # CP862
    data += "קבלה\n".encode('cp862')
    data += "תלמיד: דוד כהן\n".encode('cp862')
    data += b"\n\n\n"
    data += GS + b'V\x31'  # CUT
    
    h = win32print.OpenPrinter("Cash Printer")
    win32print.StartDocPrinter(h, 1, ("Test3", None, 'RAW'))
    win32print.StartPagePrinter(h)
    win32print.WritePrinter(h, data)
    win32print.EndPagePrinter(h)
    win32print.EndDocPrinter(h)
    win32print.ClosePrinter(h)
    print("✓ Sent")

def test_print_4():
    """Test 4: Hebrew WITH reversal"""
    print("\n=== Test 4: Hebrew (with reversal) ===")
    
    ESC = b'\x1b'
    GS = b'\x1d'
    
    data = ESC + b'@'  # INIT
    data += ESC + b't\x0F'  # CP862
    data += "הלבק\n".encode('cp862')  # קבלה reversed
    data += "ןהכ דוד :דימלת\n".encode('cp862')  # תלמיד: דוד כהן reversed
    data += b"\n\n\n"
    data += GS + b'V\x31'  # CUT
    
    h = win32print.OpenPrinter("Cash Printer")
    win32print.StartDocPrinter(h, 1, ("Test4", None, 'RAW'))
    win32print.StartPagePrinter(h)
    win32print.WritePrinter(h, data)
    win32print.EndPagePrinter(h)
    win32print.EndDocPrinter(h)
    win32print.ClosePrinter(h)
    print("✓ Sent")

def test_print_5():
    """Test 5: With BOLD"""
    print("\n=== Test 5: With BOLD ===")
    
    ESC = b'\x1b'
    GS = b'\x1d'
    
    data = ESC + b'@'  # INIT
    data += ESC + b't\x0F'  # CP862
    data += ESC + b'E\x01'  # BOLD ON
    data += "הלבק\n".encode('cp862')
    data += ESC + b'E\x00'  # BOLD OFF
    data += "ןהכ דוד :דימלת\n".encode('cp862')
    data += b"\n\n\n"
    data += GS + b'V\x31'  # CUT
    
    h = win32print.OpenPrinter("Cash Printer")
    win32print.StartDocPrinter(h, 1, ("Test5", None, 'RAW'))
    win32print.StartPagePrinter(h)
    win32print.WritePrinter(h, data)
    win32print.EndPagePrinter(h)
    win32print.EndDocPrinter(h)
    win32print.ClosePrinter(h)
    print("✓ Sent")

if __name__ == '__main__':
    print("=" * 60)
    print("Thermal Printer Test Suite")
    print("=" * 60)
    print("\nThis will print 5 test receipts.")
    print("Check each one to see which works correctly.")
    print()
    
    input("Press Enter to start Test 1 (minimum)...")
    try:
        test_print_1()
    except Exception as e:
        print(f"✗ Error: {e}")
    
    input("\nPress Enter for Test 2 (INIT+CUT)...")
    try:
        test_print_2()
    except Exception as e:
        print(f"✗ Error: {e}")
    
    input("\nPress Enter for Test 3 (Hebrew no reversal)...")
    try:
        test_print_3()
    except Exception as e:
        print(f"✗ Error: {e}")
    
    input("\nPress Enter for Test 4 (Hebrew with reversal)...")
    try:
        test_print_4()
    except Exception as e:
        print(f"✗ Error: {e}")
    
    input("\nPress Enter for Test 5 (with BOLD)...")
    try:
        test_print_5()
    except Exception as e:
        print(f"✗ Error: {e}")
    
    print("\n" + "=" * 60)
    print("Tests complete!")
    print("=" * 60)
    print("\nWhich test printed correctly?")
    print("Tell me the number and I'll fix the code accordingly.")
