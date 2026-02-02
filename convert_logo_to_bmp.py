"""Convert logo to BMP format for DownLoad.exe tool."""
from PIL import Image


def convert_to_bmp():
    """Convert logo to BMP format like Hastok.bmp."""
    # Load original logo
    img = Image.open(r"C:\מיצד\SchoolPoints\לוגו שחור לבן לא שקוף.png")
    
    # Convert to grayscale
    img = img.convert('L')
    
    # Resize to reasonable size
    w, h = img.size
    max_size = 200
    if w > max_size or h > max_size:
        scale = min(max_size / w, max_size / h)
        new_w = int(w * scale)
        new_h = int(h * scale)
        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    
    # Save as 1-bit BMP
    img = img.point(lambda p: 0 if p < 128 else 255, mode='1')
    img.save(r'I:\Install\TOOLS\DownloadLogo\nofish_logo.bmp', 'BMP')
    
    print(f"Converted logo to BMP: {img.size}")
    print("Saved to: I:\\Install\\TOOLS\\DownloadLogo\\nofish_logo.bmp")
    
    # Also check Hastok.bmp properties
    try:
        hastok = Image.open(r'I:\Install\TOOLS\DownloadLogo\Hastok.bmp')
        print(f"Hastok.bmp: {hastok.size}, mode: {hastok.mode}")
    except Exception as e:
        print(f"Could not read Hastok.bmp: {e}")


if __name__ == '__main__':
    convert_to_bmp()
