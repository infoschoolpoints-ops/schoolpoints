"""Find all GS / commands in legacy file."""
import sys

def parse_hex_file(path):
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

legacy_path = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\עמדת קופה\Documents\Install\TOOLS\Printer Test-eng0816\חשבונית עברית.txt"
legacy = parse_hex_file(legacy_path)

# Find all GS / (1D 2F)
print("=== Searching for GS / (1D 2F) ===")
pos = 0
found = False
while True:
    pos = legacy.find(b'\x1d\x2f', pos)
    if pos < 0:
        break
    found = True
    m = legacy[pos+2] if pos+2 < len(legacy) else 0
    print(f"Found at byte {pos}: 1D 2F {m:02X} (m={m})")
    pos += 1

if not found:
    print("NOT FOUND!")

# Also search for FS p (1C 70) - print NV bit image
print("\n=== Searching for FS p (1C 70) - NV bit image ===")
pos = 0
found = False
while True:
    pos = legacy.find(b'\x1c\x70', pos)
    if pos < 0:
        break
    found = True
    print(f"Found at byte {pos}: context = {legacy[max(0,pos-2):pos+6].hex(' ')}")
    pos += 1
if not found:
    print("NOT FOUND!")

# Show all ESC/GS commands
print("\n=== All control sequences (1B/1D/1C xx) ===")
i = 0
while i < len(legacy):
    if legacy[i] in (0x1B, 0x1D, 0x1C):
        cmd = legacy[i:i+4]
        print(f"Byte {i}: {cmd.hex(' ')}")
    i += 1
