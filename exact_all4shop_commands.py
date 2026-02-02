"""Use exact ALL4SHOP commands for Hebrew text."""
import os
import time
import win32print


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


def extract_text_commands():
    """Extract exact text commands from ALL4SHOP."""
    print("=== Extracting Exact Text Commands ===")
    
    legacy_path = r"C:\Users\עמדת קופה\Documents\Install\TOOLS\Printer Test-eng0816\חשבונית עברית.txt"
    legacy = parse_hex_file(legacy_path)
    
    # Find the exact text commands
    text_commands = []
    
    # Look for "חנות רות שלי" pattern
    target_pattern = [0x89, 0x8c, 0x99, 0x20, 0x9a, 0x85, 0x90, 0x87, 0x84]  # "ילש תונחה"
    
    for i in range(len(legacy) - len(target_pattern)):
        if legacy[i:i+len(target_pattern)] == bytes(target_pattern):
            # Found the pattern, extract the command sequence
            start = i - 10  # Look for command start
            if start < 0:
                start = 0
            
            end = i + len(target_pattern) + 10  # Some context after
            if end > len(legacy):
                end = len(legacy)
            
            command_seq = legacy[start:end]
            text_commands.append((start, command_seq))
    
    print(f"Found {len(text_commands)} text command sequences")
    
    for i, (pos, seq) in enumerate(text_commands[:3]):  # Show first 3
        print(f"\nCommand {i+1} at position {pos}:")
        print(f"Hex: {' '.join(f'{b:02x}' for b in seq)}")
        
        # Find the Hebrew part
        hebrew_start = -1
        hebrew_end = -1
        for j, b in enumerate(seq):
            if 0x80 <= b <= 0x9A:  # Hebrew byte
                if hebrew_start == -1:
                    hebrew_start = j
                hebrew_end = j + 1
        
        if hebrew_start != -1:
            hebrew_bytes = seq[hebrew_start:hebrew_end]
            print(f"Hebrew: {' '.join(f'{b:02x}' for b in hebrew_bytes)}")
    
    return text_commands


def create_exact_text_test():
    """Create text using exact ALL4SHOP commands."""
    print("\n=== Creating Exact Text Test ===")
    
    try:
        # Extract commands
        commands = extract_text_commands()
        
        if not commands:
            print("No text commands found")
            return False
        
        # Use the first command as template
        pos, template = commands[0]
        
        # Create our own text using the same command structure
        # Template: 1B 21 08 1B 21 30 (formatting) + Hebrew + 0A (newline)
        
        # Our text "חנות רות שלי" in ALL4SHOP format
        our_hebrew = bytes([0x89, 0x8c, 0x99, 0x20, 0x9a, 0x85, 0x90, 0x87, 0x84])  # "ילש תונחה"
        
        # Build the command
        test_command = bytearray()
        test_command.extend(b'\x1B\x40')  # Initialize
        test_command.extend(b'\x1B\x21\x08')  # Bold
        test_command.extend(b'\x1B\x21\x30')  # Large
        test_command.extend(b'\x20\x20\x20\x20\x20\x20')  # Spacing
        test_command.extend(our_hebrew)  # Our Hebrew text
        test_command.extend(b'\x20\x20\x20\x20\x20\x20')  # Spacing
        test_command.extend(b'\x0A')  # Newline
        test_command.extend(b'\x1B\x21\x00')  # Normal text
        test_command.extend(b'\x1B\x21\x08')  # Bold
        test_command.extend(b'\x1B\x21\x30')  # Large
        test_command.extend(b'\x20\x20\x20\x20\x20\x20\x20\x20')  # Spacing
        test_command.extend(bytes([0x9a, 0x89, 0x94, 0x85, 0x90]))  # "תיפונ"
        test_command.extend(b'\x20\x20\x20\x20\x20\x20\x20\x20')  # Spacing
        test_command.extend(b'\x0A\x0A\x0A')  # Newlines
        test_command.extend(b'\x1D\x56\x31')  # Cut
        
        # Save to file
        with open("exact_text_test.bin", "wb") as f:
            f.write(test_command)
        
        print("✓ Exact text test created: exact_text_test.bin")
        print(f"Command: {' '.join(f'{b:02x}' for b in test_command)}")
        
        return True
        
    except Exception as e:
        print(f"✗ Error creating exact text test: {e}")
        return False


def create_simple_hebrew_test():
    """Create simple Hebrew test with minimal commands."""
    print("\n=== Creating Simple Hebrew Test ===")
    
    try:
        # Try the simplest possible Hebrew command
        simple_command = bytearray()
        simple_command.extend(b'\x1B\x40')  # Initialize
        
        # Try without formatting first
        simple_command.extend(bytes([0x89, 0x8c, 0x99]))  # "ילש"
        simple_command.extend(b'\x0A')  # Newline
        
        simple_command.extend(bytes([0x9a, 0x85, 0x90]))  # "תונח"
        simple_command.extend(b'\x0A')  # Newline
        
        simple_command.extend(bytes([0x87, 0x84]))  # "חה"
        simple_command.extend(b'\x0A\x0A\x0A')  # Newlines
        simple_command.extend(b'\x1D\x56\x31')  # Cut
        
        with open("simple_hebrew_test.bin", "wb") as f:
            f.write(simple_command)
        
        print("✓ Simple Hebrew test created: simple_hebrew_test.bin")
        print(f"Command: {' '.join(f'{b:02x}' for b in simple_command)}")
        
        return True
        
    except Exception as e:
        print(f"✗ Error creating simple Hebrew test: {e}")
        return False


def test_logo_with_exact_commands():
    """Test logo with exact command structure."""
    print("\n=== Testing Logo with Exact Commands ===")
    
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
        
        # Use exact initialization from ALL4SHOP
        printer._raw(b'\x1B\x40')
        
        # Add logo
        printer.set(align='center')
        printer.image(img_bw)
        
        # Add exact Hebrew text
        printer._raw(b'\x0A')  # Newline
        printer._raw(b'\x1B\x21\x08')  # Bold
        printer._raw(b'\x1B\x21\x30')  # Large
        printer._raw(b'\x20\x20\x20\x20\x20\x20')  # Spacing
        printer._raw(bytes([0x89, 0x8c, 0x99, 0x20, 0x9a, 0x85, 0x90, 0x87, 0x84]))  # "ילש תונחה"
        printer._raw(b'\x20\x20\x20\x20\x20\x20')  # Spacing
        printer._raw(b'\x0A')  # Newline
        printer._raw(b'\x1B\x21\x00')  # Normal
        printer._raw(b'\x1B\x21\x08')  # Bold
        printer._raw(b'\x1B\x21\x30')  # Large
        printer._raw(b'\x20\x20\x20\x20\x20\x20\x20\x20')  # Spacing
        printer._raw(bytes([0x9a, 0x89, 0x94, 0x85, 0x90]))  # "תיפונ"
        printer._raw(b'\x20\x20\x20\x20\x20\x20\x20\x20')  # Spacing
        printer._raw(b'\x0A\x0A\x0A')  # Newlines
        printer._raw(b'\x1D\x56\x31')  # Cut
        
        # Save
        with open("logo_exact_commands.bin", "wb") as f:
            f.write(printer.output)
        
        print("✓ Logo with exact commands created: logo_exact_commands.bin")
        
        return True
        
    except Exception as e:
        print(f"✗ Error creating logo with exact commands: {e}")
        return False


def print_exact_tests():
    """Print all exact command tests."""
    print("\n=== Printing Exact Command Tests ===")
    
    files_to_test = [
        ("simple_hebrew_test.bin", "Simple Hebrew test"),
        ("exact_text_test.bin", "Exact text test"),
        ("logo_exact_commands.bin", "Logo with exact commands")
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
                print(f"Expected: {description} with EXACT ALL4SHOP commands!")
                
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
    print("=== EXACT ALL4SHOP COMMANDS TEST ===")
    print("Using the exact same commands as the working ALL4SHOP!")
    
    # Create tests
    if not create_simple_hebrew_test():
        print("Failed to create simple Hebrew test")
        return 1
    
    if not create_exact_text_test():
        print("Failed to create exact text test")
        return 1
    
    if not test_logo_with_exact_commands():
        print("Failed to create logo with exact commands")
        return 1
    
    # Print tests
    print_exact_tests()
    
    print("\n=== EXACT COMMANDS TEST COMPLETE ===")
    print("This uses the exact same command structure as ALL4SHOP!")
    print("If this works, we know the exact format to use!")
    
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
