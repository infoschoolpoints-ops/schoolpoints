"""Extract the exact bytes between GS * end and first GS /."""
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

# Find GS *
gs_star_pos = legacy.find(b'\x1d\x2a')
x, y = legacy[gs_star_pos+2], legacy[gs_star_pos+3]
gs_star_end = gs_star_pos + 4 + x * y * 8

# Find first GS /
gs_slash_pos = legacy.find(b'\x1d\x2f')

print(f"GS * ends at byte: {gs_star_end}")
print(f"First GS / at byte: {gs_slash_pos}")
print(f"Bytes between: {gs_slash_pos - gs_star_end}")

section = legacy[gs_star_end:gs_slash_pos]
print(f"\n=== EXACT BYTES BETWEEN GS * DATA END AND FIRST GS / ===")
print(f"Length: {len(section)} bytes")
print(f"Hex:\n{section.hex(' ')}")

# Save to file for easy inspection
with open('legacy_middle_section.bin', 'wb') as f:
    f.write(section)
print(f"\nSaved to: legacy_middle_section.bin")
