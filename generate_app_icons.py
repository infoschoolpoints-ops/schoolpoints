import os


def _safe_font(size: int):
    try:
        from PIL import ImageFont
        for name in (
            "arial.ttf",
            "Arial.ttf",
            "segoeui.ttf",
            "SegoeUI.ttf",
        ):
            try:
                return ImageFont.truetype(name, size)
            except Exception:
                pass
        try:
            return ImageFont.load_default()
        except Exception:
            return None
    except Exception:
        return None


def _remove_near_white_bg(img, *, threshold: int = 245):
    try:
        img = img.convert('RGBA')
        pix = img.getdata()
        new = []
        for r, g, b, a in pix:
            if a == 0:
                new.append((r, g, b, 0))
                continue
            if r >= threshold and g >= threshold and b >= threshold:
                new.append((r, g, b, 0))
            else:
                new.append((r, g, b, a))
        img.putdata(new)
        return img
    except Exception:
        return img


def _center_crop_square(img):
    w, h = img.size
    s = min(w, h)
    left = int((w - s) / 2)
    top = int((h - s) / 2)
    return img.crop((left, top, left + s, top + s))


def _save_ico(img, out_path: str):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def _convert_source_to_ico(src_path: str, out_path: str) -> bool:
    try:
        from PIL import Image

        img = Image.open(src_path)
        img = img.convert('RGBA')
        img = _remove_near_white_bg(img)
        img = _center_crop_square(img)
        _save_ico(img, out_path)
        return True
    except Exception:
        return False


def _draw_icon(label: str, *, bg: str, fg: str, out_path: str):
    from PIL import Image, ImageDraw

    try:
        if out_path and os.path.exists(out_path):
            return
    except Exception:
        pass

    img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    pad = 18
    r = 42
    d.rounded_rectangle((pad, pad, 256 - pad, 256 - pad), radius=r, fill=bg)

    cx, cy = 128, 116
    s = 70
    pts = [
        (cx, cy - s),
        (cx + 18, cy - 20),
        (cx + s, cy - 20),
        (cx + 30, cy + 10),
        (cx + 42, cy + s),
        (cx, cy + 38),
        (cx - 42, cy + s),
        (cx - 30, cy + 10),
        (cx - s, cy - 20),
        (cx - 18, cy - 20),
    ]
    d.polygon(pts, fill=fg)

    font = _safe_font(72)
    text = str(label)
    try:
        bbox = d.textbbox((0, 0), text, font=font)
        tw = int(bbox[2] - bbox[0])
        th = int(bbox[3] - bbox[1])
    except Exception:
        tw, th = (80, 70)

    tx = int((256 - tw) / 2)
    ty = 168
    d.text((tx + 2, ty + 2), text, fill=(0, 0, 0, 120), font=font)
    d.text((tx, ty), text, fill=fg, font=font)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    icons_dir = os.path.join(base_dir, "icons")
    os.makedirs(icons_dir, exist_ok=True)

    targets = {
        'admin': {
            'out': os.path.join(icons_dir, 'admin.ico'),
            'fallback': lambda: _draw_icon('A', bg="#1f4e79", fg="#f1c40f", out_path=os.path.join(icons_dir, 'admin.ico')),
        },
        'public': {
            'out': os.path.join(icons_dir, 'public.ico'),
            'fallback': lambda: _draw_icon('P', bg="#0b6b3a", fg="#f1c40f", out_path=os.path.join(icons_dir, 'public.ico')),
        },
        'cashier': {
            'out': os.path.join(icons_dir, 'cashier.ico'),
            'fallback': lambda: _draw_icon('C', bg="#8a4b00", fg="#f1c40f", out_path=os.path.join(icons_dir, 'cashier.ico')),
        },
        'installer': {
            'out': os.path.join(icons_dir, 'installer.ico'),
            'fallback': lambda: _draw_icon('SP', bg="#2c3e50", fg="#f1c40f", out_path=os.path.join(icons_dir, 'installer.ico')),
        },
    }

    exts = ('.png', '.jpg', '.jpeg', '.webp', '.bmp')
    for key, info in targets.items():
        out_path = info['out']
        src_path = None
        for ext in exts:
            candidate = os.path.join(icons_dir, f'{key}{ext}')
            if os.path.exists(candidate):
                src_path = candidate
                break

        if src_path:
            _convert_source_to_ico(src_path, out_path)
        else:
            try:
                info['fallback']()
            except Exception:
                pass


if __name__ == "__main__":
    main()
