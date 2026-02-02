import argparse
import re
import sys


def _parse_hex_string(s: str) -> bytes:
    # Accept formats like: "1B 40", "1b40", "1B,40", multi-line
    cleaned = re.sub(r"[^0-9A-Fa-f]", " ", str(s or ""))
    parts = [p for p in cleaned.split() if p]
    if not parts:
        return b""
    # If user provided a single long hex blob without spaces, split into pairs
    if len(parts) == 1 and len(parts[0]) > 2 and len(parts[0]) % 2 == 0:
        blob = parts[0]
        parts = [blob[i : i + 2] for i in range(0, len(blob), 2)]
    return bytes(int(p, 16) for p in parts)


def _read_text_file_best_effort(path: str) -> str:
    # Try a few common encodings used by vendor tools
    raw = None
    with open(path, 'rb') as f:
        raw = f.read()
    for enc in ('utf-8-sig', 'utf-16', 'cp1255', 'cp1252', 'latin-1'):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    # Last resort: replace errors
    return raw.decode('utf-8', errors='replace')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--printer", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--hex", help='Hex bytes, e.g. "1B 74 1F"')
    g.add_argument("--hex-file", help='Path to a text file containing hex bytes (spaces/newlines allowed).')
    ap.add_argument("--datatype", default="RAW", choices=["RAW", "TEXT"])
    ap.add_argument("--suffix", default="", help="Optional extra bytes as hex appended after --hex")
    args = ap.parse_args()

    try:
        import win32print  # type: ignore
    except Exception as e:
        print("ERROR: win32print not available:", repr(e))
        return 2

    if args.hex_file:
        try:
            txt = _read_text_file_best_effort(args.hex_file)
        except Exception as e:
            print('ERROR: failed to read hex file:', args.hex_file)
            print(repr(e))
            return 2
        data = _parse_hex_string(txt)
    else:
        data = _parse_hex_string(args.hex or '')
    if args.suffix:
        data += _parse_hex_string(args.suffix)

    if not data:
        print("ERROR: no data parsed from hex")
        return 2

    h = None
    try:
        h = win32print.OpenPrinter(args.printer)
        win32print.StartDocPrinter(h, 1, ("PySendHex", None, args.datatype))
        win32print.StartPagePrinter(h)
        n = win32print.WritePrinter(h, data)
        win32print.EndPagePrinter(h)
        win32print.EndDocPrinter(h)
        print("OK: wrote", n, "bytes")
        return 0
    except Exception as e:
        print("ERROR: send failed:", repr(e))
        return 2
    finally:
        if h is not None:
            try:
                win32print.ClosePrinter(h)
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
