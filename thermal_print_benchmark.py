import argparse
import os
import sys
import time
from typing import Optional


def _ms(t0: float, t1: float) -> float:
    return (t1 - t0) * 1000.0


def _send_raw_bytes_to_printer(printer_name: str, data: bytes) -> bool:
    printer_name = str(printer_name or '').strip()
    if not printer_name or not data:
        return False
    try:
        import win32print  # type: ignore
    except Exception as e:
        try:
            print(f"[BENCH] RAW print failed: missing win32print (pywin32). error={e}")
            print(f"[BENCH] Python exe: {sys.executable}")
        except Exception:
            pass
        return False

    h = None
    try:
        h = win32print.OpenPrinter(printer_name)
        try:
            win32print.StartDocPrinter(h, 1, ('SchoolPoints-Benchmark', None, 'RAW'))
            win32print.StartPagePrinter(h)
            win32print.WritePrinter(h, data)
            win32print.EndPagePrinter(h)
            win32print.EndDocPrinter(h)
        finally:
            try:
                win32print.ClosePrinter(h)
            except Exception:
                pass
        return True
    except Exception as e:
        try:
            print(f"[BENCH] RAW print failed: {e}")
        except Exception:
            pass
        try:
            if h:
                win32print.ClosePrinter(h)
        except Exception:
            pass
        return False


def _try_load_logo(logo_path: Optional[str]) -> Optional[str]:
    if not logo_path:
        return None
    p = str(logo_path).strip().replace('/', '\\')
    if not p or not os.path.exists(p):
        return None
    return p


def _print_text_raw(printer_name: str) -> bool:
    ESC = b'\x1b'
    GS = b'\x1d'
    INIT = ESC + b'@'
    CENTER = ESC + b'a\x01'
    LEFT = ESC + b'a\x00'
    BOLD_ON = ESC + b'E\x01'
    BOLD_OFF = ESC + b'E\x00'
    CUT = GS + b'V\x42\x00'

    now_s = time.strftime('%Y-%m-%d %H:%M:%S')

    data = INIT
    data += CENTER + BOLD_ON
    data += 'SCHOOLPOINTS\n'.encode('cp862', errors='ignore')
    data += 'THERMAL BENCHMARK\n'.encode('cp862', errors='ignore')
    data += BOLD_OFF
    data += ('-' * 32 + '\n').encode('cp862', errors='ignore')
    data += LEFT
    data += f'Time: {now_s}\n'.encode('cp862', errors='ignore')
    data += 'Text-only RAW (no image)\n'.encode('cp862', errors='ignore')
    data += '\n\n\n'.encode('cp862', errors='ignore')
    data += CUT
    return _send_raw_bytes_to_printer(printer_name, data)


def _print_text_serial(port: str, *, baudrate: int) -> bool:
    port = str(port or '').strip()
    if not port:
        return False
    # Windows: some drivers require the \\.\COMx device path
    try:
        if port.upper().startswith('COM') and port[3:].isdigit():
            port = r'\\.\\' + port
    except Exception:
        pass
    try:
        import serial  # type: ignore
    except Exception as e:
        try:
            print(f"[BENCH] Serial print failed: missing pyserial. error={e}")
        except Exception:
            pass
        return False
    try:
        ser = serial.Serial(port, int(baudrate or 38400), bytesize=8, parity='N', stopbits=1, timeout=2)
        try:
            ser.write(bytes([27, 64]))
            ser.write(b'SCHOOLPOINTS\r\n')
            ser.write(b'THERMAL BENCHMARK\r\n')
            ser.write(b'-------------------------------\r\n')
            ser.write(b'HELLO SERIAL\r\n')
            ser.write(b'\r\n\r\n')
            # Cut (GS V 0)
            ser.write(bytes([29, 86, 66, 0]))
        finally:
            try:
                ser.close()
            except Exception:
                pass
        return True
    except Exception as e:
        try:
            print(f"[BENCH] Serial print failed: {e}")
        except Exception:
            pass
        return False


def _print_image_escpos(printer_name: str, img, *, impl: str, dry_run: bool, port: str = '', baudrate: int = 38400) -> bool:
    if dry_run:
        return True
    port = str(port or '').strip()
    if port and port.upper().startswith('COM'):
        try:
            if port[3:].isdigit():
                port = r'\\.\\' + port
        except Exception:
            pass
        from escpos.printer import Serial  # type: ignore
        p = None
        try:
            p = Serial(port=port, baudrate=int(baudrate or 38400), timeout=2)
            p.image(img, center=False, impl=impl)
            p.text('\n\n\n')
            p.cut()
            try:
                p._raw(b'')
            except Exception:
                pass
            return True
        finally:
            try:
                if p is not None:
                    p.close()
            except Exception:
                pass

    from escpos.printer import Win32Raw
    p = None
    try:
        p = Win32Raw(printer_name)
        p.image(img, center=False, impl=impl)
        p.text('\n\n\n')
        p.cut()
        try:
            p._raw(b'')
        except Exception:
            pass
        return True
    finally:
        try:
            if p is not None:
                p.close()
        except Exception:
            pass


def _make_sample_receipt_data() -> dict:
    return {
        'student_name': 'בדיקה תלמיד',
        'class_name': "ח׳1",
        'items': [
            {'name': 'טוסט', 'price': 12},
            {'name': 'שתיה', 'price': 8},
            {'name': 'חטיף', 'price': 5},
        ],
        'total': 25,
        'balance_before': 100,
        'balance_after': 75,
    }


def main() -> int:
    try:
        print(f"[BENCH] python_exe={sys.executable}")
        print(f"[BENCH] python_version={sys.version.splitlines()[0]}")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument('--printer', required=True, help='Windows printer name')
    ap.add_argument('--port', default='', help='Optional serial port (e.g. COM2). If set, prints via Serial directly.')
    ap.add_argument('--baudrate', type=int, default=38400, help='Serial baudrate (default 38400)')
    ap.add_argument('--logo', default='', help='Optional logo path (BW works best)')
    ap.add_argument('--impl', default='graphics', help='python-escpos image impl: graphics/bitImageRaster/bitImageColumn')
    ap.add_argument('--loops', type=int, default=1, help='How many runs to measure')
    ap.add_argument('--dry-run', action='store_true', help='Generate images and measure, but do not send to printer')
    ap.add_argument('--mode', default='image', choices=['image', 'voucher', 'text'], help='Print mode to benchmark')
    args = ap.parse_args()

    printer = str(args.printer or '').strip()
    port = str(args.port or '').strip()
    baudrate = int(args.baudrate or 38400)
    logo_path = _try_load_logo(args.logo)
    impl = str(args.impl or 'graphics').strip() or 'graphics'
    loops = max(int(args.loops or 1), 1)
    dry_run = bool(args.dry_run)

    if args.mode == 'text':
        t0 = time.perf_counter()
        if dry_run:
            ok = True
        else:
            if port and port.upper().startswith('COM'):
                ok = _print_text_serial(port, baudrate=baudrate)
            else:
                ok = _print_text_raw(printer)
        t1 = time.perf_counter()
        print(f'[BENCH] text_raw total_ms={_ms(t0, t1):.1f} ok={ok}')
        return 0 if ok else 2

    t_import0 = time.perf_counter()
    if args.mode == 'voucher':
        from voucher_image_generator import create_voucher_image
    else:
        from receipt_image_generator import create_receipt_image
    t_import1 = time.perf_counter()

    print(f'[BENCH] imports_ms={_ms(t_import0, t_import1):.1f}')

    best = None
    for i in range(loops):
        if args.mode == 'voucher':
            data = {
                'student_name': 'בדיקה תלמיד',
                'class_name': "ח׳1",
                'item_name': 'טוסט',
                'qty': 1,
                'price': 12,
                'slot_text': '',
                'duration_minutes': 0,
            }
        else:
            data = _make_sample_receipt_data()

        t0 = time.perf_counter()
        if args.mode == 'voucher':
            img = create_voucher_image(data, logo_path)
        else:
            img = create_receipt_image(data, logo_path, closing_message='')
        t1 = time.perf_counter()

        t2 = time.perf_counter()
        ok = _print_image_escpos(printer, img, impl=impl, dry_run=dry_run, port=port, baudrate=baudrate)
        t3 = time.perf_counter()

        ms_img = _ms(t0, t1)
        ms_send = _ms(t2, t3)
        ms_total = _ms(t0, t3)
        print(f'[BENCH] run={i+1}/{loops} mode={args.mode} impl={impl} img_ms={ms_img:.1f} send_ms={ms_send:.1f} total_ms={ms_total:.1f} ok={ok} size={getattr(img, "size", None)}')

        if best is None or ms_total < best:
            best = ms_total

    print(f'[BENCH] best_total_ms={best:.1f} (lower is better)')
    if dry_run:
        print('[BENCH] dry-run enabled: did not send data to printer')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
