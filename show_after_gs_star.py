"""Show what comes after GS * data in legacy file."""
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

gs_pos = legacy.find(b'\x1d\x2a')
x, y = legacy[gs_pos+2], legacy[gs_pos+3]
data_end = gs_pos + 4 + x * y * 8

print(f"GS * data ends at byte {data_end}")
print(f"Total file: {len(legacy)} bytes")
print(f"Bytes after GS * data: {len(legacy) - data_end}")
print(f"\n=== First 100 bytes after GS * data ===")
after = legacy[data_end:data_end+100]
print(f"Hex: {after.hex(' ')}")
print(f"\n=== Decoded (printable chars) ===")
for i, b in enumerate(after[:50]):
    if 32 <= b < 127:
        print(f"{i}: 0x{b:02x} = '{chr(b)}'")
    else:
        print(f"{i}: 0x{b:02x}")
