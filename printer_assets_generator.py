"""
Generate printer assets (logo, decorations) once and save as ESC/POS binary files.
Run this once when setting up the printer or when changing the logo.
"""
import os
from PIL import Image, ImageDraw
import pickle


def image_to_escpos(img, width=384):
    """Convert PIL image to ESC/POS raster format."""
    # Resize to printer width
    aspect = img.height / img.width
    new_height = int(width * aspect)
    img = img.resize((width, new_height), Image.Resampling.LANCZOS)
    
    # Convert to black and white
    img = img.convert('1')
    
    # ESC/POS raster image command
    data = bytearray()
    
    # GS v 0: Print raster bit image
    data.extend(b'\x1D\x76\x30\x00')
    
    # Width in bytes (384 pixels = 48 bytes)
    width_bytes = width // 8
    data.extend(width_bytes.to_bytes(2, 'little'))
    
    # Height in pixels
    data.extend(new_height.to_bytes(2, 'little'))
    
    # Image data
    pixels = img.load()
    for y in range(new_height):
        for x in range(0, width, 8):
            byte = 0
            for bit in range(8):
                if x + bit < width:
                    if pixels[x + bit, y] == 0:  # Black pixel
                        byte |= (1 << (7 - bit))
            data.append(byte)
    
    return bytes(data)


def create_star_decoration(width=384, height=30):
    """Create star decoration."""
    img = Image.new('1', (width, height), 1)
    draw = ImageDraw.Draw(img)
    
    star_text = "★ " * 20
    try:
        draw.text((10, 5), star_text, fill=0)
    except:
        # Fallback if font not available
        for i in range(0, width, 30):
            draw.text((i, 5), "*", fill=0)
    
    return img


def create_dots_decoration(width=384, height=20):
    """Create dotted line decoration."""
    img = Image.new('1', (width, height), 1)
    draw = ImageDraw.Draw(img)
    
    for x in range(0, width, 8):
        draw.ellipse([x, height//2-2, x+4, height//2+2], fill=0)
    
    return img


def create_wave_decoration(width=384, height=25):
    """Create wave decoration."""
    img = Image.new('1', (width, height), 1)
    draw = ImageDraw.Draw(img)
    
    import math
    points = []
    for x in range(width):
        y = int(height/2 + math.sin(x * 0.1) * height/3)
        points.append((x, y))
    
    for i in range(len(points)-1):
        draw.line([points[i], points[i+1]], fill=0, width=2)
    
    return img


def create_zigzag_decoration(width=384, height=25):
    """Create zigzag decoration."""
    img = Image.new('1', (width, height), 1)
    draw = ImageDraw.Draw(img)
    
    points = []
    for x in range(0, width, 20):
        y = 5 if (x // 20) % 2 == 0 else height - 5
        points.append((x, y))
    
    for i in range(len(points)-1):
        draw.line([points[i], points[i+1]], fill=0, width=2)
    
    return img


def generate_all_assets(logo_path=None, output_dir="printer_assets"):
    """Generate all printer assets and save them."""
    os.makedirs(output_dir, exist_ok=True)
    
    assets = {}
    
    # Generate decorations
    print("Generating decorations...")
    
    decorations = {
        'stars': create_star_decoration(),
        'dots': create_dots_decoration(),
        'wave': create_wave_decoration(),
        'zigzag': create_zigzag_decoration()
    }
    
    for name, img in decorations.items():
        print(f"  Converting {name}...")
        escpos_data = image_to_escpos(img)
        assets[name] = escpos_data
        
        # Save as binary file
        with open(os.path.join(output_dir, f"{name}.bin"), 'wb') as f:
            f.write(escpos_data)
        print(f"  ✓ Saved {name}.bin ({len(escpos_data)} bytes)")
    
    # Generate logo if provided
    if logo_path and os.path.exists(logo_path):
        print(f"\nGenerating logo from {logo_path}...")
        try:
            logo_img = Image.open(logo_path)
            escpos_data = image_to_escpos(logo_img)
            assets['logo'] = escpos_data
            
            with open(os.path.join(output_dir, "logo.bin"), 'wb') as f:
                f.write(escpos_data)
            print(f"  ✓ Saved logo.bin ({len(escpos_data)} bytes)")
        except Exception as e:
            print(f"  ✗ Error: {e}")
    
    # Save all assets in one pickle file for quick loading
    with open(os.path.join(output_dir, "all_assets.pkl"), 'wb') as f:
        pickle.dump(assets, f)
    print(f"\n✓ All assets saved to {output_dir}/")
    print(f"  Total: {len(assets)} assets")
    
    return assets


if __name__ == '__main__':
    import sys
    
    logo_path = None
    if len(sys.argv) > 1:
        logo_path = sys.argv[1]
    else:
        # Default logo path
        logo_path = r"Z:\לוגו שחור לבן לא שקוף.png"
    
    print("=" * 50)
    print("Printer Assets Generator")
    print("=" * 50)
    print()
    
    assets = generate_all_assets(logo_path)
    
    print()
    print("=" * 50)
    print("Done! Assets are ready to use.")
    print("=" * 50)
    print()
    print("To use in your application:")
    print("  1. Load assets once at startup")
    print("  2. Reuse them for every print")
    print("  3. Regenerate only when logo changes")
