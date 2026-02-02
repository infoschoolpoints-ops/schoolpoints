import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import os
import json
import shutil
import time
import re
import socket
import threading
import ctypes
import urllib.request
import urllib.parse
from ctypes import wintypes
from datetime import datetime

from PIL import Image, ImageTk
from PIL import ImageDraw, ImageFont
from PIL import ImageOps

from database import Database
from jewish_calendar import hebrew_date_from_gregorian_str
from license_manager import LicenseManager
from customer_display import CustomerDisplay
from receipt_image_generator import create_receipt_image
from thermal_printer import ThermalPrinterCached, HebrewDate


UNIVERSAL_MASTER_CODE = "05276247440527624744"

APP_VERSION = "1.4.3"


def _enable_windows_dpi_awareness():
    try:
        # Windows 8.1+ (per-monitor DPI aware)
        shcore = ctypes.WinDLL('shcore', use_last_error=True)
        try:
            shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
            return
        except Exception:
            pass
    except Exception:
        pass

    try:
        # Windows Vista+ (system DPI aware)
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass
    except Exception:
        pass


def _apply_tk_scaling(root: tk.Tk, *, compact: bool = False) -> None:
    try:
        if compact:
            root.tk.call('tk', 'scaling', 1.0)
            return
        try:
            fpix = float(root.winfo_fpixels('1i') or 0.0)
        except Exception:
            fpix = 0.0
        if fpix and fpix > 0:
            scale = fpix / 72.0
        else:
            scale = 96.0 / 72.0
        if scale < 1.0:
            scale = 1.0
        if scale > 4.0:
            scale = 4.0
        root.tk.call('tk', 'scaling', float(scale))
    except Exception:
        pass


# Best-effort DPI awareness as early as possible (before Tk exists)
try:
    _enable_windows_dpi_awareness()
except Exception:
    pass


class CashierStation:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("🧾 עמדת קופה")

        self._display_mode_before = None
        self._resolution_forced = False

        self._compact_ui = False

        self._tile_by_pid = {}

        # Stable station identifier (used for licensing and cross-station holds)
        try:
            self.station_id = str(os.environ.get('COMPUTERNAME') or os.environ.get('HOSTNAME') or socket.gethostname() or '').strip()
        except Exception:
            self.station_id = ''
        if not self.station_id:
            self.station_id = 'cashier'

        try:
            self._license_blocked = False
            self._license_block_message = ''
        except Exception:
            pass

        # Ensure shared folder is configured before DB is opened (first-run wizard)
        if not self.ensure_shared_folder_config():
            try:
                self.root.after(100, self.root.destroy)
            except Exception:
                pass
            return

        # הפעלת סנכרון רקע אוטומטי (Hybrid/Cloud בלבד)
        self._sync_agent_thread = None
        self._sync_agent_started = False
        try:
            self._maybe_start_sync_agent()
        except Exception:
            pass

        # License check (counts this cashier as another station)
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            self.license_manager = LicenseManager(base_dir, "cashier")
            if not self.license_manager.can_run_cashier_station():
                try:
                    if self.license_manager.over_limit:
                        msg = self.license_manager.get_over_limit_message()
                    elif getattr(self.license_manager, 'is_monthly', False) and (not bool(getattr(self.license_manager, 'allow_cashier', True))):
                        exp = str(getattr(self.license_manager, 'expiry_date', '') or '').strip()
                        suffix = f" (עד {exp})" if exp else ""
                        msg = (
                            "הרישיון החודשי פעיל" + suffix + ", אך אינו כולל עמדת קופה.\n\n"
                            "להפעלת עמדת קופה נדרש רישיון חודשי מסוג 'כולל קופה' (באישור מיוחד).\n"
                            "יש להפעיל רישיון בעמדת הניהול (⚙ הגדרות מערכת → רישום מערכת)."
                        )
                    elif getattr(self.license_manager, 'is_term', False) and (not bool(getattr(self.license_manager, 'allow_cashier', True))):
                        exp = str(getattr(self.license_manager, 'expiry_date', '') or '').strip()
                        suffix = f" (עד {exp})" if exp else ""
                        msg = (
                            "הרישיון פעיל" + suffix + ", אך אינו כולל עמדת קופה.\n\n"
                            "להפעלת עמדת קופה נדרש רישיון הכולל עמדת קופה.\n"
                            "יש להפעיל רישיון בעמדת הניהול (⚙ הגדרות מערכת → רישום מערכת)."
                        )
                    elif getattr(self.license_manager, 'is_monthly', False) and bool(getattr(self.license_manager, 'monthly_expired', False)):
                        exp = str(getattr(self.license_manager, 'expiry_date', '') or '').strip()
                        suffix = f" (עד {exp})" if exp else ""
                        msg = (
                            "הרישיון החודשי פג תוקף" + suffix + ".\n"
                            "לא ניתן להפעיל את עמדת הקופה ללא רישיון בתוקף.\n\n"
                            "יש להפעיל רישיון בעמדת הניהול (⚙ הגדרות מערכת → רישום מערכת)."
                        )
                    elif getattr(self.license_manager, 'is_term', False) and bool(getattr(self.license_manager, 'term_expired', False)):
                        exp = str(getattr(self.license_manager, 'expiry_date', '') or '').strip()
                        suffix = f" (עד {exp})" if exp else ""
                        msg = (
                            "הרישיון פג תוקף" + suffix + ".\n"
                            "עמדת הקופה תיפתח במצב צפייה בלבד – ללא אפשרות לבצע פעולות.\n\n"
                            "יש להפעיל רישיון בעמדת הניהול (⚙ הגדרות מערכת → רישום מערכת)."
                        )
                    elif self.license_manager.trial_expired and not self.license_manager.is_licensed:
                        msg = (
                            "תקופת הניסיון הסתיימה.\n"
                            "לא ניתן להפעיל את עמדת הקופה ללא רישיון פעיל.\n\n"
                            "יש להפעיל רישיון בעמדת הניהול (⚙ הגדרות מערכת → רישום מערכת)."
                        )
                    else:
                        msg = (
                            "הרישיון אינו מאפשר הפעלה של עמדת קופה במחשב זה.\n\n"
                            "יש לבדוק את הרישיון בעמדת הניהול."
                        )
                    try:
                        self._license_blocked = True
                        self._license_block_message = str(msg or '').strip()
                    except Exception:
                        pass
                    try:
                        messagebox.showwarning("עמדת קופה לא מורשית", msg)
                    except Exception:
                        pass
                except Exception:
                    pass
        except Exception:
            # If license subsystem fails unexpectedly, do not block cashier startup
            pass

        self.db = Database()

    def _maybe_start_sync_agent(self) -> None:
        try:
            if bool(getattr(self, '_sync_agent_started', False)):
                return
        except Exception:
            pass

        try:
            cfg = self._load_app_config() or {}
        except Exception:
            cfg = {}

        try:
            mode = str(cfg.get('deployment_mode') or 'local').strip().lower()
        except Exception:
            mode = 'local'

        if mode not in ('hybrid', 'cloud'):
            return

        try:
            tenant_id = str(cfg.get('sync_tenant_id') or '').strip()
        except Exception:
            tenant_id = ''
        try:
            api_key = str(cfg.get('sync_api_key') or '').strip()
        except Exception:
            api_key = ''
        try:
            push_url = str(cfg.get('sync_push_url') or '').strip()
        except Exception:
            push_url = ''

        if not (tenant_id and api_key and push_url):
            return

        try:
            interval_sec = int(cfg.get('sync_interval_sec') or 60)
        except Exception:
            interval_sec = 60
        interval_sec = max(10, int(interval_sec or 60))

        def _run_sync_loop():
            try:
                import sync_agent
                sync_agent.main_loop(interval_sec=interval_sec)
            except Exception:
                pass

        try:
            self._sync_agent_started = True
        except Exception:
            pass
        try:
            t = threading.Thread(target=_run_sync_loop, daemon=True)
            self._sync_agent_thread = t
            t.start()
        except Exception:
            try:
                self._sync_agent_started = False
            except Exception:
                pass
            return

        # Initialize customer display (VeriFone MX980L or compatible) - lazy/async connect
        try:
            self._customer_display_config = self._load_customer_display_config()
        except Exception:
            self._customer_display_config = {'enabled': False, 'com_port': 'COM1', 'baud_rate': 9600}
        try:
            self._customer_display_enabled = bool(self._customer_display_config.get('enabled', False))
        except Exception:
            self._customer_display_enabled = False
        self._customer_display_connecting = False
        self.customer_display = None
        if self._customer_display_enabled:
            try:
                self.root.after(200, lambda: self._ensure_customer_display(show_welcome=True))
            except Exception:
                pass

        # Must exist before _setup_ui() because product grid rendering uses it
        self._locked = True

        self._current_student = None
        self._operator = None  # teacher/responsible who unlocked
        self._operator_card = ''

        # Debounce for card readers that deliver the same scan twice (e.g. Entry + bind, or driver quirks)
        self._last_scanned_card = ''
        self._last_scanned_ts = 0.0

        self._products = []  # catalog products
        self._product_by_id = {}
        self._variant_by_id = {}
        self._variants_by_product = {}  # pid -> [variant dict]
        self._selected_variant_by_product = {}  # pid -> variant_id (0 for default)
        self._product_categories = []
        self._selected_category_id = 0  # 0=all
        self._cart = {}  # (product_id, variant_id) -> qty
        self._scheduled_cart = []  # list of {'product_id','service_id','service_date','slot_start_time','duration_minutes'}
        self._pending_payment = None
        self._pending_payment_dialog = None
        self._settings_auth_dialog = None
        self._master_actions_dialog = None
        self._cart_row_meta = []  # list of {'type': 'product'|'scheduled', ...} aligned with cart_tree rows

        self._last_activity_ts = time.time()
        self._idle_job = None
        self._hold_heartbeat_job = None
        self._hold_ttl_minutes = 10
        self._last_hold_refresh_ts = 0.0
        self._exit_code = self._load_master_card()

        try:
            self.cashier_mode = self.db.get_cashier_mode()
        except Exception:
            self.cashier_mode = 'teacher'
        try:
            self.idle_timeout_sec = int(self.db.get_cashier_idle_timeout_sec())
        except Exception:
            self.idle_timeout_sec = 300

        # Payment confirm mode is evaluated per-payment (can be threshold-based)
        self.require_rescan_confirm = True

        self._logo_imgtk = None
        self._product_img_cache = {}

        self._scheduled_by_pid = {}  # pid -> scheduled_service row
        self._scheduled_dates_by_service = {}  # service_id -> [YYYY-MM-DD]

        self._grid_cols = 3
        self._grid_cols_locked = False
        self._lock_overlay = None
        self._lock_entry = None
        self._scan_entry = None
        self._scan_entry_submit_job = None

        self._tile_last_qty_by_pid = {}

        self._setup_kiosk_window()
        self._setup_ui()
        self._bind_activity_tracking()

        try:
            self._apply_license_block_if_needed()
        except Exception:
            pass

        try:
            self.root.protocol('WM_DELETE_WINDOW', self._exit_app)
        except Exception:
            pass

        self._lock()
        self._schedule_idle_check()
        self._schedule_hold_heartbeat()
        try:
            self._schedule_update_checks()
        except Exception:
            pass

    def _refresh_tile_controls(self, product_id: int) -> bool:
        try:
            pid = int(product_id or 0)
        except Exception:
            pid = 0
        if not pid:
            return False

    def _build_thermal_text_receipt_bytes(
        self,
        receipt_data: dict,
        encoding: str = "cp862",
        codepage: int = 0x08,
        send_codepage: bool = True,
        logo_path: str | None = None,
        closing_message: str | None = None,
    ) -> bytes:
        try:
            from datetime import datetime
            now = datetime.now()
        except Exception:
            now = None

        ESC = b'\x1b'
        GS = b'\x1d'
        INIT = ESC + b'@'
        codepage_byte = bytes([codepage & 0xFF])
        CODEPAGE = ESC + b't' + codepage_byte
        CUT = GS + b'V\x31'
        BOLD_ON = ESC + b'E\x01'
        BOLD_OFF = ESC + b'E\x00'
        LARGE = GS + b'!\x11'
        XLARGE = GS + b'!\x33'
        LARGE2 = GS + b'!\x22'
        NORMAL = GS + b'!\x00'
        CENTER = ESC + b'a\x01'
        RIGHT = ESC + b'a\x02'
        LEFT = ESC + b'a\x00'
        UNDERLINE_ON = ESC + b'-\x02'
        UNDERLINE_OFF = ESC + b'-\x00'

        def _rev(s: str) -> str:
            return s[::-1]

        def _enc(s: str) -> bytes:
            return str(s or "").encode(encoding, errors="replace")

        out = INIT
        if send_codepage:
            out += CODEPAGE

        # Logo
        logo_bytes = b''
        try:
            logo_bytes = self._get_cached_text_logo_bytes(str(logo_path or '').strip())
        except Exception:
            logo_bytes = b''
        if logo_bytes:
            out += CENTER
            out += logo_bytes
            out += b'\n'

        # Creative top decoration
        out += CENTER
        top_decoration = self._get_cached_text_decoration('stars')
        if top_decoration:
            out += top_decoration + b'\n'
        else:
            out += b'=' * 32 + b'\n'

        # Title with underline (prefer bitmap title)
        out += CENTER
        title_bytes = self._get_cached_text_title_bytes('קבלה')
        if title_bytes:
            out += title_bytes + b'\n'
        else:
            out += XLARGE + BOLD_ON + UNDERLINE_ON
            title = _rev('קבלה')
            out += _enc(title)
            out += b'\n'
            out += UNDERLINE_OFF + NORMAL + BOLD_OFF

        mid_decoration = self._get_cached_text_decoration('wave')
        if mid_decoration:
            out += mid_decoration + b'\n\n'
        else:
            out += b'-' * 32 + b'\n\n'

        # Student info
        out += RIGHT + LARGE
        try:
            student_name = str(receipt_data.get('student_name') or '').strip()
        except Exception:
            student_name = ''
        try:
            class_name = str(receipt_data.get('class_name') or '').strip()
        except Exception:
            class_name = ''
        
        if student_name:
            line = _rev(f"תלמיד: {student_name}")
            out += _enc(line)
            out += b'\n'
        if class_name:
            line = _rev(f"כיתה: {class_name}")
            out += _enc(line)
            out += b'\n'
        out += NORMAL + b'\n'

        # Hebrew date and time
        try:
            if now is not None:
                hebrew_date = HebrewDate.get_hebrew_date(now)
                out += _enc(_rev(hebrew_date))
                out += b'\n'
                time_line = f"{now.strftime('%H:%M:%S')} :" + _rev('שעה')
                out += _enc(time_line)
                out += b'\n\n'
        except Exception:
            pass

        # Purchases section with arrows
        out += CENTER
        header_decoration = self._get_cached_text_decoration('zigzag')
        if header_decoration:
            out += header_decoration + b'\n'
        else:
            out += b'-' * 32 + b'\n'
        out += BOLD_ON
        header = ">>> " + _rev('פירוט קניות') + " <<<"
        out += _enc(header)
        out += b'\n'
        out += BOLD_OFF
        underline_decoration = self._get_cached_text_decoration('dots')
        if underline_decoration:
            out += underline_decoration + b'\n'
        else:
            out += b'-' * 32 + b'\n'
        
        try:
            items = receipt_data.get('items', []) or []
        except Exception:
            items = []
        
        out += RIGHT
        total_points = 0
        for item in items:
            try:
                nm = str(item.get('name', '') or '').strip()
            except Exception:
                nm = ''
            try:
                qty = int(item.get('quantity', item.get('qty', 1)) or 1)
            except Exception:
                qty = 1
            try:
                price = int(float(item.get('price', 0) or 0))
            except Exception:
                price = 0
            try:
                item_total = int(float(item.get('total_points', qty * price) or 0))
            except Exception:
                item_total = qty * price
            total_points += item_total
            
            if nm:
                # Format: "נקודות 10      שוקולד x2"
                points_text = _rev('נקודות')
                if qty > 1:
                    item_name = f"{nm} x{qty}"
                    spacing = max(1, 20 - len(item_name))
                    line = points_text + f" {item_total:d}" + " " * spacing + _rev(item_name)
                else:
                    spacing = max(1, 20 - len(nm))
                    line = points_text + f" {item_total:d}" + " " * spacing + _rev(nm)
                out += _enc(line)
                out += b'\n'

        # Total
        out += CENTER
        total_divider = self._get_cached_text_decoration('dots')
        if total_divider:
            out += total_divider + b'\n'
        else:
            out += b'=' * 32 + b'\n'
        out += CENTER + LARGE2 + BOLD_ON + UNDERLINE_ON
        total_line = f"{total_points:d} :" + _rev('סך הכל')
        out += _enc(total_line)
        out += b'\n'
        out += UNDERLINE_OFF + NORMAL + BOLD_OFF
        out += b'\n'

        # Points balance
        points_divider = self._get_cached_text_decoration('dots')
        if points_divider:
            out += points_divider + b'\n'
        else:
            out += b'.' * 32 + b'\n'
        out += RIGHT
        try:
            bb = receipt_data.get('balance_before', None)
            ba = receipt_data.get('balance_after', None)
            if bb is not None or ba is not None:
                try:
                    bb_i = int(float(bb)) if bb is not None else None
                except Exception:
                    bb_i = None
                try:
                    ba_i = int(float(ba)) if ba is not None else None
                except Exception:
                    ba_i = None
                if bb_i is not None:
                    line = f"{bb_i:d} :" + _rev('נקודות לפני')
                    out += _enc(line)
                    out += b'\n'
                if ba_i is not None:
                    line = f"{ba_i:d} :" + _rev('נקודות אחרי')
                    out += _enc(line)
                    out += b'\n'
        except Exception:
            pass

        if points_divider:
            out += points_divider + b'\n'
        else:
            out += b'.' * 32 + b'\n'

        # Closing message
        closing_text = str(closing_message or receipt_data.get('closing_message') or '').strip()
        if closing_text:
            out += b'\n'
            out += CENTER + BOLD_ON
            for line in closing_text.split('\n'):
                if line.strip():
                    msg_line = _rev(line.strip())
                    out += _enc(msg_line)
                    out += b'\n'
            out += BOLD_OFF

        # Bottom line
        out += b'\n'
        bottom_decoration = self._get_cached_text_decoration('stars')
        out += CENTER
        if bottom_decoration:
            out += bottom_decoration + b'\n'
        else:
            out += b'=' * 32 + b'\n'

        out += b'\n\n\n\n\n'
        out += CUT
        return out
    
    def _print_with_decorated_printer(self, receipt_data: dict, printer_name: str, cfg: dict) -> bool:
        """Print using new decorated thermal printer with caching."""
        try:
            print(f"[DECORATED] Starting decorated printer")
            print(f"[DECORATED] Printer name: {printer_name}")
            
            # Get logo path
            logo_path = ''
            try:
                logo_path = self.db.get_cashier_bw_logo_path() or cfg.get('logo_path', '')
            except:
                logo_path = cfg.get('logo_path', '')
            
            if logo_path:
                logo_path = logo_path.replace('/', '\\')
            
            print(f"[DECORATED] Logo path: {logo_path}")
            
            # Create printer with caching (logo loads once)
            if not hasattr(self, '_cached_thermal_printer'):
                print(f"[DECORATED] Creating new printer instance")
                self._cached_thermal_printer = ThermalPrinterCached(printer_name=printer_name, logo_path=logo_path)
            else:
                print(f"[DECORATED] Using cached printer instance")
            
            # Get closing message
            closing_message = ''
            try:
                closing_message = self.db.get_cashier_closing_message() or ''
            except:
                pass
            
            # Prepare purchases list
            purchases = []
            try:
                items = receipt_data.get('items', []) or []
                for item in items:
                    name = str(item.get('name', '') or '').strip()
                    qty = int(item.get('quantity', 1) or 1)
                    price = int(float(item.get('price', 0) or 0))
                    total = qty * price
                    
                    if name:
                        purchases.append({
                            'name': name,
                            'quantity': qty,
                            'points_each': price,
                            'total_points': total
                        })
            except:
                pass
            
            # Get student info
            student_name = str(receipt_data.get('student_name', '') or '').strip()
            student_class = str(receipt_data.get('class_name', '') or '').strip()
            
            # Get points
            try:
                points_before = int(float(receipt_data.get('balance_before', 0) or 0))
            except:
                points_before = 0
            
            try:
                points_after = int(float(receipt_data.get('balance_after', 0) or 0))
            except:
                points_after = 0
            
            # Print using decorated printer
            return self._cached_thermal_printer.print_receipt(
                student_name=student_name,
                student_class=student_class,
                purchases=purchases,
                points_before=points_before,
                points_after=points_after,
                closing_message=closing_message
            )
            
        except Exception as e:
            print(f"Decorated printer error: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _build_thermal_text_voucher_bytes(
        self,
        voucher_data: dict,
        encoding: str = "cp862",
        codepage: int = 0x08,
        send_codepage: bool = True,
        logo_path: str | None = None,
    ) -> bytes:
        try:
            from datetime import datetime
            now = datetime.now()
        except Exception:
            now = None

        ESC = b'\x1b'
        GS = b'\x1d'
        INIT = ESC + b'@'
        codepage_byte = bytes([codepage & 0xFF])
        CODEPAGE = ESC + b't' + codepage_byte
        CENTER = ESC + b'a\x01'
        RIGHT = ESC + b'a\x02'
        BOLD_ON = ESC + b'E\x01'
        BOLD_OFF = ESC + b'E\x00'
        LARGE = GS + b'!\x11'
        LARGE2 = GS + b'!\x22'
        NORMAL = GS + b'!\x00'
        UNDERLINE_ON = ESC + b'-\x02'
        UNDERLINE_OFF = ESC + b'-\x00'
        CUT = GS + b'V\x31'

        def _enc(s: str) -> bytes:
            return str(s or '').encode(encoding, errors='replace')

        def _rev(s: str) -> str:
            return s[::-1]

        out = INIT
        if send_codepage:
            out += CODEPAGE

        out += CENTER
        top_decoration = self._get_cached_text_decoration('stars')
        if top_decoration:
            out += top_decoration + b'\n'
        else:
            out += b'=' * 32 + b'\n'

        out += CENTER
        title_bytes = self._get_cached_text_title_bytes('שובר קנייה')
        if title_bytes:
            out += title_bytes + b'\n'
        else:
            out += LARGE2 + BOLD_ON + UNDERLINE_ON
            out += _enc(_rev('שובר קנייה'))
            out += b'\n'
            out += UNDERLINE_OFF + NORMAL + BOLD_OFF

        mid_decoration = self._get_cached_text_decoration('wave')
        if mid_decoration:
            out += mid_decoration + b'\n'
        else:
            out += b'-' * 32 + b'\n'

        try:
            student_name = str(voucher_data.get('student_name') or '').strip()
        except Exception:
            student_name = ''
        try:
            class_name = str(voucher_data.get('class_name') or '').strip()
        except Exception:
            class_name = ''
        out += RIGHT + LARGE
        if student_name:
            out += _enc(_rev(f"תלמיד: {student_name}"))
            out += b'\n'
        if class_name:
            out += _enc(_rev(f"כיתה: {class_name}"))
            out += b'\n'
        out += NORMAL

        try:
            if now is not None:
                hebrew_date = HebrewDate.get_hebrew_date(now)
                out += _enc(_rev(hebrew_date))
                out += b'\n'
                time_line = f"{now.strftime('%H:%M:%S')} :" + _rev('שעה')
                out += _enc(time_line)
                out += b'\n'
        except Exception:
            pass

        out += b'\n'

        out += CENTER
        header_decoration = self._get_cached_text_decoration('zigzag')
        if header_decoration:
            out += header_decoration + b'\n'
        else:
            out += b'-' * 32 + b'\n'
        out += BOLD_ON
        header = ">>> " + _rev('פרטי פריט') + " <<<"
        out += _enc(header)
        out += b'\n'
        out += BOLD_OFF
        underline_decoration = self._get_cached_text_decoration('dots')
        if underline_decoration:
            out += underline_decoration + b'\n'
        else:
            out += b'-' * 32 + b'\n'

        try:
            item_name = str(voucher_data.get('item_name') or '').strip()
        except Exception:
            item_name = ''
        try:
            qty = int(voucher_data.get('qty') or 1)
        except Exception:
            qty = 1
        try:
            price = int(float(voucher_data.get('price') or 0))
        except Exception:
            price = 0
        try:
            slot_text = str(voucher_data.get('slot_text') or '').strip()
        except Exception:
            slot_text = ''
        try:
            service_date = str(voucher_data.get('service_date') or '').strip()
        except Exception:
            service_date = ''
        try:
            slot_time = str(voucher_data.get('slot_time') or '').strip()
        except Exception:
            slot_time = ''
        try:
            duration_minutes = int(voucher_data.get('duration_minutes') or 0)
        except Exception:
            duration_minutes = 0

        out += RIGHT
        if item_name:
            out += BOLD_ON
            out += _enc(_rev(item_name))
            out += b'\n'
            out += BOLD_OFF
        if qty and qty != 1:
            out += _enc(f"{qty:d} :" + _rev('כמות'))
            out += b'\n'
        if price:
            out += _enc(f"{price:d} :" + _rev('נקודות ליחידה'))
            out += b'\n'
        if qty and price:
            total_points = qty * price
            out += _enc(f"{total_points:d} :" + _rev('סך הכל'))
            out += b'\n'
        if service_date:
            hebrew_service_date = ''
            try:
                hebrew_service_date = hebrew_date_from_gregorian_str(service_date)
            except Exception:
                hebrew_service_date = ''
            if hebrew_service_date:
                out += _enc(f"{_rev(hebrew_service_date)} :" + _rev('תאריך עברי'))
                out += b'\n'
        if slot_time:
            out += _enc(f"{slot_time} :" + _rev('שעה'))
            out += b'\n'
        if slot_text and not (service_date or slot_time):
            out += _enc(f"{slot_text} :" + _rev('זמן האתגר'))
            out += b'\n'
        if duration_minutes:
            out += _enc(f"{duration_minutes:d} :" + _rev('משך (דקות)'))
            out += b'\n'

        points_before = voucher_data.get('points_before', None)
        points_after = voucher_data.get('points_after', None)
        if points_before is not None or points_after is not None:
            divider = self._get_cached_text_decoration('dots')
            out += CENTER
            if divider:
                out += divider + b'\n'
            else:
                out += b'.' * 32 + b'\n'
            out += RIGHT
            try:
                if points_before is not None:
                    pb_i = int(float(points_before))
                    out += _enc(f"{pb_i:d} :" + _rev('נקודות לפני'))
                    out += b'\n'
            except Exception:
                pass
            try:
                if points_after is not None:
                    pa_i = int(float(points_after))
                    out += _enc(f"{pa_i:d} :" + _rev('נקודות אחרי'))
                    out += b'\n'
            except Exception:
                pass

        out += b'\n'
        bottom_decoration = self._get_cached_text_decoration('stars')
        out += CENTER
        if bottom_decoration:
            out += bottom_decoration + b'\n'
        else:
            out += b'=' * 32 + b'\n'

        out += b'\n\n\n'
        out += CUT
        return out

        t = None
        try:
            t = (self._tile_by_pid or {}).get(int(pid))
        except Exception:
            t = None
        if t is not None and callable(getattr(t, '_refresh_controls', None)):
            try:
                t._refresh_controls()
                return True
            except Exception:
                return False
        return False

    def _sync_tile_qty_var(self, product_id: int) -> int:
        try:
            pid = int(product_id or 0)
        except Exception:
            pid = 0
        if not pid:
            return 0
        q = 0
        try:
            q = int(self._get_total_qty_for_product(int(pid)) or 0)
        except Exception:
            q = 0
        t = None
        try:
            t = (self._tile_by_pid or {}).get(int(pid))
        except Exception:
            t = None
        if t is not None:
            try:
                v = getattr(t, '_qty_var', None)
                if v is not None and hasattr(v, 'set'):
                    v.set(str(int(q)))
            except Exception:
                pass
        return int(q)

    def _ensure_scan_focus(self):
        try:
            if self.root is None:
                return
        except Exception:
            return
        # When locked: keep focus on lock entry.
        try:
            if bool(self._locked):
                if self._lock_entry is not None:
                    self._lock_entry.focus_set()
                return
        except Exception:
            pass
        # When unlocked: keep focus on scan entry (hidden input).
        try:
            if self._scan_entry is not None and self._scan_entry.winfo_exists():
                self._scan_entry.focus_set()
        except Exception:
            pass

    def _exit_app(self):
        # Close customer display connection
        try:
            if self.customer_display:
                self.customer_display.close()
        except Exception:
            pass
        
        self._restore_display_resolution()
        try:
            self.root.destroy()
        except Exception:
            pass

    def _force_display_resolution(self, width: int, height: int):
        try:
            user32 = ctypes.WinDLL('user32', use_last_error=True)
        except Exception:
            return

        ENUM_CURRENT_SETTINGS = -1
        CDS_UPDATEREGISTRY = 0x00000001
        CDS_TEST = 0x00000002
        DISP_CHANGE_SUCCESSFUL = 0

        class DEVMODE(ctypes.Structure):
            _fields_ = [
                ('dmDeviceName', wintypes.WCHAR * 32),
                ('dmSpecVersion', wintypes.WORD),
                ('dmDriverVersion', wintypes.WORD),
                ('dmSize', wintypes.WORD),
                ('dmDriverExtra', wintypes.WORD),
                ('dmFields', wintypes.DWORD),
                ('dmOrientation', wintypes.SHORT),
                ('dmPaperSize', wintypes.SHORT),
                ('dmPaperLength', wintypes.SHORT),
                ('dmPaperWidth', wintypes.SHORT),
                ('dmScale', wintypes.SHORT),
                ('dmCopies', wintypes.SHORT),
                ('dmDefaultSource', wintypes.SHORT),
                ('dmPrintQuality', wintypes.SHORT),
                ('dmColor', wintypes.SHORT),
                ('dmDuplex', wintypes.SHORT),
                ('dmYResolution', wintypes.SHORT),
                ('dmTTOption', wintypes.SHORT),
                ('dmCollate', wintypes.SHORT),
                ('dmFormName', wintypes.WCHAR * 32),
                ('dmLogPixels', wintypes.WORD),
                ('dmBitsPerPel', wintypes.DWORD),
                ('dmPelsWidth', wintypes.DWORD),
                ('dmPelsHeight', wintypes.DWORD),
                ('dmDisplayFlags', wintypes.DWORD),
                ('dmDisplayFrequency', wintypes.DWORD),
                ('dmICMMethod', wintypes.DWORD),
                ('dmICMIntent', wintypes.DWORD),
                ('dmMediaType', wintypes.DWORD),
                ('dmDitherType', wintypes.DWORD),
                ('dmReserved1', wintypes.DWORD),
                ('dmReserved2', wintypes.DWORD),
                ('dmPanningWidth', wintypes.DWORD),
                ('dmPanningHeight', wintypes.DWORD),
            ]

        try:
            user32.EnumDisplaySettingsW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(DEVMODE)]
            user32.EnumDisplaySettingsW.restype = wintypes.BOOL
            user32.ChangeDisplaySettingsW.argtypes = [ctypes.POINTER(DEVMODE), wintypes.DWORD]
            user32.ChangeDisplaySettingsW.restype = wintypes.LONG
        except Exception:
            pass

        dm = DEVMODE()
        dm.dmSize = ctypes.sizeof(DEVMODE)
        try:
            ok = bool(user32.EnumDisplaySettingsW(None, ENUM_CURRENT_SETTINGS, ctypes.byref(dm)))
        except Exception:
            ok = False
        if not ok:
            return

        if self._display_mode_before is None:
            self._display_mode_before = (int(dm.dmPelsWidth or 0), int(dm.dmPelsHeight or 0))

        dm.dmPelsWidth = int(width)
        dm.dmPelsHeight = int(height)
        DM_PELSWIDTH = 0x00080000
        DM_PELSHEIGHT = 0x00100000
        try:
            dm.dmFields |= (DM_PELSWIDTH | DM_PELSHEIGHT)
        except Exception:
            pass

        try:
            if int(user32.ChangeDisplaySettingsW(ctypes.byref(dm), CDS_TEST)) != DISP_CHANGE_SUCCESSFUL:
                return
        except Exception:
            return

        try:
            res = int(user32.ChangeDisplaySettingsW(ctypes.byref(dm), CDS_UPDATEREGISTRY))
        except Exception:
            return
        if res == DISP_CHANGE_SUCCESSFUL:
            self._resolution_forced = True

    def _restore_display_resolution(self):
        if not self._resolution_forced:
            return
        if not self._display_mode_before:
            return
        try:
            w0, h0 = self._display_mode_before
        except Exception:
            return
        try:
            self._resolution_forced = False
        except Exception:
            pass
        try:
            self._force_display_resolution(int(w0), int(h0))
        except Exception:
            pass

    def _touch_confirm(self, *, title: str, message: str, ok_text: str = 'אישור', cancel_text: str = 'ביטול') -> bool:
        try:
            if self.root is None:
                return bool(messagebox.askyesno(title, message))
        except Exception:
            return bool(messagebox.askyesno(title, message))

        dlg = tk.Toplevel(self.root)
        dlg.title(str(title or ''))
        dlg.configure(bg='#0f0f14')
        dlg.transient(self.root)
        dlg.grab_set()
        try:
            dlg.minsize(640, 320)
        except Exception:
            pass

        res = {'ok': False}
        tk.Label(dlg, text=str(message or ''), font=('Arial', 18, 'bold'), fg='white', bg='#0f0f14', justify='right', wraplength=580).pack(padx=18, pady=(22, 18), anchor='e')

        btns = tk.Frame(dlg, bg='#0f0f14')
        btns.pack(fill=tk.X, padx=18, pady=(0, 20))
        btns.grid_columnconfigure(0, weight=1)
        btns.grid_columnconfigure(1, weight=1)

        def _ok():
            res['ok'] = True
            try:
                dlg.destroy()
            except Exception:
                pass

        def _cancel():
            res['ok'] = False
            try:
                dlg.destroy()
            except Exception:
                pass

        tk.Button(btns, text=str(cancel_text or 'ביטול'), command=_cancel, font=('Arial', 18, 'bold'), bg='#7f8c8d', fg='white', padx=22, pady=16).grid(row=0, column=0, sticky='ew', padx=(0, 10))
        tk.Button(btns, text=str(ok_text or 'אישור'), command=_ok, font=('Arial', 18, 'bold'), bg='#27ae60', fg='white', padx=22, pady=16).grid(row=0, column=1, sticky='ew', padx=(10, 0))

        try:
            dlg.protocol('WM_DELETE_WINDOW', _cancel)
        except Exception:
            pass
        try:
            dlg.wait_window()
        except Exception:
            pass
        return bool(res.get('ok'))

    # ----------------------------
    # Window / Config
    # ----------------------------

    def _setup_kiosk_window(self):
        try:
            self.root.configure(bg='#0f0f14')
        except Exception:
            pass

        sw = 0
        sh = 0
        try:
            sw = int(self.root.winfo_screenwidth() or 0)
            sh = int(self.root.winfo_screenheight() or 0)
        except Exception:
            sw = 0
            sh = 0

        # Do NOT force system display resolution on large screens.
        # On some Windows + DPI setups this results in a "quarter screen" rendering.
        self._compact_ui = bool((sw and sw <= 1100) or (sh and sh <= 820))

        _apply_tk_scaling(self.root, compact=bool(getattr(self, '_compact_ui', False)))

        # In forced 1024x768 mode we want a stable, non-stretched layout.
        # Fullscreen on larger displays (and DPI scaling) caused awkward spacing and "broken" look.
        try:
            if getattr(self, '_compact_ui', False):
                self.root.attributes('-fullscreen', False)
                self.root.geometry('1024x768+0+0')
                try:
                    self.root.resizable(False, False)
                except Exception:
                    pass
                # Remove window chrome so the client area is exactly 1024x768
                try:
                    self.root.overrideredirect(True)
                except Exception:
                    pass
            else:
                self.root.attributes('-fullscreen', True)
        except Exception:
            pass
        if not getattr(self, '_compact_ui', False):
            try:
                self.root.overrideredirect(False)
            except Exception:
                pass
        try:
            self.root.focus_force()
        except Exception:
            pass

        try:
            self.root.update_idletasks()
            self.root.update()
        except Exception:
            pass

    def _get_config_file_path(self) -> str:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        for env_name in ("PROGRAMDATA", "LOCALAPPDATA", "APPDATA"):
            root = os.environ.get(env_name)
            if not root:
                continue
            try:
                if os.path.isdir(root) and os.access(root, os.W_OK):
                    cfg_dir = os.path.join(root, "SchoolPoints")
                    try:
                        os.makedirs(cfg_dir, exist_ok=True)
                    except Exception:
                        pass
                    return os.path.join(cfg_dir, "config.json")
            except Exception:
                continue
        return os.path.join(base_dir, 'config.json')

    def _load_app_config(self) -> dict:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        live_config = self._get_config_file_path()
        base_config = os.path.join(base_dir, 'config.json')
        try:
            if not os.path.exists(live_config) and os.path.exists(base_config):
                try:
                    shutil.copy2(base_config, live_config)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            if os.path.exists(live_config):
                with open(live_config, 'r', encoding='utf-8') as f:
                    local_cfg = json.load(f)
            else:
                local_cfg = {}
        except Exception:
            local_cfg = {}

        shared_folder = None
        try:
            if isinstance(local_cfg, dict):
                shared_folder = local_cfg.get('shared_folder') or local_cfg.get('network_root')
        except Exception:
            shared_folder = None

        if shared_folder and os.path.isdir(shared_folder):
            shared_cfg_path = os.path.join(shared_folder, 'config.json')
            if os.path.exists(shared_cfg_path):
                try:
                    with open(shared_cfg_path, 'r', encoding='utf-8') as f:
                        shared_cfg = json.load(f)
                    try:
                        if isinstance(local_cfg, dict) and local_cfg.get('db_path'):
                            merged = dict(shared_cfg) if isinstance(shared_cfg, dict) else {}
                            merged['db_path'] = local_cfg.get('db_path')
                            return merged
                    except Exception:
                        pass
                    return shared_cfg
                except Exception:
                    pass

        if isinstance(local_cfg, dict) and local_cfg:
            return local_cfg

        try:
            if os.path.exists(base_config):
                with open(base_config, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def _save_app_config(self, cfg: dict) -> bool:
        try:
            live_config = self._get_config_file_path()
            data_dir = os.path.dirname(live_config)
            try:
                if data_dir:
                    os.makedirs(data_dir, exist_ok=True)
            except Exception:
                pass
            with open(live_config, 'w', encoding='utf-8') as f:
                json.dump(cfg or {}, f, ensure_ascii=False, indent=4)

            # also save to shared folder if configured
            try:
                shared_folder = None
                if isinstance(cfg, dict):
                    shared_folder = cfg.get('shared_folder') or cfg.get('network_root')
                if shared_folder and os.path.isdir(shared_folder):
                    shared_cfg_path = os.path.join(shared_folder, 'config.json')
                    try:
                        os.makedirs(shared_folder, exist_ok=True)
                    except Exception:
                        pass
                    with open(shared_cfg_path, 'w', encoding='utf-8') as f:
                        shared_cfg = dict(cfg) if isinstance(cfg, dict) else {}
                        try:
                            shared_cfg.pop('db_path', None)
                        except Exception:
                            pass
                        json.dump(shared_cfg, f, ensure_ascii=False, indent=4)
            except Exception:
                pass

            return True
        except Exception:
            return False

    def ensure_shared_folder_config(self) -> bool:
        """First-run: ensure shared folder exists. Returns False if user cancels."""
        try:
            cfg = self._load_app_config() or {}
            try:
                mode = str((cfg or {}).get('deployment_mode') or '').strip().lower()
            except Exception:
                mode = ''
            if mode in ('cloud', 'cloud_only', 'online'):
                return True
            shared = None
            if isinstance(cfg, dict):
                shared = cfg.get('shared_folder') or cfg.get('network_root')
            if shared and os.path.isdir(shared):
                return True
            return self._open_shared_folder_dialog(cfg)
        except Exception:
            return True

    def _open_shared_folder_dialog(self, cfg: dict) -> bool:
        dialog = tk.Toplevel(self.root)
        dialog.title("הגדרת עמדת קופה - תיקיית רשת משותפת")
        dialog.geometry("760x320")
        try:
            dialog.minsize(740, 300)
        except Exception:
            pass
        dialog.configure(bg='#ecf0f1')
        dialog.transient(self.root)
        dialog.grab_set()
        try:
            dialog.resizable(True, True)
        except Exception:
            pass

        tk.Label(
            dialog,
            text="בחר תיקיית רשת משותפת שבה נשמרים מסד הנתונים והקבצים של המערכת.",
            font=('Arial', 11),
            bg='#ecf0f1'
        ).pack(pady=(16, 10))

        frame = tk.Frame(dialog, bg='#ecf0f1')
        frame.pack(fill=tk.X, padx=20, pady=5)

        shared_var = tk.StringVar(value=str((cfg or {}).get('shared_folder') or (cfg or {}).get('network_root') or ''))
        entry = tk.Entry(frame, textvariable=shared_var, font=('Arial', 11), width=44)
        entry.pack(side=tk.RIGHT, padx=5, pady=5, fill=tk.X, expand=True)

        def browse():
            folder = filedialog.askdirectory(title="בחר תיקיית רשת משותפת")
            if folder:
                shared_var.set(folder)

        tk.Button(frame, text="עיון...", command=browse, font=('Arial', 11, 'bold'), bg='#3498db', fg='white').pack(side=tk.LEFT, padx=5)

        btns = tk.Frame(dialog, bg='#ecf0f1')
        btns.pack(pady=18)
        btns.grid_columnconfigure(0, weight=1)
        btns.grid_columnconfigure(1, weight=1)

        result = {'ok': False}

        def save():
            folder = str(shared_var.get() or '').strip()
            if not folder:
                messagebox.showwarning('אזהרה', 'יש לבחור תיקייה')
                return
            if not os.path.isdir(folder):
                messagebox.showwarning('אזהרה', 'התיקייה לא קיימת או לא זמינה')
                return

            new_cfg = dict(cfg) if isinstance(cfg, dict) else {}
            new_cfg['shared_folder'] = folder
            if 'network_root' in new_cfg:
                new_cfg.pop('network_root', None)

            if not self._save_app_config(new_cfg):
                messagebox.showerror('שגיאה', 'לא הצלחנו לשמור את ההגדרות')
                return
            result['ok'] = True
            dialog.destroy()

        def cancel():
            result['ok'] = False
            dialog.destroy()

        tk.Button(btns, text='שמור', command=save, font=('Arial', 12, 'bold'), bg='#27ae60', fg='white', padx=18, pady=8).grid(row=0, column=0, padx=10)
        tk.Button(btns, text='ביטול', command=cancel, font=('Arial', 12, 'bold'), bg='#7f8c8d', fg='white', padx=18, pady=8).grid(row=0, column=1, padx=10)

        self.root.wait_window(dialog)
        return bool(result.get('ok'))

    def _load_master_card(self) -> str:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        # 1. shared folder
        try:
            cfg = self._load_app_config()
            shared_folder = None
            if isinstance(cfg, dict):
                shared_folder = cfg.get('shared_folder') or cfg.get('network_root')
            if shared_folder and os.path.isdir(shared_folder):
                master_file = os.path.join(shared_folder, 'master_card.txt')
                if os.path.exists(master_file):
                    with open(master_file, 'r', encoding='utf-8') as f:
                        card = f.read().strip()
                        if card:
                            return card
        except Exception:
            pass

        # 2. data dir
        try:
            config_file = self._get_config_file_path()
            data_dir = os.path.dirname(config_file) or base_dir
            master_file = os.path.join(data_dir, 'master_card.txt')
            if os.path.exists(master_file):
                with open(master_file, 'r', encoding='utf-8') as f:
                    card = f.read().strip()
                    if card:
                        return card
        except Exception:
            pass

        # 3. base dir
        try:
            master_file = os.path.join(base_dir, 'master_card.txt')
            if os.path.exists(master_file):
                with open(master_file, 'r', encoding='utf-8') as f:
                    card = f.read().strip()
                    if card:
                        return card
        except Exception:
            pass

        return '9999'

    def _load_customer_display_config(self) -> dict:
        """טעינת הגדרות מסך לקוח"""
        try:
            cfg = self._load_app_config() or {}
            customer_display_cfg = cfg.get('customer_display', {})
            if not isinstance(customer_display_cfg, dict):
                customer_display_cfg = {}
            
            return {
                'enabled': customer_display_cfg.get('enabled', False),
                'com_port': customer_display_cfg.get('com_port', 'COM1'),
                'baud_rate': int(customer_display_cfg.get('baud_rate', 9600))
            }
        except Exception:
            return {'enabled': False, 'com_port': 'COM1', 'baud_rate': 9600}

    def _ensure_customer_display(self, show_welcome: bool = False):
        try:
            if not bool(getattr(self, '_customer_display_enabled', False)):
                return None
        except Exception:
            return None

        try:
            display = getattr(self, 'customer_display', None)
            if display and getattr(display, 'enabled', False):
                if show_welcome:
                    try:
                        cfg = self._load_app_config() or {}
                        campaign_name = cfg.get('campaign_name', '')
                        display.show_welcome(campaign_name)
                    except Exception:
                        pass
                return display
        except Exception:
            pass

        try:
            if getattr(self, '_customer_display_connecting', False):
                return None
        except Exception:
            pass

        try:
            self._customer_display_connecting = True
        except Exception:
            pass

        try:
            cfg = getattr(self, '_customer_display_config', None)
            if not isinstance(cfg, dict):
                cfg = self._load_customer_display_config()
        except Exception:
            cfg = self._load_customer_display_config()

        def _worker():
            display_obj = None
            try:
                display_obj = CustomerDisplay(
                    com_port=cfg.get('com_port', 'COM1'),
                    baud_rate=cfg.get('baud_rate', 9600),
                    enabled=bool(cfg.get('enabled', False))
                )
                if display_obj and getattr(display_obj, 'enabled', False) and show_welcome:
                    try:
                        cfg2 = self._load_app_config() or {}
                        campaign_name = cfg2.get('campaign_name', '')
                        display_obj.show_welcome(campaign_name)
                    except Exception:
                        pass
            except Exception:
                display_obj = None
            try:
                self.customer_display = display_obj
            except Exception:
                pass
            try:
                self._customer_display_connecting = False
            except Exception:
                pass

        try:
            t = threading.Thread(target=_worker, daemon=True)
            t.start()
        except Exception:
            try:
                self._customer_display_connecting = False
            except Exception:
                pass
        return None

    # ----------------------------
    # UI
    # ----------------------------

    def _setup_ui(self):
        try:
            style = ttk.Style()
            try:
                style.theme_use('clam')
            except Exception:
                pass
            compact = bool(getattr(self, '_compact_ui', False))
            style.configure(
                'Cashier.Treeview',
                font=('Arial', 14 if compact else 16, 'bold'),
                rowheight=36 if compact else 44,
                background='#1b1b24',
                fieldbackground='#1b1b24',
                foreground='white'
            )
            style.configure(
                'Cashier.Treeview.Heading',
                font=('Arial', 12 if compact else 14, 'bold'),
                background='#2c3e50',
                foreground='white'
            )
            try:
                style.map('Cashier.Treeview.Heading', background=[('active', '#34495e')])
            except Exception:
                pass
            try:
                style.configure('Cashier.Vertical.TScrollbar', width=28)
            except Exception:
                pass
        except Exception:
            pass

        compact = bool(getattr(self, '_compact_ui', False))

        self.header = tk.Frame(self.root, bg='#0f0f14')
        try:
            # Keep header height stable so student card content doesn't push the whole UI down
            self.header.configure(height=(96 if compact else 110))
            self.header.pack_propagate(False)
        except Exception:
            pass
        self.header.pack(fill=tk.X, padx=(10 if compact else 18), pady=((8 if compact else 12), 6))

        # Hidden scan Entry: keeps keyboard focus for card readers in unlocked state.
        # (Some readers act like a keyboard; without a focused Entry scans are lost.)
        try:
            self._scan_entry = tk.Entry(self.header, font=('Arial', 1), width=1, bd=0, highlightthickness=0)
            try:
                self._scan_entry.place(x=-2000, y=-2000, width=1, height=1)
            except Exception:
                pass
        except Exception:
            self._scan_entry = None

        def _scan_submit(_e=None):
            try:
                if self._scan_entry is None:
                    return
                card = str(self._scan_entry.get() or '').strip()
            except Exception:
                card = ''
            if not card:
                return
            try:
                self._scan_entry.delete(0, tk.END)
            except Exception:
                pass
            self.on_card_scanned(card)
            self._ensure_scan_focus()

        def _schedule_scan_submit(_e=None):
            try:
                if self._scan_entry_submit_job is not None:
                    self.root.after_cancel(self._scan_entry_submit_job)
            except Exception:
                pass

            def _fire():
                self._scan_entry_submit_job = None
                _scan_submit()

            try:
                self._scan_entry_submit_job = self.root.after(250, _fire)
            except Exception:
                self._scan_entry_submit_job = None

        try:
            if self._scan_entry is not None:
                self._scan_entry.bind('<Return>', _scan_submit)
                self._scan_entry.bind('<KP_Enter>', _scan_submit)
                self._scan_entry.bind('<KeyRelease>', _schedule_scan_submit)
        except Exception:
            pass

        # Any click should restore scan focus (unless locked).
        try:
            self.root.bind('<Button-1>', lambda _e=None: self._ensure_scan_focus(), add='+')
        except Exception:
            pass

        header_left = tk.Frame(self.header, bg='#0f0f14')
        header_left.pack(side=tk.LEFT, anchor='w')

        self.logo_label = tk.Label(header_left, bg='#0f0f14')
        self.logo_label.pack(side=tk.LEFT, padx=(0, 12))

        self.operator_label = tk.Label(
            header_left,
            text="",
            font=('Arial', 12, 'bold'),
            fg='#bdc3c7',
            bg='#0f0f14'
        )
        self.operator_label.pack(side=tk.LEFT, padx=(0, 12))

        header_right = tk.Frame(self.header, bg='#0f0f14')
        header_right.pack(side=tk.RIGHT, anchor='e')

        self.student_card = tk.Frame(header_right, bg='#14141c', highlightthickness=2, highlightbackground='#2c2c3a')
        try:
            self.student_card.configure(width=(260 if compact else 320), height=(86 if compact else 96))
            self.student_card.pack_propagate(False)
        except Exception:
            pass
        self.student_card.pack(side=tk.RIGHT)

        sc_body = tk.Frame(self.student_card, bg='#14141c')
        sc_body.pack(fill=tk.BOTH, expand=True, padx=12, pady=10)

        self.student_photo_label = tk.Label(sc_body, bg='#14141c', text='👤', font=('Arial', 26), fg='#bdc3c7')
        self.student_photo_label.pack(side=tk.RIGHT, padx=(0, 12))

        sc_text = tk.Frame(sc_body, bg='#14141c')
        sc_text.pack(side=tk.RIGHT, fill=tk.Y)

        self.student_label = tk.Label(
            sc_text,
            text="",
            font=('Arial', 16, 'bold'),
            fg='white',
            bg='#14141c',
            anchor='e'
        )
        self.student_label.pack(fill=tk.X)

        self.student_points_label = tk.Label(
            sc_text,
            text='— נק',
            font=('Arial', 22, 'bold'),
            fg='#27ae60',
            bg='#14141c',
            anchor='e'
        )
        self.student_points_label.pack(fill=tk.X, pady=(2, 0))

        self.title_label = None

        self.main = tk.Frame(self.root, bg='#0f0f14')
        self.main.pack(fill=tk.BOTH, expand=True, padx=(10 if compact else 18), pady=(6, (10 if compact else 12)))

        self.left_panel = tk.Frame(self.main, bg='#14141c')
        try:
            self.left_panel.configure(width=380 if compact else 540)
            self.left_panel.pack_propagate(False)
        except Exception:
            pass
        self.left_panel.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 14))

        try:
            self.left_panel.grid_columnconfigure(0, weight=1)
            # Cart area expands; everything else is fixed-height.
            self.left_panel.grid_rowconfigure(1, weight=1)
        except Exception:
            pass

        self.cart_title = tk.Label(self.left_panel, text="סל קניות", font=('Arial', 18, 'bold'), fg='white', bg='#14141c', anchor='e')
        self.cart_title.grid(row=0, column=0, sticky='ew', padx=12, pady=((8 if compact else 10), 6))

        cart_wrap = tk.Frame(self.left_panel, bg='#14141c')
        cart_wrap.grid(row=1, column=0, sticky='nsew', padx=12, pady=(0, 10))

        self.cart_canvas = tk.Canvas(cart_wrap, bg='#14141c', highlightthickness=0, bd=0)
        self.cart_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.cart_scroll = ttk.Scrollbar(cart_wrap, orient=tk.VERTICAL, command=self.cart_canvas.yview)
        self.cart_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        try:
            self.cart_canvas.configure(yscrollcommand=self.cart_scroll.set)
        except Exception:
            pass

        self.cart_items_container = tk.Frame(self.cart_canvas, bg='#14141c')
        try:
            self._cart_items_window = self.cart_canvas.create_window((0, 0), window=self.cart_items_container, anchor='nw')
        except Exception:
            self._cart_items_window = None

        def _sync_cart_width(_ev=None):
            try:
                if self._cart_items_window is not None:
                    self.cart_canvas.itemconfigure(self._cart_items_window, width=int(self.cart_canvas.winfo_width()))
            except Exception:
                pass

        def _on_cart_configure(_ev=None):
            try:
                self.cart_canvas.configure(scrollregion=self.cart_canvas.bbox('all'))
            except Exception:
                pass
            _sync_cart_width()

        try:
            self.cart_items_container.bind('<Configure>', _on_cart_configure)
            self.cart_canvas.bind('<Configure>', _sync_cart_width)
        except Exception:
            pass

        try:
            self._cart_drag_y = None
        except Exception:
            pass

        def _cart_touch_start(e=None):
            try:
                self._cart_drag_y = int(getattr(e, 'y_root', 0) or 0)
                self.cart_canvas.scan_mark(0, int(getattr(e, 'y', 0) or 0))
            except Exception:
                self._cart_drag_y = None

        def _cart_touch_move(e=None):
            try:
                if self._cart_drag_y is None:
                    return
                self.cart_canvas.scan_dragto(0, int(getattr(e, 'y', 0) or 0), gain=1)
            except Exception:
                pass

        try:
            self.cart_canvas.bind('<ButtonPress-1>', _cart_touch_start, add='+')
            self.cart_canvas.bind('<B1-Motion>', _cart_touch_move, add='+')
        except Exception:
            pass

        self.summary_frame = tk.Frame(self.left_panel, bg='#14141c')
        self.summary_frame.grid(row=2, column=0, sticky='ew', padx=12, pady=(0, 10))

        self.total_var = tk.StringVar(value='סה"כ קנייה: 0 נקודות')
        self.balance_var = tk.StringVar(value='יתרת נקודות: —')
        self.after_var = tk.StringVar(value='יתרה לאחר הקנייה: —')

        tk.Label(self.summary_frame, textvariable=self.balance_var, font=('Arial', 14, 'bold'), fg='white', bg='#14141c', anchor='e').pack(fill=tk.X, pady=2)
        tk.Label(self.summary_frame, textvariable=self.total_var, font=('Arial', 14, 'bold'), fg='white', bg='#14141c', anchor='e').pack(fill=tk.X, pady=2)
        tk.Label(self.summary_frame, textvariable=self.after_var, font=('Arial', 14, 'bold'), fg='white', bg='#14141c', anchor='e').pack(fill=tk.X, pady=2)

        # Actions area under cart (match reference layout)
        self.cart_actions = tk.Frame(self.left_panel, bg='#14141c')
        self.cart_actions.grid(row=3, column=0, sticky='ew', padx=12, pady=(0, 12))

        self.btn_pay = tk.Button(
            self.cart_actions,
            text='תשלום (0 נקודות)',
            command=self._pay,
            font=('Arial', 18 if getattr(self, '_compact_ui', False) else 20, 'bold'),
            bg='#16a34a',
            fg='white',
            padx=18,
            pady=10 if getattr(self, '_compact_ui', False) else 16
        )
        self.btn_pay.pack(fill=tk.X)

        self.btn_clear_cart = tk.Button(
            self.cart_actions,
            text='ניקוי סל',
            command=self._clear_cart_only,
            font=('Arial', 16 if getattr(self, '_compact_ui', False) else 18, 'bold'),
            bg='#dc2626',
            fg='white',
            padx=18,
            pady=9 if getattr(self, '_compact_ui', False) else 14
        )
        self.btn_clear_cart.pack(fill=tk.X, pady=(10, 0))

        self.bottom_actions = tk.Frame(self.cart_actions, bg='#14141c')
        self.bottom_actions.pack(fill=tk.X, pady=(12, 0))
        try:
            self.bottom_actions.grid_columnconfigure(0, weight=1)
            self.bottom_actions.grid_columnconfigure(1, weight=1)
        except Exception:
            pass

        self.btn_settings = tk.Button(
            self.bottom_actions,
            text='⚙ הגדרות',
            command=self._open_cashier_settings_auth_dialog,
            font=('Arial', 14, 'bold'),
            bg='#2d3748',
            fg='white',
            padx=14,
            pady=10
        )
        self.btn_settings.grid(row=0, column=0, sticky='ew', padx=(0, 8), pady=(0, 10))

        self.btn_history = tk.Button(
            self.bottom_actions,
            text='🕘 היסטוריה',
            command=self._open_student_history_dialog,
            font=('Arial', 14, 'bold'),
            bg='#2d3748',
            fg='white',
            padx=14,
            pady=10
        )
        self.btn_history.grid(row=0, column=1, sticky='ew', padx=(8, 0), pady=(0, 10))

        self.btn_student_exit = tk.Button(
            self.bottom_actions,
            text='👤 יציאת תלמיד',
            command=self._student_exit,
            font=('Arial', 14, 'bold'),
            bg='#2d3748',
            fg='white',
            padx=14,
            pady=10
        )
        self.btn_student_exit.grid(row=1, column=0, sticky='ew', padx=(0, 8))

        self.btn_operator_exit_bottom = tk.Button(
            self.bottom_actions,
            text='↩ יציאת מפעיל',
            command=self._operator_exit,
            font=('Arial', 14, 'bold'),
            bg='#2d3748',
            fg='white',
            padx=14,
            pady=10
        )
        self.btn_operator_exit_bottom.grid(row=1, column=1, sticky='ew', padx=(8, 0))

        self.right_panel = tk.Frame(self.main, bg='#0f0f14')
        self.right_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Status line above products
        self.status_var = tk.StringVar(value='')
        self.status_label = tk.Label(self.right_panel, textvariable=self.status_var, font=('Arial', 12, 'bold'), fg='#ecf0f1', bg='#0f0f14', anchor='w')
        self.status_label.pack(fill=tk.X, padx=(0, 12), pady=(0, 8))

        # Categories chips bar (above products)
        self.categories_bar = tk.Frame(self.right_panel, bg='#0f0f14')
        self.categories_bar.pack(fill=tk.X, padx=(0, 12), pady=(0, 10))

        # Products column: scrollable products + actions below (classic cashier layout)
        self.products_area = tk.Frame(self.right_panel, bg='#0f0f14')
        self.products_area.pack(fill=tk.BOTH, expand=True)

        self.products_canvas = tk.Canvas(self.products_area, bg='#0f0f14', highlightthickness=0)
        self.products_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.products_scroll = ttk.Scrollbar(self.products_area, orient=tk.VERTICAL, command=self.products_canvas.yview)
        self.products_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.products_canvas.configure(yscrollcommand=self.products_scroll.set)

        try:
            self.products_scroll.configure(style='Cashier.Vertical.TScrollbar')
        except Exception:
            pass

        self.products_container = tk.Frame(self.products_canvas, bg='#0f0f14')
        self.products_window_id = self.products_canvas.create_window((0, 0), window=self.products_container, anchor='nw')

        def _on_frame_config(_e=None):
            try:
                self.products_canvas.configure(scrollregion=self.products_canvas.bbox('all'))
            except Exception:
                pass

        def _on_canvas_config(e=None):
            try:
                self.products_canvas.itemconfig(self.products_window_id, width=(e.width if e else self.products_canvas.winfo_width()))
            except Exception:
                pass

        try:
            self.products_container.bind('<Configure>', _on_frame_config)
            self.products_canvas.bind('<Configure>', _on_canvas_config)
        except Exception:
            pass

        try:
            self._products_drag_y = None
        except Exception:
            pass

        def _products_touch_start(e=None):
            try:
                self._products_drag_y = int(getattr(e, 'y_root', 0) or 0)
                self.products_canvas.scan_mark(0, int(getattr(e, 'y', 0) or 0))
            except Exception:
                self._products_drag_y = None

        def _products_touch_move(e=None):
            try:
                if self._products_drag_y is None:
                    return
                self.products_canvas.scan_dragto(0, int(getattr(e, 'y', 0) or 0), gain=1)
            except Exception:
                pass

        try:
            self.products_canvas.bind('<ButtonPress-1>', _products_touch_start, add='+')
            self.products_canvas.bind('<B1-Motion>', _products_touch_move, add='+')
        except Exception:
            pass

        # Mouse wheel scroll: route to cart/products based on cursor position (always enabled)
        def _mw_is_descendant(child, parent) -> bool:
            try:
                cur = child
                while cur is not None:
                    if cur == parent:
                        return True
                    try:
                        cur = cur.master
                    except Exception:
                        break
            except Exception:
                return False
            return False

        def _mw_on_mousewheel_routed(e=None):
            try:
                if e is None:
                    return
                delta = int(getattr(e, 'delta', 0) or 0)
                step = 0
                if delta != 0:
                    step = -1 if delta > 0 else 1
                else:
                    try:
                        num = int(getattr(e, 'num', 0) or 0)
                    except Exception:
                        num = 0
                    if num == 4:
                        step = -1
                    elif num == 5:
                        step = 1
                if step == 0:
                    return

                try:
                    w = self.root.winfo_containing(e.x_root, e.y_root)
                except Exception:
                    w = None

                try:
                    if w == self.cart_canvas or _mw_is_descendant(w, self.cart_canvas) or _mw_is_descendant(w, self.cart_items_container):
                        self.cart_canvas.yview_scroll(step, 'units')
                        return
                except Exception:
                    pass
                try:
                    if w == self.products_canvas or _mw_is_descendant(w, self.products_canvas) or _mw_is_descendant(w, self.products_container):
                        self.products_canvas.yview_scroll(step, 'units')
                        return
                except Exception:
                    pass
            except Exception:
                pass

        try:
            self.root.bind_all('<MouseWheel>', _mw_on_mousewheel_routed)
            self.root.bind_all('<Shift-MouseWheel>', _mw_on_mousewheel_routed)
            self.root.bind_all('<Button-4>', _mw_on_mousewheel_routed)
            self.root.bind_all('<Button-5>', _mw_on_mousewheel_routed)
        except Exception:
            pass

        # Touch drag scrolling (works even when touching child widgets inside canvases)
        self._touch_scroll_state = {
            'active': False,
            'canvas': None,
            'start_y_root': 0,
            'moved': False,
        }

        def _touch_scroll_pick_canvas(e=None):
            try:
                if e is None:
                    return None

                # Don't hijack taps on interactive widgets
                try:
                    wc = str(e.widget.winfo_class() or '')
                except Exception:
                    wc = ''
                if wc in ('Button', 'TButton', 'Entry', 'TEntry', 'Spinbox', 'TSpinbox'):
                    return None

                try:
                    w = self.root.winfo_containing(e.x_root, e.y_root)
                except Exception:
                    w = None

                try:
                    if w == self.cart_canvas or _mw_is_descendant(w, self.cart_canvas) or _mw_is_descendant(w, self.cart_items_container):
                        return self.cart_canvas
                except Exception:
                    pass
                try:
                    if w == self.products_canvas or _mw_is_descendant(w, self.products_canvas) or _mw_is_descendant(w, self.products_container):
                        return self.products_canvas
                except Exception:
                    pass
            except Exception:
                return None
            return None

        def _touch_scroll_start(e=None):
            try:
                canvas = _touch_scroll_pick_canvas(e)
                if canvas is None:
                    return
                self._touch_scroll_state['active'] = True
                self._touch_scroll_state['canvas'] = canvas
                self._touch_scroll_state['start_y_root'] = int(getattr(e, 'y_root', 0) or 0)
                self._touch_scroll_state['moved'] = False

                try:
                    cx = int(getattr(e, 'x_root', 0) or 0) - int(canvas.winfo_rootx() or 0)
                    cy = int(getattr(e, 'y_root', 0) or 0) - int(canvas.winfo_rooty() or 0)
                except Exception:
                    cx, cy = 0, 0
                try:
                    canvas.scan_mark(int(cx), int(cy))
                except Exception:
                    pass
            except Exception:
                pass

        def _touch_scroll_move(e=None):
            try:
                if not bool(self._touch_scroll_state.get('active')):
                    return
                canvas = self._touch_scroll_state.get('canvas')
                if canvas is None:
                    return

                try:
                    dy = int(getattr(e, 'y_root', 0) or 0) - int(self._touch_scroll_state.get('start_y_root') or 0)
                except Exception:
                    dy = 0
                if abs(dy) < 6:
                    return
                self._touch_scroll_state['moved'] = True

                try:
                    cx = int(getattr(e, 'x_root', 0) or 0) - int(canvas.winfo_rootx() or 0)
                    cy = int(getattr(e, 'y_root', 0) or 0) - int(canvas.winfo_rooty() or 0)
                except Exception:
                    cx, cy = 0, 0
                try:
                    canvas.scan_dragto(int(cx), int(cy), gain=1)
                except Exception:
                    pass
            except Exception:
                pass

        def _touch_scroll_end(_e=None):
            try:
                self._touch_scroll_state['active'] = False
                self._touch_scroll_state['canvas'] = None
            except Exception:
                pass

        try:
            self.root.bind_all('<ButtonPress-1>', _touch_scroll_start, add='+')
            self.root.bind_all('<B1-Motion>', _touch_scroll_move, add='+')
            self.root.bind_all('<ButtonRelease-1>', _touch_scroll_end, add='+')
        except Exception:
            pass

        try:
            if bool(getattr(self, '_license_blocked', False)):
                self._apply_license_block_if_needed()
        except Exception:
            pass

    def _apply_license_block_if_needed(self):
        if not bool(getattr(self, '_license_blocked', False)):
            return
        msg = str(getattr(self, '_license_block_message', '') or '').strip()
        if not msg:
            msg = 'העמדה לא מורשית ואין אפשרות לבצע פעולות.'

        # Hard lock: prevent any scan/unlock + disable action buttons
        try:
            self._locked = True
        except Exception:
            pass

        try:
            self._set_status('עמדת קופה לא מורשית – אין אפשרות לבצע פעולות', is_error=True)
        except Exception:
            pass

        for bname in ('btn_pay', 'btn_clear_cart', 'btn_settings', 'btn_history', 'btn_student_exit', 'btn_operator_exit_bottom'):
            try:
                btn = getattr(self, bname, None)
                if btn is not None:
                    btn.config(state=tk.DISABLED)
            except Exception:
                pass

        try:
            self._lock()
        except Exception:
            pass
        try:
            self._set_status(msg, is_error=True)
        except Exception:
            pass

        # Stable hover highlight without Enter/Leave flicker
        self._hover_tile = None

        def _find_tile_widget(w):
            try:
                cur = w
                while cur is not None:
                    try:
                        if bool(getattr(cur, '_is_product_tile', False)):
                            return cur
                    except Exception:
                        pass
                    try:
                        cur = cur.master
                    except Exception:
                        break
            except Exception:
                return None
            return None

        def _apply_tile_hover(new_tile):
            try:
                if self._hover_tile is not None and self._hover_tile != new_tile:
                    try:
                        self._hover_tile.configure(highlightbackground='#2c2c3a')
                    except Exception:
                        pass
            except Exception:
                pass
            self._hover_tile = new_tile
            if new_tile is not None:
                try:
                    new_tile.configure(highlightbackground='#27ae60')
                except Exception:
                    pass

        def _on_products_motion(ev=None):
            try:
                if ev is None:
                    return
                w = self.root.winfo_containing(ev.x_root, ev.y_root)
            except Exception:
                w = None
            tile = _find_tile_widget(w)
            if tile != self._hover_tile:
                _apply_tile_hover(tile)

        def _on_products_leave(_ev=None):
            _apply_tile_hover(None)

        try:
            self.products_canvas.bind('<Motion>', _on_products_motion)
            self.products_canvas.bind('<Leave>', _on_products_leave)
        except Exception:
            pass

        self.product_actions = None

        self._load_logo()

        # Stable grid cols: compute once from actual container width (prevents 3->4 jump and "squashed" controls)
        self._grid_cols = int(self._grid_cols or 3)
        try:
            self.root.update_idletasks()
        except Exception:
            pass

    def _refresh_all_tile_controls(self):
        try:
            for _pid, t in list((self._tile_by_pid or {}).items()):
                try:
                    if t is not None and callable(getattr(t, '_refresh_controls', None)):
                        t._refresh_controls()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            self.root.update_idletasks()
        except Exception:
            pass

    def _get_total_qty_for_product(self, product_id: int) -> int:
        try:
            pid = int(product_id or 0)
        except Exception:
            pid = 0
        if not pid:
            return 0
        try:
            items = list((self._cart or {}).items())
        except Exception:
            items = []
        s = 0
        for k, q in items:
            try:
                kpid = int((k or (0, 0))[0])
            except Exception:
                continue
            if int(kpid) != int(pid):
                continue
            try:
                s += int(q or 0)
            except Exception:
                pass
        return int(s)

    def _clear_cart_state(self, *, clear_db: bool = True, show_lock_overlay: bool = True, reload_products: bool = True, reload_categories: bool = True):
        self._pending_payment = None
        if clear_db:
            try:
                sid = int((self._current_student or {}).get('id') or 0)
            except Exception:
                sid = 0
            if sid:
                try:
                    self.db.clear_holds(station_id=str(self.station_id or '').strip(), student_id=int(sid))
                except Exception:
                    pass
        self._cart = {}
        self._scheduled_cart = []
        self._refresh_cart_ui()
        try:
            self._refresh_all_tile_controls()
        except Exception:
            pass
        self._compute_and_lock_grid_cols()

        if bool(show_lock_overlay):
            # Show lock overlay BEFORE loading products to avoid a brief flash of the catalog
            self._build_lock_overlay()
            try:
                self._show_lock_overlay()
            except Exception:
                pass
            try:
                self.root.update_idletasks()
            except Exception:
                pass

        if bool(reload_products):
            self._reload_products()

        if bool(reload_categories):
            try:
                self._reload_categories()
            except Exception:
                pass

        # (overlay already built and shown above)

    def _load_student_photo_to_header(self, student: dict):
        try:
            if not hasattr(self, 'student_photo_label'):
                return
        except Exception:
            return

        try:
            self.student_photo_label.config(image='', text='👤')
            self.student_photo_label.image = None
        except Exception:
            pass

        if not student:
            return

        photo_value = ''
        try:
            photo_value = str((student or {}).get('photo_number') or '').strip()
        except Exception:
            photo_value = ''
        if not photo_value:
            return

        photos_folder = self._get_photos_folder_cached()

        candidate_paths = []
        if os.path.isabs(photo_value):
            candidate_paths.append(photo_value)
        else:
            if photos_folder:
                candidate_paths.append(os.path.join(photos_folder, photo_value))
            # fallback: base dir
            try:
                base_dir = os.path.dirname(os.path.abspath(__file__))
            except Exception:
                base_dir = ''
            if base_dir:
                candidate_paths.append(os.path.join(base_dir, photo_value))

        photo_path = None
        for pth in candidate_paths:
            try:
                if pth and os.path.exists(pth):
                    photo_path = pth
                    break
            except Exception:
                continue
        if not photo_path:
            return

        try:
            expected_id = int((student or {}).get('id') or 0)
        except Exception:
            expected_id = 0

        def _worker(pth: str, sid: int):
            try:
                img = Image.open(pth)
                try:
                    img = ImageOps.exif_transpose(img)
                except Exception:
                    pass
                img = img.convert('RGBA')

                size = 76
                try:
                    img = ImageOps.contain(img, (size, size), method=Image.LANCZOS)
                except Exception:
                    img = ImageOps.contain(img, (size, size))

                base = Image.new('RGBA', (size, size), (0, 0, 0, 0))
                try:
                    x = int((size - img.size[0]) / 2)
                    y = int((size - img.size[1]) / 2)
                except Exception:
                    x, y = 0, 0
                base.paste(img, (x, y), img if img.mode == 'RGBA' else None)

                mask = Image.new('L', (size, size), 0)
                draw = ImageDraw.Draw(mask)
                draw.ellipse((0, 0, size - 1, size - 1), fill=255)
                out = Image.new('RGBA', (size, size), (0, 0, 0, 0))
                out.paste(base, (0, 0), mask)
            except Exception:
                return

            def _apply():
                try:
                    cur = self._current_student or {}
                    cur_id = int(cur.get('id') or 0)
                except Exception:
                    cur_id = 0
                if sid and cur_id and sid != cur_id:
                    return
                try:
                    imgtk = ImageTk.PhotoImage(out)
                except Exception:
                    return
                try:
                    self.student_photo_label.config(image=imgtk, text='')
                    self.student_photo_label.image = imgtk
                except Exception:
                    pass

            try:
                self.root.after(0, _apply)
            except Exception:
                _apply()

        try:
            t = threading.Thread(target=_worker, args=(str(photo_path), int(expected_id)), daemon=True)
            t.start()
        except Exception:
            pass

    def _clear_cart_only(self):
        self._touch_activity()
        if bool(getattr(self, '_license_blocked', False)):
            try:
                msg = str(getattr(self, '_license_block_message', '') or '').strip()
            except Exception:
                msg = ''
            if not msg:
                msg = 'עמדת קופה לא מורשית – אין אפשרות לבצע פעולות'
            try:
                self._set_status(msg, is_error=True)
            except Exception:
                pass
            return
        if self._locked:
            return
        self._clear_cart_state(clear_db=True, show_lock_overlay=False, reload_products=False, reload_categories=False)

    def _reload_categories(self):
        try:
            self._product_categories = self.db.get_product_categories(active_only=True) or []
        except Exception:
            self._product_categories = []
        self._render_categories_bar()

    def _render_categories_bar(self):
        try:
            for w in self.categories_bar.winfo_children():
                try:
                    w.destroy()
                except Exception:
                    pass
        except Exception:
            return

        # "All" chip
        def _mk_btn(text: str, cid: int):
            selected = (int(self._selected_category_id or 0) == int(cid or 0))
            bg = '#27ae60' if selected else '#34495e'
            fg = 'white'

            def _choose():
                self._touch_activity()
                self._selected_category_id = int(cid or 0)
                self._render_categories_bar()
                self._render_product_grid()

            tk.Button(
                self.categories_bar,
                text=str(text or ''),
                command=_choose,
                font=('Arial', 12, 'bold'),
                bg=bg,
                fg=fg,
                padx=14,
                pady=8
            ).pack(side=tk.RIGHT, padx=(0, 8))

        _mk_btn('הכל', 0)
        for c in (self._product_categories or []):
            try:
                cid = int(c.get('id') or 0)
            except Exception:
                cid = 0
            if not cid:
                continue
            name = str(c.get('name') or '').strip()
            if not name:
                continue
            _mk_btn(name, cid)

    def _build_lock_overlay(self):
        if self._lock_overlay is not None:
            return
        self._lock_overlay = tk.Frame(self.root, bg='#0f0f14')

        center = tk.Frame(self._lock_overlay, bg='#0f0f14')
        center.place(relx=0.5, rely=0.45, anchor='center')

        # Logo above title
        try:
            self._lock_logo_label = tk.Label(center, bg='#0f0f14')
            try:
                if getattr(self, '_logo_imgtk', None) is not None:
                    self._lock_logo_label.config(image=self._logo_imgtk)
                    self._lock_logo_label.image = self._logo_imgtk
            except Exception:
                pass
            self._lock_logo_label.pack(pady=(0, 10))
        except Exception:
            pass

        self._lock_title = tk.Label(center, text='עמדת קופה', font=('Arial', 26, 'bold'), fg='white', bg='#0f0f14')
        self._lock_title.pack(pady=(0, 14))

        self._lock_subtitle = tk.Label(center, text='', font=('Arial', 16, 'bold'), fg='#bdc3c7', bg='#0f0f14')
        self._lock_subtitle.pack(pady=(0, 14))

        self._lock_entry = tk.Entry(center, font=('Arial', 22), justify='center', width=26, show='*')
        self._lock_entry.pack(pady=(0, 10), ipady=10)

        self._lock_hint = tk.Label(center, text='', font=('Arial', 11), fg='#7f8c8d', bg='#0f0f14')
        self._lock_hint.pack(pady=(0, 0))

        def _submit(_e=None):
            try:
                card = str(self._lock_entry.get() or '').strip()
            except Exception:
                card = ''
            if card:
                self.on_card_scanned(card)
                # Clear only if action succeeded (unlock or exit). If auth failed we keep the masked value
                # so it doesn't look like the input was ignored.
                try:
                    if (not self._locked) or (not self.root.winfo_exists()):
                        self._lock_entry.delete(0, tk.END)
                except Exception:
                    pass

        self._lock_entry_submit_job = None

        def _schedule_submit(_e=None):
            # Allow manual typing/paste to auto-submit after a short idle.
            # Card readers usually send Enter; if not, idle submit still works.
            try:
                if self._lock_entry_submit_job is not None:
                    self.root.after_cancel(self._lock_entry_submit_job)
            except Exception:
                pass

            def _fire():
                self._lock_entry_submit_job = None
                _submit()

            try:
                self._lock_entry_submit_job = self.root.after(900, _fire)
            except Exception:
                self._lock_entry_submit_job = None

        try:
            self._lock_entry.bind('<Return>', _submit)
        except Exception:
            pass
        try:
            self._lock_entry.bind('<KP_Enter>', _submit)
            self._lock_entry.bind('<Tab>', _submit)
        except Exception:
            pass
        try:
            self._lock_entry.bind('<KeyRelease>', _schedule_submit)
        except Exception:
            pass

    def _show_lock_overlay(self):
        if self._lock_overlay is None:
            self._build_lock_overlay()
        try:
            if self.cashier_mode == 'self_service':
                txt = 'העבר כרטיס תלמיד לפתיחה'
            elif self.cashier_mode == 'responsible_student':
                txt = 'העבר כרטיס מפעיל (תלמיד אחראי) לפתיחה'
            else:
                txt = 'העבר כרטיס מורה לפתיחה'
            self._lock_subtitle.config(text=txt)
        except Exception:
            pass
        try:
            self._lock_overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        except Exception:
            pass
        try:
            self._lock_overlay.lift()
        except Exception:
            pass
        try:
            if self._lock_entry is not None:
                self._lock_entry.focus_set()
        except Exception:
            pass
        # Some Windows setups require focus_force after the window is mapped.
        try:
            if self._lock_entry is not None:
                self.root.after(50, lambda: (self._lock_entry.focus_force(), self._lock_entry.icursor(tk.END)))
        except Exception:
            pass

    def _hide_lock_overlay(self):
        try:
            if self._lock_overlay is not None:
                self._lock_overlay.place_forget()
        except Exception:
            pass
        try:
            self._ensure_scan_focus()
        except Exception:
            pass

    def _load_logo(self):
        cfg = self._load_app_config()
        base_dir = os.path.dirname(os.path.abspath(__file__))
        logo_path = None
        try:
            custom_logo = (cfg or {}).get('logo_path')
            if custom_logo and os.path.exists(custom_logo):
                logo_path = custom_logo
        except Exception:
            logo_path = None
        if not logo_path:
            fallback = os.path.join(base_dir, "דובר שלום לוגו תת.jpg")
            if os.path.exists(fallback):
                logo_path = fallback

        if not logo_path or not os.path.exists(logo_path):
            return
        try:
            img = Image.open(logo_path)
            img = img.convert('RGBA')
            img.thumbnail((160, 80))
            self._logo_imgtk = ImageTk.PhotoImage(img)
            self.logo_label.config(image=self._logo_imgtk)
        except Exception:
            pass

    # ----------------------------
    # Products
    # ----------------------------

    def _reload_products(self):
        try:
            self._products = self.db.get_cashier_catalog() or []
        except Exception:
            self._products = []
        self._product_by_id = {}
        self._variant_by_id = {}
        self._variants_by_product = {}
        self._scheduled_by_pid = {}
        self._scheduled_dates_by_service = {}
        for p in (self._products or []):
            try:
                pid = int(p.get('id') or 0)
            except Exception:
                pid = 0
            if not pid:
                continue
            self._product_by_id[pid] = p

            try:
                s = self.db.get_scheduled_service_by_product(pid)
            except Exception:
                s = None
            if s and int(s.get('is_active', 1) or 0) == 1:
                self._scheduled_by_pid[pid] = s
                try:
                    sid = int(s.get('id') or 0)
                except Exception:
                    sid = 0
                if sid:
                    try:
                        self._scheduled_dates_by_service[sid] = self.db.get_scheduled_service_dates(sid, active_only=True) or []
                    except Exception:
                        self._scheduled_dates_by_service[sid] = []

            vars_ = p.get('variants') or []
            self._variants_by_product[pid] = list(vars_)
            for v in vars_:
                try:
                    vid = int(v.get('id') or 0)
                except Exception:
                    vid = 0
                if vid:
                    self._variant_by_id[vid] = v
        self._render_product_grid()

    def _render_product_grid(self):
        # Preserve scroll position across renders
        try:
            y0 = self.products_canvas.yview()
        except Exception:
            y0 = None

        try:
            self._tile_by_pid = {}
        except Exception:
            pass

        for w in self.products_container.winfo_children():
            try:
                w.destroy()
            except Exception:
                pass

        cols = int(self._grid_cols or 3)
        compact = bool(getattr(self, '_compact_ui', False))
        if compact:
            img_sz = 110 if cols >= 4 else (130 if cols == 3 else 150)
        else:
            img_sz = 190 if cols >= 4 else (230 if cols == 3 else 280)

        products = list(self._products or [])

        # Availability filtering by student (class / points)
        st = self._current_student or {}
        try:
            st_points = int(st.get('points', 0) or 0)
        except Exception:
            st_points = 0
        st_cls = str(st.get('class_name') or '').strip()

        if self._current_student:
            filtered = []
            for p in products:
                allowed = str(p.get('allowed_classes') or '').strip()
                if allowed and st_cls:
                    allowed_list = [x.strip() for x in allowed.split(',') if x.strip()]
                    if allowed_list and (st_cls not in allowed_list):
                        continue
                try:
                    minp = int(p.get('min_points_required', 0) or 0)
                except Exception:
                    minp = 0
                if minp > 0 and st_points < minp:
                    continue
                filtered.append(p)
            products = filtered
        try:
            cid = int(self._selected_category_id or 0)
        except Exception:
            cid = 0
        if cid:
            try:
                products = [p for p in products if int(p.get('category_id') or 0) == int(cid)]
            except Exception:
                products = list(self._products or [])

        if not products:
            tk.Label(self.products_container, text='אין מוצרים פעילים', font=('Arial', 18, 'bold'), fg='white', bg='#0f0f14').pack(pady=30)
            return

        pad = 6 if compact else 10
        for i, p in enumerate(products):
            r = i // cols
            c = i % cols
            tile = tk.Frame(self.products_container, bg='#14141c', relief='raised', bd=3, highlightbackground='#2c2c3a', highlightthickness=2)
            try:
                tile._is_product_tile = True
            except Exception:
                pass
            try:
                if compact:
                    if cols >= 4:
                        tile_w = 170
                        tile_h = 235
                    elif cols == 3:
                        tile_w = 200
                        tile_h = 245
                    else:
                        tile_w = 250
                        tile_h = 265
                else:
                    tile_w = 330 if cols <= 3 else 300
                    tile_h = 330 if cols <= 3 else 310
                tile.configure(width=int(tile_w), height=int(tile_h))
                tile.grid_propagate(False)
            except Exception:
                pass
            tile.grid(row=r, column=c, padx=pad, pady=pad, sticky='nsew')

            try:
                pid = int(p.get('id') or 0)
            except Exception:
                pid = 0

            name = (str(p.get('display_name') or '').strip() or str(p.get('name') or '').strip())
            name = self._strip_asterisk_annotations(name)

            vars_ = self._variants_by_product.get(pid, [])
            selected_vid = int(self._selected_variant_by_product.get(pid, 0) or 0)
            if len(vars_) == 1:
                try:
                    selected_vid = int(vars_[0].get('id') or 0)
                except Exception:
                    selected_vid = 0
                self._selected_variant_by_product[pid] = selected_vid

            scheduled = self._scheduled_by_pid.get(pid)
            if scheduled:
                try:
                    badge = tk.Label(tile, text='⏱', font=('Arial', 12, 'bold'), fg='#f1c40f', bg='#14141c')
                    badge.place(relx=1.0, rely=0.0, x=-6, y=6, anchor='ne')
                except Exception:
                    pass

            for cc in range(cols):
                try:
                    self.products_container.grid_columnconfigure(cc, weight=1)
                except Exception:
                    pass

            selected_variant = None
            if selected_vid and selected_vid in self._variant_by_id:
                selected_variant = self._variant_by_id.get(selected_vid)
            elif len(vars_) == 1:
                selected_variant = vars_[0]

            try:
                base_price = int((selected_variant or {}).get('price_points', p.get('price_points', 0)) or 0)
            except Exception:
                base_price = 0
            price = int(base_price)
            if self._current_student:
                try:
                    po_min = p.get('price_override_min_points', None)
                    po_price = p.get('price_override_points', None)
                    po_pct = p.get('price_override_discount_pct', None)
                    if po_min is not None and int(st_points) >= int(po_min):
                        if po_pct is not None:
                            try:
                                pct = int(po_pct)
                            except Exception:
                                pct = 0
                            if pct < 0:
                                pct = 0
                            if pct > 100:
                                pct = 100
                            try:
                                price = int(round(int(base_price) * (100 - pct) / 100))
                            except Exception:
                                price = int(base_price)
                        elif po_price is not None:
                            price = int(po_price)
                        if price < 0:
                            price = 0
                except Exception:
                    price = int(base_price)

            body = tk.Frame(tile, bg='#14141c')
            body.pack(fill=tk.BOTH, expand=True, padx=(6 if compact else 10), pady=(6 if compact else 10))
            try:
                body.grid_rowconfigure(0, weight=0)
                body.grid_rowconfigure(1, weight=1)
                body.grid_rowconfigure(2, weight=0)
                body.grid_columnconfigure(0, weight=1)
            except Exception:
                pass

            img_wrap = tk.Frame(body, bg='#14141c')
            img_wrap.grid(row=0, column=0, sticky='n')
            try:
                img_wrap.configure(width=int(img_sz), height=int(img_sz))
                img_wrap.pack_propagate(False)
            except Exception:
                pass

            img_lbl = tk.Label(img_wrap, bg='#14141c')
            img_lbl.pack(fill=tk.BOTH, expand=True)

            imgtk = self._get_product_img(pid)
            if imgtk is not None:
                img_lbl.config(image=imgtk)
                img_lbl.image = imgtk
            else:
                img_lbl.config(text='🛒', font=('Arial', 44), fg='#bdc3c7')

            mid = tk.Frame(body, bg='#14141c')
            mid.grid(row=1, column=0, sticky='nsew', pady=(10, 6))

            name_wrap = 150 if (compact and cols >= 4) else (190 if compact else (220 if cols >= 4 else (250 if cols == 3 else 280)))
            tk.Label(
                mid,
                text=name,
                font=('Arial', 12 if compact else 15, 'bold'),
                fg='#93c5fd',
                bg='#14141c',
                anchor='center',
                justify='center',
                wraplength=name_wrap
            ).pack(fill=tk.X, pady=(0, 4 if compact else 4))
            if len(vars_) > 1:
                vtxt = 'בחר אפשרות' if not selected_variant else self._strip_asterisk_annotations(str((selected_variant or {}).get('variant_name') or '').strip())
                tk.Label(mid, text=vtxt, font=('Arial', 12, 'bold'), fg='#f1c40f', bg='#14141c', anchor='center').pack(fill=tk.X, pady=(0, 2))

            price_row = tk.Frame(mid, bg='#14141c')
            price_row.pack(fill=tk.X)
            # RLM prefix keeps "75 נקודות" order stable in RTL environments
            price_txt = f"\u200f{price} נקודות"
            tk.Label(price_row, text=price_txt, font=('Arial', 16 if compact else 22, 'bold'), fg='white', bg='#14141c', anchor='center', justify='center').pack(fill=tk.X)

            qty = int(self._get_total_qty_for_product(int(pid)) or 0)
            qty_var = tk.StringVar(value=str(qty))

            ctl = tk.Frame(body, bg='#14141c')
            ctl.grid(row=2, column=0, sticky='sew', pady=(2, 0))
            disabled = (self._locked or (not self._current_student))

            # Capture loop variables in default args to avoid closure bug
            def _refresh_controls_for_tile(_ctl=ctl, _qty_var=qty_var, _pid=pid, _scheduled=scheduled, _compact=compact):
                try:
                    for ww in list(_ctl.winfo_children()):
                        try:
                            ww.destroy()
                        except Exception:
                            pass
                except Exception:
                    pass

                # Prefer the already-synced qty_var (updated by _sync_tile_qty_var) to avoid stale reads.
                try:
                    q_now = int(str(_qty_var.get() or '0').strip() or '0')
                except Exception:
                    q_now = 0

                disabled_now = (self._locked or (not self._current_student))

                if _scheduled:
                    _ctl.grid_columnconfigure(0, weight=1)
                    _ctl.grid_columnconfigure(1, weight=1)

                    def _auto(__pid=_pid):
                        self._touch_activity()
                        self._add_scheduled_service_to_cart(__pid, mode='auto')

                    def _manual(__pid=_pid):
                        self._touch_activity()
                        self._add_scheduled_service_to_cart(__pid, mode='manual')

                    tk.Button(_ctl, text='אוטומטי', command=_auto, state=(tk.DISABLED if disabled_now else tk.NORMAL), font=('Arial', 12 if _compact else 16, 'bold'), bg='#27ae60', fg='white', padx=8 if _compact else 12, pady=6 if _compact else 10).grid(row=0, column=0, sticky='ew', padx=(0, 4 if _compact else 6))
                    tk.Button(_ctl, text='ידני', command=_manual, state=(tk.DISABLED if disabled_now else tk.NORMAL), font=('Arial', 12 if _compact else 16, 'bold'), bg='#2980b9', fg='white', padx=8 if _compact else 12, pady=6 if _compact else 10).grid(row=0, column=1, sticky='ew', padx=(4 if _compact else 6, 0))
                    return

                def _mk_dec(__pid=_pid):
                    self._touch_activity()
                    self._decrement_product(__pid)

                def _mk_inc(__pid=_pid):
                    self._touch_activity()
                    self._increment_product(__pid)

                if int(q_now or 0) <= 0:
                    _ctl.grid_columnconfigure(0, weight=1)
                    tk.Button(
                        _ctl,
                        text='הוסף',
                        command=_mk_inc,
                        state=(tk.DISABLED if disabled_now else tk.NORMAL),
                        font=('Arial', 14 if _compact else 18, 'bold'),
                        bg='#27ae60',
                        fg='white',
                        activebackground='#27ae60',
                        activeforeground='white',
                        padx=16,
                        pady=8 if _compact else 12
                    ).grid(row=0, column=0, sticky='ew')
                else:
                    _ctl.grid_columnconfigure(0, weight=1)
                    _ctl.grid_columnconfigure(1, weight=1)
                    _ctl.grid_columnconfigure(2, weight=1)

                    btn_minus = tk.Button(_ctl, text='-', command=_mk_dec, state=(tk.DISABLED if disabled_now else tk.NORMAL), font=('Arial', 16 if _compact else 20, 'bold'), bg='#dc2626', fg='white', activebackground='#dc2626', activeforeground='white', width=3, height=1)
                    btn_minus.grid(row=0, column=0, sticky='ew', padx=(0, 6))
                    tk.Label(_ctl, textvariable=_qty_var, font=('Arial', 14 if _compact else 18, 'bold'), bg='#ecf0f1', fg='#2c3e50', width=3 if _compact else 4).grid(row=0, column=1, sticky='ew')
                    btn_plus = tk.Button(_ctl, text='+', command=_mk_inc, state=(tk.DISABLED if disabled_now else tk.NORMAL), font=('Arial', 18 if _compact else 20, 'bold'), bg='#16a34a', fg='white', activebackground='#16a34a', activeforeground='white', width=2 if _compact else 3, height=1)
                    btn_plus.grid(row=0, column=2, sticky='ew', padx=(4 if _compact else 6, 0))

            # initial controls build
            _refresh_controls_for_tile()

            # store refs for refresh without full re-render
            tile._qty_var = qty_var
            tile._refresh_controls = _refresh_controls_for_tile
            try:
                self._tile_by_pid[int(pid)] = tile
            except Exception:
                pass

        # Restore scroll position after render
        if y0 is not None:
            try:
                self.products_canvas.yview_moveto(float(y0[0]))
            except Exception:
                pass

    def _get_product_img(self, product_id: int):
        if product_id in self._product_img_cache:
            return self._product_img_cache[product_id]
        p = self._product_by_id.get(int(product_id or 0))
        if not p:
            self._product_img_cache[product_id] = None
            return None
        path = str(p.get('image_path') or '').strip()
        if not path or not os.path.exists(path):
            self._product_img_cache[product_id] = None
            return None
        try:
            img = Image.open(path)
            img = img.convert('RGBA')
            cols = int(self._grid_cols or 3)
            # Fit/crop to a square to better match TSX tiles (image fills the box)
            compact = bool(getattr(self, '_compact_ui', False))
            if compact:
                if cols >= 3:
                    target = (150, 150)
                else:
                    target = (170, 170)
            else:
                if cols >= 4:
                    target = (190, 190)
                elif cols == 3:
                    target = (230, 230)
                else:
                    target = (280, 280)
            try:
                img = ImageOps.fit(img, target, method=Image.LANCZOS, centering=(0.5, 0.5))
            except Exception:
                try:
                    img = ImageOps.fit(img, target, method=Image.ANTIALIAS, centering=(0.5, 0.5))
                except Exception:
                    img.thumbnail(target)
            imgtk = ImageTk.PhotoImage(img)
            self._product_img_cache[product_id] = imgtk
            return imgtk
        except Exception:
            self._product_img_cache[product_id] = None
            return None

    def _compute_and_lock_grid_cols(self):
        """Compute product grid columns once using actual container width."""
        if getattr(self, '_grid_cols_locked', False):
            return
        try:
            # Prefer container width; fallback to screen width
            w = int(self.products_canvas.winfo_width() or 0)
            if w <= 10:
                w = int(self.root.winfo_width() or 0)
            if w <= 10:
                w = int(self.root.winfo_screenwidth() or 1024)

            compact = bool(getattr(self, '_compact_ui', False))
            if compact:
                # In 1024x768 we want a dense grid like the reference (4 columns on the right panel)
                if w >= 620:
                    cols = 4
                elif w >= 460:
                    cols = 3
                else:
                    cols = 2
            else:
                # Keep tiles large enough so buttons don't get squashed
                # Prefer 3 columns unless the window is really wide
                if w >= 2000:
                    cols = 4
                elif w >= 1350:
                    cols = 3
                else:
                    cols = 2
            self._grid_cols = cols
        except Exception:
            self._grid_cols = int(self._grid_cols or 3)

        self._grid_cols_locked = True

    # ----------------------------
    # Cart
    # ----------------------------

    def _strip_asterisk_annotations(self, text: str) -> str:
        try:
            if not text:
                return text
            cleaned = re.sub(r'\*[^*]*\*', '', str(text))
            cleaned = re.sub(r'\s{2,}', ' ', cleaned).strip()
            return cleaned
        except Exception:
            return text

    def _set_cart_qty(self, product_id: int, variant_id: int, qty: int):
        if self._locked:
            return
        if not self._current_student:
            self._set_status('העבר כרטיס תלמיד לפתיחת קנייה', is_error=True)
            return
        if qty < 0:
            qty = 0
        pid = int(product_id or 0)
        vid = int(variant_id or 0)
        key = (pid, vid)
        if qty == 0:
            if key in self._cart:
                self._cart.pop(key, None)
        else:
            self._cart[key] = int(qty)
            
            # Show item on customer display when added
            try:
                display = self._ensure_customer_display()
                if display and display.enabled and qty > 0:
                    product = self._product_by_id.get(pid)
                    if product:
                        item_name = str(product.get('name', ''))
                        item_points = int(product.get('points', 0))
                        if vid > 0:
                            variant = self._variant_by_id.get(vid)
                            if variant:
                                item_name = f"{item_name} - {variant.get('name', '')}"
                                item_points = int(variant.get('points', item_points))
                        display.show_item(item_name, item_points)
            except Exception:
                pass
        
        self._refresh_cart_ui()

        # First: update displayed qty var immediately (cheap and reliable)
        try:
            q_total = int(self._sync_tile_qty_var(int(pid)) or 0)
        except Exception:
            q_total = 0

        # If we crossed the 0<->1 boundary we must rebuild the controls to swap "הוסף" <-> "+/-".
        try:
            prev = int((self._tile_last_qty_by_pid or {}).get(int(pid), -999999))
        except Exception:
            prev = -999999
        try:
            self._tile_last_qty_by_pid[int(pid)] = int(q_total)
        except Exception:
            pass
        crossed_boundary = (prev == -999999) or ((prev <= 0) != (int(q_total) <= 0))

        # Update only the affected tile to avoid flicker and keep scroll position.
        # Schedule refresh as well (some UI paths delay updates until next event).
        refreshed = False
        try:
            refreshed = bool(self._refresh_tile_controls(int(pid)))
        except Exception:
            refreshed = False
        try:
            self.root.after(0, lambda _pid=int(pid): self._refresh_tile_controls(_pid))
        except Exception:
            pass
        # Some UI paths (dialogs/grabs) delay visual updates; refresh THIS tile again on idle.
        try:
            self.root.after_idle(lambda _pid=int(pid): self._refresh_tile_controls(_pid))
        except Exception:
            pass
        # In some Tk/Windows setups, the 0<->1 swap can still be visually delayed.
        # Retry a couple of targeted refreshes ONLY when crossing the boundary.
        if bool(crossed_boundary):
            try:
                self.root.after(20, lambda _pid=int(pid): self._refresh_tile_controls(_pid))
            except Exception:
                pass
            try:
                self.root.after(80, lambda _pid=int(pid): self._refresh_tile_controls(_pid))
            except Exception:
                pass
        # Fallback: if tile reference isn't available (or refresh failed), re-render grid.
        # Avoid full re-render just because we crossed 0<->1; tile refresh handles swapping controls.
        if not refreshed:
            try:
                self.root.after(1, self._render_product_grid)
            except Exception:
                pass
        try:
            self.root.update_idletasks()
        except Exception:
            pass

    def _add_scheduled_service_to_cart(self, product_id: int, *, mode: str = 'auto'):
        if self._locked:
            return
        if not self._current_student:
            self._set_status('העבר כרטיס תלמיד לפתיחת קנייה', is_error=True)
            return

        pid = int(product_id or 0)
        svc = self._scheduled_by_pid.get(pid)
        if not svc:
            return

        # Check availability criteria
        try:
            st_cls = str(self._current_student.get('class_name') or '').strip()
        except Exception:
            st_cls = ''
        try:
            st_points = int(self._current_student.get('points', 0) or 0)
        except Exception:
            st_points = 0

        allowed = str(svc.get('allowed_classes') or '').strip()
        if allowed and st_cls:
            allowed_list = [x.strip() for x in allowed.split(',') if x.strip()]
            if allowed_list and (st_cls not in allowed_list):
                messagebox.showwarning('לא זמין', 'אתגר זה לא זמין לכיתה שלך')
                return

        try:
            minp = int(svc.get('min_points_required', 0) or 0)
        except Exception:
            minp = 0
        if minp > 0 and st_points < minp:
            messagebox.showwarning('לא מספיק נקודות', f'נדרשות לפחות {minp} נקודות עבור אתגר זה')
            return

        try:
            vid_selected = int(self._selected_variant_by_product.get(int(pid), 0) or 0)
        except Exception:
            vid_selected = 0
        try:
            sid = int(svc.get('id') or 0)
        except Exception:
            sid = 0
        if not sid:
            return

        dates = list(self._scheduled_dates_by_service.get(sid, []) or [])
        dates = [str(d or '').strip() for d in dates if str(d or '').strip()]
        if not dates:
            messagebox.showwarning('אין תאריכים', 'לא הוגדרו תאריכים לאתגר זה')
            return

        if mode != 'auto':
            self._open_scheduled_service_picker(pid)
            return

        try:
            student_id = int(self._current_student.get('id') or 0)
        except Exception:
            student_id = 0
        dur0 = int(svc.get('duration_minutes', 10) or 10)

        def _to_min(hhmm: str) -> int:
            try:
                hhmm = str(hhmm or '').strip()
                if ':' not in hhmm:
                    return -1
                hh, mm = hhmm.split(':', 1)
                return int(hh) * 60 + int(mm)
            except Exception:
                return -1

        for d in dates:
            try:
                slots = self.db.get_scheduled_service_slots(service_id=int(sid), service_date=str(d)) or []
            except Exception:
                slots = []

            try:
                existing = self.db.get_student_scheduled_reservations_on_date(student_id=int(student_id), service_date=str(d)) or []
            except Exception:
                existing = []

            def _conflicts(start_time: str) -> bool:
                sm = _to_min(start_time)
                if sm < 0:
                    return True
                em = sm + int(dur0 or 0)

                for r in (existing or []):
                    try:
                        os_ = _to_min(r.get('slot_start_time'))
                        od = int(r.get('duration_minutes') or 0)
                    except Exception:
                        os_ = -1
                        od = 0
                    if os_ < 0 or od <= 0:
                        continue
                    oe = os_ + od
                    if sm < oe and os_ < em:
                        return True

                for r in (self._scheduled_cart or []):
                    if str(r.get('service_date') or '').strip() != str(d):
                        continue
                    try:
                        os_ = _to_min(r.get('slot_start_time'))
                        od = int(r.get('duration_minutes') or 0)
                    except Exception:
                        os_ = -1
                        od = 0
                    if os_ < 0 or od <= 0:
                        continue
                    oe = os_ + od
                    if sm < oe and os_ < em:
                        return True

                return False

            for s in slots:
                if int(s.get('remaining', 0) or 0) <= 0:
                    continue
                stt = str(s.get('slot_start_time') or '').strip()
                if _conflicts(stt):
                    continue
                hr = self.db.create_scheduled_hold(
                    station_id=str(self.station_id or '').strip(),
                    student_id=int(student_id or 0),
                    service_id=int(sid),
                    service_date=str(d),
                    slot_start_time=str(stt),
                    duration_minutes=int(dur0),
                )
                if not hr or not hr.get('ok'):
                    continue
                self._scheduled_cart.append({
                    'product_id': int(pid),
                    'variant_id': int(vid_selected or 0),
                    'service_id': int(sid),
                    'service_date': str(d),
                    'slot_start_time': stt,
                    'duration_minutes': int(dur0),
                })
                self._refresh_cart_ui()
                self._render_product_grid()
                return

        messagebox.showwarning('אין זמן פנוי', 'אין סלוט פנוי שאינו מתנגש עם אתגר אחר של התלמיד')
        return

    def _open_scheduled_service_picker(self, product_id: int):
        pid = int(product_id or 0)
        svc = self._scheduled_by_pid.get(pid)
        if not svc:
            return
        try:
            sid = int(svc.get('id') or 0)
        except Exception:
            sid = 0
        if not sid:
            return

        dates = list(self._scheduled_dates_by_service.get(sid, []) or [])
        dates = [str(d or '').strip() for d in dates if str(d or '').strip()]
        if not dates:
            messagebox.showwarning('אין תאריכים', 'לא הוגדרו תאריכים לאתגר זה')
            return

        single_day = len(dates) == 1

        dlg = tk.Toplevel(self.root)
        dlg.title('בחירת זמן')
        dlg.configure(bg='#0f0f14')
        dlg.transient(self.root)
        dlg.grab_set()

        p = self._product_by_id.get(pid, {}) or {}
        name = (str(p.get('display_name') or '').strip() or str(p.get('name') or '').strip())
        name = self._strip_asterisk_annotations(name)
        tk.Label(dlg, text=name, font=('Arial', 18, 'bold'), fg='white', bg='#0f0f14').pack(pady=(14, 10))

        body = tk.Frame(dlg, bg='#0f0f14')
        body.pack(fill=tk.BOTH, expand=True, padx=16, pady=10)

        left = tk.Frame(body, bg='#0f0f14')
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        right = tk.Frame(body, bg='#0f0f14')
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        selected_date = {'value': dates[0]}
        selected_slot = {'value': ''}

        if not single_day:
            tk.Label(left, text='בחר יום', font=('Arial', 14, 'bold'), fg='white', bg='#0f0f14').pack(anchor='w')
            dates_lb = tk.Listbox(left, font=('Arial', 14))
            dates_lb.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
            for d in dates:
                he = hebrew_date_from_gregorian_str(d) or ''
                dates_lb.insert(tk.END, he or d)
            dates_lb.selection_set(0)
        else:
            dates_lb = None

        tk.Label(right, text='בחר שעה', font=('Arial', 14, 'bold'), fg='white', bg='#0f0f14').pack(anchor='w')
        slots_lb = tk.Listbox(right, font=('Arial', 14))
        slots_lb.pack(fill=tk.BOTH, expand=True, pady=(8, 0))

        def _load_slots(d: str):
            selected_slot['value'] = ''
            try:
                slots_lb.delete(0, tk.END)
            except Exception:
                pass
            slots = []
            try:
                slots = self.db.get_scheduled_service_slots(service_id=int(sid), service_date=str(d)) or []
            except Exception:
                slots = []
            for s in slots:
                t = str(s.get('slot_start_time') or '').strip()
                rem = int(s.get('remaining', 0) or 0)
                cap = int(s.get('capacity', 0) or 0)
                if rem <= 0:
                    txt = f"{t}  (מלא)"
                else:
                    txt = f"{t}  ({rem}/{cap})"
                slots_lb.insert(tk.END, txt)

        def _on_date_change(_event=None):
            if dates_lb is None:
                return
            try:
                idx = int(dates_lb.curselection()[0])
            except Exception:
                idx = 0
            if idx < 0 or idx >= len(dates):
                idx = 0
            selected_date['value'] = dates[idx]
            _load_slots(selected_date['value'])

        def _on_slot_change(_event=None):
            try:
                idx = int(slots_lb.curselection()[0])
            except Exception:
                idx = -1
            if idx < 0:
                selected_slot['value'] = ''
                return
            raw = str(slots_lb.get(idx) or '')
            t = raw.split(' ', 1)[0].strip()
            if '(מלא)' in raw:
                selected_slot['value'] = ''
                return
            selected_slot['value'] = t

        if dates_lb is not None:
            dates_lb.bind('<<ListboxSelect>>', _on_date_change)
        slots_lb.bind('<<ListboxSelect>>', _on_slot_change)

        _load_slots(selected_date['value'])

        btns = tk.Frame(dlg, bg='#0f0f14')
        btns.pack(pady=(10, 14))
        btns.grid_columnconfigure(0, weight=1)
        btns.grid_columnconfigure(1, weight=1)

        def _choose():
            if not selected_slot['value']:
                messagebox.showwarning('אזהרה', 'בחר שעה פנויה')
                return
            try:
                student_id = int((self._current_student or {}).get('id') or 0)
            except Exception:
                student_id = 0
            hr = self.db.create_scheduled_hold(
                station_id=str(self.station_id or '').strip(),
                student_id=int(student_id or 0),
                service_id=int(sid),
                service_date=str(selected_date['value']),
                slot_start_time=str(selected_slot['value']),
                duration_minutes=int(svc.get('duration_minutes', 10) or 10),
            )
            if not hr or not hr.get('ok'):
                messagebox.showwarning('אין מקום', str((hr or {}).get('error') or 'הסלוט מלא'))
                try:
                    _load_slots(str(selected_date['value']))
                except Exception:
                    pass
                return
            self._scheduled_cart.append({
                'product_id': int(pid),
                'service_id': int(sid),
                'service_date': str(selected_date['value']),
                'slot_start_time': str(selected_slot['value']),
                'duration_minutes': int(svc.get('duration_minutes', 10) or 10),
            })
            dlg.destroy()
            self._refresh_cart_ui()
            self._render_product_grid()

        # equal-size buttons
        tk.Button(btns, text='אוטומטי', command=lambda: (dlg.destroy(), self._add_scheduled_service_to_cart(pid, mode='auto')),
                  font=('Arial', 16, 'bold'), bg='#27ae60', fg='white', padx=18, pady=12).grid(row=0, column=0, sticky='ew', padx=(0, 8))
        tk.Button(btns, text='ידני', command=_choose,
                  font=('Arial', 16, 'bold'), bg='#2980b9', fg='white', padx=18, pady=12).grid(row=0, column=1, sticky='ew', padx=(8, 0))
        tk.Button(dlg, text='ביטול', command=dlg.destroy, font=('Arial', 14, 'bold'), bg='#7f8c8d', fg='white', padx=18, pady=10).pack(pady=(0, 14))

        try:
            dlg.minsize(740, 520)
        except Exception:
            pass

    def _get_variant_for_cart_key(self, pid: int, vid: int) -> dict:
        if int(vid or 0) > 0:
            return dict(self._variant_by_id.get(int(vid), {}) or {})
        p = self._product_by_id.get(int(pid), {}) or {}
        return {
            'id': 0,
            'product_id': int(pid),
            'variant_name': 'ברירת מחדל',
            'display_name': str(p.get('display_name') or '').strip(),
            'price_points': int(p.get('price_points', 0) or 0),
            'stock_qty': p.get('stock_qty', None),
            'deduct_points': int(p.get('deduct_points', 1) or 0),
            'is_active': 1,
        }

    def _increment_product(self, product_id: int):
        if self._locked:
            return
        if not self._current_student:
            self._set_status('העבר כרטיס תלמיד לפתיחת קנייה', is_error=True)
            return
        pid = int(product_id or 0)
        vars_ = self._variants_by_product.get(pid, [])
        if len(vars_) > 1:
            # If a variant is already selected (or exists in cart), increment it directly.
            try:
                vid_sel = int(self._selected_variant_by_product.get(pid, 0) or 0)
            except Exception:
                vid_sel = 0
            if not vid_sel:
                try:
                    existing_vids = sorted({int(kvid) for (kpid, kvid) in (self._cart or {}).keys() if int(kpid) == int(pid) and int(kvid) > 0})
                except Exception:
                    existing_vids = []
                if existing_vids:
                    try:
                        vid_sel = int(existing_vids[-1] or 0)
                        self._selected_variant_by_product[int(pid)] = int(vid_sel)
                    except Exception:
                        vid_sel = 0
            if not vid_sel:
                self._open_variant_picker(pid)
                return
            vid = int(vid_sel)
        else:
            vid = 0
            if len(vars_) == 1:
                try:
                    vid = int(vars_[0].get('id') or 0)
                except Exception:
                    vid = 0
        # If the cart already contains this product under a different variant_id (e.g. legacy), prefer that.
        if int(vid or 0) == 0:
            try:
                existing_vids = sorted({int(kvid) for (kpid, kvid) in (self._cart or {}).keys() if int(kpid) == int(pid)})
            except Exception:
                existing_vids = []
            if existing_vids:
                try:
                    vid = int(existing_vids[-1] or 0)
                    self._selected_variant_by_product[int(pid)] = int(vid)
                except Exception:
                    pass
        key = (pid, int(vid))
        try:
            sid = int((self._current_student or {}).get('id') or 0)
        except Exception:
            sid = 0
        if not sid:
            self._set_status('בחר תלמיד', is_error=True)
            return

        hr = self.db.apply_product_hold_delta(
            station_id=str(self.station_id or '').strip(),
            student_id=int(sid),
            product_id=int(pid),
            variant_id=int(vid),
            delta_qty=1,
        )
        if not hr or not hr.get('ok'):
            self._set_status(str((hr or {}).get('error') or 'אין מספיק מלאי'), is_error=True)
            return

        self._set_cart_qty(pid, int(vid), int(self._cart.get(key, 0) or 0) + 1)
        # Force immediate redraw of the tile controls (avoid waiting for an unrelated UI refresh)
        try:
            t = self._tile_by_pid.get(int(pid))
            if t is not None and callable(getattr(t, '_refresh_controls', None)):
                t._refresh_controls()
        except Exception:
            pass
        # Some Windows/Tk setups can delay the visual swap from "הוסף" to +/-.
        # Retry a couple of targeted refreshes (not full grid render).
        try:
            self.root.after(0, lambda _pid=int(pid): self._refresh_tile_controls(_pid))
        except Exception:
            pass
        try:
            self.root.after(30, lambda _pid=int(pid): self._refresh_tile_controls(_pid))
        except Exception:
            pass
        try:
            self.root.after(120, lambda _pid=int(pid): self._refresh_tile_controls(_pid))
        except Exception:
            pass
        try:
            self.root.update_idletasks()
        except Exception:
            pass

    def _decrement_product(self, product_id: int):
        if self._locked:
            return
        if not self._current_student:
            self._set_status('העבר כרטיס תלמיד לפתיחת קנייה', is_error=True)
            return
        pid = int(product_id or 0)
        vars_ = self._variants_by_product.get(pid, [])
        if len(vars_) > 1:
            # decrease selected variant if chosen; otherwise pick an existing variant from cart
            try:
                vid = int(self._selected_variant_by_product.get(pid, 0) or 0)
            except Exception:
                vid = 0
            if not vid:
                try:
                    existing_vids = sorted({int(kvid) for (kpid, kvid) in (self._cart or {}).keys() if int(kpid) == int(pid) and int(kvid) > 0})
                except Exception:
                    existing_vids = []
                if existing_vids:
                    try:
                        vid = int(existing_vids[-1] or 0)
                        self._selected_variant_by_product[int(pid)] = int(vid)
                    except Exception:
                        vid = 0
            if not vid:
                return
        else:
            vid = 0
            if len(vars_) == 1:
                try:
                    vid = int(vars_[0].get('id') or 0)
                except Exception:
                    vid = 0
            # If the cart already contains this product under a different variant_id (e.g. legacy), prefer that.
            if int(vid or 0) == 0:
                try:
                    existing_vids = sorted({int(kvid) for (kpid, kvid) in (self._cart or {}).keys() if int(kpid) == int(pid)})
                except Exception:
                    existing_vids = []
                if existing_vids:
                    try:
                        vid = int(existing_vids[-1] or 0)
                        self._selected_variant_by_product[int(pid)] = int(vid)
                    except Exception:
                        pass
        key = (pid, int(vid))
        cur = int(self._cart.get(key, 0) or 0)
        if cur <= 0:
            return

        try:
            sid = int((self._current_student or {}).get('id') or 0)
        except Exception:
            sid = 0
        if not sid:
            self._set_status('בחר תלמיד', is_error=True)
            return

        hr = self.db.apply_product_hold_delta(
            station_id=str(self.station_id or '').strip(),
            student_id=int(sid),
            product_id=int(pid),
            variant_id=int(vid),
            delta_qty=-1,
        )
        if not hr or not hr.get('ok'):
            self._set_status(str((hr or {}).get('error') or 'שגיאה בשחרור שריון'), is_error=True)
            return
        self._set_cart_qty(pid, int(vid), cur - 1)

    def _open_variant_picker(self, product_id: int):
        if self._locked:
            return
        if not self._current_student:
            self._set_status('העבר כרטיס תלמיד לפתיחת קנייה', is_error=True)
            return
        pid = int(product_id or 0)
        vars_ = self._variants_by_product.get(pid, [])
        if not vars_:
            return

        dlg = tk.Toplevel(self.root)
        dlg.title('בחר אפשרות')
        dlg.configure(bg='#0f0f14')
        dlg.transient(self.root)
        dlg.grab_set()

        p = self._product_by_id.get(pid, {}) or {}
        name = (str(p.get('display_name') or '').strip() or str(p.get('name') or '').strip())
        name = self._strip_asterisk_annotations(name)
        tk.Label(dlg, text=name, font=('Arial', 18, 'bold'), fg='white', bg='#0f0f14').pack(pady=(14, 10))

        grid = tk.Frame(dlg, bg='#0f0f14')
        grid.pack(fill=tk.BOTH, expand=True, padx=16, pady=10)

        # large touch buttons
        cols = 2
        for i, v in enumerate(vars_):
            try:
                vid = int(v.get('id') or 0)
            except Exception:
                vid = 0
            vname = self._strip_asterisk_annotations(str(v.get('variant_name') or '').strip())
            try:
                price = int(v.get('price_points', 0) or 0)
            except Exception:
                price = 0
            stock = v.get('stock_qty', None)
            stock_txt = '∞' if stock is None else str(stock)
            txt = f"{vname}\n{price} נקודות\nמלאי: {stock_txt}"

            r = i // cols
            c = i % cols

            def _choose(_vid=vid):
                self._selected_variant_by_product[pid] = int(_vid)
                key = (pid, int(_vid))
                try:
                    sid = int((self._current_student or {}).get('id') or 0)
                except Exception:
                    sid = 0
                if not sid:
                    self._set_status('בחר תלמיד', is_error=True)
                    return
                hr = self.db.apply_product_hold_delta(
                    station_id=str(self.station_id or '').strip(),
                    student_id=int(sid),
                    product_id=int(pid),
                    variant_id=int(_vid),
                    delta_qty=1,
                )
                if not hr or not hr.get('ok'):
                    self._set_status(str((hr or {}).get('error') or 'אין מספיק מלאי'), is_error=True)
                    return
                self._set_cart_qty(pid, int(_vid), int(self._cart.get(key, 0) or 0) + 1)
                try:
                    dlg.destroy()
                except Exception:
                    pass
                # Ensure the underlying tile redraw happens after dialog/grab releases.
                try:
                    self.root.after(0, lambda _pid=int(pid): (self._tile_by_pid.get(_pid) and getattr(self._tile_by_pid.get(_pid), '_refresh_controls', lambda: None)()))
                except Exception:
                    pass
                try:
                    self.root.after_idle(self._refresh_all_tile_controls)
                except Exception:
                    pass

            b = tk.Button(grid, text=txt, command=_choose, font=('Arial', 16, 'bold'), bg='#2980b9', fg='white', padx=18, pady=18)
            b.grid(row=r, column=c, padx=10, pady=10, sticky='nsew')
            grid.grid_columnconfigure(c, weight=1)
            grid.grid_rowconfigure(r, weight=1)

        tk.Button(dlg, text='ביטול', command=dlg.destroy, font=('Arial', 14, 'bold'), bg='#7f8c8d', fg='white', padx=18, pady=10).pack(pady=(0, 14))

        try:
            dlg.minsize(520, 420)
        except Exception:
            pass

    def _refresh_cart_ui(self):
        try:
            for w in list(self.cart_items_container.winfo_children()):
                try:
                    w.destroy()
                except Exception:
                    pass
        except Exception:
            pass
        self._cart_row_meta = []
        total = 0

        compact = bool(getattr(self, '_compact_ui', False))
        item_bg = '#101826'
        border = '#1f2a44'
        title_fg = 'white'
        sub_fg = '#93c5fd'
        price_fg = '#22c55e'
        del_fg = '#ef4444'
        pad_x = 8 if compact else 10
        pad_y = 7 if compact else 9
        title_font = ('Arial', 12 if compact else 13, 'bold')
        sub_font = ('Arial', 10 if compact else 11)
        price_font = ('Arial', 12 if compact else 13, 'bold')

        def _fmt_time_range(start_hhmm: str, duration_min: int) -> str:
            try:
                s = str(start_hhmm or '').strip()
                if ':' not in s:
                    return s
                hh, mm = s.split(':', 1)
                start_m = int(hh) * 60 + int(mm)
                end_m = start_m + int(duration_min or 0)
                eh = int(end_m // 60) % 24
                em = int(end_m % 60)
                return f"{s}-{eh:02d}:{em:02d}"
            except Exception:
                return str(start_hhmm or '').strip()

        def _add_item_row(*, meta: dict, title: str, subtitle: str, total_item_points: int):
            self._cart_row_meta.append(dict(meta or {}))

            row = tk.Frame(self.cart_items_container, bg=item_bg, highlightthickness=1, highlightbackground=border)
            row.pack(fill=tk.X, pady=(0, 8))

            top = tk.Frame(row, bg=item_bg)
            top.pack(fill=tk.X, padx=pad_x, pady=(pad_y, 0))

            btn = tk.Button(top, text='✕', command=lambda m=dict(meta or {}): self._remove_cart_row(m),
                            font=('Arial', 12, 'bold'), bg=item_bg, fg=del_fg, bd=0, activebackground=item_bg, activeforeground=del_fg)
            btn.pack(side=tk.LEFT, padx=(0, 8))

            tk.Label(top, text=title, font=title_font, fg=title_fg, bg=item_bg, anchor='e', justify='right').pack(side=tk.RIGHT, fill=tk.X, expand=True)

            bottom = tk.Frame(row, bg=item_bg)
            bottom.pack(fill=tk.X, padx=pad_x, pady=(4, pad_y))

            tk.Label(bottom, text=f"\u200f{total_item_points} נקודות", font=price_font, fg=price_fg, bg=item_bg, anchor='w', justify='left').pack(side=tk.LEFT)
            if subtitle:
                tk.Label(bottom, text=f"\u200f{subtitle}", font=sub_font, fg=sub_fg, bg=item_bg, anchor='e', justify='right').pack(side=tk.RIGHT, fill=tk.X, expand=True)

        for (pid, vid), qty in sorted(self._cart.items(), key=lambda x: (x[0][0], x[0][1])):
            p = self._product_by_id.get(pid) or {}
            name = (str(p.get('display_name') or '').strip() or str(p.get('name') or '').strip())
            name = self._strip_asterisk_annotations(name)
            v = self._get_variant_for_cart_key(pid, vid)
            vname = str(v.get('variant_name') or '').strip()
            vname = self._strip_asterisk_annotations(vname)
            try:
                price = int(v.get('price_points', 0) or 0)
            except Exception:
                price = 0
            if vid and vname and vname != 'ברירת מחדל':
                disp = f"{name} – {vname}"
            else:
                disp = name
            total_item = price * int(qty)
            total += total_item
            _add_item_row(
                meta={'type': 'product', 'product_id': int(pid), 'variant_id': int(vid), 'qty': int(qty)},
                title=str(disp),
                subtitle=f"{int(qty)} × {int(price)} נקודות",
                total_item_points=int(total_item),
            )

        # scheduled services (each entry is qty=1)
        for it in (self._scheduled_cart or []):
            try:
                pid = int(it.get('product_id') or 0)
            except Exception:
                pid = 0
            if not pid:
                continue
            try:
                vid = int(it.get('variant_id') or 0)
            except Exception:
                vid = 0
            p = self._product_by_id.get(pid) or {}
            name = (str(p.get('display_name') or '').strip() or str(p.get('name') or '').strip())

            if vid:
                v = self._get_variant_for_cart_key(pid, vid)
                vname = str(v.get('variant_name') or '').strip()
                if vname and vname != 'ברירת מחדל':
                    name = f"{name} – {vname}"
                try:
                    price = int(v.get('price_points', p.get('price_points', 0)) or 0)
                except Exception:
                    price = int(p.get('price_points', 0) or 0)
            else:
                try:
                    price = int(p.get('price_points', 0) or 0)
                except Exception:
                    price = 0

            sd = str(it.get('service_date') or '').strip()
            st = str(it.get('slot_start_time') or '').strip()
            try:
                dur = int(it.get('duration_minutes', 0) or 0)
            except Exception:
                dur = 0

            date_txt = ''
            try:
                sid = int(it.get('service_id') or 0)
            except Exception:
                sid = 0
            allowed_dates = list(self._scheduled_dates_by_service.get(sid, []) or [])
            if sid and len(allowed_dates) > 1:
                date_txt = hebrew_date_from_gregorian_str(sd) or ''
            # if only one date configured -> no date
            if date_txt:
                disp = f"{name} – {date_txt}"
            else:
                disp = f"{name}"
            total_item = int(price)
            total += int(price)
            subtitle = _fmt_time_range(str(st), int(dur))
            if date_txt:
                subtitle = f"{date_txt} · {subtitle}"
            _add_item_row(
                meta={
                    'type': 'scheduled',
                    'product_id': int(pid),
                    'variant_id': int(vid or 0),
                    'service_id': int(sid),
                    'service_date': str(sd),
                    'slot_start_time': str(st),
                    'duration_minutes': int(dur),
                },
                title=str(disp),
                subtitle=str(subtitle),
                total_item_points=int(price),
            )

        # Keep product tiles in sync even if cart state changes outside of _set_cart_qty
        try:
            self._refresh_all_tile_controls()
        except Exception:
            pass

        bal = '—'
        after = '—'
        if self._current_student:
            try:
                bal = str(int(self._current_student.get('points', 0) or 0))
                after = str(int(self._current_student.get('points', 0) or 0) - int(self._get_total_deduct_points()))
            except Exception:
                pass
        self.total_var.set(f"סה\"כ קנייה: {total} נקודות")
        self.balance_var.set(f"יתרת נקודות: {bal} נקודות")
        self.after_var.set(f"יתרה לאחר הקנייה: {after} נקודות")
        self.btn_pay.config(text=f"תשלום ({total} נקודות)")

        try:
            self.cart_canvas.configure(scrollregion=self.cart_canvas.bbox('all'))
        except Exception:
            pass

    def _remove_cart_row(self, meta: dict):
        if self._locked:
            return
        if not self._current_student:
            return
        if not isinstance(meta, dict):
            return

        if meta.get('type') == 'product':
            try:
                pid = int(meta.get('product_id') or 0)
                vid = int(meta.get('variant_id') or 0)
                qty = int(meta.get('qty') or 0)
            except Exception:
                pid, vid, qty = 0, 0, 0
            if not pid or qty <= 0:
                return
            try:
                sid = int((self._current_student or {}).get('id') or 0)
            except Exception:
                sid = 0
            if not sid:
                return
            try:
                hr = self.db.apply_product_hold_delta(
                    station_id=str(self.station_id or '').strip(),
                    student_id=int(sid),
                    product_id=int(pid),
                    variant_id=int(vid),
                    delta_qty=-int(qty),
                )
                if not hr or not hr.get('ok'):
                    self._set_status(str((hr or {}).get('error') or 'שגיאה בשחרור שריון'), is_error=True)
                    return
            except Exception:
                pass
            try:
                self._cart.pop((int(pid), int(vid)), None)
            except Exception:
                pass
            self._refresh_cart_ui()
            self._render_product_grid()
            return

        if meta.get('type') == 'scheduled':
            try:
                student_id = int((self._current_student or {}).get('id') or 0)
            except Exception:
                student_id = 0
            if not student_id:
                return
            try:
                self.db.release_scheduled_hold(
                    station_id=str(self.station_id or '').strip(),
                    student_id=int(student_id),
                    service_id=int(meta.get('service_id') or 0),
                    service_date=str(meta.get('service_date') or '').strip(),
                    slot_start_time=str(meta.get('slot_start_time') or '').strip(),
                )
            except Exception:
                pass

            removed = False
            for i, it in enumerate(list(self._scheduled_cart or [])):
                try:
                    if int(it.get('service_id') or 0) != int(meta.get('service_id') or 0):
                        continue
                    if str(it.get('service_date') or '').strip() != str(meta.get('service_date') or '').strip():
                        continue
                    if str(it.get('slot_start_time') or '').strip() != str(meta.get('slot_start_time') or '').strip():
                        continue
                except Exception:
                    continue
                try:
                    self._scheduled_cart.pop(i)
                except Exception:
                    pass
                removed = True
                break
            if removed:
                self._refresh_cart_ui()
                self._render_product_grid()

    def _on_cart_tree_click(self, event=None):
        if self._locked:
            return
        if not self._current_student:
            return
        try:
            region = self.cart_tree.identify('region', event.x, event.y)
            if region != 'cell':
                return
            col = self.cart_tree.identify_column(event.x)
            # '#1' is the first column = 'del'
            if str(col or '') != '#1':
                return
            row_id = self.cart_tree.identify_row(event.y)
            if not row_id:
                return
            all_ids = list(self.cart_tree.get_children())
            idx = all_ids.index(row_id)
        except Exception:
            return
        try:
            meta = (self._cart_row_meta or [])[idx]
        except Exception:
            meta = None
        if not isinstance(meta, dict):
            return
        self._remove_cart_row(meta)

    def _on_cart_row_double_click(self, _event=None):
        if self._locked:
            return
        if not self._current_student:
            return
        try:
            item_id = self.cart_tree.focus()
        except Exception:
            item_id = ''
        if not item_id:
            return
        try:
            all_ids = list(self.cart_tree.get_children())
            idx = all_ids.index(item_id)
        except Exception:
            idx = -1
        if idx < 0:
            return
        meta = None
        try:
            meta = (self._cart_row_meta or [])[idx]
        except Exception:
            meta = None
        if not isinstance(meta, dict):
            return

        if meta.get('type') == 'product':
            self._decrement_product(int(meta.get('product_id') or 0))
            return

        if meta.get('type') == 'scheduled':
            try:
                student_id = int((self._current_student or {}).get('id') or 0)
            except Exception:
                student_id = 0
            if not student_id:
                return
            try:
                self.db.release_scheduled_hold(
                    station_id=str(self.station_id or '').strip(),
                    student_id=int(student_id),
                    service_id=int(meta.get('service_id') or 0),
                    service_date=str(meta.get('service_date') or '').strip(),
                    slot_start_time=str(meta.get('slot_start_time') or '').strip(),
                )
            except Exception:
                pass

            # remove one matching scheduled entry from cart
            removed = False
            for i, it in enumerate(list(self._scheduled_cart or [])):
                if str(it.get('service_date') or '').strip() != str(meta.get('service_date') or '').strip():
                    continue
                if str(it.get('slot_start_time') or '').strip() != str(meta.get('slot_start_time') or '').strip():
                    continue
                try:
                    if int(it.get('service_id') or 0) != int(meta.get('service_id') or 0):
                        continue
                except Exception:
                    continue
                self._scheduled_cart.pop(i)
                removed = True
                break
            if removed:
                self._refresh_cart_ui()
                self._render_product_grid()
            return

    def _remove_one_selected_cart_item(self):
        self._touch_activity()
        if self._locked:
            return
        if not self._current_student:
            return
        try:
            sel = self.cart_tree.selection()
        except Exception:
            sel = ()
        if not sel:
            return
        try:
            all_ids = list(self.cart_tree.get_children())
            idx = all_ids.index(sel[0])
        except Exception:
            idx = -1
        if idx < 0:
            return
        meta = None
        try:
            meta = (self._cart_row_meta or [])[idx]
        except Exception:
            meta = None
        if not isinstance(meta, dict):
            return

        if meta.get('type') == 'product':
            try:
                self._decrement_product(int(meta.get('product_id') or 0))
            except Exception:
                pass
            return

        if meta.get('type') == 'scheduled':
            try:
                student_id = int((self._current_student or {}).get('id') or 0)
            except Exception:
                student_id = 0
            if not student_id:
                return
            try:
                self.db.release_scheduled_hold(
                    station_id=str(self.station_id or '').strip(),
                    student_id=int(student_id),
                    service_id=int(meta.get('service_id') or 0),
                    service_date=str(meta.get('service_date') or '').strip(),
                    slot_start_time=str(meta.get('slot_start_time') or '').strip(),
                )
            except Exception:
                pass

            removed = False
            for i, it in enumerate(list(self._scheduled_cart or [])):
                if str(it.get('service_date') or '').strip() != str(meta.get('service_date') or '').strip():
                    continue
                if str(it.get('slot_start_time') or '').strip() != str(meta.get('slot_start_time') or '').strip():
                    continue
                try:
                    if int(it.get('service_id') or 0) != int(meta.get('service_id') or 0):
                        continue
                except Exception:
                    continue
                self._scheduled_cart.pop(i)
                removed = True
                break
            return
        if not card_id:
            self._set_status('כרטיס לא תקין', is_error=True)
            return
        try:
            card_id = int(card_id)
        except Exception:
            self._set_status('כרטיס לא תקין', is_error=True)
            return
        if not card_id:
            self._set_status('כרטיס לא תקין', is_error=True)
            return
        try:
            student = self.db.get_student_by_card_id(card_id)
        except Exception:
            student = None
        if not student:
            self._set_status('תלמיד לא נמצא', is_error=True)
            return
        self._current_student = student
        self._refresh_cart_ui()
        self._render_product_grid()

    def _open_student_history_dialog(self):
        self._touch_activity()
        if bool(getattr(self, '_license_blocked', False)):
            try:
                self._set_status('עמדת קופה לא מורשית – אין אפשרות לבצע פעולות', is_error=True)
            except Exception:
                pass
            return
        if self._locked:
            return
        if not self._current_student:
            self._set_status('בחר תלמיד', is_error=True)
            return
        try:
            student_id = int((self._current_student or {}).get('id') or 0)
        except Exception:
            student_id = 0
        if not student_id:
            return

        dlg = tk.Toplevel(self.root)
        dlg.title('🧾 היסטוריה')
        dlg.configure(bg='#0f0f14')
        try:
            dlg.minsize(820, 520)
        except Exception:
            pass
        dlg.transient(self.root)
        dlg.grab_set()

        tk.Label(dlg, text='בחר רכישה (היסטוריית התלמיד)', font=('Arial', 14, 'bold'), fg='white', bg='#0f0f14').pack(pady=(12, 8))

        frame = tk.Frame(dlg, bg='#0f0f14')
        frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 10))

        try:
            style = ttk.Style()
            style.configure('History.Treeview',
                            font=('Arial', 12),
                            rowheight=30,
                            background='#0b1220',
                            fieldbackground='#0b1220',
                            foreground='white')
            style.configure('History.Treeview.Heading',
                            font=('Arial', 12, 'bold'),
                            background='#111827',
                            foreground='white')
            try:
                style.map('History.Treeview.Heading', background=[('active', '#1f2937')])
            except Exception:
                pass
        except Exception:
            pass

        # Track selected items for touchscreen (checkboxes)
        selected_items = set()
        
        cols = ('select', 'purchase_id', 'created_at', 'item', 'qty', 'total', 'refunded')
        tree = ttk.Treeview(frame, columns=cols, show='headings', height=16, style='History.Treeview')
        tree.heading('select', text='☑')
        tree.heading('purchase_id', text='מס\' עסקה')
        tree.heading('created_at', text='תאריך/שעה')
        tree.heading('item', text='פריט')
        tree.heading('qty', text='כמות')
        tree.heading('total', text='סה"כ נק')
        tree.heading('refunded', text='בוטל')

        tree.column('select', width=50, anchor='center')
        tree.column('purchase_id', width=90, anchor='center')
        tree.column('created_at', width=150, anchor='center')
        tree.column('item', width=270, anchor='e')
        tree.column('qty', width=60, anchor='center')
        tree.column('total', width=90, anchor='center')
        tree.column('refunded', width=60, anchor='center')

        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=tree.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        tree.configure(yscrollcommand=sb.set)

        try:
            tree.tag_configure('odd', background='#0b1220', foreground='white')
            tree.tag_configure('even', background='#0f172a', foreground='white')
            tree.tag_configure('refunded', foreground='#fca5a5')
        except Exception:
            pass

        # Toggle checkbox on click (for touchscreen)
        def _toggle_checkbox(event):
            region = tree.identify_region(event.x, event.y)
            if region != "cell":
                return
            item = tree.identify_row(event.y)
            if not item:
                return
            
            # Toggle selection
            if item in selected_items:
                selected_items.remove(item)
                # Update checkbox display
                vals = list(tree.item(item, 'values'))
                vals[0] = '☐'
                tree.item(item, values=vals)
            else:
                selected_items.add(item)
                # Update checkbox display
                vals = list(tree.item(item, 'values'))
                vals[0] = '☑'
                tree.item(item, values=vals)
        
        tree.bind('<Button-1>', _toggle_checkbox)

        btns = tk.Frame(dlg, bg='#0f0f14')
        btns.pack(fill=tk.X, padx=12, pady=(0, 12))

        def _get_selected_purchase_ids() -> list:
            """Get all selected purchase IDs based on checkboxes"""
            ids = []
            for item in selected_items:
                try:
                    vals = tree.item(item).get('values') or ()
                    pid = int(vals[1]) if len(vals) > 1 else 0  # Index 1 now (after checkbox column)
                    if pid > 0:
                        ids.append(pid)
                except Exception:
                    pass
            return ids
        
        def _get_selected_purchase_id() -> int:
            """Get first selected purchase ID (for backward compatibility)"""
            ids = _get_selected_purchase_ids()
            return ids[0] if ids else 0

        def _reprint_selected():
            self._touch_activity()
            pid = _get_selected_purchase_id()
            if not pid:
                return
            try:
                self._reprint_receipt_from_purchase_id(int(pid))
            except Exception:
                pass

        def _refund_selected():
            self._touch_activity()
            pids = _get_selected_purchase_ids()
            if not pids:
                return

            # confirm
            count = len(pids)
            msg = f'לבטל {count} רכישות ולהחזיר נקודות?' if count > 1 else 'לבטל רכישה זו ולהחזיר נקודות?'
            if not self._touch_confirm(title='ביטול קנייה', message=msg, ok_text='בטל קנייה', cancel_text='חזור'):
                return

            # No reason needed
            reason = ''

            # operator identity
            op = getattr(self, '_operator', None) or {}
            op_name = ''
            try:
                op_name = str(op.get('name') or '').strip()
            except Exception:
                op_name = ''
            if not op_name:
                try:
                    op_name = f"{str(op.get('first_name') or '').strip()} {str(op.get('last_name') or '').strip()}".strip()
                except Exception:
                    op_name = ''
            if not op_name:
                op_name = 'מפעיל'

            try:
                op_id = int(op.get('id') or 0)
            except Exception:
                op_id = 0

            approver = {'id': int(op_id) if op_id else None, 'name': str(op_name or '').strip()}

            # Cancel all selected purchases
            total_refunded = 0
            failed_count = 0
            
            for pid in pids:
                try:
                    rr = self.db.refund_purchase(
                        purchase_id=int(pid),
                        approved_by_teacher=approver,
                        reason=str(reason or '').strip(),
                        station_type='cashier',
                    )
                    if rr and rr.get('ok'):
                        try:
                            total_refunded += int((rr or {}).get('refunded_points') or 0)
                        except Exception:
                            pass
                    else:
                        failed_count += 1
                except Exception as e:
                    failed_count += 1
            
            # Show result
            if failed_count > 0:
                messagebox.showwarning('בוצע חלקית', f'בוטלו {len(pids) - failed_count} מתוך {len(pids)} קניות\nהוחזרו {total_refunded} נקודות', parent=dlg)
            else:
                messagebox.showinfo('בוצע', f'בוטלו {len(pids)} קניות והוחזרו {total_refunded} נקודות', parent=dlg)

            # refresh dialog + current student balance
            try:
                self._current_student = self.db.get_student_by_id(int(student_id))
                try:
                    _pts_dbg = (self._current_student or {}).get('points', None)
                except Exception:
                    _pts_dbg = None
                print(f"[CANCEL] Refreshed student data: {self._current_student.get('first_name')} - points: {_pts_dbg}")
            except Exception as e:
                print(f"[CANCEL] Error refreshing student: {e}")
            
            # Update UI with new balance - update the points label in header
            try:
                if self._current_student:
                    pts_raw = (self._current_student or {}).get('points', None)
                    if pts_raw is None:
                        print("[CANCEL] Student points is None - keeping existing UI value")
                    else:
                        pts = int(pts_raw or 0)
                        print(f"[CANCEL] Updating UI with points: {pts}")
                        self.student_points_label.config(text=f'{pts} נקודות')
                else:
                    print("[CANCEL] No current student to update")
            except Exception as e:
                print(f"[CANCEL] Error updating points label: {e}")
                import traceback
                traceback.print_exc()
            
            try:
                self._refresh_cart_ui()
            except Exception:
                pass

            try:
                tree.delete(*tree.get_children())
            except Exception:
                pass
            try:
                rows2 = self.db.get_student_purchases(int(student_id), limit=400, include_refunded=True) or []
            except Exception:
                rows2 = []
            for r2 in rows2:
                try:
                    pid2 = int(r2.get('id') or 0)
                except Exception:
                    pid2 = 0
                if not pid2:
                    continue
                created_at2 = str(r2.get('created_at') or '').strip()[:16]
                qty2 = r2.get('qty')
                total2 = r2.get('total_points')
                refunded2 = 'כן' if int(r2.get('is_refunded', 0) or 0) == 1 else ''
                prod_name2 = str(r2.get('product_display_name') or '').strip() or str(r2.get('product_name') or '').strip()
                var_name2 = str(r2.get('variant_display_name') or '').strip() or str(r2.get('variant_name') or '').strip()
                item2 = (f"{prod_name2} - {var_name2}".strip(' -') if var_name2 else prod_name2)
                tree.insert('', 'end', values=('☐', pid2, created_at2, item2, qty2, total2, refunded2))

        tk.Button(btns, text='⛔ ביטול קנייה', command=_refund_selected, font=('Arial', 16, 'bold'), bg='#e74c3c', fg='white', padx=18, pady=10).pack(side=tk.RIGHT, padx=(0, 10))
        tk.Button(btns, text='🖨 הדפס מחדש', command=_reprint_selected, font=('Arial', 16, 'bold'), bg='#27ae60', fg='white', padx=18, pady=10).pack(side=tk.RIGHT, padx=(0, 10))
        tk.Button(btns, text='סגור', command=dlg.destroy, font=('Arial', 14, 'bold'), bg='#7f8c8d', fg='white', padx=18, pady=10).pack(side=tk.RIGHT)

        try:
            tree.bind('<Double-1>', lambda _e: _reprint_selected())
        except Exception:
            pass

        try:
            rows = self.db.get_student_purchases(int(student_id), limit=400, include_refunded=True) or []
        except Exception:
            rows = []
        for i, r in enumerate(rows):
            try:
                pid = int(r.get('id') or 0)
            except Exception:
                pid = 0
            if not pid:
                continue
            created_at = str(r.get('created_at') or '').strip()[:16]
            qty = r.get('qty')
            total = r.get('total_points')
            refunded = 'כן' if int(r.get('is_refunded', 0) or 0) == 1 else ''
            prod_name = str(r.get('product_display_name') or '').strip() or str(r.get('product_name') or '').strip()
            var_name = str(r.get('variant_display_name') or '').strip() or str(r.get('variant_name') or '').strip()
            item = (f"{prod_name} - {var_name}".strip(' -') if var_name else prod_name)
            base_tag = 'even' if (i % 2 == 0) else 'odd'
            if refunded:
                tree.insert('', 'end', values=('☐', pid, created_at, item, qty, total, refunded), tags=(base_tag, 'refunded'))
            else:
                tree.insert('', 'end', values=('☐', pid, created_at, item, qty, total, refunded), tags=(base_tag,))


    def _reprint_receipt_from_purchase_id(self, purchase_id: int):
        purchase_id = int(purchase_id or 0)
        if purchase_id <= 0:
            return
        try:
            snap = self.db.get_receipt_snapshot_by_purchase(int(purchase_id))
        except Exception:
            snap = None
        if not snap:
            messagebox.showwarning('אין חשבונית', 'לא נמצא Snapshot לחשבונית זו. ייתכן שנרכשה לפני עדכון המערכת.')
            return

        # Reprint directly to thermal printer (no PDF)
        snap_data = (snap.get('data') or {}) if isinstance(snap, dict) else {}
        if not isinstance(snap_data, dict):
            snap_data = {}

        student_name = ''
        cls = ''
        try:
            sid = int(snap_data.get('student_id') or snap.get('student_id') or 0)
        except Exception:
            sid = 0
        if sid:
            try:
                st = self.db.get_student_by_id(int(sid)) or {}
            except Exception:
                st = {}
            student_name = f"{str(st.get('first_name') or '').strip()} {str(st.get('last_name') or '').strip()}".strip()
            cls = str(st.get('class_name') or '').strip()

        items_out = []
        total = 0
        for it in (snap_data.get('items') or []):
            if not isinstance(it, dict):
                continue
            try:
                pid = int(it.get('product_id') or 0)
            except Exception:
                pid = 0
            try:
                vid = int(it.get('variant_id') or 0)
            except Exception:
                vid = 0
            try:
                qty = int(it.get('qty') or 0)
            except Exception:
                qty = 0
            if not pid or qty <= 0:
                continue

            p = self._product_by_id.get(pid) or {}
            pname = (str(p.get('display_name') or '').strip() or str(p.get('name') or '').strip() or f"מוצר {pid}")
            pname = self._strip_asterisk_annotations(pname)
            v = self._get_variant_for_cart_key(pid, vid)
            vname = self._strip_asterisk_annotations(str(v.get('variant_name') or '').strip())
            label = pname if (not vid or not vname or vname == 'ברירת מחדל') else f"{pname} {vname}".strip()

            price_each = 0
            try:
                price_each = int(it.get('points_each') or it.get('price_points') or 0)
            except Exception:
                price_each = 0
            if price_each <= 0:
                try:
                    price_each = int(it.get('total_points') or 0) // max(1, int(qty))
                except Exception:
                    price_each = 0

            for _ in range(int(qty)):
                items_out.append({'name': label, 'price': int(price_each)})
            total += int(price_each) * int(qty)

        receipt_data = {
            'student_name': student_name,
            'class_name': cls,
            'items': items_out,
            'total': int(total),
        }

        try:
            ok = bool(self._print_to_thermal_printer(receipt_data))
        except Exception:
            ok = False
        if not ok:
            messagebox.showerror('שגיאה', 'הדפסה מחדש נכשלה (מדפסת תרמית).')
            return


    def _generate_receipt_pdf_from_snapshot(self, snapshot: dict) -> str:
        snap = snapshot or {}
        data = snap.get('data') or {}
        if not isinstance(data, dict):
            data = {}

        created_at = str(snap.get('created_at') or '').strip()
        dt_txt = created_at[:16] if created_at else datetime.now().strftime('%Y-%m-%d %H:%M')
        
        # Add Hebrew date
        heb_date = ''
        try:
            from jewish_calendar import hebrew_date_from_gregorian_str
            greg_date = dt_txt[:10] if len(dt_txt) >= 10 else datetime.now().strftime('%Y-%m-%d')
            heb_date = hebrew_date_from_gregorian_str(greg_date)
        except Exception:
            heb_date = ''

        student_name = ''
        cls = ''
        try:
            student_id = int(data.get('student_id') or 0)
        except Exception:
            student_id = 0
        if student_id:
            try:
                st = self.db.get_student_by_id(int(student_id)) or {}
            except Exception:
                st = {}
            student_name = f"{str(st.get('first_name') or '').strip()} {str(st.get('last_name') or '').strip()}".strip()
            cls = str(st.get('class_name') or '').strip()
            student_name = self._receipt_line(student_name)
            cls = self._receipt_line(cls)

        lines = ['חשבונית (הדפסה מחדש)', dt_txt]
        if heb_date:
            lines.append(heb_date)
        lines.append(f"{student_name} | {cls}".strip(' |'))
        lines.append('--------------------------')
        total = 0

        for it in (data.get('items') or []):
            try:
                pid = int(it.get('product_id') or 0)
            except Exception:
                pid = 0
            try:
                vid = int(it.get('variant_id') or 0)
            except Exception:
                vid = 0
            try:
                qty = int(it.get('qty') or 0)
            except Exception:
                qty = 0
            if not pid or qty <= 0:
                continue

            p = self._product_by_id.get(pid) or {}
            pname = (str(p.get('display_name') or '').strip() or str(p.get('name') or '').strip() or f"מוצר {pid}")
            pname = self._receipt_line(pname)
            v = self._get_variant_for_cart_key(pid, vid)
            vname = self._receipt_line(str(v.get('variant_name') or '').strip())

            price_each = 0
            try:
                price_each = int(it.get('points_each') or it.get('price_points') or 0)
            except Exception:
                price_each = 0
            if price_each <= 0:
                try:
                    price_each = int(it.get('total_points') or 0) // max(1, int(qty))
                except Exception:
                    price_each = 0

            label = pname if (not vid or not vname or vname == 'ברירת מחדל') else f"{pname} {vname}".strip()
            lines.append(f"{qty}x {label} - {price_each} נק")
            total += int(price_each) * int(qty)

        for sr in (data.get('scheduled_reservations') or []):
            sd = str(sr.get('service_date') or '').strip()
            stt = str(sr.get('slot_start_time') or '').strip()
            if sd and stt:
                lines.append(f"אתגר {sd} {stt}".strip())

        lines.append('--------------------------')
        lines.append(f"סה\"כ: {int(total)} נק")

        width = 620
        pad = 22
        line_h = 30
        height = max(240, pad * 2 + line_h * (len(lines) + 2))
        img = Image.new('RGB', (width, height), color='white')
        draw = ImageDraw.Draw(img)
        font = self._font_try_load(22)
        font_small = self._font_try_load(18)
        y = pad
        for i, ln in enumerate(lines):
            f = font_small if i in (1, 2) else font
            try:
                self._receipt_draw_line(draw, str(ln or ''), width=width, pad=pad, y=y, font=f)
            except Exception:
                try:
                    draw.text((pad, y), str(ln or ''), font=f, fill='black')
                except Exception:
                    pass
            y += line_h

        out_dir = os.path.join(os.environ.get('PROGRAMDATA', r'C:\ProgramData'), 'SchoolPoints', 'receipts')
        try:
            os.makedirs(out_dir, exist_ok=True)
        except Exception:
            out_dir = os.path.dirname(os.path.abspath(__file__))
        fn = f"receipt_reprint_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        out_path = os.path.join(out_dir, fn)
        try:
            img.save(out_path, 'PDF', resolution=200.0)
        except Exception:
            return ''
        return out_path

    def _generate_operator_summary_voucher_pdf(self, *, student_id: int, items: list, scheduled_reservations: list, total_points: int = 0) -> str:
        """Generate a detailed operator voucher PDF with full purchase details."""
        try:
            st = self.db.get_student_by_id(int(student_id or 0))
        except Exception:
            st = None
        st = st or (self._current_student or {})
        student_name = f"{str(st.get('first_name') or '').strip()} {str(st.get('last_name') or '').strip()}".strip()
        cls = str(st.get('class_name') or '').strip()

        op = getattr(self, '_operator', None) or {}
        op_name = ''
        try:
            op_name = str(op.get('name') or '').strip()
        except Exception:
            op_name = ''
        if not op_name:
            try:
                op_name = f"{str(op.get('first_name') or '').strip()} {str(op.get('last_name') or '').strip()}".strip()
            except Exception:
                op_name = ''
        if not op_name:
            op_name = 'מפעיל'

        now = datetime.now()
        dt_txt = now.strftime('%Y-%m-%d %H:%M')
        
        # Add Hebrew date
        heb_date = ''
        try:
            from jewish_calendar import hebrew_date_from_gregorian_str
            greg_date = now.strftime('%Y-%m-%d')
            heb_date = hebrew_date_from_gregorian_str(greg_date)
        except Exception:
            heb_date = ''

        try:
            total_points = int(total_points or 0)
        except Exception:
            total_points = 0

        lines = []
        lines.append('שובר למפעיל')
        lines.append(dt_txt)
        if heb_date:
            lines.append(heb_date)
        lines.append(f"מפעיל: {op_name}")
        if student_name or cls:
            lines.append(f"{student_name} | {cls}".strip(' |'))
        lines.append('--------------------------')
        lines.append('פריטים:')

        # map scheduled reservation by purchase_item_index
        by_idx = {}
        for sr in (scheduled_reservations or []):
            try:
                idx = int(sr.get('purchase_item_index') or -1)
            except Exception:
                idx = -1
            if idx >= 0:
                by_idx[idx] = sr

        total_calc = 0
        printed_any = False
        for idx, it in enumerate(list(items or [])):
            try:
                pid = int(it.get('product_id') or 0)
            except Exception:
                pid = 0
            try:
                vid = int(it.get('variant_id') or 0)
            except Exception:
                vid = 0
            try:
                qty = int(it.get('qty') or 0)
            except Exception:
                qty = 0
            if not pid or qty <= 0:
                continue

            p = self._product_by_id.get(pid) or {}
            pname = (str(p.get('display_name') or '').strip() or str(p.get('name') or '').strip() or f"מוצר {pid}")
            pname = self._receipt_line(pname)
            v = self._get_variant_for_cart_key(pid, vid)
            vname = self._receipt_line(str(v.get('variant_name') or '').strip())
            try:
                price = int(v.get('price_points', p.get('price_points', 0)) or 0)
            except Exception:
                price = int(p.get('price_points', 0) or 0)
            item_total = int(price) * int(qty)
            total_calc += item_total

            label = pname
            if int(vid or 0) > 0 and vname and vname != 'ברירת מחדל':
                label = f"{pname} - {vname}".strip(' -')

            slot = ''
            sr = by_idx.get(int(it.get('purchase_item_index') or idx)) or by_idx.get(int(idx))
            if sr:
                sdate = str(sr.get('service_date') or '').strip()
                stt = str(sr.get('slot_start_time') or '').strip()
                if sdate and stt:
                    slot = f"{sdate} {stt}".strip()
                elif stt:
                    slot = stt

            if slot:
                lines.append(f"{qty} x {label} ({slot}) = {item_total} נק")
            else:
                lines.append(f"{qty} x {label} = {item_total} נק")
            printed_any = True

        if not printed_any:
            lines.append('אין פריטים בשובר')

        lines.append('--------------------------')
        if total_points <= 0:
            total_points = int(total_calc)
        lines.append(f"סה\"כ: {int(total_points)} נק")

        font = self._font_try_load(22)
        font_small = self._font_try_load(18)
        width = 620
        pad = 22
        line_h = 30
        height = max(260, pad * 2 + line_h * (len(lines) + 2))
        img = Image.new('RGB', (width, height), color='white')
        draw = ImageDraw.Draw(img)
        y = pad

        for i, ln in enumerate(lines):
            f = font_small if i in (1, 2, 3) else font
            try:
                self._receipt_draw_line(draw, str(ln or ''), width=width, pad=pad, y=y, font=f)
            except Exception:
                try:
                    draw.text((pad, y), str(ln or ''), font=f, fill='black')
                except Exception:
                    pass
            y += line_h

        out_dir = os.path.join(os.environ.get('PROGRAMDATA', r'C:\ProgramData'), 'SchoolPoints', 'receipts')
        try:
            os.makedirs(out_dir, exist_ok=True)
        except Exception:
            out_dir = os.path.dirname(os.path.abspath(__file__))
        fn = f"operator_voucher_{now.strftime('%Y%m%d_%H%M%S_%f')}.pdf"
        out_path = os.path.join(out_dir, fn)
        try:
            img.save(out_path, 'PDF', resolution=200.0)
        except Exception:
            return ''
        return out_path

    def _get_total_deduct_points(self) -> int:
        total = 0
        for (pid, vid), qty in (self._cart or {}).items():
            v = self._get_variant_for_cart_key(pid, vid)
            try:
                deduct = 1 if int(v.get('deduct_points', 1) or 0) == 1 else 0
            except Exception:
                deduct = 1
            if deduct != 1:
                continue
            try:
                price = int(v.get('price_points', 0) or 0)
            except Exception:
                price = 0
            total += int(price) * int(qty)
        for it in (self._scheduled_cart or []):
            try:
                pid = int(it.get('product_id') or 0)
            except Exception:
                pid = 0
            if not pid:
                continue
            p = self._product_by_id.get(pid) or {}
            try:
                deduct = 1 if int(p.get('deduct_points', 1) or 0) == 1 else 0
            except Exception:
                deduct = 1
            if deduct != 1:
                continue
            try:
                price = int(p.get('price_points', 0) or 0)
            except Exception:
                price = 0
            total += int(price)
        return int(total)

    def _cancel_cart(self):
        self._touch_activity()
        try:
            self._clear_cart_state(clear_db=True)
        except Exception:
            pass
        self._render_product_grid()

    def _student_exit(self):
        # exit current student and clear cart
        self._touch_activity()
        if bool(getattr(self, '_license_blocked', False)):
            try:
                msg = str(getattr(self, '_license_block_message', '') or '').strip()
            except Exception:
                msg = ''
            if not msg:
                msg = 'עמדת קופה לא מורשית – אין אפשרות לבצע פעולות'
            try:
                self._set_status(msg, is_error=True)
            except Exception:
                pass
            return
        try:
            self._clear_cart_state(clear_db=True, show_lock_overlay=False, reload_products=False, reload_categories=False)
        except Exception:
            self._pending_payment = None
        self._current_student = None
        self.student_label.config(text='')
        try:
            self.student_points_label.config(text='— נק')
        except Exception:
            pass
        try:
            self.student_photo_label.config(image='', text='👤')
            self.student_photo_label.image = None
        except Exception:
            pass
        self._refresh_cart_ui()
        self._render_product_grid()
        if not self._locked:
            self._set_status('קופה פתוחה. העבר כרטיס תלמיד לתחילת קנייה', is_error=False)
        try:
            self._ensure_scan_focus()
        except Exception:
            pass

    def _operator_exit(self):
        # lock cashier (operator exit)
        self._touch_activity()
        if bool(getattr(self, '_license_blocked', False)):
            try:
                msg = str(getattr(self, '_license_block_message', '') or '').strip()
            except Exception:
                msg = ''
            if not msg:
                msg = 'עמדת קופה לא מורשית – אין אפשרות לבצע פעולות'
            try:
                self._set_status(msg, is_error=True)
            except Exception:
                pass
            return
        self._lock()

    # ----------------------------
    # Auth / Lock
    # ----------------------------

    def _lock(self):
        self._locked = True
        self._operator = None
        self._operator_card = ''
        try:
            self._clear_cart_state(clear_db=True)
        except Exception:
            self._pending_payment = None
        self._current_student = None
        self.student_label.config(text='')
        try:
            self.student_points_label.config(text='— נק')
        except Exception:
            pass
        try:
            self.student_photo_label.config(image='', text='👤')
            self.student_photo_label.image = None
        except Exception:
            pass
        self.operator_label.config(text='')
        self._show_lock_overlay()
        if self.cashier_mode == 'self_service':
            self._set_status('העבר כרטיס תלמיד לפתיחה', is_error=False)
        elif self.cashier_mode == 'responsible_student':
            self._set_status('העבר כרטיס תלמיד אחראי לפתיחת הקופה', is_error=False)
        else:
            self._set_status('העבר כרטיס מורה לפתיחת הקופה', is_error=False)

    def _unlock_with_operator(self, operator: dict, card: str):
        self._locked = False
        self._operator = operator
        self._operator_card = str(card or '').strip()
        self._touch_activity()
        self._hide_lock_overlay()
        self._set_status('קופה פתוחה. העבר כרטיס תלמיד לתחילת קנייה', is_error=False)
        try:
            if self.cashier_mode == 'teacher':
                name = str(operator.get('name') or operator.get('full_name') or '').strip()
                if not name:
                    name = str(operator.get('first_name') or '').strip()
                self.operator_label.config(text=f"מפעיל העמדה: {name or 'מורה'}")
            else:
                n = f"{(operator.get('first_name') or '').strip()} {(operator.get('last_name') or '').strip()}".strip()
                self.operator_label.config(text=f"מפעיל העמדה: {n or 'אחראי'}")
        except Exception:
            pass

    def _clear_lock_entry(self):
        try:
            if self._lock_entry is not None:
                self._lock_entry.delete(0, tk.END)
        except Exception:
            pass

    def _set_current_student(self, student: dict):
        # If switching students mid-session, clear previous student's cart/holds first
        try:
            prev_id = int((self._current_student or {}).get('id') or 0)
        except Exception:
            prev_id = 0
        try:
            new_id = int((student or {}).get('id') or 0)
        except Exception:
            new_id = 0
        if prev_id and new_id and int(prev_id) != int(new_id):
            try:
                self._clear_cart_state(clear_db=True)
            except Exception:
                pass
        self._current_student = student
        name = f"{(student.get('first_name') or '').strip()} {(student.get('last_name') or '').strip()}".strip()
        cls = str(student.get('class_name') or '').strip()
        name = self._strip_asterisk_annotations(name)
        cls = self._strip_asterisk_annotations(cls)
        self.student_label.config(text=f"{name} | {cls}")
        try:
            bal = int((student or {}).get('points', 0) or 0)
        except Exception:
            bal = 0
        try:
            self.student_points_label.config(text=f"{bal} נקודות")
        except Exception:
            pass
        
        # Update customer display with student info
        try:
            display = self._ensure_customer_display()
            if display and display.enabled:
                display.show_student(name, bal)
        except Exception:
            pass
        try:
            self._load_student_photo_to_header(student)
        except Exception:
            pass
        self._refresh_cart_ui()
        self._render_product_grid()
        try:
            self._refresh_all_tile_controls()
        except Exception:
            pass

    def on_card_scanned(self, card_number: str):
        if bool(getattr(self, '_license_blocked', False)):
            try:
                msg = str(getattr(self, '_license_block_message', '') or '').strip()
            except Exception:
                msg = ''
            if not msg:
                msg = 'עמדת קופה לא מורשית – אין אפשרות לבצע פעולות'
            try:
                self._set_status(msg, is_error=True)
            except Exception:
                pass
            return
        card_number = str(card_number or '').strip()
        # Some readers add hidden prefix/suffix chars (e.g. ';', '?', '=', spaces, etc.).
        # Strip them to avoid lookup failures.
        try:
            card_number = re.sub(r'[^0-9A-Za-z]', '', card_number)
        except Exception:
            pass
        if not card_number:
            return

        # Debounce duplicates (prevents operator card from toggling lock/unlock immediately)
        try:
            now = float(time.time())
            if card_number == str(self._last_scanned_card or '') and (now - float(self._last_scanned_ts or 0.0)) < 0.7:
                return
            self._last_scanned_card = card_number
            self._last_scanned_ts = now
        except Exception:
            pass
        self._touch_activity()

        # Master card actions (exit/settings/db selection)
        if card_number == self._exit_code or card_number == UNIVERSAL_MASTER_CODE:
            try:
                self._open_master_actions_dialog()
            except Exception:
                pass
            return

        # If open with operator: card of operator again locks
        if not self._locked and self._operator_card and card_number == self._operator_card:
            self._lock()
            return

        # Lock screen auth
        if self._locked:
            if self.cashier_mode == 'self_service':
                # student opens directly
                student = self._find_student_by_card(card_number)
                if not student:
                    self._set_status('כרטיס לא נמצא', is_error=True)
                    self._clear_lock_entry()
                    return
                self._locked = False
                self._hide_lock_overlay()
                self._set_current_student(student)
                self._set_status('בחר מוצרים', is_error=False)
                return

            if self.cashier_mode == 'responsible_student':
                student = self._find_student_by_card(card_number)
                if not student:
                    self._set_status('כרטיס לא נמצא', is_error=True)
                    self._clear_lock_entry()
                    return
                try:
                    allowed = self.db.is_cashier_responsible(int(student.get('id') or 0))
                except Exception:
                    allowed = False
                if not allowed:
                    self._set_status('מפעיל לא מורשה (התלמיד אינו מוגדר כאחראי קופה)', is_error=True)
                    self._clear_lock_entry()
                    return
                self._unlock_with_operator(student, card_number)
                return

            # teacher mode
            teacher = self._find_teacher_by_card(card_number)
            if not teacher:
                self._set_status('מפעיל לא מורשה (כרטיס מורה לא נמצא)', is_error=True)
                self._clear_lock_entry()
                return
            self._unlock_with_operator(teacher, card_number)
            return

        # Payment confirmation by rescanning the same student card
        if self._pending_payment is not None:
            expected = str(self._pending_payment.get('student_card') or '').strip()
            if expected and card_number != expected:
                self._set_status('יש להעביר שוב את כרטיס התלמיד לביצוע תשלום', is_error=True)
                return
            try:
                if self._pending_payment_dialog is not None:
                    self._pending_payment_dialog.destroy()
            except Exception:
                pass
            self._pending_payment_dialog = None
            self._finalize_payment()
            return

        # Settings auth by admin card
        if self._settings_auth_dialog is not None:
            teacher = self._find_teacher_by_card(card_number)
            if not teacher:
                self._set_status('כרטיס מנהל לא נמצא', is_error=True)
                return
            try:
                is_admin = int(teacher.get('is_admin', 0) or 0) == 1
            except Exception:
                is_admin = False
            if not is_admin:
                self._set_status('נדרש כרטיס מנהל לפתיחת הגדרות', is_error=True)
                return
            try:
                self._settings_auth_dialog.destroy()
            except Exception:
                pass
            self._settings_auth_dialog = None
            try:
                self._open_cashier_settings_dialog()
            except Exception:
                pass
            return

        # Unlocked: student scan sets current student
        student = self._find_student_by_card(card_number)
        if not student:
            self._set_status('כרטיס תלמיד לא נמצא', is_error=True)
            return
        self._set_current_student(student)
        self._set_status('בחר מוצרים', is_error=False)
        try:
            self._ensure_scan_focus()
        except Exception:
            pass

    def _find_student_by_card(self, card: str):
        card = str(card or '').strip()
        if not card:
            return None
        try:
            s = self.db.get_student_by_card(card)
        except Exception:
            s = None
        if s:
            return s
        for converted in self._convert_card_format(card):
            try:
                s = self.db.get_student_by_card(converted)
            except Exception:
                s = None
            if s:
                return s
        return None

    def _find_teacher_by_card(self, card: str):
        card = str(card or '').strip()
        if not card:
            return None
        try:
            t = self.db.get_teacher_by_card(card)
        except Exception:
            t = None
        if t:
            return t
        for converted in self._convert_card_format(card):
            try:
                t = self.db.get_teacher_by_card(converted)
            except Exception:
                t = None
            if t:
                return t
        return None

    def _convert_card_format(self, card_number: str):
        """Convert between common RFID reader formats (decimal, hex, little/big endian 32-bit)."""
        converted_options = []
        card_number = str(card_number or '').strip()
        if not card_number:
            return converted_options
        try:
            if card_number.isdigit():
                dec_num = int(card_number)
                hex_num = format(dec_num, 'X').upper()
                converted_options.append(hex_num)
                if dec_num < 4294967296:
                    bytes_big = dec_num.to_bytes(4, byteorder='big')
                    dec_little = int.from_bytes(bytes_big, byteorder='little')
                    converted_options.append(format(dec_little, 'X').upper())
            else:
                hex_num = card_number.upper()
                dec_num = int(hex_num, 16)
                converted_options.append(str(dec_num))
                if len(hex_num) <= 8:
                    hex_padded = hex_num.zfill(8)
                    bytes_val = bytes.fromhex(hex_padded)
                    dec_reversed = int.from_bytes(bytes_val, byteorder='little')
                    converted_options.append(str(dec_reversed))
        except Exception:
            pass
        # de-dup, keep order
        out = []
        seen = set()
        for x in converted_options:
            x = str(x or '').strip()
            if x and x not in seen and x != card_number:
                seen.add(x)
                out.append(x)
        return out

    # ----------------------------
    # Payment
    # ----------------------------

    def _pay(self):
        self._touch_activity()
        if bool(getattr(self, '_license_blocked', False)):
            try:
                msg = str(getattr(self, '_license_block_message', '') or '').strip()
            except Exception:
                msg = ''
            if not msg:
                msg = 'עמדת קופה לא מורשית – אין אפשרות לבצע פעולות'
            try:
                self._set_status(msg, is_error=True)
            except Exception:
                pass
            try:
                messagebox.showwarning('עמדת קופה לא מורשית', msg)
            except Exception:
                pass
            return
        if self._locked:
            self._set_status('הקופה נעולה', is_error=True)
            return
        if not self._current_student:
            self._set_status('בחר תלמיד', is_error=True)
            return
        if (not self._cart) and (not self._scheduled_cart):
            self._set_status('העגלה ריקה', is_error=True)
            return

        total = 0
        items = []
        for (pid, vid), qty in self._cart.items():
            v = self._get_variant_for_cart_key(pid, vid)
            p = self._product_by_id.get(pid) or {}
            
            # Get product name
            product_name = (str(p.get('display_name') or '').strip() or str(p.get('name') or '').strip())
            variant_name = str(v.get('variant_name') or '').strip()
            
            # Build full item name
            if vid and variant_name and variant_name != 'ברירת מחדל':
                item_name = f"{product_name} - {variant_name}"
            else:
                item_name = product_name
            
            try:
                price = int(v.get('price_points', 0) or 0)
            except Exception:
                price = 0
            total += int(price) * int(qty)
            items.append({
                'product_id': int(pid), 
                'variant_id': int(vid or 0), 
                'qty': int(qty),
                'name': item_name,
                'price': price
            })

        # scheduled services are also paid as product price_points (qty=1)
        scheduled_reservations = []
        for it in (self._scheduled_cart or []):
            try:
                pid = int(it.get('product_id') or 0)
            except Exception:
                pid = 0
            if not pid:
                continue
            p = self._product_by_id.get(pid) or {}

            try:
                vid = int(it.get('variant_id') or 0)
            except Exception:
                vid = 0
            if vid:
                v = self._get_variant_for_cart_key(pid, vid)
                try:
                    price = int(v.get('price_points', p.get('price_points', 0)) or 0)
                except Exception:
                    price = int(p.get('price_points', 0) or 0)
            else:
                try:
                    price = int(p.get('price_points', 0) or 0)
                except Exception:
                    price = 0

            # Get product name for scheduled service
            product_name = (str(p.get('display_name') or '').strip() or str(p.get('name') or '').strip())
            if vid:
                v = self._get_variant_for_cart_key(pid, vid)
                variant_name = str(v.get('variant_name') or '').strip()
                if variant_name and variant_name != 'ברירת מחדל':
                    item_name = f"{product_name} - {variant_name}"
                else:
                    item_name = product_name
            else:
                item_name = product_name
            
            total += int(price)
            purchase_item_index = len(items)
            items.append({
                'product_id': int(pid), 
                'variant_id': int(vid or 0), 
                'qty': 1,
                'name': item_name,
                'price': price
            })
            scheduled_reservations.append({
                'service_id': int(it.get('service_id') or 0),
                'service_date': str(it.get('service_date') or '').strip(),
                'slot_start_time': str(it.get('slot_start_time') or '').strip(),
                'duration_minutes': int(it.get('duration_minutes', 0) or 0),
                'purchase_item_index': int(purchase_item_index),
            })

        # refresh setting so changes from admin apply without restart
        try:
            self.require_rescan_confirm = bool(self.db.should_cashier_require_rescan_confirm(int(total)))
        except Exception:
            try:
                self.require_rescan_confirm = bool(self.db.get_cashier_require_rescan_confirm())
            except Exception:
                self.require_rescan_confirm = True

        if self.require_rescan_confirm:
            # Require rescanning the same student card to confirm
            try:
                student_card = str(self._current_student.get('card_number') or '').strip()
            except Exception:
                student_card = ''
            if not student_card:
                self._set_status('לא נמצא מספר כרטיס תלמיד – לא ניתן לאשר תשלום בסריקה', is_error=True)
                messagebox.showwarning('אזהרה', 'לא נמצא מספר כרטיס תלמיד במערכת. יש לוודא שלתלמיד מוגדר מספר כרטיס.')
                return

            self._pending_payment = {
                'student_id': int(self._current_student.get('id') or 0),
                'student_card': student_card,
                'items': items,
                'scheduled_reservations': scheduled_reservations,
                'total': int(total),
            }
            self._open_payment_approval_dialog(total_points=int(total))
            return

        # immediate payment (no rescan)
        self._execute_payment(int(self._current_student.get('id') or 0), items, scheduled_reservations)

    def _finalize_payment(self):
        pending = self._pending_payment or {}
        self._pending_payment = None
        sid = int(pending.get('student_id') or 0)
        items = pending.get('items') or []
        scheduled_reservations = pending.get('scheduled_reservations') or []
        self._execute_payment(sid, items, scheduled_reservations)

    def _execute_payment(self, student_id: int, items: list, scheduled_reservations: list):
        if scheduled_reservations:
            res = self.db.cashier_purchase_batch_with_scheduled(
                student_id=int(student_id or 0),
                items=items,
                scheduled_reservations=scheduled_reservations,
                station_type='cashier',
                actor_name='cashier'
            )
        else:
            res = self.db.cashier_purchase_batch(student_id=int(student_id or 0), items=items, station_type='cashier', actor_name='cashier')
        if not res.get('ok'):
            self._set_status(str(res.get('error') or 'שגיאה בתשלום'), is_error=True)
            messagebox.showerror('שגיאה', str(res.get('error') or 'שגיאה בתשלום'))
            try:
                self.db.clear_holds(station_id=str(self.station_id or '').strip(), student_id=int(student_id or 0))
            except Exception:
                pass
            return

        try:
            purchase_ids = []
            for it in (res.get('items') or []):
                try:
                    pid = int((it or {}).get('purchase_id') or 0)
                except Exception:
                    pid = 0
                if pid > 0:
                    purchase_ids.append(pid)
            purchase_ids = list(dict.fromkeys(purchase_ids))
            if purchase_ids:
                self.db.save_receipt_snapshot(
                    station_type='cashier',
                    student_id=int(student_id or 0),
                    purchase_ids=purchase_ids,
                    items=items or [],
                    scheduled_reservations=scheduled_reservations or [],
                )
        except Exception:
            pass

        try:
            self.db.clear_holds(station_id=str(self.station_id or '').strip(), student_id=int(student_id or 0))
        except Exception:
            pass

        # Show total on customer display
        try:
            display = self._ensure_customer_display()
            if display and display.enabled:
                total_points = sum(int(it.get('qty', 1)) * int(self._get_variant_for_cart_key(
                    int(it.get('product_id', 0)), int(it.get('variant_id', 0))
                ).get('price_points', 0)) for it in items)
                student = self.db.get_student_by_id(int(student_id or 0))
                balance_after = int(student.get('points', 0)) if student else 0
                display.show_total(total_points, balance_after)
        except Exception:
            pass

        # Print receipt automatically
        try:
            # Try thermal printer first
            thermal_printed = False
            try:
                student = self.db.get_student_by_id(int(student_id or 0))
                
                # Get student balance
                balance_before = student.get('points', 0) if student else 0
                total_cost = sum(item.get('price', 0) for item in items)
                balance_after = balance_before - total_cost
                
                receipt_items = []
                for item in (items or []):
                    try:
                        name = str(item.get('name', '') or '').strip()
                    except Exception:
                        name = ''
                    name = self._strip_asterisk_annotations(name)
                    try:
                        qty = int(item.get('qty', item.get('quantity', 1)) or 1)
                    except Exception:
                        qty = 1
                    try:
                        price = int(float(item.get('price', 0) or 0))
                    except Exception:
                        price = 0
                    try:
                        pid = int(item.get('product_id', 0) or 0)
                    except Exception:
                        pid = 0
                    try:
                        vid = int(item.get('variant_id', 0) or 0)
                    except Exception:
                        vid = 0

                    if not name:
                        try:
                            p = self._product_by_id.get(pid) or {}
                            name = str(p.get('display_name') or p.get('name') or '').strip()
                            name = self._strip_asterisk_annotations(name)
                        except Exception:
                            pass

                    variant_name = ''
                    if vid:
                        try:
                            v = self._get_variant_for_cart_key(pid, vid)
                            variant_name = self._strip_asterisk_annotations(str(v.get('variant_name') or '').strip())
                        except Exception:
                            variant_name = ''

                    full_name = name
                    if variant_name and variant_name != 'ברירת מחדל' and variant_name not in str(name):
                        if full_name:
                            full_name = f"{full_name} - {variant_name}".strip()
                        else:
                            full_name = variant_name

                    receipt_items.append({
                        'name': full_name,
                        'variant_name': variant_name,
                        'price': price,
                        'qty': qty,
                        'total_points': price * qty,
                    })

                student_name = ''
                try:
                    student_name = str(student.get('name', '') or '').strip() if student else ''
                except Exception:
                    student_name = ''
                if not student_name:
                    try:
                        student_name = f"{str(student.get('first_name') or '').strip()} {str(student.get('last_name') or '').strip()}".strip()
                    except Exception:
                        student_name = ''

                receipt_data = {
                    'student_name': student_name,
                    'student_id': student.get('id_number', '') if student else '',
                    'class_name': student.get('class_name', '') if student else '',
                    'items': receipt_items,
                    'total': total_cost,
                    'balance_before': balance_before,
                    'balance_after': balance_after
                }
                thermal_printed = self._print_to_thermal_printer(receipt_data)
            except Exception as e:
                print(f"Thermal printer error: {e}")
                thermal_printed = False
            
            # Fallback to PDF if thermal printer failed (optional)
            if not thermal_printed:
                disable_pdf_fallback = False
                try:
                    cfg = self._load_app_config() or {}
                    printer_cfg = cfg.get('receipt_printer', {}) if isinstance(cfg, dict) else {}
                    disable_pdf_fallback = bool(
                        (printer_cfg or {}).get('disable_pdf_fallback')
                        or (cfg or {}).get('disable_pdf_fallback')
                    )
                except Exception:
                    disable_pdf_fallback = False
                if not disable_pdf_fallback:
                    pdf_path = self._generate_receipt_pdf(
                        student_id=int(student_id or 0),
                        items=items,
                        scheduled_reservations=scheduled_reservations,
                    )
                    if pdf_path:
                        self._print_or_open_pdf(pdf_path)
        except Exception:
            pass
        
        # Show payment complete on customer display
        try:
            display = self._ensure_customer_display()
            if display and display.enabled:
                display.show_payment_complete()
        except Exception:
            pass

        # Optional extra vouchers: one voucher per cart line (operator copy)
        try:
            enabled = bool(self.db.get_cashier_print_item_receipts())
        except Exception:
            enabled = False
        if enabled:
            try:
                by_idx = {}
                for sr in (scheduled_reservations or []):
                    try:
                        idx = int(sr.get('purchase_item_index') or -1)
                    except Exception:
                        idx = -1
                    if idx >= 0:
                        by_idx[idx] = sr

                for it in (items or []):
                    try:
                        pid = int(it.get('product_id') or 0)
                    except Exception:
                        pid = 0
                    try:
                        vid = int(it.get('variant_id') or 0)
                    except Exception:
                        vid = 0
                    try:
                        qty = int(it.get('qty') or 0)
                    except Exception:
                        qty = 0
                    if not pid or qty <= 0:
                        continue

                    p = self._product_by_id.get(pid) or {}
                    pname = (str(p.get('display_name') or '').strip() or str(p.get('name') or '').strip() or f"מוצר {pid}")
                    pname = self._strip_asterisk_annotations(pname)
                    v = self._get_variant_for_cart_key(pid, vid)
                    vname = self._strip_asterisk_annotations(str(v.get('variant_name') or '').strip())
                    try:
                        price = int(v.get('price_points', p.get('price_points', 0)) or 0)
                    except Exception:
                        price = 0
                    if int(vid or 0) > 0 and vname and vname != 'ברירת מחדל':
                        label = f"{pname} - {vname}".strip()
                    else:
                        label = pname

                    slot_txt = ''
                    dur_mins = 0
                    sr = by_idx.get(int(it.get('purchase_item_index') or -1))
                    if not sr:
                        try:
                            sr = by_idx.get(int((items or []).index(it)))
                        except Exception:
                            sr = None
                    if sr:
                        sdate = str(sr.get('service_date') or '').strip()
                        stt = str(sr.get('slot_start_time') or '').strip()
                        try:
                            dur_mins = int(sr.get('duration_minutes', 0) or 0)
                        except Exception:
                            dur_mins = 0
                        if sdate and stt:
                            slot_txt = f"{sdate} {stt}".strip()
                        elif stt:
                            slot_txt = stt

                    # Print voucher to thermal printer instead of PDF
                    try:
                        self._print_item_voucher_to_thermal(
                            student_id=int(student_id or 0),
                            item_label=str(label or '').strip(),
                            qty=int(qty or 1),
                            price_points=int(price or 0),
                            slot_text=str(slot_txt or '').strip(),
                            duration_minutes=int(dur_mins or 0),
                            service_date=str(sdate or '').strip(),
                            slot_time=str(stt or '').strip(),
                        )
                    except Exception as e:
                        print(f"Voucher print error: {e}")
            except Exception as e:
                print(f"Voucher loop error: {e}")

        # Auto student exit after completing payment (and optional receipt print)
        try:
            self._student_exit()
        except Exception:
            pass
        if self.cashier_mode == 'self_service':
            try:
                self._lock()
            except Exception:
                pass

        self._set_status('התשלום בוצע. העבר כרטיס תלמיד לתחילת קנייה', is_error=False)

    def _open_payment_approval_dialog(self, total_points: int):
        self._touch_activity()

        try:
            if self._pending_payment_dialog is not None:
                try:
                    self._pending_payment_dialog.destroy()
                except Exception:
                    pass
        except Exception:
            pass
        self._pending_payment_dialog = None

        dlg = tk.Toplevel(self.root)
        dlg.title('אישור תשלום')
        dlg.configure(bg='#0f0f14')
        dlg.transient(self.root)
        dlg.grab_set()
        try:
            dlg.minsize(720, 300)
        except Exception:
            pass

        total_points = int(total_points or 0)
        tk.Label(dlg, text=f'לאישור תשלום בסך {total_points} נקודות', font=('Arial', 20, 'bold'), fg='white', bg='#0f0f14', anchor='e', justify='right').pack(padx=18, pady=(22, 10), anchor='e')
        tk.Label(dlg, text='העבר כרטיס תלמיד לאישור', font=('Arial', 26, 'bold'), fg='#f1c40f', bg='#0f0f14', anchor='e', justify='right').pack(padx=18, pady=(0, 18), anchor='e')

        btns = tk.Frame(dlg, bg='#0f0f14')
        btns.pack(fill=tk.X, padx=18, pady=(0, 18))

        def _cancel():
            self._touch_activity()
            self._pending_payment = None
            try:
                dlg.destroy()
            except Exception:
                pass
            self._pending_payment_dialog = None
            self._set_status('תשלום בוטל', is_error=False)

        tk.Button(btns, text='ביטול', command=_cancel, font=('Arial', 20, 'bold'), bg='#7f8c8d', fg='white', padx=22, pady=14).pack(side=tk.RIGHT)

        try:
            dlg.protocol('WM_DELETE_WINDOW', _cancel)
        except Exception:
            pass

        self._pending_payment_dialog = dlg

    def _open_cashier_settings_auth_dialog(self):
        self._touch_activity()
        if bool(getattr(self, '_license_blocked', False)):
            try:
                msg = str(getattr(self, '_license_block_message', '') or '').strip()
            except Exception:
                msg = ''
            if not msg:
                msg = 'עמדת קופה לא מורשית – אין אפשרות לבצע פעולות'
            try:
                self._set_status(msg, is_error=True)
            except Exception:
                pass
            try:
                messagebox.showwarning('עמדת קופה לא מורשית', msg)
            except Exception:
                pass
            return
        if self._locked:
            self._set_status('הקופה נעולה', is_error=True)
            return

        try:
            if self._settings_auth_dialog is not None:
                try:
                    self._settings_auth_dialog.destroy()
                except Exception:
                    pass
        except Exception:
            pass
        self._settings_auth_dialog = None

        dlg = tk.Toplevel(self.root)
        dlg.title('⚙ הגדרות')
        dlg.configure(bg='#0f0f14')
        dlg.transient(self.root)
        dlg.grab_set()
        try:
            dlg.minsize(520, 240)
        except Exception:
            pass
        try:
            dlg.resizable(False, False)
        except Exception:
            pass

        tk.Label(dlg, text='פתיחת הגדרות דורשת כרטיס מנהל', font=('Arial', 20, 'bold'), fg='white', bg='#0f0f14', anchor='e', justify='right').pack(padx=18, pady=(20, 10), anchor='e')
        tk.Label(dlg, text='העבר כרטיס מנהל לפתיחה', font=('Arial', 26, 'bold'), fg='#f1c40f', bg='#0f0f14', anchor='e', justify='right').pack(padx=18, pady=(0, 18), anchor='e')

        def _close():
            self._touch_activity()
            try:
                dlg.destroy()
            except Exception:
                pass
            self._settings_auth_dialog = None

        tk.Button(dlg, text='ביטול', command=_close, font=('Arial', 18, 'bold'), bg='#7f8c8d', fg='white', padx=22, pady=12).pack(pady=(0, 18))
        try:
            dlg.protocol('WM_DELETE_WINDOW', _close)
        except Exception:
            pass

        self._settings_auth_dialog = dlg

    def _select_db_path_for_station(self):
        self._touch_activity()
        try:
            cfg = self._load_app_config() or {}
        except Exception:
            cfg = {}

        try:
            current_db = str((cfg or {}).get('db_path') or '').strip()
        except Exception:
            current_db = ''

        initial_dir = ''
        if current_db:
            try:
                initial_dir = os.path.dirname(current_db)
            except Exception:
                initial_dir = ''
        if not initial_dir:
            try:
                shared = str((cfg or {}).get('shared_folder') or (cfg or {}).get('network_root') or '').strip()
            except Exception:
                shared = ''
            if shared and os.path.isdir(shared):
                initial_dir = shared
        if not initial_dir:
            try:
                initial_dir = os.path.dirname(os.path.abspath(__file__))
            except Exception:
                initial_dir = ''

        db_path = filedialog.askopenfilename(
            title='בחר מסד נתונים (school_points.db)',
            initialdir=initial_dir or None,
            filetypes=[('SchoolPoints DB', '*.db'), ('All files', '*.*')]
        )
        if not db_path:
            return
        if not os.path.exists(db_path):
            messagebox.showwarning('אזהרה', 'הקובץ שנבחר לא נמצא')
            return

        try:
            _ = Database(db_path=db_path)
        except Exception as e:
            messagebox.showerror('שגיאה', f'לא ניתן לפתוח מסד נתונים זה:\n{db_path}\n\n{e}')
            return

        new_cfg = dict(cfg) if isinstance(cfg, dict) else {}
        new_cfg['db_path'] = db_path
        if not self._save_app_config(new_cfg):
            messagebox.showerror('שגיאה', 'לא הצלחנו לשמור את ההגדרות')
            return

        try:
            messagebox.showinfo('עודכן', 'מסד הנתונים שויך לעמדה זו.\nיש להפעיל מחדש את העמדה כדי לטעון אותו.')
        except Exception:
            pass

    def _open_master_actions_dialog(self):
        self._touch_activity()
        try:
            if self._master_actions_dialog is not None and self._master_actions_dialog.winfo_exists():
                try:
                    self._master_actions_dialog.lift()
                except Exception:
                    pass
                return
        except Exception:
            pass

        dlg = tk.Toplevel(self.root)
        dlg.title('🔐 כרטיס מאסטר')
        dlg.configure(bg='#0f0f14')
        dlg.transient(self.root)
        dlg.grab_set()
        try:
            dlg.minsize(520, 320)
        except Exception:
            pass
        try:
            dlg.resizable(False, False)
        except Exception:
            pass

        tk.Label(
            dlg,
            text='פעולות כרטיס מאסטר',
            font=('Arial', 22, 'bold'),
            fg='white',
            bg='#0f0f14',
            anchor='e',
            justify='right'
        ).pack(padx=18, pady=(18, 6), anchor='e')
        tk.Label(
            dlg,
            text='בחר פעולה לביצוע',
            font=('Arial', 15),
            fg='#f1c40f',
            bg='#0f0f14',
            anchor='e',
            justify='right'
        ).pack(padx=18, pady=(0, 16), anchor='e')

        btns = tk.Frame(dlg, bg='#0f0f14')
        btns.pack(fill=tk.X, padx=18, pady=(0, 16))

        def _close():
            self._touch_activity()
            try:
                dlg.destroy()
            except Exception:
                pass
            self._master_actions_dialog = None

        def _open_settings():
            self._touch_activity()
            _close()
            try:
                self._open_cashier_settings_dialog()
            except Exception:
                pass

        def _select_db():
            self._touch_activity()
            _close()
            try:
                self._select_db_path_for_station()
            except Exception:
                pass

        def _exit_now():
            self._touch_activity()
            try:
                if not messagebox.askyesno('יציאה', 'לצאת מעמדת הקופה?', parent=dlg):
                    return
            except Exception:
                pass
            _close()
            try:
                self._exit_app()
            except Exception:
                pass

        tk.Button(
            btns,
            text='⚙ פתיחת הגדרות',
            command=_open_settings,
            font=('Arial', 16, 'bold'),
            bg='#3498db',
            fg='white',
            padx=18,
            pady=10
        ).pack(fill=tk.X, pady=6)
        tk.Button(
            btns,
            text='🗄️ שיוך מסד נתונים לעמדה',
            command=_select_db,
            font=('Arial', 16, 'bold'),
            bg='#8e44ad',
            fg='white',
            padx=18,
            pady=10
        ).pack(fill=tk.X, pady=6)
        tk.Button(
            btns,
            text='⛔ יציאה מהעמדה',
            command=_exit_now,
            font=('Arial', 16, 'bold'),
            bg='#c0392b',
            fg='white',
            padx=18,
            pady=10
        ).pack(fill=tk.X, pady=6)

        tk.Button(
            dlg,
            text='סגור',
            command=_close,
            font=('Arial', 14, 'bold'),
            bg='#7f8c8d',
            fg='white',
            padx=18,
            pady=8
        ).pack(pady=(0, 18))

        try:
            dlg.protocol('WM_DELETE_WINDOW', _close)
        except Exception:
            pass

        self._master_actions_dialog = dlg

    def _open_cashier_settings_dialog(self):
        self._touch_activity()

        cfg = {}
        try:
            cfg = self._load_app_config() or {}
        except Exception:
            cfg = {}

        dlg = tk.Toplevel(self.root)
        dlg.title('⚙ הגדרות עמדת קופה')
        dlg.configure(bg='#ecf0f1')
        dlg.transient(self.root)
        dlg.grab_set()
        try:
            dlg.geometry('940x680')
        except Exception:
            pass
        try:
            dlg.minsize(820, 560)
        except Exception:
            pass
        try:
            dlg.resizable(True, True)
        except Exception:
            pass

        tk.Label(dlg, text='הגדרות עמדת קופה', font=('Arial', 16, 'bold'), bg='#ecf0f1', fg='#2c3e50').pack(pady=(14, 10))

        frame = tk.Frame(dlg, bg='#ecf0f1')
        frame.pack(fill=tk.BOTH, expand=True, padx=18, pady=(0, 10))

        # Shared folder
        tk.Label(frame, text='תיקיית רשת משותפת:', font=('Arial', 12, 'bold'), bg='#ecf0f1', fg='#2c3e50', anchor='e').grid(row=0, column=0, sticky='e', pady=8)
        shared_var = tk.StringVar(value=str((cfg or {}).get('shared_folder') or (cfg or {}).get('network_root') or ''))
        shared_entry = tk.Entry(frame, textvariable=shared_var, font=('Arial', 12), width=46)
        shared_entry.grid(row=0, column=1, sticky='ew', padx=(10, 10), pady=8)

        def _lock_shared_entry() -> None:
            try:
                value = str(shared_var.get() or '').strip()
            except Exception:
                value = ''
            if value:
                try:
                    shared_entry.configure(state='readonly', readonlybackground='#e5e5e5')
                except Exception:
                    pass
            else:
                try:
                    shared_entry.configure(state='normal')
                except Exception:
                    pass

        def _browse_shared():
            try:
                current = str(shared_var.get() or '').strip()
            except Exception:
                current = ''
            if current:
                try:
                    if not messagebox.askyesno('שינוי מיקום', 'הוגדרה כבר תיקיית רשת.\nלשנות את המיקום?', parent=dlg):
                        return
                except Exception:
                    pass
            folder = filedialog.askdirectory(title='בחר תיקיית רשת משותפת')
            if folder:
                shared_var.set(str(folder))
                _lock_shared_entry()

        tk.Button(frame, text='עיון...', command=_browse_shared, font=('Arial', 11, 'bold'), bg='#3498db', fg='white', padx=14, pady=6).grid(row=0, column=2, sticky='w', pady=8)
        _lock_shared_entry()

        # Default printer
        tk.Label(frame, text='מדפסת ברירת מחדל:', font=('Arial', 12, 'bold'), bg='#ecf0f1', fg='#2c3e50', anchor='e').grid(row=1, column=0, sticky='e', pady=8)
        printer_var = tk.StringVar(value=str((cfg or {}).get('default_printer') or ''))
        printers = []
        try:
            import win32print  # type: ignore
            flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
            for p in (win32print.EnumPrinters(flags) or []):
                try:
                    nm = str(p[2] or '').strip()
                except Exception:
                    nm = ''
                if nm:
                    printers.append(nm)
        except Exception:
            printers = []
        printers = [p for p in printers if p]
        # de-dup keep order
        seen = set()
        dedup = []
        for p in printers:
            if p not in seen:
                seen.add(p)
                dedup.append(p)
        printers = dedup

        if printers:
            printer_cb = ttk.Combobox(frame, textvariable=printer_var, values=printers, state='readonly', width=44, justify='right')
            printer_cb.grid(row=1, column=1, sticky='ew', padx=(10, 10), pady=8)
        else:
            printer_entry = tk.Entry(frame, textvariable=printer_var, font=('Arial', 12), width=46)
            printer_entry.grid(row=1, column=1, sticky='ew', padx=(10, 10), pady=8)
        tk.Label(frame, text='(שם מדפסת כפי שמופיע ב-Windows)', font=('Arial', 10), bg='#ecf0f1', fg='#7f8c8d', anchor='e').grid(row=2, column=1, sticky='e', pady=(0, 10))

        # Customer display settings
        tk.Label(frame, text='', bg='#ecf0f1').grid(row=3, column=0, columnspan=3, pady=5)
        tk.Label(frame, text='הגדרות מסך לקוח (VeriFone MX980L):', font=('Arial', 12, 'bold'), bg='#ecf0f1', fg='#2c3e50', anchor='e').grid(row=4, column=0, columnspan=3, sticky='ew', pady=(10, 5))
        
        customer_display_cfg = cfg.get('customer_display', {})
        if not isinstance(customer_display_cfg, dict):
            customer_display_cfg = {}
        
        # Enable customer display
        tk.Label(frame, text='הפעל מסך לקוח:', font=('Arial', 12, 'bold'), bg='#ecf0f1', fg='#2c3e50', anchor='e').grid(row=5, column=0, sticky='e', pady=8)
        customer_display_enabled_var = tk.BooleanVar(value=bool(customer_display_cfg.get('enabled', False)))
        tk.Checkbutton(frame, variable=customer_display_enabled_var, bg='#ecf0f1', font=('Arial', 12)).grid(row=5, column=1, sticky='w', padx=(10, 10), pady=8)
        
        # COM port
        tk.Label(frame, text='יציאת COM:', font=('Arial', 12, 'bold'), bg='#ecf0f1', fg='#2c3e50', anchor='e').grid(row=6, column=0, sticky='e', pady=8)
        customer_display_com_var = tk.StringVar(value=str(customer_display_cfg.get('com_port', 'COM1')))
        com_ports = ['COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8']
        customer_display_com_cb = ttk.Combobox(frame, textvariable=customer_display_com_var, values=com_ports, state='normal', width=44, justify='right')
        customer_display_com_cb.grid(row=6, column=1, sticky='ew', padx=(10, 10), pady=8)
        
        # Baud rate
        tk.Label(frame, text='קצב תקשורת (Baud):', font=('Arial', 12, 'bold'), bg='#ecf0f1', fg='#2c3e50', anchor='e').grid(row=7, column=0, sticky='e', pady=8)
        customer_display_baud_var = tk.StringVar(value=str(customer_display_cfg.get('baud_rate', 9600)))
        baud_rates = ['9600', '19200', '38400', '57600', '115200']
        customer_display_baud_cb = ttk.Combobox(frame, textvariable=customer_display_baud_var, values=baud_rates, state='readonly', width=44, justify='right')
        customer_display_baud_cb.grid(row=7, column=1, sticky='ew', padx=(10, 10), pady=8)
        tk.Label(frame, text='(ברירת מחדל: 9600)', font=('Arial', 10), bg='#ecf0f1', fg='#7f8c8d', anchor='e').grid(row=8, column=1, sticky='e', pady=(0, 10))

        frame.grid_columnconfigure(1, weight=1)

        btns = tk.Frame(dlg, bg='#ecf0f1')
        btns.pack(fill=tk.X, padx=18, pady=(0, 16))

        def _test_print():
            """Test thermal printer with sample receipt"""
            printer = str(printer_var.get() or '').strip()
            if not printer:
                messagebox.showwarning('אזהרה', 'בחר מדפסת תחילה', parent=dlg)
                return
            
            # Create test receipt with ESC/POS commands
            ESC = b'\x1b'
            INIT = ESC + b'@'
            BOLD_ON = ESC + b'E\x01'
            BOLD_OFF = ESC + b'E\x00'
            CENTER = ESC + b'a\x01'
            LEFT = ESC + b'a\x00'
            CUT = ESC + b'i'
            
            receipt = INIT
            receipt += CENTER + BOLD_ON
            receipt += "SCHOOLPOINTS SYSTEM\n".encode('cp862', errors='ignore')
            receipt += "TEST RECEIPT\n".encode('cp862', errors='ignore')
            receipt += BOLD_OFF
            receipt += "================================\n".encode('cp862', errors='ignore')
            receipt += "\n"
            receipt += LEFT
            receipt += "Date: {}\n".format(datetime.now().strftime('%d/%m/%Y')).encode('cp862', errors='ignore')
            receipt += "Time: {}\n".format(datetime.now().strftime('%H:%M:%S')).encode('cp862', errors='ignore')
            receipt += "\n"
            receipt += BOLD_ON + "ITEMS:\n".encode('cp862', errors='ignore') + BOLD_OFF
            receipt += "--------------------------------\n".encode('cp862', errors='ignore')
            receipt += "Test Item 1          10 pts\n".encode('cp862', errors='ignore')
            receipt += "Test Item 2          20 pts\n".encode('cp862', errors='ignore')
            receipt += "Test Item 3          15 pts\n".encode('cp862', errors='ignore')
            receipt += "--------------------------------\n".encode('cp862', errors='ignore')
            receipt += BOLD_ON
            receipt += "TOTAL:               45 pts\n".encode('cp862', errors='ignore')
            receipt += BOLD_OFF
            receipt += "\n"
            receipt += CENTER
            receipt += "Thank You!\n".encode('cp862', errors='ignore')
            receipt += "Thermal Print Test OK\n".encode('cp862', errors='ignore')
            receipt += "\n\n\n"
            receipt += CUT
            
            # Send to printer using existing method
            if self._send_raw_bytes_to_printer(printer, receipt):
                messagebox.showinfo('הצלחה', 'חשבונית דוגמה נשלחה למדפסת:\n{}\n\nאם לא הודפס, בדוק:\n1. המדפסת מוגדרת כ-TEXT ONLY\n2. המדפסת מחוברת ופועלת'.format(printer), parent=dlg)
            else:
                messagebox.showerror('שגיאה', 'ההדפסה נכשלה.\nבדוק:\n1. שם המדפסת נכון\n2. המדפסת מחוברת\n3. pywin32 מותקן', parent=dlg)

        def _save():
            new_cfg = dict(cfg) if isinstance(cfg, dict) else {}
            new_cfg['shared_folder'] = str(shared_var.get() or '').strip()
            if 'network_root' in new_cfg:
                try:
                    new_cfg.pop('network_root', None)
                except Exception:
                    pass
            new_cfg['default_printer'] = str(printer_var.get() or '').strip()
            
            # Save customer display settings
            new_cfg['customer_display'] = {
                'enabled': bool(customer_display_enabled_var.get()),
                'com_port': str(customer_display_com_var.get() or 'COM1').strip(),
                'baud_rate': int(customer_display_baud_var.get() or 9600)
            }
            
            if not self._save_app_config(new_cfg):
                messagebox.showerror('שגיאה', 'לא הצלחנו לשמור את ההגדרות', parent=dlg)
                return
            
            # Reconnect customer display with new settings (lazy/async)
            try:
                if self.customer_display:
                    self.customer_display.close()
            except Exception:
                pass
            try:
                self.customer_display = None
            except Exception:
                pass
            try:
                self._customer_display_config = self._load_customer_display_config()
                self._customer_display_enabled = bool(self._customer_display_config.get('enabled', False))
            except Exception:
                self._customer_display_config = {'enabled': False, 'com_port': 'COM1', 'baud_rate': 9600}
                self._customer_display_enabled = False
            try:
                self._customer_display_connecting = False
            except Exception:
                pass
            if bool(self._customer_display_enabled):
                try:
                    self.root.after(200, lambda: self._ensure_customer_display(show_welcome=True))
                except Exception:
                    pass
            
            try:
                dlg.destroy()
            except Exception:
                pass
            self._set_status('הגדרות נשמרו', is_error=False)

        tk.Button(btns, text='🖨️ טסט הדפסה', command=_test_print, font=('Arial', 12, 'bold'), bg='#3498db', fg='white', padx=18, pady=10).pack(side=tk.LEFT)
        tk.Button(btns, text='שמור', command=_save, font=('Arial', 12, 'bold'), bg='#27ae60', fg='white', padx=18, pady=10).pack(side=tk.LEFT, padx=(10, 0))
        tk.Button(btns, text='סגור', command=dlg.destroy, font=('Arial', 12, 'bold'), bg='#7f8c8d', fg='white', padx=18, pady=10).pack(side=tk.LEFT, padx=(10, 0))

    def _get_default_printer_from_config(self) -> str:
        try:
            cfg = self._load_app_config() or {}
        except Exception:
            cfg = {}
        try:
            return str((cfg or {}).get('default_printer') or '').strip()
        except Exception:
            return ''

    def _get_auto_cut_settings_from_config(self):
        try:
            cfg = self._load_app_config() or {}
        except Exception:
            cfg = {}
        enabled = True
        try:
            if isinstance(cfg, dict) and 'auto_cut' in cfg:
                enabled = bool(cfg.get('auto_cut'))
        except Exception:
            enabled = True
        cmd = '1D 56 42 11'
        try:
            if isinstance(cfg, dict) and str(cfg.get('printer_cut_command') or '').strip():
                cmd = str(cfg.get('printer_cut_command') or '').strip()
        except Exception:
            cmd = '1D 56 42 11'
        return enabled, cmd

    def _image_to_escpos_bytes(self, img) -> bytes:
        try:
            w, h = img.size
            width_bytes = (w + 7) // 8
            data = bytearray()
            data.extend(b'\x1D\x76\x30\x00')
            data.extend(bytes([width_bytes & 0xFF, (width_bytes >> 8) & 0xFF]))
            data.extend(bytes([h & 0xFF, (h >> 8) & 0xFF]))
            for y in range(h):
                for x in range(0, w, 8):
                    byte_val = 0
                    for bit in range(8):
                        if x + bit < w:
                            try:
                                pixel = img.getpixel((x + bit, y))
                            except Exception:
                                pixel = 255
                            if pixel == 0:
                                byte_val |= (1 << (7 - bit))
                    data.append(byte_val)
            return bytes(data)
        except Exception:
            return b''

    def _get_cached_text_title_bytes(self, title: str) -> bytes:
        title = str(title or '').strip()
        if not title:
            return b''
        try:
            cache = getattr(self, '_text_title_cache', None)
            if not isinstance(cache, dict):
                cache = {}
                setattr(self, '_text_title_cache', cache)
            if title in cache:
                return cache.get(title) or b''
        except Exception:
            cache = None

        try:
            from PIL import Image, ImageDraw, ImageFont
        except Exception:
            return b''

        try:
            base_dir = os.path.dirname(os.path.abspath(__file__))
        except Exception:
            base_dir = ''
        font_path = os.path.join(base_dir, 'Agas.ttf') if base_dir else 'Agas.ttf'
        if not os.path.exists(font_path):
            return b''
        try:
            font = ImageFont.truetype(font_path, 32)
        except Exception:
            return b''

        render_text = title[::-1]
        try:
            bbox = font.getbbox(render_text)
            text_w = max(1, int(bbox[2] - bbox[0]))
            text_h = max(1, int(bbox[3] - bbox[1]))
        except Exception:
            try:
                text_w, text_h = font.getsize(render_text)
            except Exception:
                text_w, text_h = (0, 0)

        width = 384
        pad_y = 6
        height = max(text_h + pad_y * 2, 24)
        img = Image.new('1', (width, height), 1)
        draw = ImageDraw.Draw(img)
        x = max(0, int((width - text_w) / 2))
        y = max(0, int((height - text_h) / 2))
        try:
            draw.text((x, y), render_text, font=font, fill=0)
        except Exception:
            return b''

        data = self._image_to_escpos_bytes(img)
        try:
            if cache is not None:
                cache[title] = data
        except Exception:
            pass
        return data

    def _get_cached_text_decoration(self, name: str) -> bytes:
        name = str(name or '').strip().lower()
        if not name:
            return b''
        try:
            cache = getattr(self, '_text_decoration_cache', None)
            if not isinstance(cache, dict):
                cache = {}
                setattr(self, '_text_decoration_cache', cache)
            if name in cache:
                return cache.get(name) or b''
        except Exception:
            cache = None

        try:
            from PIL import Image, ImageDraw
        except Exception:
            return b''

        try:
            if name == 'stars':
                img = Image.new('1', (384, 26), 1)
                draw = ImageDraw.Draw(img)
                for i in range(8):
                    x = 48 * i + 24
                    y = 13
                    size = 9
                    points = [(x, y - size), (x + size // 2, y), (x, y + size), (x - size // 2, y)]
                    draw.polygon(points, fill=0)
            elif name == 'dots':
                img = Image.new('1', (384, 18), 1)
                draw = ImageDraw.Draw(img)
                for x in range(0, 384, 12):
                    draw.ellipse([x, 7, x + 4, 11], fill=0)
            elif name == 'wave':
                img = Image.new('1', (384, 20), 1)
                draw = ImageDraw.Draw(img)
                import math
                points = []
                for x in range(384):
                    y = int(10 + 6 * math.sin(2 * math.pi * 4 * x / 384))
                    points.append((x, y))
                for offset in range(-1, 2):
                    draw.line([(p[0], p[1] + offset) for p in points], fill=0)
            elif name == 'zigzag':
                img = Image.new('1', (384, 20), 1)
                draw = ImageDraw.Draw(img)
                points = []
                for i in range(13):
                    x = i * 32
                    y = 4 if i % 2 == 0 else 16
                    points.append((x, y))
                draw.line(points, fill=0, width=3)
            else:
                return b''

            data = self._image_to_escpos_bytes(img)
            if isinstance(cache, dict):
                cache[name] = data
            return data
        except Exception:
            return b''

    def _get_cached_text_logo_bytes(self, logo_path: str) -> bytes:
        logo_path = str(logo_path or '').strip()
        if not logo_path:
            return b''
        try:
            logo_path = logo_path.replace('/', '\\')
        except Exception:
            pass
        try:
            if not os.path.exists(logo_path):
                return b''
        except Exception:
            return b''

        try:
            cache = getattr(self, '_text_logo_cache', None)
            if not isinstance(cache, dict):
                cache = {}
                setattr(self, '_text_logo_cache', cache)
            mtime = os.path.getmtime(logo_path)
            cached = cache.get('data') if cache.get('path') == logo_path and cache.get('mtime') == mtime else None
            if cached:
                return cached
        except Exception:
            cache = None

        try:
            from PIL import Image
        except Exception:
            return b''

        try:
            img = Image.open(logo_path).convert('L')
            w, h = img.size
            scale = min(384 / max(1, w), 120 / max(1, h))
            new_w = max(1, int(w * scale))
            new_h = max(1, int(h * scale))
            try:
                resample = Image.Resampling.LANCZOS
            except Exception:
                resample = Image.ANTIALIAS
            img_resized = img.resize((new_w, new_h), resample)
            img_bw = img_resized.point(lambda p: 0 if p < 128 else 255, mode='1')

            data = self._image_to_escpos_bytes(img_bw)
            try:
                if isinstance(cache, dict):
                    cache['path'] = logo_path
                    cache['mtime'] = mtime
                    cache['data'] = data
            except Exception:
                pass
            return data
        except Exception:
            return b''

    def _send_raw_bytes_to_printer(self, printer_name: str, data: bytes) -> bool:
        printer_name = str(printer_name or '').strip()
        if not printer_name or not data:
            return False
        try:
            import win32print  # type: ignore
        except Exception as e:
            print(f"[PRINT] win32print not available: {e}")
            return False
        h = None
        try:
            h = win32print.OpenPrinter(printer_name)
            try:
                win32print.StartDocPrinter(h, 1, ('SchoolPoints', None, 'RAW'))
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
            print(f"[PRINT] Raw print failed: {e}")
            try:
                if h:
                    win32print.ClosePrinter(h)
            except Exception:
                pass
            return False

    def _try_send_cut_command(self):
        printer = self._get_default_printer_from_config()
        if not printer:
            return
        enabled, cmd = self._get_auto_cut_settings_from_config()
        if not enabled:
            return
        hex_str = str(cmd or '').strip()
        if not hex_str:
            return
        parts = [p for p in re.split(r'[^0-9A-Fa-f]+', hex_str) if p]
        if not parts:
            return
        try:
            data = bytes(int(p, 16) for p in parts)
        except Exception:
            return
        self._send_raw_bytes_to_printer(printer, data)

    def _print_to_thermal_printer(self, receipt_data: dict) -> bool:
        """Print beautiful receipt as image to thermal printer"""
        try:
            cfg = self._load_app_config() or {}
            debug_prints = False
            try:
                debug_prints = bool(cfg.get('debug_prints') or cfg.get('debug_logs'))
            except Exception:
                debug_prints = False

            def _dbg(msg: str) -> None:
                if not debug_prints:
                    return
                try:
                    print(str(msg))
                except Exception:
                    pass

            _dbg("[PRINT] Starting thermal printer...")
            printer_cfg = cfg.get('receipt_printer', {})
            if not isinstance(printer_cfg, dict):
                _dbg("[PRINT] No printer config found")
                return False

            try:
                mode = str(printer_cfg.get('mode') or '').strip().lower()
            except Exception:
                mode = ''
            
            # Check if using new decorated printer (opt-in)
            use_decorated = printer_cfg.get('use_decorated_printer', False)
            
            if mode == 'text':
                printer_name = ''
                try:
                    printer_name = str((cfg or {}).get('default_printer') or '').strip()
                except Exception:
                    printer_name = ''
                if not printer_name:
                    printer_name = 'Cash Printer'
                
                if use_decorated:
                    # Use new decorated printer with caching and decorations
                    _dbg("[PRINT] Using decorated printer")
                    return self._print_with_decorated_printer(receipt_data, printer_name, cfg)
                else:
                    # Old simple text mode
                    _dbg("[PRINT] Using old text mode")
                    text_encoding = str(printer_cfg.get('text_encoding') or 'cp862').strip()
                    try:
                        text_codepage = int(printer_cfg.get('text_codepage', 0x0F))
                    except Exception:
                        text_codepage = 0x0F
                    send_codepage = bool(printer_cfg.get('send_codepage', True))
                    _dbg(f"[PRINT] text_encoding={text_encoding}, text_codepage={hex(text_codepage)}, send_codepage={send_codepage}")
                    # Resolve logo/closing message for text receipts
                    logo_path = ''
                    try:
                        logo_path = self.db.get_cashier_bw_logo_path() or cfg.get('logo_path', '')
                    except Exception:
                        logo_path = cfg.get('logo_path', '')
                    closing_message = ''
                    try:
                        closing_message = self.db.get_cashier_closing_message() or ''
                    except Exception:
                        try:
                            closing_message = self.db.get_cashier_receipt_footer_text() or ''
                        except Exception:
                            closing_message = ''

                    data = self._build_thermal_text_receipt_bytes(
                        receipt_data,
                        encoding=text_encoding,
                        codepage=text_codepage,
                        send_codepage=send_codepage,
                        logo_path=logo_path,
                        closing_message=closing_message,
                    )
                    ok = bool(self._send_raw_bytes_to_printer(printer_name, data))
                    if not ok:
                        _dbg("[PRINT] Raw text send failed")
                    return ok
            
            # Get print logo path from DB (set in admin panel) or fallback to config logo
            try:
                logo_path = self.db.get_cashier_bw_logo_path() or cfg.get('logo_path', '')
                _dbg(f"[PRINT] Logo path from DB: {logo_path}")
            except Exception as e:
                print(f"[PRINT] Error getting logo from DB: {e}")
                logo_path = cfg.get('logo_path', '')
            
            if logo_path:
                # Normalize path - convert forward slashes to backslashes for Windows
                logo_path = logo_path.replace('/', '\\')
                _dbg(f"[PRINT] Normalized logo path: {logo_path}")
                if not os.path.exists(logo_path):
                    _dbg(f"[PRINT] Logo not found: {logo_path}")
                    logo_path = None
                else:
                    _dbg(f"[PRINT] Logo found: {logo_path}")
            
            # Get closing message from DB (set in admin panel)
            try:
                closing_message = self.db.get_cashier_receipt_footer_text()
                _dbg(f"[PRINT] Closing message: {closing_message}")
            except Exception as e:
                print(f"[PRINT] Error getting closing message: {e}")
                closing_message = ''
            
            # Create receipt image
            _dbg("[PRINT] Creating receipt image...")
            receipt_img = create_receipt_image(receipt_data, logo_path, closing_message)
            _dbg(f"[PRINT] Receipt image created: {receipt_img.size if receipt_img else 'None'}")

            # Printing implementation (speed vs compatibility)
            image_impl = 'graphics'
            try:
                prn_cfg0 = cfg.get('receipt_printer', {})
                if isinstance(prn_cfg0, dict) and str(prn_cfg0.get('image_impl') or '').strip():
                    image_impl = str(prn_cfg0.get('image_impl') or '').strip()
            except Exception:
                image_impl = 'graphics'
            
            # Print using python-escpos
            try:
                from escpos.printer import Win32Raw

                # If configured to use a serial port (COMx), prefer direct Serial printing.
                # This avoids Windows "Generic / Text Only" driver path that may print ESC/POS binary as gibberish.
                try:
                    prn_cfg1 = cfg.get('receipt_printer', {})
                    port = ''
                    baudrate = 38400
                    if isinstance(prn_cfg1, dict):
                        port = str(prn_cfg1.get('port') or '').strip()
                        try:
                            baudrate = int(prn_cfg1.get('baudrate') or 38400)
                        except Exception:
                            baudrate = 38400
                    if port and port.upper().startswith('COM'):
                        from escpos.printer import Serial  # type: ignore
                        _dbg(f"[PRINT] Using Serial printer on {port} baud={baudrate}")
                        ps = None
                        try:
                            ps = Serial(port=port, baudrate=baudrate, timeout=2)
                            _dbg("[PRINT] Printing receipt image (Serial)...")
                            ps.image(receipt_img, center=False, impl=image_impl)
                            ps.text('\n\n\n')
                            ps.cut()
                            try:
                                ps._raw(b'')
                            except Exception:
                                pass
                            _dbg("[PRINT] Print completed successfully! (Serial)")
                            return True
                        finally:
                            try:
                                if ps is not None:
                                    ps.close()
                            except Exception:
                                pass
                except Exception:
                    pass
                
                printer_name = ''
                try:
                    printer_name = str((cfg or {}).get('default_printer') or '').strip()
                except Exception:
                    printer_name = ''
                if not printer_name:
                    printer_name = "Cash Printer"

                # Warm-up on first use: reduces first-print latency (spooler/printer wake)
                try:
                    warmed = getattr(self, '_thermal_printer_warmed', None)
                    if not isinstance(warmed, dict):
                        warmed = {}
                        setattr(self, '_thermal_printer_warmed', warmed)
                    if not warmed.get(printer_name):
                        try:
                            # ESC/POS init only (should not feed paper)
                            self._send_raw_bytes_to_printer(printer_name, b'\x1b@')
                        except Exception:
                            pass
                        warmed[printer_name] = True
                except Exception:
                    pass
                _dbg(f"[PRINT] Connecting to printer: {printer_name}")
                p = None
                try:
                    p = Win32Raw(printer_name)
                    
                    # Print receipt image
                    _dbg("[PRINT] Printing receipt image...")
                    p.image(receipt_img, center=False, impl=image_impl)
                    
                    # Cut paper
                    _dbg("[PRINT] Cutting paper...")
                    p.text('\n\n\n')
                    p.cut()
                    
                    # Force flush to printer
                    _dbg("[PRINT] Flushing to printer...")
                    try:
                        p._raw(b'')  # Send empty command to flush
                    except Exception:
                        pass

                    _dbg("[PRINT] Print completed successfully!")
                    return True
                finally:
                    # IMPORTANT: close handle so Windows flushes the raw job immediately
                    try:
                        if p is not None:
                            p.close()
                    except Exception:
                        pass
                
            except ImportError as e:
                # Fallback: python-escpos not installed, try direct COM port
                print(f"[PRINT] python-escpos not available: {e}")
                return self._print_to_thermal_printer_fallback(receipt_data)
            except Exception as e:
                print(f"[PRINT] Printer error: {e}")
                import traceback
                traceback.print_exc()
                return False
            
        except Exception as e:
            print(f"[PRINT] Thermal printer error: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _print_to_thermal_printer_fallback(self, receipt_data: dict) -> bool:
        """Fallback: Print simple text receipt via COM port (old method)"""
        try:
            cfg = self._load_app_config() or {}
            printer_cfg = cfg.get('receipt_printer', {})
            if not isinstance(printer_cfg, dict):
                return False
            
            port = str(printer_cfg.get('port', '')).strip()
            baudrate = int(printer_cfg.get('baudrate', 38400))
            
            if not port:
                return False
            
            import serial
            
            ser = serial.Serial(
                port=port,
                baudrate=baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=2
            )
            
            # ESC/POS commands
            ESC = b'\x1B'
            GS = b'\x1D'
            INIT = ESC + b'@'
            CUT = GS + b'V\x42\x00'
            
            # Simple text receipt
            ser.write(INIT)
            ser.write(b'Receipt\n')
            ser.write(b'=' * 32 + b'\n')
            
            if receipt_data.get('student_name'):
                ser.write(f"Student: {receipt_data['student_name']}\n".encode('ascii', errors='ignore'))
            
            for item in receipt_data.get('items', []):
                name = str(item.get('name', ''))
                price = float(item.get('price', 0))
                ser.write(f"{name}: {price:.2f}\n".encode('ascii', errors='ignore'))
            
            total = float(receipt_data.get('total', 0))
            ser.write(f"Total: {total:.2f}\n".encode('ascii', errors='ignore'))
            ser.write(b'\n\n\n')
            ser.write(CUT)
            
            ser.close()
            return True
            
        except Exception as e:
            print(f"Fallback thermal printer error: {e}")
            return False
    
    def _print_item_voucher_to_thermal(
        self,
        student_id: int,
        item_label: str,
        qty: int = 1,
        price_points: int = 0,
        slot_text: str = '',
        duration_minutes: int = 0,
        service_date: str = '',
        slot_time: str = '',
    ):
        """Print simple item voucher to thermal printer"""
        try:
            # Get student info
            try:
                st = self.db.get_student_by_id(int(student_id or 0))
            except Exception:
                st = None
            st = st or (self._current_student or {})
            student_name = f"{str(st.get('first_name') or '').strip()} {str(st.get('last_name') or '').strip()}".strip()
            cls = str(st.get('class_name') or '').strip()
            
            try:
                cfg = self._load_app_config() or {}
            except Exception:
                cfg = {}

            points_after = None
            points_before = None
            try:
                points_after = int(float(st.get('points', 0) or 0)) if st else None
                points_before = int(points_after or 0) + int(qty or 0) * int(price_points or 0)
            except Exception:
                points_before = None
                points_after = None

            service_date = str(service_date or '').strip()
            slot_time = str(slot_time or '').strip()
            if not service_date and not slot_time and slot_text:
                try:
                    parts = str(slot_text).strip().split()
                except Exception:
                    parts = []
                if len(parts) >= 2:
                    service_date = parts[0]
                    slot_time = parts[1]
                elif len(parts) == 1 and ':' in parts[0]:
                    slot_time = parts[0]

            # Build simple voucher data
            voucher_data = {
                'student_name': student_name,
                'class_name': cls,
                'item_name': item_label,
                'qty': qty,
                'price': price_points,
                'slot_text': slot_text,
                'service_date': service_date,
                'slot_time': slot_time,
                'duration_minutes': duration_minutes,
                'points_before': points_before,
                'points_after': points_after,
            }

            try:
                printer_cfg = cfg.get('receipt_printer', {})
                mode = str((printer_cfg or {}).get('mode') or '').strip().lower()
            except Exception:
                mode = ''
            if mode == 'text':
                printer_name = ''
                try:
                    printer_name = str((cfg or {}).get('default_printer') or '').strip()
                except Exception:
                    printer_name = ''
                if not printer_name:
                    printer_name = 'Cash Printer'
                text_encoding = str((printer_cfg or {}).get('text_encoding') or 'cp862').strip()
                try:
                    text_codepage = int((printer_cfg or {}).get('text_codepage', 0x0F))
                except Exception:
                    text_codepage = 0x0F
                send_codepage = bool((printer_cfg or {}).get('send_codepage', True))
                logo_path = ''
                try:
                    logo_path = self.db.get_cashier_bw_logo_path() or cfg.get('logo_path', '')
                except Exception:
                    logo_path = cfg.get('logo_path', '')
                data = self._build_thermal_text_voucher_bytes(
                    voucher_data,
                    encoding=text_encoding,
                    codepage=text_codepage,
                    send_codepage=send_codepage,
                    logo_path=logo_path,
                )
                return bool(self._send_raw_bytes_to_printer(printer_name, data))
            
            # Create simple voucher image (not full receipt)
            from voucher_image_generator import create_voucher_image
            
            # Get print logo path from DB (set in admin panel) or fallback to config logo
            try:
                logo_path = self.db.get_cashier_bw_logo_path() or cfg.get('logo_path', '')
            except Exception:
                logo_path = cfg.get('logo_path', '')
            
            if logo_path:
                # Normalize path - convert forward slashes to backslashes for Windows
                logo_path = logo_path.replace('/', '\\')
                if not os.path.exists(logo_path):
                    print(f"Print logo not found in voucher: {logo_path}")
                    logo_path = None
            
            # Create voucher image
            voucher_img = create_voucher_image(voucher_data, logo_path)

            image_impl = 'graphics'
            try:
                prn_cfg0 = cfg.get('receipt_printer', {})
                if isinstance(prn_cfg0, dict) and str(prn_cfg0.get('image_impl') or '').strip():
                    image_impl = str(prn_cfg0.get('image_impl') or '').strip()
            except Exception:
                image_impl = 'graphics'
            
            # Print using python-escpos
            try:
                from escpos.printer import Win32Raw

                # Prefer direct Serial printing if configured (COMx)
                try:
                    prn_cfg1 = cfg.get('receipt_printer', {})
                    port = ''
                    baudrate = 38400
                    if isinstance(prn_cfg1, dict):
                        port = str(prn_cfg1.get('port') or '').strip()
                        try:
                            baudrate = int(prn_cfg1.get('baudrate') or 38400)
                        except Exception:
                            baudrate = 38400
                    if port and port.upper().startswith('COM'):
                        from escpos.printer import Serial  # type: ignore
                        ps = None
                        try:
                            ps = Serial(port=port, baudrate=baudrate, timeout=2)
                            # Print voucher image (all info is in the image, no extra text needed)
                            ps.image(voucher_img, center=False, impl=image_impl)
                            ps.text('\n\n')
                            ps.cut()
                            try:
                                ps._raw(b'')
                            except Exception:
                                pass
                            return True
                        finally:
                            try:
                                if ps is not None:
                                    ps.close()
                            except Exception:
                                pass
                except Exception:
                    pass
                
                printer_name = ''
                try:
                    printer_name = str((cfg or {}).get('default_printer') or '').strip()
                except Exception:
                    printer_name = ''
                if not printer_name:
                    printer_name = "Cash Printer"
                p = None
                try:
                    p = Win32Raw(printer_name)
                    
                    # Print voucher image (all info is in the image, no extra text needed)
                    p.image(voucher_img, center=False, impl=image_impl)
                    
                    # Cut paper
                    p.text('\n\n')
                    p.cut()
                    
                    # Force flush to printer
                    try:
                        p._raw(b'')  # Send empty command to flush
                    except Exception:
                        pass
                    
                    return True
                finally:
                    # IMPORTANT: close handle so Windows flushes the raw job immediately
                    try:
                        if p is not None:
                            p.close()
                    except Exception:
                        pass
                
            except ImportError as e:
                print(f"python-escpos not available for voucher printing: {e}")
                return False
            
        except Exception as e:
            print(f"Voucher thermal printer error: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _print_or_open_pdf(self, pdf_path: str):
        """
        NOTE: This function name is misleading for thermal printers.
        For TEXT ONLY thermal printers, we should NOT print the PDF.
        Instead, generate and send raw text with ESC/POS commands.
        The PDF is only for fallback/preview purposes.
        """
        pdf_path = str(pdf_path or '').strip()
        if not pdf_path or not os.path.exists(pdf_path):
            return

        # Try to print to configured/default printer first
        printed = False
        try:
            printer = self._get_default_printer_from_config()
        except Exception:
            printer = ''

        try:
            # Use ShellExecute print/printto (works for PDF readers that register these verbs)
            import win32api  # type: ignore
            if printer:
                try:
                    win32api.ShellExecute(0, 'printto', pdf_path, f'"{printer}"', '.', 0)
                    printed = True
                except Exception:
                    printed = False
            if not printed:
                try:
                    win32api.ShellExecute(0, 'print', pdf_path, None, '.', 0)
                    printed = True
                except Exception:
                    printed = False
        except Exception:
            printed = False

        if printed:
            return

        # Fallback: open PDF
        try:
            os.startfile(pdf_path)
        except Exception:
            messagebox.showerror('שגיאה', f'לא ניתן לפתוח את הקובץ:\n{pdf_path}')

    def _get_photos_folder_cached(self) -> str:
        try:
            v = str(getattr(self, '_photos_folder_cache', '') or '').strip()
        except Exception:
            v = ''
        if v:
            return v
        try:
            cfg = self._load_app_config() or {}
        except Exception:
            cfg = {}
        try:
            if isinstance(cfg, dict):
                v = str(cfg.get('photos_folder') or '').strip()
        except Exception:
            v = ''
        try:
            self._photos_folder_cache = v
        except Exception:
            pass
        return v

    def _font_try_load(self, size: int):
        size = int(size or 16)
        for fp in [
            'C:/Windows/Fonts/arial.ttf',
            'C:/Windows/Fonts/Arial.ttf',
            'C:/Windows/Fonts/ARIALUNI.TTF',
            'C:/Windows/Fonts/tahoma.ttf',
        ]:
            try:
                if os.path.exists(fp):
                    return ImageFont.truetype(fp, size=size)
            except Exception:
                pass
        try:
            return ImageFont.load_default()
        except Exception:
            return None

    def _receipt_line(self, text: str) -> str:
        return self._strip_asterisk_annotations(str(text or ''))

    def _rtl_display(self, s: str) -> str:
        s = str(s or '')
        # Only apply BiDi on Hebrew-containing strings. This avoids odd reordering for numeric-only lines.
        try:
            if not re.search(r'[\u0590-\u05FF]', s):
                return s
        except Exception:
            pass
        try:
            from bidi.algorithm import get_display  # type: ignore
        except Exception:
            return s
        try:
            return get_display(s)
        except Exception:
            return s

    def _generate_item_voucher_pdf(self, *, student_id: int, item_label: str, qty: int = 1, price_points: int = 0, slot_text: str = '', duration_minutes: int = 0) -> str:
        """Generate a small per-item voucher PDF for operator collection."""
        try:
            st = self.db.get_student_by_id(int(student_id or 0))
        except Exception:
            st = None
        st = st or (self._current_student or {})
        student_name = f"{str(st.get('first_name') or '').strip()} {str(st.get('last_name') or '').strip()}".strip()
        cls = str(st.get('class_name') or '').strip()
        now = datetime.now()
        dt_txt = now.strftime('%Y-%m-%d %H:%M')
        
        # Add Hebrew date
        heb_date = ''
        try:
            from jewish_calendar import hebrew_date_from_gregorian_str
            greg_date = now.strftime('%Y-%m-%d')
            heb_date = hebrew_date_from_gregorian_str(greg_date)
        except Exception:
            heb_date = ''

        op = getattr(self, '_operator', None) or {}
        op_name = ''
        try:
            op_name = str(op.get('name') or '').strip()
        except Exception:
            op_name = ''
        if not op_name:
            try:
                op_name = f"{str(op.get('first_name') or '').strip()} {str(op.get('last_name') or '').strip()}".strip()
            except Exception:
                op_name = ''

        label = str(item_label or '').strip()
        if not label:
            label = 'פריט'
        try:
            pts = int(price_points or 0)
        except Exception:
            pts = 0
        try:
            qty = int(qty or 1)
        except Exception:
            qty = 1
        if qty <= 0:
            qty = 1
        slot_text = str(slot_text or '').strip()

        date_part = ''
        start_time = ''
        # slot_text can be either "HH:MM" or "YYYY-MM-DD HH:MM"
        if slot_text:
            parts0 = [p for p in str(slot_text).split(' ') if p]
            if len(parts0) >= 2:
                date_part = parts0[0].strip()
                start_time = parts0[-1].strip()
            else:
                start_time = parts0[0].strip() if parts0 else ''

        time_range = ''
        if start_time and duration_minutes:
            try:
                dur = int(duration_minutes or 0)
            except Exception:
                dur = 0
            if dur > 0:
                try:
                    hh, mm = str(start_time).split(':', 1)
                    start_min = int(hh) * 60 + int(mm)
                    end_min = (start_min + int(dur)) % (24 * 60)
                    end_h = int(end_min // 60)
                    end_m = int(end_min % 60)
                    end_txt = f"{end_h:02d}:{end_m:02d}"
                    time_range = f"משעה {start_time} עד שעה {end_txt}".strip()
                except Exception:
                    time_range = ''

        points_total = int(pts) * int(qty)

        footer_text = ''
        try:
            footer_text = str(self.db.get_cashier_receipt_footer_text() or '').strip()
        except Exception:
            footer_text = ''

        lines = []
        lines.append('שובר למפעיל')
        lines.append(dt_txt)
        if heb_date:
            lines.append(heb_date)
        if op_name:
            lines.append(f"מפעיל: {op_name}")
        lines.append(f"{student_name} | {cls}".strip(' |'))
        lines.append('--------------------------')
        lines.append(f"פריט: {label}")
        if date_part:
            try:
                he = hebrew_date_from_gregorian_str(date_part) or ''
            except Exception:
                he = ''
            if he:
                lines.append(f"תאריך: {he}")
            else:
                lines.append(f"תאריך: {date_part}")
        if time_range:
            lines.append(f"זמן: {time_range}")
        elif start_time:
            lines.append(f"שעה: {start_time}")
        lines.append(f"כמות: {qty}")
        lines.append(f"סה\"כ לשורה: {points_total} נק'")
        lines.append('--------------------------')
        if footer_text:
            lines.append(str(footer_text))
        # Extra bottom padding so the last line won't get cut on thermal printers
        lines.append('')
        lines.append('')

        font = self._font_try_load(24)
        font_small = self._font_try_load(18)
        try:
            line_h = int((font_small.size if hasattr(font_small, 'size') else 18) * 1.4)
        except Exception:
            line_h = 26
        width = 620
        pad = 22
        height = max(240, pad * 2 + line_h * (len(lines) + 4))
        img = Image.new('RGB', (width, height), color='white')
        draw = ImageDraw.Draw(img)

        y = pad

        # Optional logo
        try:
            logo_fp = ''
            try:
                logo_fp = str(self.db.get_cashier_bw_logo_path() or '').strip()
            except Exception:
                logo_fp = ''
            if logo_fp and os.path.exists(logo_fp):
                l_img = Image.open(logo_fp).convert('RGBA')
                l_img.thumbnail((220, 120))
                lx = int((width - l_img.size[0]) / 2)
                img.paste(l_img, (max(0, lx), y), l_img)
                y += int(l_img.size[1] + 8)
        except Exception:
            pass

        for i, ln in enumerate(lines):
            f = font_small if i in (1, 2) else font
            try:
                self._receipt_draw_line(draw, ln, width=width, pad=pad, y=y, font=f)
            except Exception:
                try:
                    draw.text((pad, y), str(ln or ''), font=f, fill='black')
                except Exception:
                    pass
            y += line_h

        base_dir = os.path.dirname(os.path.abspath(__file__))
        out_dir = os.path.join(os.environ.get('PROGRAMDATA', r'C:\ProgramData'), 'SchoolPoints', 'receipts')
        try:
            os.makedirs(out_dir, exist_ok=True)
        except Exception:
            out_dir = base_dir
        fn = f"voucher_{now.strftime('%Y%m%d_%H%M%S_%f')}.pdf"
        out_path = os.path.join(out_dir, fn)
        try:
            img.save(out_path, 'PDF', resolution=200.0)
        except Exception:
            try:
                out_path = os.path.join(out_dir, f"voucher_{now.strftime('%Y%m%d_%H%M%S_%f')}.png")
                img.save(out_path)
            except Exception:
                return ''
        return out_path

    def _receipt_draw_line(self, draw, text: str, *, width: int, pad: int, y: int, font):
        # Don't reverse text for PDF - PDF viewers handle RTL correctly
        ln = self._receipt_line(text)
        try:
            bbox = draw.textbbox((0, 0), ln, font=font)
            tw = int((bbox[2] - bbox[0]) if bbox else 0)
        except Exception:
            try:
                tw = int(draw.textlength(ln, font=font) or 0)
            except Exception:
                tw = 0
        x = max(pad, width - pad - tw)
        draw.text((x, y), ln, font=font, fill='black')

    def _generate_receipt_pdf(self, *, student_id: int, items: list, scheduled_reservations: list) -> str:
        try:
            st = self.db.get_student_by_id(int(student_id or 0))
        except Exception:
            st = None
        st = st or (self._current_student or {})

        student_name = f"{str(st.get('first_name') or '').strip()} {str(st.get('last_name') or '').strip()}".strip()
        cls = str(st.get('class_name') or '').strip()

        now = datetime.now()
        dt_txt = now.strftime('%Y-%m-%d %H:%M')
        
        # Add Hebrew date
        heb_date = ''
        try:
            from jewish_calendar import hebrew_date_from_gregorian_str
            greg_date = now.strftime('%Y-%m-%d')
            heb_date = hebrew_date_from_gregorian_str(greg_date)
        except Exception:
            heb_date = ''

        lines = []
        lines.append('קבלה - קופה')
        lines.append(dt_txt)
        if heb_date:
            lines.append(heb_date)
        if student_name or cls:
            lines.append(f"{student_name} | {cls}".strip(' |'))
        lines.append('--------------------------')

        total = 0
        for it in (items or []):
            try:
                pid = int(it.get('product_id') or 0)
            except Exception:
                pid = 0
            try:
                vid = int(it.get('variant_id') or 0)
            except Exception:
                vid = 0
            try:
                qty = int(it.get('qty') or 0)
            except Exception:
                qty = 0
            if not pid or qty <= 0:
                continue

            p = self._product_by_id.get(pid) or {}
            pname = (str(p.get('display_name') or '').strip() or str(p.get('name') or '').strip())
            pname = self._receipt_line(pname)

            v = self._get_variant_for_cart_key(pid, vid)
            vname = self._receipt_line(str(v.get('variant_name') or '').strip())
            try:
                price = int(v.get('price_points', 0) or 0)
            except Exception:
                price = 0
            item_total = int(price) * int(qty)
            total += item_total

            if int(vid or 0) > 0 and vname and vname != 'ברירת מחדל':
                item_label = f"{pname} - {vname}".strip(' -')
            else:
                item_label = pname
            lines.append(f"{qty} x {item_label}  =  {item_total} נק")

        # scheduled reservations: add service details by purchase_item_index
        by_idx = {}
        for sr in (scheduled_reservations or []):
            try:
                idx = int(sr.get('purchase_item_index') or -1)
            except Exception:
                idx = -1
            if idx >= 0:
                by_idx[idx] = sr

        for idx, it in enumerate(items or []):
            sr = by_idx.get(int(idx))
            if not sr:
                continue
            try:
                pid = int(it.get('product_id') or 0)
            except Exception:
                pid = 0
            if not pid:
                continue
            p = self._product_by_id.get(pid) or {}
            pname = (str(p.get('display_name') or '').strip() or str(p.get('name') or '').strip())
            pname = self._receipt_line(pname)
            sd = str(sr.get('service_date') or '').strip()
            stt = str(sr.get('slot_start_time') or '').strip()

            # duration: from scheduled_service row if available
            dur = ''
            try:
                svc = self._scheduled_by_pid.get(pid) or {}
                dm = int(svc.get('duration_minutes', 0) or 0)
                if dm > 0:
                    dur = f"{dm} דק'"
            except Exception:
                dur = ''

            date_txt = ''
            try:
                sid = int(sr.get('service_id') or 0)
            except Exception:
                sid = 0
            allowed_dates = list(self._scheduled_dates_by_service.get(sid, []) or [])
            if sid and len(allowed_dates) > 1:
                date_txt = hebrew_date_from_gregorian_str(sd) or ''
            if date_txt:
                lines.append(f"{pname}: {date_txt} {stt} {dur}".strip())
            else:
                lines.append(f"{pname}: {stt} {dur}".strip())

        # Summary
        lines.append('--------------------------')
        lines.append(f"סה\"כ: {total} נק")
        try:
            before_pts = int((st or {}).get('points', 0) or 0)
        except Exception:
            before_pts = 0
        try:
            after_pts = int(before_pts) - int(total)
        except Exception:
            after_pts = before_pts
        lines.append(f"יתרה לפני: {before_pts} נק")
        lines.append(f"עלות הקנייה: {total} נק")
        lines.append(f"יתרה אחרי: {after_pts} נק")

        footer_text = ''
        try:
            footer_text = str(self.db.get_cashier_receipt_footer_text() or '').strip()
        except Exception:
            footer_text = ''
        if footer_text:
            lines.append('--------------------------')
            lines.append(str(footer_text))
        # Extra bottom padding so the last line won't get cut
        lines.append('')
        lines.append('')

        # Render receipt to image
        font = self._font_try_load(22)
        font_small = self._font_try_load(18)
        try:
            line_h = int((font_small.size if hasattr(font_small, 'size') else 18) * 1.35)
        except Exception:
            line_h = 26
        # 80mm thermal printers: keep page narrow
        width = 620
        pad = 22
        height = max(260, pad * 2 + line_h * (len(lines) + 5))
        img = Image.new('RGB', (width, height), color='white')
        draw = ImageDraw.Draw(img)

        y = pad

        # Optional logo for printing (bw logo setting preferred)
        try:
            logo_fp = ''
            try:
                logo_fp = str(self.db.get_cashier_bw_logo_path() or '').strip()
            except Exception:
                logo_fp = ''
            if not logo_fp:
                try:
                    cfg = self._load_app_config() or {}
                    logo_fp = str(cfg.get('logo_path') or '').strip()
                except Exception:
                    logo_fp = ''
            if logo_fp and os.path.exists(logo_fp):
                l_img = Image.open(logo_fp).convert('RGBA')
                try:
                    l_img.thumbnail((max(120, int(width - pad * 2)), 140))
                except Exception:
                    l_img.thumbnail((260, 140))
                lx = int((width - l_img.size[0]) / 2)
                img.paste(l_img, (max(0, lx), y), l_img)
                y += int(l_img.size[1] + 10)
        except Exception:
            pass

        for i, ln in enumerate(lines):
            f = font_small if i in (1,) else font
            try:
                self._receipt_draw_line(draw, ln, width=width, pad=pad, y=y, font=f)
            except Exception:
                try:
                    draw.text((pad, y), str(ln or ''), font=f, fill='black')
                except Exception:
                    pass
            y += line_h

        base_dir = os.path.dirname(os.path.abspath(__file__))
        out_dir = os.path.join(os.environ.get('PROGRAMDATA', r'C:\ProgramData'), 'SchoolPoints', 'receipts')
        try:
            os.makedirs(out_dir, exist_ok=True)
        except Exception:
            out_dir = base_dir
        fn = f"receipt_{now.strftime('%Y%m%d_%H%M%S')}.pdf"
        out_path = os.path.join(out_dir, fn)
        try:
            img.save(out_path, 'PDF', resolution=200.0)
        except Exception:
            try:
                out_path = os.path.join(out_dir, f"receipt_{now.strftime('%Y%m%d_%H%M%S')}.png")
                img.save(out_path)
            except Exception:
                return ''
        return out_path

    # ----------------------------
    # Idle + input
    # ----------------------------

    def _bind_activity_tracking(self):
        # We accept both card reader as keyboard and GUI interaction.
        self._card_buffer = ''
        # bind_all is critical because focus is often inside Entry widgets (lock screen),
        # and card readers type as keyboard events to the focused widget.
        try:
            self.root.bind_all('<Key>', self._on_key)
            self.root.bind_all('<Motion>', lambda _e: self._touch_activity())
            self.root.bind_all('<Button>', lambda _e: self._touch_activity())
        except Exception:
            # fallback
            self.root.bind('<Key>', self._on_key)
            self.root.bind('<Motion>', lambda _e: self._touch_activity())
            self.root.bind('<Button>', lambda _e: self._touch_activity())

    def _on_key(self, event):
        # When the lock overlay Entry is focused, it will receive the card reader input itself
        # (and <Return>/<KP_Enter>/<Tab> trigger submit). If we also process the same keystrokes
        # here via bind_all, we may submit twice: unlock and then immediately re-lock.
        try:
            if self._locked and self._lock_entry is not None:
                try:
                    if self.root.focus_get() == self._lock_entry:
                        return
                except Exception:
                    pass
        except Exception:
            pass

        # Some readers send Enter/Tab with empty event.char; use keysym as well.
        try:
            keysym = str(getattr(event, 'keysym', '') or '')
        except Exception:
            keysym = ''
        try:
            ch = event.char
        except Exception:
            ch = ''

        # If we have no printable char, try to extract it from keysym (e.g. some readers / keypad drivers).
        if not ch:
            if keysym in ('Return', 'KP_Enter', 'Tab'):
                ch = ''
            elif len(keysym) == 1 and keysym.isprintable():
                ch = keysym
            elif keysym.startswith('KP_'):
                kp = keysym.replace('KP_', '', 1)
                if len(kp) == 1 and kp.isdigit():
                    ch = kp

        if not ch and keysym not in ('Return', 'KP_Enter', 'Tab'):
            return
        self._touch_activity()

        if ch in ('\r', '\n') or keysym in ('Return', 'KP_Enter', 'Tab'):
            card = self._card_buffer.strip()
            self._card_buffer = ''
            if card:
                self.on_card_scanned(card)
            return
        if ch.isprintable():
            self._card_buffer += ch

    def _touch_activity(self):
        self._last_activity_ts = time.time()
        try:
            now = float(self._last_activity_ts)
            if (now - float(self._last_hold_refresh_ts or 0.0)) >= 20.0:
                self._refresh_holds_heartbeat()
        except Exception:
            pass

    def _refresh_holds_heartbeat(self):
        try:
            if self._locked:
                return
            if not self._current_student:
                return
            sid = int((self._current_student or {}).get('id') or 0)
            if not sid:
                return
            try:
                ttl = int(self._hold_ttl_minutes or 10)
            except Exception:
                ttl = 10
            self.db.refresh_holds(
                station_id=str(self.station_id or '').strip(),
                student_id=int(sid),
                ttl_minutes=int(ttl),
            )
            self._last_hold_refresh_ts = time.time()
        except Exception:
            pass

    def _schedule_hold_heartbeat(self):
        def _tick():
            try:
                self._refresh_holds_heartbeat()
            except Exception:
                pass
            try:
                self._hold_heartbeat_job = self.root.after(30000, _tick)
            except Exception:
                self._hold_heartbeat_job = None
        try:
            if self._hold_heartbeat_job is None:
                self._hold_heartbeat_job = self.root.after(30000, _tick)
        except Exception:
            self._hold_heartbeat_job = None

    def _schedule_idle_check(self):
        try:
            if self._idle_job is not None:
                self.root.after_cancel(self._idle_job)
        except Exception:
            pass

        def _tick():
            try:
                if (not self._locked) and self.cashier_mode in ('teacher', 'responsible_student'):
                    if time.time() - float(self._last_activity_ts) >= float(self.idle_timeout_sec or 300):
                        self._lock()
                self._idle_job = self.root.after(1000, _tick)
            except Exception:
                try:
                    self._idle_job = self.root.after(1000, _tick)
                except Exception:
                    self._idle_job = None

        try:
            self._idle_job = self.root.after(1000, _tick)
        except Exception:
            self._idle_job = None

    def _schedule_update_checks(self):
        try:
            self._check_for_updates_async(show_no_update=False)
            try:
                self.update_check_job = self.root.after(600000, lambda: self._check_for_updates_async(show_no_update=False))
            except Exception:
                self.update_check_job = None
        except Exception:
            pass

    def _compare_versions(self, local_v: str, remote_v: str) -> int:
        def _parts(v: str):
            try:
                return [int(p) for p in str(v or '').strip().split('.') if p != '']
            except Exception:
                return []

        a = _parts(local_v)
        b = _parts(remote_v)
        n = max(len(a), len(b))
        a += [0] * (n - len(a))
        b += [0] * (n - len(b))
        if a < b:
            return -1
        if a > b:
            return 1
        return 0

    def _check_for_updates_async(self, show_no_update: bool = False):
        try:
            cfg = self._load_app_config() or {}
            manifest_url = (cfg.get('update_manifest_url') or '').strip()
            if not manifest_url:
                return
        except Exception:
            return

        def _worker():
            payload = None
            err = None
            try:
                local_path = ''
                if manifest_url.lower().startswith('file://'):
                    try:
                        local_path = urllib.request.url2pathname(urllib.parse.urlparse(manifest_url).path or '')
                    except Exception:
                        local_path = ''
                elif os.path.exists(manifest_url):
                    local_path = manifest_url

                if local_path:
                    with open(local_path, 'r', encoding='utf-8') as f:
                        data = f.read()
                else:
                    req = urllib.request.Request(
                        manifest_url,
                        headers={'User-Agent': f'SchoolPoints/{APP_VERSION}'}
                    )
                    with urllib.request.urlopen(req, timeout=6) as resp:
                        data = resp.read().decode('utf-8', errors='replace')
                payload = json.loads(data)
            except Exception as e:
                err = str(e)

            def _on_ui():
                if err is not None:
                    return
                if not isinstance(payload, dict):
                    return

                remote_v = str(payload.get('version') or '').strip()
                if not remote_v:
                    return
                try:
                    if self._compare_versions(APP_VERSION, remote_v) >= 0:
                        return
                except Exception:
                    return

                cfg2 = self._load_app_config() or {}
                download_url = (payload.get('download_url') or cfg2.get('update_download_url') or '').strip()
                if download_url:
                    try:
                        self._download_update_package_async(download_url, remote_v)
                    except Exception:
                        pass

            try:
                self.root.after(0, _on_ui)
            except Exception:
                pass

        try:
            threading.Thread(target=_worker, daemon=True).start()
        except Exception:
            pass

    def _get_downloads_dir(self) -> str:
        try:
            home = os.path.expanduser('~')
            p = os.path.join(home, 'Downloads')
            if os.path.isdir(p):
                return p
        except Exception:
            pass
        return ''

    def _resolve_update_download_path(self, download_url: str, remote_version: str) -> str:
        try:
            url = str(download_url or '').strip()
        except Exception:
            url = ''
        filename = ''
        try:
            if url:
                parsed = urllib.parse.urlparse(url)
                filename = os.path.basename(parsed.path or '')
        except Exception:
            filename = ''
        if not filename:
            filename = f"SchoolPoints_Setup_v{remote_version}.exe" if remote_version else "SchoolPoints_Setup.exe"
        downloads_dir = self._get_downloads_dir()
        if not downloads_dir:
            try:
                downloads_dir = os.path.dirname(os.path.abspath(__file__))
            except Exception:
                downloads_dir = ''
        if downloads_dir:
            return os.path.join(downloads_dir, filename)
        return filename

    def _download_update_package_async(self, download_url: str, remote_version: str) -> str:
        try:
            url = str(download_url or '').strip()
        except Exception:
            url = ''
        if not url:
            return ''
        try:
            local_path = ''
            if url.lower().startswith('file://'):
                try:
                    local_path = urllib.request.url2pathname(urllib.parse.urlparse(url).path or '')
                except Exception:
                    local_path = ''
            elif os.path.exists(url):
                local_path = url
            if local_path and os.path.exists(local_path):
                return local_path
        except Exception:
            pass
        download_path = self._resolve_update_download_path(url, remote_version)
        if not download_path:
            return ''
        try:
            if os.path.exists(download_path) and os.path.getsize(download_path) > 0:
                return download_path
        except Exception:
            pass
        try:
            if getattr(self, '_update_download_version_in_progress', '') == remote_version:
                return download_path
        except Exception:
            pass
        self._update_download_version_in_progress = remote_version

        def _worker():
            ok = False
            tmp_path = download_path + '.part'
            try:
                try:
                    os.makedirs(os.path.dirname(download_path), exist_ok=True)
                except Exception:
                    pass
                with urllib.request.urlopen(url, timeout=20) as resp:
                    with open(tmp_path, 'wb') as f:
                        while True:
                            chunk = resp.read(65536)
                            if not chunk:
                                break
                            f.write(chunk)
                try:
                    os.replace(tmp_path, download_path)
                except Exception:
                    shutil.copy2(tmp_path, download_path)
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass
                ok = True
            except Exception:
                try:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)
                except Exception:
                    pass

            def _on_ui():
                try:
                    self._update_download_version_in_progress = ''
                except Exception:
                    pass
                if not ok:
                    return
                try:
                    self._update_downloaded_version = remote_version
                except Exception:
                    pass

            try:
                self.root.after(0, _on_ui)
            except Exception:
                pass

        try:
            threading.Thread(target=_worker, daemon=True).start()
        except Exception:
            try:
                self._update_download_version_in_progress = ''
            except Exception:
                pass
        return download_path

    def _set_status(self, msg: str, *, is_error: bool = False):
        self.status_var.set(str(msg or ''))
        try:
            self.status_label.config(fg=('#e74c3c' if is_error else '#ecf0f1'))
        except Exception:
            pass


def main():
    try:
        _enable_windows_dpi_awareness()
    except Exception:
        pass
    root = tk.Tk()
    try:
        import sys
        base_dir = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
        candidates = [
            os.path.join(base_dir, 'icons', 'cashier.ico'),
            os.path.join(os.path.dirname(base_dir), 'icons', 'cashier.ico'),
        ]
        for p in candidates:
            if p and os.path.exists(p):
                root.iconbitmap(p)
                break
    except Exception:
        pass
    try:
        # Avoid showing the main UI briefly before lock overlay is placed
        root.withdraw()
    except Exception:
        pass
    CashierStation(root)
    try:
        root.deiconify()
    except Exception:
        pass
    root.mainloop()


if __name__ == '__main__':
    main()
