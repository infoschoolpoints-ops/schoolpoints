"""Create a simple text logo programmatically."""
from PIL import Image, ImageDraw, ImageFont


def create_text_logo(text="NOFISH", size=60):
    """Create a simple black text on white background."""
    WIDTH = 352
    HEIGHT = 80
    
    # Create white background
    img = Image.new('RGB', (WIDTH, HEIGHT), 'white')
    draw = ImageDraw.Draw(img)
    
    try:
        # Try to use a simple font
        font = ImageFont.truetype("arial.ttf", size)
    except:
        # Fallback to default font
        font = ImageFont.load_default()
    
    # Get text size
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    
    # Center text
    x = (WIDTH - text_width) // 2
    y = (HEIGHT - text_height) // 2
    
    # Draw black text
    draw.text((x, y), text, fill='black', font=font)
    
    # Save as PNG
    img.save('simple_text_logo.png')
    print(f"Created: simple_text_logo.png")
    print(f"Text: '{text}' at position ({x}, {y})")
    
    return img


def main():
    # Create simple text logo
    img = create_text_logo("NOFISH", 50)
    
    # Also create a test with Hebrew
    try:
        img_heb = create_text_logo("נופית", 50)
        img_heb.save('simple_text_logo_heb.png')
        print("Created: simple_text_logo_heb.png")
    except Exception as e:
        print(f"Hebrew text failed: {e}")
    
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
