"""
עמדה ציבורית - תצוגת נקודות לתלמידים
מקבל קלט מקורא RFID (מדמה מקלדת)
"""
import tkinter as tk
from tkinter import messagebox, filedialog
import tkinter.font as tkfont
from database import Database
from messages import MessagesDB
from PIL import Image, ImageTk, ImageOps, ImageDraw, ImageFont
import os
import json
import shutil
import time
import textwrap
import sys
import ctypes
import random
import traceback
import threading
import subprocess
import socket
import urllib.request
import urllib.parse
from license_manager import LicenseManager
from datetime import date, datetime
from sound_manager import SoundManager, USE_PYGAME

try:
    from ui_icons import normalize_ui_icons as _normalize_ui_icons
except Exception:
    _normalize_ui_icons = None

try:
    import jewish_calendar
except Exception:
    jewish_calendar = None
try:
    from bidi.algorithm import get_display
    BIDI_AVAILABLE = True
except ImportError:
    BIDI_AVAILABLE = False

# ניסיון אופציונלי להשתמש ב-pyautogui לצורך סימולציית קליק עכבר בחלון העמדה
try:
    pyautogui = None
    AUTO_CLICK_AVAILABLE = True
except Exception:
    pyautogui = None
    AUTO_CLICK_AVAILABLE = False


def _lazy_import_pyautogui():
    global pyautogui, AUTO_CLICK_AVAILABLE
    if pyautogui is not None:
        return pyautogui
    if not AUTO_CLICK_AVAILABLE:
        return None
    try:
        import pyautogui as _p
        pyautogui = _p
        AUTO_CLICK_AVAILABLE = True
        return pyautogui
    except Exception:
        pyautogui = None
        AUTO_CLICK_AVAILABLE = False
        return None

# סימני BIDI לתיקון כיוון טקסט עברי
RLE = '\u202b'  # Right-to-Left Embedding
PDF = '\u202c'  # Pop Directional Formatting
RLM = '\u200f'  # Right-to-Left Mark
LRM = '\u200e'  # Left-to-Right Mark
LRE = '\u202a'  # Left-to-Right Embedding

UNIVERSAL_MASTER_CODE = "05276247440527624744"

APP_VERSION = "1.6.4"

_DEBUG_LOG_ENABLED = False
_DEBUG_LOG_PATH = None


def _init_debug_log_settings() -> None:
    global _DEBUG_LOG_ENABLED, _DEBUG_LOG_PATH
    if _DEBUG_LOG_PATH is not None:
        return
    try:
        env = str(os.environ.get('SP_DEBUG_LOG', '') or '').strip().lower()
        if env in ('1', 'true', 'yes', 'on'):
            _DEBUG_LOG_ENABLED = True
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            roots = [base_dir, os.environ.get('PROGRAMDATA'), os.environ.get('LOCALAPPDATA'), os.environ.get('APPDATA'), os.environ.get('TEMP'), os.environ.get('TMP')]
            flags = ('public_station_debug.flag', 'enable_startup_log.flag')
            found = False
            for root in roots:
                if not root:
                    continue
                try:
                    for flag in flags:
                        if os.path.exists(os.path.join(root, flag)):
                            found = True
                            break
                        if os.path.exists(os.path.join(root, 'SchoolPoints', flag)):
                            found = True
                            break
                    if found:
                        break
                    if os.path.exists(os.path.join(root, 'SchoolPoints', 'public_station_startup.log')):
                        found = True
                        break
                except Exception:
                    continue
            _DEBUG_LOG_ENABLED = bool(found)

        if not _DEBUG_LOG_ENABLED:
            _DEBUG_LOG_PATH = None
            return

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
                    candidate = os.path.join(cfg_dir, 'public_station_startup.log')
                    try:
                        test_dir = os.path.dirname(candidate)
                        if os.path.isdir(test_dir) and os.access(test_dir, os.W_OK):
                            _DEBUG_LOG_PATH = candidate
                            break
                    except Exception:
                        pass
            except Exception:
                continue

        if not _DEBUG_LOG_PATH:
            try:
                tmp = os.environ.get('TEMP') or os.environ.get('TMP')
                if tmp and os.path.isdir(tmp) and os.access(tmp, os.W_OK):
                    _DEBUG_LOG_PATH = os.path.join(tmp, 'public_station_startup.log')
            except Exception:
                _DEBUG_LOG_PATH = None
        if not _DEBUG_LOG_PATH:
            _DEBUG_LOG_PATH = os.path.join(base_dir, 'public_station_startup.log')
    except Exception:
        _DEBUG_LOG_ENABLED = False
        _DEBUG_LOG_PATH = None

def _debug_log(msg: str) -> None:
    """רישום הודעת דיבוג לקובץ לוג מקומי, ללא זריקת חריגות.

    נועד לעזור כאשר התוכנית לא נפתחת ואין חלון קונסול (למשל בהרצה דרך קיצור דרך).
    """
    if not _DEBUG_LOG_ENABLED:
        return
    try:
        if _DEBUG_LOG_PATH is None:
            _init_debug_log_settings()
        if not _DEBUG_LOG_ENABLED or not _DEBUG_LOG_PATH:
            return
        ts = time.strftime('%Y-%m-%d %H:%M:%S')
        with open(_DEBUG_LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        # אסור לשבור את התוכנית בגלל לוג
        pass


try:
    _init_debug_log_settings()
    _debug_log('public_station module imported')
except Exception:
    pass


def _set_windows_dpi_awareness() -> None:
    try:
        if sys.platform != 'win32':
            return
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
            return
        except Exception:
            pass
    except Exception:
        pass


def _is_running_as_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _restart_as_admin() -> bool:
    if _is_running_as_admin():
        return False
    try:
        exe = sys.executable
    except Exception:
        return False
    try:
        script = os.path.abspath(__file__)
    except Exception:
        return False
    params = f'"{script}"'
    try:
        res = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
    except Exception:
        return False
    try:
        code = int(res)
    except Exception:
        code = 0
    return code > 32


def _safe_isdir(path: str, timeout_sec: float = 1.5) -> bool:
    """בדיקת תיקייה עם timeout כדי למנוע תקיעה על נתיבי רשת/UNC."""
    p = str(path or '').strip()
    if not p:
        return False

    out = {'ok': False}

    def _worker():
        try:
            out['ok'] = bool(os.path.isdir(p))
        except Exception:
            out['ok'] = False

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout=float(timeout_sec or 0))
    if t.is_alive():
        _debug_log(f'⚠ isdir timeout for path: {p}')
        return False
    return bool(out.get('ok'))


def _force_tk_scaling_96dpi(root: tk.Tk) -> None:
    try:
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


def _hex_to_rgb(color: str):
    try:
        if not color:
            return (255, 255, 255)
        c = str(color).strip()
        if c.startswith('#'):
            c = c[1:]
        if len(c) == 3:
            c = ''.join(ch * 2 for ch in c)
        if len(c) != 6:
            return (255, 255, 255)
        r = int(c[0:2], 16)
        g = int(c[2:4], 16)
        b = int(c[4:6], 16)
        return (r, g, b)
    except Exception:
        return (255, 255, 255)


def _get_color_settings_file(base_dir: str) -> str:
    """איתור נתיב קובץ הגדרות הצבעים במיקום כתיב, עם העתקת ברירת-מחדל אם צריך.

    כאשר מוגדרת תיקיית רשת משותפת (shared_folder) ב-config.json, נעדיף לשמור ולטעון
    את color_settings.json מתוכה כך שכל העמדות ישתמשו באותן הגדרות צבעים.
    """

    # ניסיון ראשון: שימוש בתיקיית רשת משותפת אם הוגדרה ב-config.json החי
    try:
        config_file = None
        for env_name in ("PROGRAMDATA", "LOCALAPPDATA", "APPDATA"):
            root = os.environ.get(env_name)
            if not root:
                continue
            cfg_dir = os.path.join(root, "SchoolPoints")
            candidate = os.path.join(cfg_dir, "config.json")
            if os.path.exists(candidate):
                config_file = candidate
                break

        if config_file and os.path.exists(config_file):
            with open(config_file, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            shared_folder = cfg.get("shared_folder") or cfg.get("network_root")
            if shared_folder and os.path.isdir(shared_folder):
                target = os.path.join(shared_folder, "color_settings.json")
                if not os.path.exists(target):
                    default = os.path.join(base_dir, "color_settings.json")
                    if os.path.exists(default):
                        try:
                            shutil.copy2(default, target)
                        except Exception:
                            pass
                return target
    except Exception:
        pass

    # ניסיון שני: קובץ הגדרות במיקום נתוני משתמש (LOCALAPPDATA/APPDATA/PROGRAMDATA)
    for env_name in ("LOCALAPPDATA", "APPDATA", "PROGRAMDATA"):
        root = os.environ.get(env_name)
        if not root or not os.path.isdir(root):
            continue
        try:
            cfg_dir = os.path.join(root, "SchoolPoints")
            os.makedirs(cfg_dir, exist_ok=True)
            _wt = os.path.join(cfg_dir, '.write_test')
            with open(_wt, 'w') as _wf:
                _wf.write('ok')
            os.remove(_wt)
            target = os.path.join(cfg_dir, "color_settings.json")
            if not os.path.exists(target):
                default = os.path.join(base_dir, "color_settings.json")
                if os.path.exists(default):
                    try:
                        shutil.copy2(default, target)
                    except Exception:
                        pass
            return target
        except Exception:
            continue

    # מוצא אחרון – שימוש בקובץ שבתיקיית הקוד (לרוב בסביבת פיתוח)
    return os.path.join(base_dir, "color_settings.json")


def fix_rtl_text(text):
    """תיקון כיוון טקסט עברי - RTL מלא"""
    if text and str(text).strip():
        # RLE בהתחלה + RLM בסוף לפני PDF - מבטיח שסימני פיסוק בסוף
        return RLE + str(text) + RLM + PDF
    return text


def render_rtl_for_tk(text: str) -> str:
    try:
        import re
        t = str(text or '')
    except Exception:
        return str(text or '')

    try:
        t = t.replace(RLE, '').replace(PDF, '').replace(RLM, '')
    except Exception:
        pass

    try:
        # הימנעות ממקפים בין עברית למספרים (בפונטים מסוימים זה יוצא כריבועים)
        t = re.sub(r'([א-ת])\s*[-–־]\s*(\d)', r'\1 \2', t)
        t = re.sub(r'(\d)\s*[-–־]\s*([א-ת])', r'\1 \2', t)
        # שמירת "מספר + יחידת זמן" יחד
        t = re.sub(r'(\d+)\s+(שעות|דקות|ימים|שעה|דקה|יום|שניות|שניה)', r'\1\u00a0\2', t)
        # עטיפת מספרים כדי למנוע קפיצות RTL
        t = re.sub(
            r'(\d+(?:[\.:]\d+)*(?:[־-]\d+(?:[\.:]\d+)*)*)',
            rf'{LRM}\1{RLM}',
            str(t or ''),
        )
    except Exception:
        pass

    try:
        disp = visual_rtl_simple(str(t or ''))
    except Exception:
        disp = str(t or '')
    try:
        for _m in (
            '\u200e', '\u200f', '\u202a', '\u202b', '\u202c', '\u202d', '\u202e',
            '\u2066', '\u2067', '\u2068', '\u2069', '\u061c',
        ):
            disp = disp.replace(_m, '')
    except Exception:
        pass
    return disp


def render_rtl_for_tk_label(text: str) -> str:
    """עיבוד RTL לטקסט ב-Tk Label – תיקון מספרים ופיסוק ב-RTL."""
    import re
    
    try:
        t = str(text or '')
    except Exception:
        return str(text or '')
    
    # נורמליזציה: הסרת מקפים בין עברית למספרים
    try:
        t = re.sub(r'([א-ת])\s*[-–־]\s*(\d)', r'\1 \2', t)
        t = re.sub(r'(\d)\s*[-–־]\s*([א-ת])', r'\1 \2', t)
        # שמירת "מספר + יחידת זמן" יחד
        t = re.sub(r'(\d+)\s+(שעות|דקות|ימים|שעה|דקה|יום|שניות|שניה)', r'\1\u00a0\2', t)
    except Exception:
        pass
    
    # תיקון פיסוק: הוספת RLM אחרי כל סימן פיסוק כדי שיישאר בצד שמאל
    try:
        t = re.sub(r'([!?.,;:])(?!\u200f)', rf'\1{RLM}', t)
    except Exception:
        pass
    
    # עטיפת מספרים + יחידות זמן ב-RLM...RLM (לא LRM/RLM) למניעת קפיצה
    try:
        # מספרים עם יחידות זמן עבריות
        t = re.sub(
            r'(\d+(?:[\.:]\d+)*)\s*(שעות|דקות|ימים|שעה|דקה|יום|שניות|שניה)',
            rf'{RLM}\1\u00a0\2{RLM}',
            t,
        )
        # מספרים בודדים שנותרו
        t = re.sub(
            r'(?<![א-ת\d\u200f])(\d+(?:[\.:]\d+)*)(?![א-ת\d\u200f])',
            rf'{RLM}\1{RLM}',
            t,
        )
    except Exception:
        pass
    
    return t


def visual_rtl_simple(text: str) -> str:
    """המרה חזותית לעברית RTL עבור טקסטים שרצים בשורה (כמו טיקר).

    משתמש בספרייה המקצועית python-bidi למניעת שיבושים.
    """
    if not text:
        return ""

    # ניקוי סימוני כיוון קודמים אם נוספו
    # חשוב: לא להסיר LRM/RLM כי הם משמשים לייצוב מספרים בתוך RTL
    t = text.replace(RLE, "").replace(PDF, "")
    if not t:
        return ""

    # שימוש בספרייה המקצועית אם זמינה
    if BIDI_AVAILABLE:
        try:
            return get_display(t, base_dir='R')
        except Exception as e:
            print(f"שגיאה ב-BIDI: {e}")
    
    # גיבוי: החזרת הטקסט כמו שהוא
    return t


def strip_asterisk_annotations(text: str) -> str:
    """הסרת הערות בין כוכביות (*...*) להצגה בעמדה הציבורית בלבד."""
    try:
        import re
        if not text:
            return text
        # מסיר כל קטע בין כוכביות כולל הכוכביות, לא גרידי.
        cleaned = re.sub(r'\*[^*]*\*', '', str(text))
        cleaned = re.sub(r'\s{2,}', ' ', cleaned).strip()
        return cleaned
    except Exception:
        return text


def normalize_ui_icons(text: str) -> str:
    """המרת אימוג'ים שלא תמיד נתמכים לסמלים פשוטים (כוכב, מידע, מעטפה)
    כדי למנוע ריבועים ובעיות כיוון עם סוגריים.
    """
    if _normalize_ui_icons is not None:
        try:
            return _normalize_ui_icons(text)
        except Exception:
            pass
    if not text:
        return text
    # כל האייקונים מומרים לסימנים שקיימים בפונט Gan CLM Bold שהותאם במיוחד,
    # כדי שלא יופיעו ריבועים.
    #
    # מיפוי לפי מה שהוגדר בפונט:
    #   U+E135  – מעטפה
    #   U+E0A2  – וי
    #   U+1F562 – שעון
    #   U+26A0  – אזהרה
    #   U+1F527 – הגדרות
    #   U+23F7  – חץ למטה
    #   U+1F3C3 – יציאה
    #   U+1F7D4 – כוכב
    #   U+1F6C8 – מידע
    replacements = {
        # וי / אישור
        "✅": "\ue0a2",
        "✔️": "\ue0a2",
        "✔": "\ue0a2",

        # כוכבים
        "⭐": "\U0001F7D4",
        "🌟": "\U0001F7D4",

        # מידע – ℹ למידע (U+1F6C8), אזהרה/שגיאה ל-26A0
        "ℹ️": "\U0001F6C8",
        "ℹ": "\U0001F6C8",
        "⚠️": "\u26A0",
        "⚠": "\u26A0",
        "❌": "\u26A0",

        # מעטפה
        "💌": "\ue135",

        # חץ למטה
        "⬇️": "\u23F7",
        "⬇": "\u23F7",

        # הגדרות
        "⚙️": "\U0001F527",
        "⚙": "\U0001F527",

        # יציאה / דלת
        "🚪": "\U0001F3C3",

        # שעונים
        "⏰": "\U0001F562",
        "🕒": "\U0001F562",
        "🕓": "\U0001F562",
        "🕔": "\U0001F562",
        "🕕": "\U0001F562",
        "🕖": "\U0001F562",
        "🕗": "\U0001F562",
        "🕘": "\U0001F562",
        "🕙": "\U0001F562",
        "🕚": "\U0001F562",
        "🕛": "\U0001F562",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)

    # ניקוי תווי שליטה שמשויכים לאימוג'י (ZWJ / variation selector) כדי שלא יופיעו כריבועים
    text = text.replace("\u200d", "").replace("\ufe0f", "")
    return text


class PublicStation:
    def __init__(self, root):
        self.root = root
        self.root.title("עמדה ציבורית - בדיקת נקודות")

        _debug_log('PublicStation.__init__ התחיל')
        self._update_loading(3, 'טוען הגדרות...')

        # תיקיית בסיס של האפליקציה (תומך ב-UNC)
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        _debug_log(f'base_dir={self.base_dir}')
        self.app_config = self.load_app_config()
        cfg_restart = self.app_config if isinstance(self.app_config, dict) else {}

        self._update_loading(8, 'בודק תצורת רשת...')
        if not self.ensure_shared_folder_config():
            try:
                self.root.after(100, self.root.destroy)
            except Exception:
                pass
            self._init_failed = True
            _debug_log('ensure_shared_folder_config נכשל – יציאה מהאתחול')
            return

        try:
            self.app_config = self.load_app_config()
        except Exception:
            pass

        try:
            self._maybe_start_local_sync_server()
        except Exception:
            pass

        # הפעלת סנכרון רקע אוטומטי (Hybrid/Cloud בלבד)
        self._update_loading(15, 'מאתחל סנכרון...')
        self._sync_agent_thread = None
        self._sync_agent_started = False
        try:
            self._maybe_start_sync_agent()
        except Exception:
            pass

        self._update_loading(22, 'טוען צלילים...')
        try:
            self._sounds_cache_dir = self._get_local_sounds_cache_dir()
        except Exception:
            self._sounds_cache_dir = None
        try:
            self._sync_sounds_from_network(self.app_config, self._sounds_cache_dir)
        except Exception:
            pass

        sounds_root = None
        try:
            cache_dir = self._sounds_cache_dir
            cache_has = False
            try:
                if cache_dir and os.path.isdir(cache_dir):
                    marker = os.path.join(cache_dir, '.sounds_cache_ready')
                    if os.path.exists(marker):
                        cache_has = True
                    else:
                        for root, _, files in os.walk(cache_dir):
                            if any(str(f).lower().endswith(('.wav', '.mp3', '.ogg')) for f in (files or [])):
                                cache_has = True
                                break
            except Exception:
                cache_has = False

            if cache_has:
                sounds_root = cache_dir
            else:
                net_dir = str(getattr(self, '_sounds_network_dir', '') or '').strip()
                if net_dir and _safe_isdir(net_dir):
                    sounds_root = net_dir
        except Exception:
            sounds_root = None

        if sounds_root:
            self._sounds_root_dir = sounds_root
        else:
            self._sounds_root_dir = os.path.join(self.base_dir, 'sounds')
        try:
            _debug_log(
                f"sounds_init cache_dir={self._sounds_cache_dir} net_dir={getattr(self, '_sounds_network_dir', None)} chosen={self._sounds_root_dir}"
            )
        except Exception:
            pass

        # צלילים
        self.sound_manager = None
        try:
            self.sound_manager = SoundManager(self.base_dir, sounds_dir=self._sounds_root_dir)
        except Exception:
            self.sound_manager = None
        try:
            self._apply_sound_settings_from_config(self.app_config)
        except Exception:
            pass

        try:
            if _DEBUG_LOG_ENABLED:
                snd_count = 0
                try:
                    if self._sounds_root_dir and os.path.isdir(self._sounds_root_dir):
                        for _root, _, files in os.walk(self._sounds_root_dir):
                            snd_count += sum(1 for f in (files or []) if str(f).lower().endswith(('.wav', '.mp3', '.ogg')))
                except Exception:
                    snd_count = -1
                _debug_log(
                    f"sounds_status pygame={USE_PYGAME} enabled={getattr(self.sound_manager, 'enabled', None)} vol={getattr(self.sound_manager, 'volume', None)} sounds_dir={getattr(self.sound_manager, 'sounds_dir', None)} files={snd_count}"
                )
        except Exception:
            pass

        # צלילי אירועים מתוך color_settings.json (אם הוגדרו)
        try:
            self.event_sounds = self.load_event_sounds()
        except Exception:
            self.event_sounds = {}
        self.restart_token_seen = str(cfg_restart.get('restart_public_stations_token', "")) if cfg_restart else ""
        self._restart_requested = False
        _debug_log(f'load_app_config הסתיים, restart_token_seen={self.restart_token_seen!r}')

        # ניסיון לאתר קובץ פונט גרפי לשימוש פנימי (ללא גישה לכוננים חיצוניים שעשויים להתקע)
        # עדיפות לפונט Gan CLM Bold שהונח בתיקיית התוכנה, עם נפילה חזרה ל-Agas אם קיים.
        self.agas_ttf_path = None
        try:
            font_candidates = [
                os.path.join(self.base_dir, "Gan CLM Bold.otf"),
                os.path.join(self.base_dir, "fonts", "Gan CLM Bold.otf"),
                os.path.join(self.base_dir, "Gan CLM.otf"),
                os.path.join(self.base_dir, "fonts", "Gan CLM.otf"),
                os.path.join(self.base_dir, "Agas.ttf"),
                os.path.join(self.base_dir, "fonts", "Agas.ttf"),
                os.path.join(self.base_dir, "תמונות", "Agas.ttf"),
            ]
            for cand in font_candidates:
                try:
                    if os.path.exists(cand):
                        self.agas_ttf_path = cand
                        _debug_log(f'נמצא קובץ פונט גרפי: {cand}')
                        break
                except Exception:
                    continue
        except Exception:
            self.agas_ttf_path = None

        self._update_loading(35, 'בודק רישיון...')
        _debug_log('לפני בדיקת רישיון public')
        # בדיקת רישיון אחרי שהוגדרה/נשמרה תיקיית הרשת (כדי להשתמש באותו קובץ רישיון משותף)
        self.license_manager = LicenseManager(self.base_dir, "public")
        if not self.license_manager.can_run_public_station():
            try:
                # הסתר את חלון העמדה לפני הצגת הודעת שגיאה
                self.root.withdraw()
            except Exception:
                pass

            if self.license_manager.over_limit:
                msg = self.license_manager.get_over_limit_message()
            elif getattr(self.license_manager, 'is_monthly', False) and bool(getattr(self.license_manager, 'monthly_expired', False)):
                exp = str(getattr(self.license_manager, 'expiry_date', '') or '').strip()
                suffix = f" (עד {exp})" if exp else ""
                msg = (
                    "הרישיון החודשי פג תוקף" + suffix + ".\n"
                    "לא ניתן להפעיל את העמדה הציבורית ללא רישיון בתוקף.\n\n"
                    "יש להפעיל רישיון בעמדת הניהול (⚙ הגדרות מערכת → רישום מערכת)."
                )
            elif self.license_manager.trial_expired and not self.license_manager.is_licensed:
                msg = (
                    "תקופת הניסיון הסתיימה.\n"
                    "לא ניתן להפעיל את העמדה הציבורית ללא רישיון פעיל.\n\n"
                    "יש להפעיל רישיון בעמדת הניהול (⚙ הגדרות מערכת → רישום מערכת)."
                )
            else:
                msg = (
                    "הרישיון אינו מאפשר הפעלה של עמדה ציבורית במחשב זה.\n\n"
                    "יש לבדוק את הרישיון בעמדת הניהול."
                )

            try:
                messagebox.showerror("רישיון אינו פעיל", msg)
            except Exception:
                pass
            try:
                self.root.destroy()
            except Exception:
                pass
            self._init_failed = True
            return

        self._update_loading(45, 'פותח מסד נתונים...')
        _debug_log('לפני הגדרת מסך מלא ויצירת Database')
        # מסך מלא - רקע שחור לקריאות מעולה בשמש (רק אחרי שרישיון תקין)
        self.root.attributes('-fullscreen', True)
        self.root.configure(bg='#000000')

        try:
            self.root.update_idletasks()
            self.root.update()
        except Exception:
            pass

        try:
            self.db = Database()
        except Exception as e:
            try:
                messagebox.showerror("שגיאה", f"לא ניתן לפתוח את מסד הנתונים.\n\n{e}")
            except Exception:
                print(f"שגיאה בפתיחת מסד נתונים: {e}")
            try:
                self.root.destroy()
            except Exception:
                pass
            self._init_failed = True
            return

        self._update_loading(55, 'מגדיר מערכת...')
        _debug_log('Database נפתח בהצלחה')

        # ניסיון שני להפעלת שרת סנכרון — עכשיו עם db_path נכון
        try:
            self._maybe_start_local_sync_server()
        except Exception:
            pass

        # שימוש באותו מסד נתונים כמו ה-Database הראשי (db_path משותף)
        self.messages_db = MessagesDB(self.db.db_path)
        self.card_buffer = ""

        self._last_settings_refresh_ts = 0.0
        self._settings_refresh_interval_sec = 5.0

        # טעינת כרטיס מאסטר מקובץ (אם קיים)
        self.exit_code = self.load_master_card()
        self.last_card_time = time.time()
        # מזהה הטיימר האחרון לאיפוס התצוגה, כדי שנוכל לאפס את 10 השניות
        # בכל סריקה חדשה ולא להסתמך על הטיימר הראשון בלבד.
        self._hide_info_after_id = None

        self._ads_popup_win = None
        self._ads_popup_img = None
        self._ads_popup_close_job = None
        self._ads_popup_loop_job = None
        self._ads_popup_index = 0
        self._ads_popup_last_shown_ts = 0.0

        # אנטי-ספאם Overlay – הודעות גדולות שלא נדרסות ע"י תיקוף נוסף
        self._anti_spam_overlay = None
        self._anti_spam_overlay_label = None
        self._anti_spam_overlay_hide_job = None
        self._anti_spam_overlay_until_ts = 0.0
        self._anti_spam_overlay_keep_name = False
        # מצב תפריט מנהל (כרטיס מאסטר 1)
        self._admin_menu_dialog = None
        self._admin_menu_open = False
        self._admin_menu_exit_deadline = None

        self._update_loading(65, 'טוען הגדרות תצוגה...')
        # טעינת הגדרות צבעים
        self.color_ranges = self.load_color_settings()
        # טעינת הגדרות מטבעות (מבוססי נקודות)
        self.coins_config = self.load_coin_settings()
        # טעינת הגדרות יעד (פס התקדמות)
        self.goal_settings = self.load_goal_settings()

        # טעינת הגדרות בונוס מיוחד (מאסטר 2)
        self.bonus_settings = self.load_bonus_settings()

        # מצב בונוס מורה (מוגדר בעמדת הניהול של המורה ומופעל בעמדה הציבורית בכרטיס המורה)
        self.teacher_bonus_running = False
        self.current_teacher_bonus_teacher_id = None
        self.current_teacher_bonus_points = 0
        self.teacher_bonus_students_got_bonus = []
        # רשימת תלמידים שמותר להם לקבל בונוס מהמורה הפעיל (לפי כיתות המורה)
        self.teacher_bonus_allowed_student_ids = set()
        try:
            self._load_teacher_bonus_state()
        except Exception:
            pass
        # רשימת הודעות שמאל ל-template1 (רשימת מחרוזות, כל אחת עד 2 שורות)
        self.left_messages_items = []

        self._update_loading(75, 'מחשב פונטים...')
        _debug_log('אחרי טעינת בונוס, לפני חישוב פונטים')
        # חישוב גודל מסך והתאמת פונטים
        try:
            sw = int(self.root.winfo_screenwidth() or 0)
            sh = int(self.root.winfo_screenheight() or 0)
        except Exception:
            sw, sh = 0, 0

        # חשוב: בעבודה עם DPI/Scaling, גודל המסך (screenwidth/height) יכול להיות שונה
        # מהגודל האמיתי של חלון ה-fullscreen. אם נצייר את הרקע לפי screen* עלול להיווצר חיתוך.
        try:
            w = int(self.root.winfo_width() or 0)
            h = int(self.root.winfo_height() or 0)
        except Exception:
            w, h = 0, 0

        self.screen_width = w if w > 100 else (sw if sw > 0 else 1920)
        self.screen_height = h if h > 100 else (sh if sh > 0 else 1080)

        self._last_root_size = (int(self.screen_width), int(self.screen_height))
        self._bg_refresh_after_id = None
        self._relayout_after_id = None
        self._bg_single_image_path = None
        self._last_template1_auto_bg = None

        # התאמת גודל פונטים לפי גובה המסך
        # בסיס: 1080p - עם מקדם קנה מידה מתון יותר
        scale = min(self.screen_height / 1080, 1.2)  # מגביל עד 120%
        self.font_title = int(40 * scale)
        self.font_instruction = int(26 * scale)
        self.font_name = int(36 * scale)
        self.font_info = int(24 * scale)
        self.font_points = max(1, int(64 * scale) - 3)  # הנקודות - גדול אבל לא יותר מדי
        self.font_points_text = int(28 * scale)

        # משפחת פונטים מועדפת לממשק – Gan CLM אם קיים, אחרת Agas, ואז Arial
        try:
            families = set(tkfont.families())
        except Exception:
            families = set()
        if "Gan CLM Bold" in families:
            self.ui_font_family = "Gan CLM Bold"
        elif "Gan CLM" in families:
            self.ui_font_family = "Gan CLM"
        elif "Agas" in families:
            self.ui_font_family = "Agas"
        elif "Agas CLM" in families:
            self.ui_font_family = "Agas CLM"
        else:
            self.ui_font_family = "Arial"

        _debug_log(f'ui_font_family={self.ui_font_family}, scale={scale}')

        self._update_loading(85, 'בונה ממשק...')
        self.setup_ui()
        self.bind_keyboard()
        self._init_cursor_auto_hide()
        self._schedule_initial_focus()
        self._schedule_restart_check()
        try:
            self._schedule_update_checks()
        except Exception:
            pass

        try:
            self._schedule_ads_popup_loop()
        except Exception:
            pass

        # חסימות/חופשות לעמדה הציבורית
        self._closure_overlay = None
        self._closure_overlay_img = None
        self._closure_check_job = None
        try:
            self._schedule_closure_check()
        except Exception:
            pass

        try:
            self.root.after(250, self._sync_window_size_after_startup)
        except Exception:
            pass

        try:
            self.root.bind('<Configure>', self._on_root_configure)
        except Exception:
            pass

        try:
            tk_scale = None
            fpix = None
            try:
                tk_scale = self.root.tk.call('tk', 'scaling')
            except Exception:
                tk_scale = None
            try:
                fpix = self.root.winfo_fpixels('1i')
            except Exception:
                fpix = None
            _debug_log(
                f'startup_metrics screen={sw}x{sh} win={w}x{h} used={self.screen_width}x{self.screen_height} tk_scaling={tk_scale} fpixels_1i={fpix}'
            )
        except Exception:
            pass

        self._update_loading(100, 'מוכן!')
        self._dismiss_loading()

    def _update_loading(self, percent, status_text=''):
        """עדכון מסך הטעינה — עיגול התקדמות + אחוזים + הודעת סטטוס"""
        try:
            ld = getattr(self.root, '_sp_loading', None)
            if not ld:
                return
            extent = -int(360 * min(percent, 100) / 100)
            ld['canvas'].itemconfigure(ld['arc'], extent=extent)
            ld['canvas'].itemconfigure(ld['pct'], text=f'{int(percent)}%')
            if status_text:
                ld['status'].config(text=status_text)
            self.root.update()
        except Exception:
            pass

    def _dismiss_loading(self):
        """הסרת מסך הטעינה — חושף את ממשק העמדה הציבורית"""
        try:
            ld = getattr(self.root, '_sp_loading', None)
            if ld:
                ld['frame'].destroy()
                self.root._sp_loading = None
        except Exception:
            pass

    def _sync_window_size_after_startup(self):
        try:
            w = int(self.root.winfo_width() or 0)
            h = int(self.root.winfo_height() or 0)
            if w <= 100 or h <= 100:
                return
            prev_w, prev_h = getattr(self, '_last_root_size', (0, 0))
            if abs(w - prev_w) < 2 and abs(h - prev_h) < 2:
                return
            self._last_root_size = (w, h)
            self.screen_width = w
            self.screen_height = h
            try:
                self._refresh_background_for_current_mode()
            except Exception:
                pass

            try:
                self._schedule_relayout()
            except Exception:
                pass
        except Exception:
            pass

    def _on_root_configure(self, event=None):
        try:
            w = int(self.root.winfo_width() or 0)
            h = int(self.root.winfo_height() or 0)
        except Exception:
            return

        if w <= 100 or h <= 100:
            return

        prev_w, prev_h = getattr(self, '_last_root_size', (0, 0))
        if abs(w - prev_w) < 4 and abs(h - prev_h) < 4:
            return

        self._last_root_size = (w, h)
        # גודל החלון בפועל הוא הגודל הקובע לרינדור הרקע והפריסה.
        self.screen_width = w
        self.screen_height = h

        try:
            if getattr(self, '_bg_refresh_after_id', None) is not None:
                self.root.after_cancel(self._bg_refresh_after_id)
        except Exception:
            pass

        try:
            self._bg_refresh_after_id = self.root.after(120, self._refresh_background_for_current_mode)
        except Exception:
            self._bg_refresh_after_id = None

        try:
            self._schedule_relayout()
        except Exception:
            pass

    def _schedule_relayout(self):
        try:
            if getattr(self, '_relayout_after_id', None) is not None:
                try:
                    self.root.after_cancel(self._relayout_after_id)
                except Exception:
                    pass
            self._relayout_after_id = self.root.after(160, self._relayout_for_window_size)
        except Exception:
            self._relayout_after_id = None

    def _relayout_for_window_size(self):
        try:
            self._relayout_after_id = None

            try:
                w = int(self.root.winfo_width() or 0)
                h = int(self.root.winfo_height() or 0)
            except Exception:
                return

            if w <= 100 or h <= 100:
                return

            self.screen_width = w
            self.screen_height = h
            self.screen_orientation = 'portrait' if h >= w else 'landscape'

            scale = min(self.screen_height / 1080, 1.2)
            self.font_title = int(40 * scale)
            self.font_instruction = int(26 * scale)
            self.font_name = int(36 * scale)
            self.font_info = int(24 * scale)
            self.font_points = max(1, int(64 * scale) - 3)
            self.font_points_text = int(28 * scale)

            try:
                if hasattr(self, 'title_label'):
                    self.title_label.config(font=(self.ui_font_family, self.font_title, 'bold'), pady=int(8 * (self.screen_height / 1080)))
                if hasattr(self, 'instruction_label'):
                    self.instruction_label.config(font=(self.ui_font_family, self.font_instruction), pady=int(8 * (self.screen_height / 1080)))
                if hasattr(self, 'always_message_label'):
                    base_wrap = 900 if self.screen_orientation == 'landscape' else 650
                    self.always_message_label.config(
                        font=(self.ui_font_family, int(self.font_info * 1.3), 'bold'),
                        wraplength=int(base_wrap * (self.screen_width / 1920)),
                        pady=int(8 * (self.screen_height / 1080)),
                    )
                if hasattr(self, 'name_label'):
                    self.name_label.config(font=(self.ui_font_family, self.font_name, 'bold'), pady=int(8 * (self.screen_height / 1080)))
                if hasattr(self, 'class_label'):
                    self.class_label.config(font=(self.ui_font_family, self.font_info), pady=int(4 * (self.screen_height / 1080)))
                if hasattr(self, 'id_label'):
                    self.id_label.config(font=(self.ui_font_family, int(self.font_info * 0.9)))
                if hasattr(self, 'points_label'):
                    self.points_label.config(font=(self.ui_font_family, self.font_points), pady=int(8 * (self.screen_height / 1080)))
                if hasattr(self, 'points_text_label'):
                    self.points_text_label.config(font=(self.ui_font_family, self.font_points_text, 'bold'))
            except Exception:
                pass

            try:
                if getattr(self, 'background_template', None) != 'template1':
                    self.position_side_labels()
            except Exception:
                pass

            try:
                if getattr(self, 'background_template', None) == 'template1':
                    self._refresh_background_for_current_mode()
            except Exception:
                pass
        except Exception:
            pass

    def _refresh_background_for_current_mode(self):
        try:
            self._bg_refresh_after_id = None

            bg_mode = getattr(self, 'bg_mode', 'default')
            template = getattr(self, 'background_template', 'default')

            if bg_mode == 'default' and template == 'template1':
                try:
                    img_path = self._get_template1_auto_background_path()
                    if img_path:
                        try:
                            prev = getattr(self, '_last_template1_auto_bg', None)
                            if img_path != prev:
                                self._last_template1_auto_bg = img_path
                                _debug_log(
                                    f'template1_auto_bg selected={img_path} win={getattr(self, "screen_width", None)}x{getattr(self, "screen_height", None)}'
                                )
                        except Exception:
                            pass
                        self._bg_single_image_path = img_path
                except Exception:
                    pass

            if bg_mode in ('image', 'default'):
                img_path = getattr(self, '_bg_single_image_path', None)
                if img_path and os.path.exists(img_path):
                    try:
                        img = Image.open(img_path)
                        try:
                            img = ImageOps.exif_transpose(img)
                        except Exception:
                            pass
                        img = self._prepare_background_image(img)
                        self.bg_base_image = img

                        if template == 'template1':
                            try:
                                has_student = False
                                if hasattr(self, 'name_label') and hasattr(self, 'points_label'):
                                    has_student = bool(self.name_label.cget('text') or self.points_label.cget('text'))
                            except Exception:
                                has_student = False

                            try:
                                if has_student:
                                    self._render_template1_overlay_from_widgets()
                                else:
                                    always_text = getattr(self, 'always_messages_text', "")
                                    self._render_static_overlay_template1(always_text)
                            except Exception:
                                self._update_bg_label(img)
                        else:
                            self._update_bg_label(img)
                    except Exception:
                        pass
                return

            if bg_mode == 'slideshow':
                mode = getattr(self, 'slideshow_mode', 'single')
                if mode in ('grid_static', 'grid_dynamic'):
                    try:
                        self._render_montage_background(static=(mode == 'grid_static'))
                    except Exception:
                        pass
                else:
                    try:
                        self.update_background_slideshow()
                    except Exception:
                        pass
        except Exception:
            pass

    def _get_template1_auto_background_path(self):
        try:
            images_dir = os.path.join(self.base_dir, 'תמונות')
            theme = getattr(self, 'theme_name', 'dark') or 'dark'
            is_portrait = bool(getattr(self, 'screen_height', 0) >= getattr(self, 'screen_width', 0))

            if is_portrait:
                dark_base = 'רקע כהה לאורך'
                light_base = 'רקע בהיר לאורך'
            else:
                dark_base = 'רקע כהה לרוחב'
                light_base = 'רקע בהיר לרוחב'

            dark_candidates = [
                f"{dark_base}.png",
                f"{dark_base}.jpg",
                f"{dark_base}.jpeg",
            ]
            light_candidates = [
                f"{light_base}.jpg",
                f"{light_base}.jpeg",
                f"{light_base}.png",
            ]

            primary = light_candidates if theme == 'light' else dark_candidates
            secondary = dark_candidates if theme == 'light' else light_candidates
            candidates = primary + secondary

            for fname in candidates:
                template_path = os.path.join(images_dir, fname)
                if os.path.exists(template_path):
                    return template_path
        except Exception:
            return None
        return None

    def _schedule_hide_info(self, delay_ms=10000, reset_name_color=False):
        """קביעת טיימר להסתרת התצוגה, עם איפוס טיימר קודם אם היה אחד.

        כך שכל סריקת כרטיס חדשה תבטל את הטיימר הישן ותתחיל ספירה מחדש
        מ-"עכשיו" למשך delay_ms מילישניות.
        """
        # ביטול טיימר קודם אם קיים
        try:
            if getattr(self, "_hide_info_after_id", None) is not None:
                self.root.after_cancel(self._hide_info_after_id)
        except Exception:
            pass

        if reset_name_color:
            default_fg = getattr(self, 'default_name_fg', '#ecf0f1')
            self._hide_info_after_id = self.root.after(
                delay_ms,
                lambda: [self.hide_info(), self.name_label.config(fg=default_fg)]
            )
        else:
            self._hide_info_after_id = self.root.after(delay_ms, self.hide_info)

    def _prepare_logo_image(self, img: Image.Image) -> Image.Image:
        """הפיכת הלוגו למדליה עגולה עם רקע שקוף.

        נחתוך את התמונה למסיכת עיגול במרכז, כך שכל מה שמחוץ לעיגול יהיה שקוף
        בלי תלות בצבע הרקע המקורי. זה מבטל לגמרי את ה"ריבוע השחור" סביב הלוגו.
        """
        try:
            # בשלב זה לא נבצע חיתוך גיאומטרי כדי לא לגזור לוגואים רחבים.
            # רק נוודא פורמט מתאים לשימוש ב-Tkinter/Pillow.
            if img.mode not in ('RGB', 'RGBA'):
                img = img.convert('RGBA')
            return img
        except Exception:
            return img
    
    def setup_ui(self):
        """בניית ממשק המשתמש"""
        # קביעת ערכת צבעים ומצב רקע לפי config.json
        config = getattr(self, 'app_config', {}) if hasattr(self, 'app_config') else {}
        raw_theme = config.get('theme', 'dark')
        # נשמור גם את מצב הרקע כפי שהוא בקובץ וגם את המצב שנשתמש בו בפועל
        config_bg_mode = config.get('background_mode', 'none')
        bg_mode = config_bg_mode
        bg_layout = config.get('background_layout', 'cover')
        screen_orientation = config.get('screen_orientation', 'landscape')
        background_template = config.get('background_template', 'default')
        try:
            if background_template == 'template1' and bg_mode in ('default', 'none', '', None):
                if bg_layout != 'contain':
                    bg_layout = 'contain'
        except Exception:
            pass

        # תאימות לאחור: אם theme נשמר כ-background_image / slideshow
        if raw_theme in ('background_image', 'slideshow') and bg_mode == 'none':
            # בעבר ערך theme שימש גם לסימון מצב רקע תמונה/מצגת
            theme_name = 'high_contrast'
            bg_mode = 'image' if raw_theme == 'background_image' else 'slideshow'
        else:
            theme_name = raw_theme

        # תאימות לאחור: מצב 'none' הישן יתנהג היום כברירת מחדל (default)
        # ההבדל בפועל יורגש רק אחרי שהמנהל ישמור הגדרות חדשות בעמדת הניהול.
        if bg_mode == 'none':
            bg_mode = 'default'

        self.theme_name = theme_name
        self.bg_mode = bg_mode
        self.bg_layout = bg_layout
        self.screen_orientation = screen_orientation
        self.background_template = background_template
        try:
            _debug_log(f'bg_effective mode={self.bg_mode} layout={self.bg_layout} template={self.background_template} orientation={self.screen_orientation}')
        except Exception:
            pass
        # שמירת מצב הרקע המקורי מהקובץ (לפני התאמות תאימות לאחור)
        self.config_bg_mode = config_bg_mode

        # זמן מעבר במצגת
        interval_sec = config.get('background_interval_sec', 15)
        try:
            interval_sec = int(interval_sec)
        except (ValueError, TypeError):
            interval_sec = 15
        if interval_sec < 3:
            interval_sec = 3
        if interval_sec > 600:
            interval_sec = 600
        self.bg_interval_ms = interval_sec * 1000

        # מצב תצוגת מצגת (תמונה אחת / מונטאז') ומספר עמודות למונטאז'
        self.slideshow_mode = config.get('slideshow_display_mode', 'single')
        cols = config.get('slideshow_grid_cols', 4)
        try:
            cols = int(cols)
        except (ValueError, TypeError):
            cols = 4
        if cols < 1:
            cols = 1
        if cols > 10:
            cols = 10
        self.slideshow_grid_cols = cols

        # ברירת מחדל: ניגודיות גבוהה (כמו עכשיו)
        root_bg = '#000000'
        main_bg = '#000000'
        info_bg = '#0a0a0a'
        border_color = '#FFFFFF'
        title_fg = '#FFFFFF'
        instr_fg = '#00FFFF'
        always_msg_fg = '#FFD700'
        side_msg_fg = '#FFD700'
        stats_fg = '#E0E0E0'
        base_text_fg = '#FFFFFF'
        secondary_text_fg = '#E0E0E0'

        if theme_name == 'dark':
            # רקע כהה, כיתוב בהיר
            root_bg = '#000000'
            main_bg = '#000000'
            info_bg = '#111111'
            border_color = '#FFFFFF'
            title_fg = '#FFFFFF'
            instr_fg = '#00BFFF'
            always_msg_fg = '#FFD700'
            side_msg_fg = '#FFD700'
            stats_fg = '#E0E0E0'
            base_text_fg = '#FFFFFF'
            secondary_text_fg = '#E0E0E0'
        elif theme_name == 'light':
            # רקע בהיר, כיתוב כהה
            root_bg = '#FFFFFF'
            main_bg = '#FFFFFF'
            info_bg = '#F8F8F8'
            border_color = '#000000'
            title_fg = '#000000'
            instr_fg = '#0055AA'
            always_msg_fg = '#B8860B'
            side_msg_fg = '#B8860B'
            stats_fg = '#333333'
            base_text_fg = '#000000'
            secondary_text_fg = '#333333'

        # רקע בצבע אחיד (מצב "צבע אחיד")
        bg_color = config.get('background_color')
        if bg_mode == 'color' and isinstance(bg_color, str) and bg_color.strip():
            color_val = bg_color.strip()
            root_bg = color_val
            main_bg = color_val
            info_bg = color_val
            # עבור template1 ניצור גם תמונת בסיס בצבע אחיד כדי שנוכל לצייר עליה את כל השכבות
            try:
                if getattr(self, 'background_template', None) == 'template1':
                    solid_img = Image.new('RGB', (self.screen_width, self.screen_height), color_val)
                    solid_img = self._prepare_background_image(solid_img)
                    self.bg_base_image = solid_img
                    self._update_bg_label(solid_img)
            except Exception:
                pass

        # סגנון פנלים (מלא / צף מעל הרקע)
        panel_style = config.get('panel_style', 'solid')
        # עבור דפי רקע גרפיים (template1) נעדיף פנלים "צפים" ועדינים
        if self.background_template == 'template1':
            panel_style = 'floating'
        self.panel_style = panel_style
        if panel_style == 'floating':
            # השתמש ברקע הראשי גם לפנלים כדי לתת תחושת קלילות ללא מסגרת
            info_bg = main_bg

        side_panel_bg = root_bg
        # במצב דף רקע גרפי (template1) לא נצבע פאנלים בצבע בהיר כדי שלא יסתירו את הרקע
        if bg_mode in ('image', 'slideshow') and self.background_template != 'template1':
            if theme_name in ('high_contrast', 'dark'):
                panel_bg = '#f8f8f8'
                main_bg = panel_bg
                info_bg = panel_bg
                border_color = '#000000'
                title_fg = '#000000'
                instr_fg = '#0055AA'
                always_msg_fg = '#B8860B'
                side_msg_fg = '#B8860B'
                stats_fg = '#333333'
                base_text_fg = '#000000'
                secondary_text_fg = '#333333'
            side_panel_bg = info_bg
        # גוון עדין יותר לפאנלים עבור template1 כדי שלא יראו כמלבן שחור
        if self.background_template == 'template1':
            # אפור כהה רך הדומה לריבועים שבתבנית הגרפית
            panel_gray = '#444654'
            main_bg = panel_gray
            info_bg = panel_gray
            side_panel_bg = panel_gray
        self.side_panel_bg = side_panel_bg

        # מסגרת חיצונית למצב תמונה/מצגת (פנל אחד מודגש)
        self.panel_outline = None
        if self.bg_mode in ('image', 'slideshow') and self.background_template != 'template1':
            self.panel_outline = tk.Frame(
                self.root,
                bg=self.side_panel_bg,
                bd=4,
                relief=tk.RIDGE,
                highlightbackground=border_color,
                highlightthickness=2
            )

        # שמירת צבע ברירת מחדל לשם תלמיד (לשימוש אחרי שגיאה)
        self.default_name_fg = base_text_fg

        # משתנה לשמירת תמונת תלמיד נוכחית (כדי שלא תיאסף ע"י ה-GC)
        self.current_photo_img = None
        # עותק מקורי של תמונת תלמיד לשימוש בציור על template1
        self.template1_photo_original = None

        # שמירת צבע רקע חלון לשימוש בעיבוד תמונות רקע
        self.root_bg_color = root_bg

        # מצב רקע מיוחד: תמונה אחת או מצגת
        self.bg_label = None
        self.bg_image = None
        self.bg_files = []
        self.bg_index = 0

        # הגדרת צבע רקע חלון
        self.root.configure(bg=root_bg)

        self.clock_label = tk.Label(
            self.root,
            text="",
            font=(getattr(self, 'ui_font_family', 'Arial'), 24, 'bold'),
            bg=root_bg,
            fg=title_fg
        )
        self.clock_label.place(x=24, y=10, anchor='nw')

        def _update_clock():
            try:
                self.clock_label.config(text=datetime.now().strftime('%H:%M:%S'))
            except Exception:
                pass
            try:
                self.root.after(1000, _update_clock)
            except Exception:
                pass

        _update_clock()

        # רקע תמונה (אם הוגדר)
        # במצב "ברירת מחדל" (default) נשתמש בדפי הרקע האוטומטיים של template1,
        # ובמצב "תמונת רקע אחת" נשתמש בתמונה שהוגדרה בקובץ ההגדרות.
        is_default_bg = (bg_mode == 'default')
        if bg_mode in ('image', 'default'):
            image_path = None
            try:
                use_auto_template_image = (
                    getattr(self, 'background_template', None) == 'template1'
                    and is_default_bg
                )
                if use_auto_template_image:
                    image_path = self._get_template1_auto_background_path()
            except Exception:
                image_path = None

            # אם לא נבחרה תמונת ברירת-מחדל עבור template1 – נשתמש בתמונה שהוגדרה בקובץ
            if not image_path:
                image_path = getattr(self, 'app_config', {}).get('background_image_path') if hasattr(self, 'app_config') else None

            try:
                _debug_log(f'bg_image_path chosen={image_path} exists={bool(image_path and os.path.exists(image_path))}')
            except Exception:
                pass

            if image_path and os.path.exists(image_path):
                try:
                    self._bg_single_image_path = image_path
                    img = Image.open(image_path)
                    try:
                        img = ImageOps.exif_transpose(img)
                    except Exception:
                        pass
                    img = self._prepare_background_image(img)
                    # שמירת תמונת בסיס לשימוש בתבנית הגרפית (template1)
                    self.bg_base_image = img
                    # אם template1 פעיל – הכיתוב ימוקם עליו בהמשך
                    if getattr(self, 'background_template', None) == 'template1':
                        try:
                            # אם יש כעת תלמיד מוצג – נצייר שכבת תלמיד, אחרת שכבת טקסט קבועה
                            has_student = False
                            if hasattr(self, 'name_label') and hasattr(self, 'points_label'):
                                has_student = bool(self.name_label.cget('text') or self.points_label.cget('text'))
                        except Exception:
                            has_student = False
                        try:
                            if has_student:
                                self._render_template1_overlay_from_widgets()
                            else:
                                always_text = getattr(self, 'always_messages_text', "")
                                self._render_static_overlay_template1(always_text)
                        except Exception:
                            self._update_bg_label(img)
                    else:
                        self._update_bg_label(img)
                except Exception as e:
                    print(f"שגיאה בטעינת תמונת רקע: {e}")
        elif bg_mode == 'slideshow':
            folder = getattr(self, 'app_config', {}).get('background_folder') if hasattr(self, 'app_config') else None
            if folder and os.path.isdir(folder):
                exts = ('.png', '.jpg', '.jpeg', '.bmp', '.gif')
                try:
                    self.bg_files = [
                        os.path.join(folder, f)
                        for f in os.listdir(folder)
                        if f.lower().endswith(exts)
                    ]
                except Exception as e:
                    print(f"שגיאה בקריאת תיקיית מצגת: {e}")
                    self.bg_files = []
                if self.bg_files:
                    self.bg_label = tk.Label(self.root, bg=root_bg)
                    self.bg_label.place(x=0, y=0, relwidth=1, relheight=1)
                    mode = getattr(self, 'slideshow_mode', 'single')
                    if mode == 'grid_static':
                        self._render_montage_background(static=True)
                    else:
                        self.update_background_slideshow()

        # מסגרת ראשית - רקע לפי ערכת הצבעים
        main_frame = tk.Frame(self.root, bg=main_bg)
        self.main_frame = main_frame

        # לוגו בראש
        # במצב template1 נצייר את הלוגו ישירות על תמונת הרקע באמצעות Pillow (ללא ריבוע),
        # ובמצבים אחרים נשתמש גם כן בלוגו כ-PIL ונשרטט אותו על הרקע (במקום Label עם צבע רקע).
        self.template1_logo_original = None
        self.template1_logo_top = None
        # לוגו כללי כ-PIL לכל מצבי הרקע (גם portrait וגם landscape)
        self.logo_image_pil = None
        self.logo_top_pos = None
        logo_margin_top = 0

        logo_path = None
        custom_logo = getattr(self, 'app_config', {}).get('logo_path') if hasattr(self, 'app_config') else None
        if custom_logo and os.path.exists(custom_logo):
            logo_path = custom_logo
        else:
            logo_path = os.path.join(self.base_dir, "דובר שלום לוגו תת.jpg")

        if os.path.exists(logo_path):
            try:
                img = Image.open(logo_path)
                img = self._prepare_logo_image(img)

                # שמירה על יחס רוחב-גובה - לוגו בגובה מאוזן יחסית למסך
                base_max_height = max(200, int(280 * (self.screen_height / 1080)))
                if getattr(self, 'screen_orientation', 'landscape') == 'portrait':
                    # במסך לאורך הלוגו היה גדול מדי - נצמצם מעט את הגובה המקסימלי
                    max_height = int(base_max_height * 0.75)
                else:
                    max_height = base_max_height

                aspect_ratio = img.width / img.height
                new_height = max_height
                new_width = int(new_height * aspect_ratio)
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

                logo_top = int(0.015 * self.screen_height)
                top_margin = logo_top + new_height + 5

                # שמירת הלוגו כ-PIL לכל מצבי הרקע (גם ללא template1), כדי שנוכל לצייר אותו ישירות על הרקע
                self.logo_image_pil = img
                self.logo_top_pos = logo_top

                if getattr(self, 'background_template', None) == 'template1':
                    # נשמור את הלוגו לשימוש בציור על template1 (ללא Label וצבע רקע)
                    self.template1_logo_original = img
                    self.template1_logo_top = logo_top
                    logo_margin_top = top_margin
                else:
                    # מצב רגיל – הלוגו יצויר על תמונת הרקע (ללא ריבוע רקע נפרד)
                    logo_margin_top = top_margin
            except Exception as e:
                print(f"שגיאה בטעינת לוגו: {e}")

        # מיקום המסגרת הראשית בהתאם לגובה הלוגו (אם קיים)
        if self.bg_mode in ('image', 'slideshow'):
            main_frame.pack(pady=(logo_margin_top, 0))
        else:
            main_frame.pack(expand=True, pady=(logo_margin_top, 0))
        
        # תצוגת מצב בונוס / בונוס מיוחד - גודל פונט מותאם, קטן יותר במצב template1 לאורך
        bonus_font_size = max(20, int(28 * (self.screen_height / 1080)))
        if getattr(self, 'background_template', None) == 'template1' and self.screen_orientation == 'portrait':
            bonus_font_size = max(16, int(22 * (self.screen_height / 1080)))

        # נשמור גדלי פונט בסיסיים לפסי הבונוס, כדי שנוכל להקטין/להחזיר במצב של התנגשות בונוסים
        self.bonus_font_size_base = bonus_font_size
        self.bonus_font_size_small = max(14, int(bonus_font_size * 0.9))
        bonus_border = 4
        bonus_relief = 'solid'
        if self.panel_style == 'floating':
            bonus_border = 0
            bonus_relief = tk.FLAT

        self.bonus_label = tk.Label(
            self.root,
            text="",
            font=(self.ui_font_family, self.bonus_font_size_base, 'bold'),
            bg=root_bg,
            fg='#FFD700',
            borderwidth=bonus_border,
            relief=bonus_relief
        )
        self.update_bonus_display()
        
        # תצוגת מצב בונוס זמנים - מתחת לבונוס רגיל
        self.time_bonus_label = tk.Label(
            self.root,
            text="",
            font=(self.ui_font_family, self.bonus_font_size_base, 'bold'),
            bg=root_bg,
            fg='#00FFFF',
            borderwidth=bonus_border,
            relief=bonus_relief
        )
        self.update_time_bonus_display()
        
        # כותרת - לבן בוהק על שחור
        campaign_name = getattr(self, 'app_config', {}).get('campaign_name', 'אשראיכם') if hasattr(self, 'app_config') else 'אשראיכם'
        title_text = f"ברוכים הבאים למבצע {campaign_name}"
        self.title_label = tk.Label(
            main_frame,
            text=fix_rtl_text(title_text),
            font=(self.ui_font_family, self.font_title, 'bold'),
            bg=main_bg,
            fg=title_fg,
            pady=int(8 * (self.screen_height / 1080))
        )
        self.title_label.pack()
        
        # הודעת הנחיה - ציאן בהיר על שחור
        self.instruction_label = tk.Label(
            main_frame,
            text=normalize_ui_icons("⬇️ הצג את כרטיסך על הקורא ⬇️"),
            font=(self.ui_font_family, self.font_instruction),
            bg=main_bg,
            fg=instr_fg,
            pady=int(8 * (self.screen_height / 1080))
        )
        self.instruction_label.pack()
        
        # הודעות קבועות (תמיד מוצגות) - מיושרות למרכז - צהוב זהב בהיר
        base_wrap = 900 if self.screen_orientation == 'landscape' else 650
        self.always_message_label = tk.Label(
            main_frame,
            text="",
            font=(self.ui_font_family, int(self.font_info * 1.3), 'bold'),
            bg=main_bg,
            fg=always_msg_fg,
            wraplength=int(base_wrap * (self.screen_width / 1920)),
            justify='center',
            pady=int(8 * (self.screen_height / 1080))
        )
        self.always_message_label.pack(padx=0)
        
        # עדכון הודעות קבועות
        self.update_always_messages()
        self.root.after(60000, self.update_always_messages_loop)  # עדכון כל דקה

        # בתבנית template1 אנחנו מציירים כותרת/הנחיה/הודעות קבועות ישירות על הרקע
        if self.background_template == 'template1':
            try:
                self.title_label.pack_forget()
                self.instruction_label.pack_forget()
                self.always_message_label.pack_forget()
                # ציור שכבת הרקע ההתחלתית (גם אם אין הודעות show_always)
                self._render_static_overlay_template1(getattr(self, 'always_messages_text', ""))
            except Exception:
                pass
        
        # אזור תצוגת פרטים - הריבוע מאוזן
        panel_bd = 6
        panel_relief = tk.RIDGE
        panel_highlight = 2
        panel_fill = tk.BOTH
        panel_expand = True
        if getattr(self, 'panel_style', 'solid') == 'floating':
            panel_bd = 0
            panel_relief = tk.FLAT
            panel_highlight = 0
            panel_fill = tk.NONE
            panel_expand = False

        # במצב תמונה/מצגת תמיד מצמצמים את אזור הפרטים למינימום
        if self.bg_mode in ('image', 'slideshow'):
            panel_fill = tk.NONE
            panel_expand = False
            panel_bd = 0
            panel_relief = tk.FLAT
            panel_highlight = 0

        self.info_frame = tk.Frame(main_frame, bg=info_bg, bd=panel_bd, relief=panel_relief, highlightbackground=border_color, highlightthickness=panel_highlight)
        # עבור template1 נצמצם את הריבוע ונמנע מגבולות בולטים
        if self.background_template == 'template1':
            self.info_frame.configure(highlightthickness=0, bd=0)
            self.info_frame.pack(pady=10, padx=10, fill=panel_fill, expand=panel_expand)
        else:
            self.info_frame.pack(pady=15, padx=50, fill=panel_fill, expand=panel_expand)

        # שמירת מאפייני הפריסה לשימוש ב-show_info
        self._panel_fill = panel_fill
        self._panel_expand = panel_expand
        
        # הודעות בצד שמאל - מחוץ לריבוע - צהוב זהב בהיר
        side_wrap = 290 if self.screen_orientation == 'landscape' else 220
        self.message_label = tk.Label(
            self.root,
            text="",
            font=(self.ui_font_family, self.font_info, 'bold'),
            bg=self.side_panel_bg,
            fg=side_msg_fg,
            wraplength=int(side_wrap * (self.screen_width / 1920)),
            justify='right',
            anchor='ne'
        )
        # לא קובע y עכשיו - נקבע אותו אחרי שהריבוע ייטען
        
        # שם התלמיד - לבן בוהק על רקע כהה
        name_class_pady = int(8 * (self.screen_height / 1080))
        points_pady = int(8 * (self.screen_height / 1080))
        try:
            if getattr(self, 'screen_orientation', None) == 'portrait':
                name_class_pady = max(0, name_class_pady - 2)
                points_pady = points_pady + 2
        except Exception:
            pass
        self.name_label = tk.Label(
            self.info_frame,
            text="",
            font=(self.ui_font_family, self.font_name, 'bold'),
            bg=info_bg,
            fg=base_text_fg,
            pady=name_class_pady
        )
        self.name_label.pack()
        
        # כיתה - לבן בהיר
        self.class_label = tk.Label(
            self.info_frame,
            text="",
            font=(self.ui_font_family, self.font_info),
            bg=info_bg,
            fg=secondary_text_fg,
            pady=name_class_pady
        )
        self.class_label.pack()
        
        # ת"ז - לבן בהיר / טקסט משני
        self.id_label = tk.Label(
            self.info_frame,
            text="",
            font=(self.ui_font_family, self.font_info),
            bg=info_bg,
            fg=secondary_text_fg,
            pady=int(8 * (self.screen_height / 1080))
        )
        self.id_label.pack()
        
        # קו מפריד - לבן בהיר
        separator = tk.Frame(self.info_frame, height=4, bg=border_color)
        self.info_separator = separator
        separator.pack(fill=tk.X, padx=50, pady=8)
        
        # נקודות - ירוק ליים בוהק על רקע כהה
        self.points_label = tk.Label(
            self.info_frame,
            text="",
            font=(self.ui_font_family, self.font_points),
            bg=info_bg,
            fg='#00FF00',
            pady=points_pady
        )
        self.points_label.pack()

        # פס יעד (התקדמות) – יימוקם בהתאם למצב תצוגה
        goal_bar_w = int((520 if self.screen_orientation == 'landscape' else 420) * (self.screen_width / 1920))
        goal_bar_h = int(22 * (self.screen_height / 1080))
        self.goal_bar_canvas = tk.Canvas(
            self.info_frame,
            width=goal_bar_w,
            height=goal_bar_h,
            bg=info_bg,
            highlightthickness=0,
            bd=0
        )
        try:
            self.goal_bar_canvas.pack_forget()
        except Exception:
            pass
        
        # הודעת נקודות - ירוק ליים בוהק
        self.points_text_label = tk.Label(
            self.info_frame,
            text="",
            font=(self.ui_font_family, self.font_points_text, 'bold'),
            bg=info_bg,
            fg='#00FF00',
            pady=int(3 * (self.screen_height / 1080))
        )
        self.points_text_label.pack()

        # מיקום הפס בהתאם למצב מסך
        try:
            if self.screen_orientation == 'portrait':
                # בין שם+כיתה לבין מספר הנקודות
                self.goal_bar_canvas.pack(pady=int(6 * (self.screen_height / 1080)), after=self.info_separator, before=self.points_label)
            else:
                # מתחת לכיתה ומעל מספר הנקודות
                self.goal_bar_canvas.pack(pady=int(6 * (self.screen_height / 1080)), after=self.class_label)
        except Exception:
            try:
                self.goal_bar_canvas.pack(pady=int(6 * (self.screen_height / 1080)))
            except Exception:
                pass
        
        # סטטיסטיקות בצד ימין - מחוץ לריבוע - לבן בהיר על שחור
        self.statistics_label = tk.Label(
            self.root,
            text="",
            font=(self.ui_font_family, int(self.font_info * 0.85)),
            bg=self.side_panel_bg,
            fg=stats_fg,
            justify='right',
            anchor='ne',
            wraplength=int(330 * (self.screen_width / 1920))
        )

        # תמונת תלמיד בצד ימין, מתחת לסטטיסטיקות (יושם ב-position_side_labels)
        self.photo_label = tk.Label(
            self.root,
            text="",
            bg=self.side_panel_bg
        )

        # במצב template1 – לצמצם את האפקט של "פנלים" צדדיים כך שלא ייראו כריבועים נפרדים
        if self.background_template == 'template1':
            side_bg = self.root_bg_color or '#000000'
            self.message_label.configure(bg=side_bg)
            self.statistics_label.configure(bg=side_bg)
            self.photo_label.configure(bg=side_bg)
        
        # הסתרת אזור הפרטים בהתחלה
        self.hide_info()
        
        # מיקום ההודעות והסטטיסטיקות אחרי שהממשק נטען
        if self.background_template != 'template1':
            self.root.after(100, self.position_side_labels)
            # עדכון מיקומים בכל שינוי גודל חלון (עם debounce למניעת הצטברות)
            self.root.bind('<Configure>', lambda e: self._debounced_position_side_labels())
        
        # כפתור יציאה נסתר (בפינה)
        self.exit_button = tk.Button(
            self.root,
            text="",
            command=self.show_exit_dialog,
            bg=root_bg,
            fg=root_bg,
            relief=tk.FLAT,
            bd=0,
            cursor='',
            width=2,
            height=1
        )
        self.exit_button.place(x=0, y=0)

        # מסגרת תחתונה לרצועת החדשות – תופסת את כל רוחב המסך
        self.news_frame = tk.Frame(
            self.root,
            bg=root_bg,
            height=int(40 * (self.screen_height / 1080))
        )
        self.news_frame.pack(side=tk.BOTTOM, fill=tk.X)

        # רצועת חדשות בתחתית המסך (טיקר) – Canvas לציור ידני
        news_height = int(40 * (self.screen_height / 1080))
        self.news_canvas = tk.Canvas(
            self.news_frame,
            bg=root_bg,
            height=news_height,
            highlightthickness=0
        )
        self.news_canvas.pack(fill=tk.BOTH, expand=True)
        
        # לא משתמשים ב-Label - כל הציור יהיה על Canvas
        self.news_label = None

        # אתחול חדשות לרצועת הטיקר
        self.news_text_full = ""
        self.news_current_text = ""
        self.news_text_width = 0
        self.news_container_width = self.screen_width
        # news_unit_width ימדד בפועל אחרי שנדע את רוחב יחידת הטקסט
        self.news_unit_width = 0
        # news_scroll_x – היסט אפקטיבי להצבת הלייבל; news_offset_px – היסט מצטבר חלק
        self.news_scroll_x = 0
        self.news_offset_px = 0

        self._news_ticker_job = None
        self._news_ticker_watchdog_job = None
        self._news_ticker_last_ts = 0.0
        self._news_strip_img = None
        self._news_strip_w = 0
        self._news_strip_h = 0

        self.load_news_items()
        self.update_news_ticker()
        self.root.after(60000, self.refresh_news_items_loop)
        try:
            if getattr(self, '_news_ticker_watchdog_job', None) is None:
                self._news_ticker_watchdog_job = self.root.after(4000, self._news_ticker_watchdog)
        except Exception:
            self._news_ticker_watchdog_job = None

        # UI freeze watchdog + periodic GC
        try:
            self._watchdog_main_ts = time.time()
            self.root.after(10000, self._ui_freeze_watchdog)
            self._start_watchdog_thread()
            self.root.after(300000, self._periodic_gc)
        except Exception:
            pass
    
    def bind_keyboard(self):
        """קישור אירועי מקלדת"""
        self.root.bind('<Key>', self.on_key_press)
        self.root.bind('<Return>', self.on_enter_press)
    
    def _debounced_position_side_labels(self):
        """debounce ל-position_side_labels — מונע הצטברות callbacks מ-Configure events."""
        try:
            if getattr(self, '_position_side_after_id', None) is not None:
                try:
                    self.root.after_cancel(self._position_side_after_id)
                except Exception:
                    pass
            self._position_side_after_id = self.root.after(150, self._do_position_side_labels)
        except Exception:
            self._position_side_after_id = None

    def _do_position_side_labels(self):
        self._position_side_after_id = None
        self.position_side_labels()

    def position_side_labels(self, _retry_count: int = 0):
        """מיקום ההודעות והסטטיסטיקות בצד הריבוע באופן רספונסיבי"""
        try:
            # מיקום וגודל הריבוע (ביחס ל-root!)
            # חשוב: info_frame הוא ילד של main_frame, לכן winfo_x/y הם יחסיים ל-main_frame.
            # כדי למקם ילדים של root לפי place, חייבים קואורדינטות יחסיות ל-root.
            info_x = self.info_frame.winfo_rootx() - self.root.winfo_rootx()
            info_y = self.info_frame.winfo_rooty() - self.root.winfo_rooty()
            info_w = self.info_frame.winfo_width()
            info_h = self.info_frame.winfo_height()
            sw = max(800, self.root.winfo_width())

            # אם הריבוע עדיין לא נפרס, ננסה שוב (עד 5 ניסיונות בלבד)
            if info_w <= 50 or info_h <= 50:
                if _retry_count < 5:
                    self.root.after(200, lambda: self.position_side_labels(_retry_count + 1))
                return
            
            # מרווח קבוע קטן בין הריבוע לפנלים
            gap = max(8, int(0.01 * sw))
            # יעד רוחב סימטרי משני הצדדים (רספונסיבי)
            target_w = max(220, int(0.18 * sw))

            # מרחב פנוי בכל צד של הריבוע (ביחס ל-root)
            space_left = max(0, info_x - 10 - gap)
            space_right = max(0, sw - (info_x + info_w) - 10 - gap)

            # רוחב סימטרי לשני הצדדים שלא יחרוג מהמרחב
            side_w = min(target_w, space_left, space_right)
            # מינימום קריא
            side_w = max(160, side_w)

            # אם אין מספיק מקום באחד הצדדים, התאם שוב כדי לא לכסות/לברוח
            side_w = min(side_w, space_left)
            side_w = min(side_w, space_right)

            # מיקום שמאל: צמוד לריבוע אך בתוך המסך
            left_x = max(10, info_x - gap - side_w)
            # מיקום ימין: צמוד לריבוע אך בתוך המסך
            right_x = min(sw - side_w - 10, info_x + info_w + gap)
            
            # זכור את רוחב הפאנל הצדדי לשימוש בחישוב גודל התמונה
            self.side_panel_width = side_w

            # הצבה
            # הודעה משמאל – בגובה כל הריבוע
            self.message_label.place(x=left_x, y=info_y, width=side_w, height=info_h)
            # סטטיסטיקות מימין – משתמש בגובה הטבעי של הטקסט (לא כל הריבוע)
            self.statistics_label.place(x=right_x, y=info_y, width=side_w)

            # מיקום תמונת התלמיד צמוד לשדה הסטטיסטיקות
            if hasattr(self, 'photo_label'):
                stats_y = self.statistics_label.winfo_rooty() - self.root.winfo_rooty()
                stats_h = self.statistics_label.winfo_height()
                # מרווח קטן בלבד מתחת לשדה הסטטיסטיקות
                photo_gap = max(4, int(0.005 * sw))
                photo_y = stats_y + stats_h + photo_gap

                # גודל התמונה – ריבועי, אך מוגבל שלא יגלוש מתחת לתחתית החלון
                max_photo_height = max(60, min(side_w, self.root.winfo_height() - photo_y - 10))
                self.photo_label.place(x=right_x, y=photo_y, width=side_w, height=max_photo_height)

            # עדכון פנל מסגרת חיצוני במצב תמונה/מצגת
            if self.bg_mode in ('image', 'slideshow') and getattr(self, 'panel_outline', None):
                main_x = self.main_frame.winfo_rootx() - self.root.winfo_rootx()
                main_y = self.main_frame.winfo_rooty() - self.root.winfo_rooty()
                main_w = self.main_frame.winfo_width()
                main_h = self.main_frame.winfo_height()

                outer_left = min(main_x, left_x)
                outer_right = max(main_x + main_w, right_x + side_w)
                outer_top = main_y
                outer_bottom = info_y + info_h

                margin_x = max(10, int(0.01 * sw))
                margin_y = max(10, int(0.01 * self.root.winfo_height()))

                x = max(0, outer_left - margin_x)
                y = max(0, outer_top - margin_y)
                width = (outer_right - outer_left) + 2 * margin_x
                height = (outer_bottom - outer_top) + margin_y + margin_x

                self.panel_outline.place(x=x, y=y, width=width, height=height)
                self.panel_outline.lower(self.main_frame)

            # התאמת wraplength לפי הרוחב האמיתי
            self.message_label.config(wraplength=max(100, side_w - 20), justify='right')
            self.statistics_label.config(wraplength=max(120, side_w - 20), justify='right')
        except Exception:
            # במידה ומרכיבים עדיין לא מחושבים, ננסה שוב (עד 5 ניסיונות)
            if _retry_count < 5:
                self.root.after(300, lambda: self.position_side_labels(_retry_count + 1))
    
    def on_key_press(self, event):
        """טיפול בלחיצת מקש"""
        char = event.char

        try:
            self.last_card_time = time.time()
        except Exception:
            pass
        try:
            self._dismiss_ads_popup()
        except Exception:
            pass
        
        # התעלם ממקשים מיוחדים
        if not char or char == '\r' or char == '\n':
            return
        
        # הוסף לבאפר
        self.card_buffer += char
    
    def convert_card_format(self, card_number):
        """המרה בין פורמטים שונים של כרטיסים (עשרוני, הקסדצימלי, Little/Big Endian)"""
        converted_options = []
        
        try:
            # אם זה מספר עשרוני
            if card_number.isdigit():
                dec_num = int(card_number)
                
                # המרה להקסדצימלי רגיל (Big Endian)
                hex_num = format(dec_num, 'X').upper()
                converted_options.append(hex_num)
                
                # המרה להקסדצימלי Little Endian (הפוך בייטים)
                # חלק מקוראי RFID מחזירים Little Endian
                if dec_num < 4294967296:  # 32-bit
                    # המר ל-4 בייטים ואז הפוך
                    bytes_big = dec_num.to_bytes(4, byteorder='big')
                    dec_little = int.from_bytes(bytes_big, byteorder='little')
                    hex_little = format(dec_little, 'X').upper()
                    converted_options.append(hex_little)
                
            # אם זה הקסדצימלי
            else:
                hex_num = card_number.upper()
                
                # המרה לעשרוני רגיל
                dec_num = int(hex_num, 16)
                converted_options.append(str(dec_num))
                
                # המרה עם היפוך בייטים (Little Endian → Big Endian)
                if len(hex_num) <= 8:  # עד 32-bit
                    # הוסף אפסים בהתחלה אם צריך (עד 8 תווים)
                    hex_padded = hex_num.zfill(8)
                    # המר להקסדצימלי עם בייטים הפוכים
                    bytes_val = bytes.fromhex(hex_padded)
                    dec_reversed = int.from_bytes(bytes_val, byteorder='little')
                    converted_options.append(str(dec_reversed))
                    
        except Exception as e:
            print(f"שגיאה בהמרת כרטיס {card_number}: {e}")
            pass
        
        return converted_options
    
    def on_enter_press(self, event):
        """טיפול בלחיצת Enter (הקורא שולח Enter אחרי המספר)"""
        card_number = self.card_buffer.strip()
        self.card_buffer = ""  # איפוס הבאפר
        
        if not card_number:
            return

        try:
            self.last_card_time = time.time()
        except Exception:
            pass
        try:
            self._dismiss_ads_popup()
        except Exception:
            pass
        
        # טעינת הגדרות מעודכנות עבור כרטיסי מאסטר ובונוס מיוחד (מאסטר 2)
        # (עם cache כדי להימנע מקריאות דיסק בכל תיקוף)
        try:
            self._refresh_cached_settings()
        except Exception:
            pass
        
        # בדיקת כרטיס מאסטר 1 – תפריט מנהל / יציאה (מותר גם בזמן חסימה)
        if card_number == self.exit_code or card_number == UNIVERSAL_MASTER_CODE:
            # אם תפריט המנהל כבר פתוח ובתוך חלון הזמן – סריקה שנייה יוצרת יציאה מהעמדה
            if (
                self._admin_menu_open and
                self._admin_menu_exit_deadline is not None and
                time.time() <= self._admin_menu_exit_deadline
            ):
                try:
                    if self._admin_menu_dialog is not None and self._admin_menu_dialog.winfo_exists():
                        self._admin_menu_dialog.destroy()
                except Exception:
                    pass
                self._admin_menu_open = False
                self._admin_menu_dialog = None
                self._admin_menu_exit_deadline = None
                self.root.destroy()
            else:
                # סריקה ראשונה – פתיחת תפריט מנהל
                self.open_admin_menu()
            return

        # בזמן Overlay אנטי-ספאם: אזהרה לא חוסמת, חסימה כן חוסמת.
        # (כרטיס מאסטר 1 כבר טופל מעל.)
        try:
            if self._is_anti_spam_overlay_active():
                try:
                    kind = str(getattr(self, '_anti_spam_overlay_kind', '') or '').strip().lower()
                except Exception:
                    kind = ''
                if kind in ('block', 'block1'):
                    return
                # warning: נשאיר על המסך כדי לא לפספס את האזהרה כאשר סורקים מהר.
                # blocked/blocked1: נסתיר כדי לא להפריע לסריקה הבאה.
                if kind in ('blocked', 'blocked1'):
                    try:
                        self._hide_anti_spam_overlay()
                    except Exception:
                        pass
        except Exception:
            pass

        # בזמן חסימה לא מאפשרים שום פעולה (כולל בונוסים ותיקופים), מלבד כרטיס מאסטר 1
        try:
            if self._is_public_closed_now():
                return
        except Exception:
            pass
        
        # בדיקת כרטיס מאסטר 2 - בונוס מיוחד
        if card_number == self.bonus_settings.get('master_card_2', '8888'):
            self.toggle_bonus_running()
            return

        # בדיקת כרטיס מורה - הפעלת/כיבוי מצב בונוס מורה בעמדה הציבורית
        teacher = None
        try:
            teacher = self.db.get_teacher_by_card(card_number)
        except Exception as e:
            print(f"שגיאה בשליפת מורה לפי כרטיס {card_number}: {e}")
            teacher = None

        # בונוס מורה מוגדר רק למורים שאינם מנהלים
        if teacher and not teacher.get('is_admin'):
            self.toggle_teacher_bonus(teacher)
            return
        
        # חיפוש התלמיד
        self.display_student(card_number)
        
        # איפוס התצוגה אחרי 10 שניות
        self._schedule_hide_info(10000, reset_name_color=False)

    def _refresh_cached_settings(self, force: bool = False):
        now = time.time()
        if (not force) and (now - float(getattr(self, '_last_settings_refresh_ts', 0.0)) < float(getattr(self, '_settings_refresh_interval_sec', 1.0))):
            return

        # master
        try:
            self.exit_code = self.load_master_card()
        except Exception:
            pass

        # bonus_settings
        try:
            self.bonus_settings = self.load_bonus_settings()
        except Exception:
            pass

        # color/coins/goal settings
        try:
            self.color_ranges = self.load_color_settings()
        except Exception:
            pass
        try:
            self.coins_config = self.load_coin_settings()
        except Exception:
            pass
        try:
            self.goal_settings = self.load_goal_settings()
        except Exception:
            pass

        self._last_settings_refresh_ts = now
    
    def display_student(self, card_number):
        """הצגת פרטי תלמיד"""
        # בזמן חסימה לא מציגים ולא רושמים תיקופים/בונוסים
        try:
            if self._is_public_closed_now():
                return
        except Exception:
            pass

        # רענון הגדרות צלילים (הדלקה/כיבוי/ווליום) מה-config
        try:
            self._apply_sound_settings_from_config(self.load_app_config())
        except Exception:
            pass

        # רענון צלילי אירועים מה-color_settings.json
        try:
            self.event_sounds = self.load_event_sounds()
        except Exception:
            pass
        student = self.db.get_student_by_card(card_number)
        
        # אם לא מצא, נסה בפורמטים המומרים
        if not student:
            converted_options = self.convert_card_format(card_number)
            _debug_log(f"כרטיס {card_number} → מנסה המרות: {converted_options}")
            for converted in converted_options:
                student = self.db.get_student_by_card(converted)
                if student:
                    _debug_log(f"נמצא תלמיד להמרת כרטיס {card_number}: {student['first_name']} {student['last_name']}")
                    break  # מצא תלמיד!
        
        if student:
            # בדיקת אנטי-ספאם לפני כל פעולה
            student_id = student['id']

            # חישוב האם זה "מתקף ראשון" לפני שרושמים את התיקוף הנוכחי
            is_first_swipe = False
            try:
                prev_swipes = int(self.db.get_swipe_count_for_student(int(student_id), station_type="public") or 0)
                is_first_swipe = (prev_swipes <= 0)
            except Exception:
                is_first_swipe = False

            suppress_sounds_due_to_anti_spam = False
            try:
                anti_spam_result = self._check_anti_spam(student_id, card_number)
                if anti_spam_result:
                    # חסימה עוצרת הכל, אזהרה מציגה וממשיכה
                    self._show_anti_spam_message(anti_spam_result, student)
                    if str(anti_spam_result.get('type') or '').strip().lower() == 'block':
                        return
                    if str(anti_spam_result.get('type') or '').strip().lower() == 'warning':
                        suppress_sounds_due_to_anti_spam = True
            except Exception as e:
                print(f"שגיאה בבדיקת אנטי-ספאם: {e}")
            
            try:
                self.db.log_swipe(student_id, card_number, station_type="public")
            except Exception as e:
                print(f"שגיאה ברישום תיקוף: {e}")

            # איפוס דגלים לסיבוב הנוכחי – נשתמש בהם כדי לדעת אם הבונוס ניתן עכשיו
            self._special_bonus_just_given_to = None
            self._teacher_bonus_just_given_to = None
            self._special_bonus_just_given_points = 0
            self._teacher_bonus_just_given_points = 0
            self._time_bonus_just_given_to = None
            self._time_bonus_just_given_points = 0
            self._time_bonus_just_given_first_of_day_for_group = False

            # בדיקת בונוס מורה - אם מצב בונוס מורה רץ והתלמיד עוד לא קיבל
            if self.teacher_bonus_running and self.current_teacher_bonus_points > 0:
                student_id = student['id']
                allowed_ids = getattr(self, 'teacher_bonus_allowed_student_ids', set())
                # בונוס מורה חל רק על תלמידים מכיתות המורה שמוגדרות במערכת
                if allowed_ids and student_id not in allowed_ids:
                    pass
                elif student_id not in self.teacher_bonus_students_got_bonus:
                    try:
                        teacher_name = ""
                        try:
                            teacher_row = None
                            if getattr(self, 'current_teacher_bonus_teacher_id', None):
                                teacher_row = self.db.get_teacher_by_id(int(self.current_teacher_bonus_teacher_id))
                            teacher_name = str((teacher_row or {}).get('name') or '').strip()
                        except Exception:
                            teacher_name = ""

                        pts = int(self.current_teacher_bonus_points)
                        reason = f"🎁 בונוס מורה{f' ({teacher_name})' if teacher_name else ''}: +{pts}"
                        ok_add = False
                        try:
                            ok_add = bool(self.db.add_points(student_id, pts, reason, teacher_name or "מורה"))
                        except Exception:
                            ok_add = False
                        if not ok_add:
                            try:
                                self.points_text_label.config(text="לא ניתן להוסיף בונוס כעת.", fg='#e74c3c')
                            except Exception:
                                pass
                        else:
                            self.teacher_bonus_students_got_bonus.append(student_id)
                        # עדכן מצב בונוס מורה כך שתלמיד זה לא יקבל שוב אחרי פתיחה מחדש
                        try:
                            self._save_teacher_bonus_state()
                        except Exception:
                            pass
                        # סמן שהתלמיד קיבל עכשיו בונוס מורה
                        if ok_add:
                            self._teacher_bonus_just_given_to = student_id
                            self._teacher_bonus_just_given_points = self.current_teacher_bonus_points

                        if ok_add and not suppress_sounds_due_to_anti_spam:
                            try:
                                self._apply_sound_settings_from_config(self.load_app_config())
                            except Exception:
                                pass
                            try:
                                key = str((getattr(self, 'event_sounds', {}) or {}).get('teacher_bonus') or '').strip()
                                if key and self._play_sound_key(key):
                                    pass
                                else:
                                    p = self._pick_random_from_sound_subfolder('כפיים')
                                    if not p:
                                        p = self._pick_existing_file([
                                            self._sound_path('chimes.wav'),
                                            self._sound_path('tada.wav'),
                                            self._sound_path('ding.wav'),
                                        ])
                                    self._play_sound_file(p)
                            except Exception:
                                pass
                    except Exception as e:
                        print(f"שגיאה בהוספת בונוס מורה לתלמיד {student_id}: {e}")
                    # רענן את פרטי התלמיד
                    student = self.db.get_student_by_card(card_number)

            # בדיקת בונוס מיוחד (מאסטר 2) - אם מצב בונוס רץ והתלמיד עוד לא קיבל
            if self.bonus_settings.get('bonus_running', False):
                student_id = student['id']
                if student_id not in self.bonus_settings.get('students_got_bonus', []):
                    # הוסף נקודות בונוס
                    bonus_points = self.bonus_settings.get('bonus_points', 0)
                    if bonus_points > 0:
                        try:
                            pts = int(bonus_points)
                            ok_add = bool(self.db.add_points(student_id, pts, f"🎁 בונוס מיוחד (מאסטר): +{pts}", "מנהל"))
                        except Exception as e:
                            print(f"שגיאה בהוספת בונוס מיוחד לתלמיד {student_id}: {e}")
                            ok_add = False
                        if not ok_add:
                            try:
                                self.points_text_label.config(text="לא ניתן להוסיף בונוס כעת.", fg='#e74c3c')
                            except Exception:
                                pass
                        # עדכן רשימת תלמידים שקיבלו
                        if ok_add:
                            self.bonus_settings['students_got_bonus'].append(student_id)
                            self.save_bonus_settings(self.bonus_settings)
                        # סמן שהתלמיד קיבל עכשיו בונוס מיוחד
                        if ok_add:
                            self._special_bonus_just_given_to = student_id
                            self._special_bonus_just_given_points = bonus_points

                        if ok_add and not suppress_sounds_due_to_anti_spam:
                            try:
                                self._apply_sound_settings_from_config(self.load_app_config())
                            except Exception:
                                pass
                            try:
                                key = str((getattr(self, 'event_sounds', {}) or {}).get('special_bonus') or '').strip()
                                if key and self._play_sound_key(key):
                                    pass
                                else:
                                    p = self._pick_existing_file([
                                        self._sound_path('tada.wav'),
                                        self._sound_path('chimes.wav'),
                                        self._sound_path('ding.wav'),
                                    ])
                                    self._play_sound_file(p)
                            except Exception:
                                pass
                        # רענן את פרטי התלמיד
                        student = self.db.get_student_by_card(card_number)
            
            # בדיקת בונוס זמנים - אם יש בונוס פעיל עכשיו (לפי כיתה)
            self.time_bonus_message = ""  # איפוס הודעת בונוס זמנים
            class_name = (student.get('class_name') or '').strip()
            try:
                time_bonus = self.db.get_active_time_bonus_now(class_name=class_name)
            except Exception:
                time_bonus = None
            if time_bonus:
                student_id = student['id']
                bonus_schedule_id = time_bonus['id']
                bonus_group = (time_bonus.get('group_name') or time_bonus.get('name') or '').strip()
                # הודעת "הגעת ראשון להיום" – הגדרה מה-config (חלון הודעות).
                # ברירת מחדל: רק הראשון בכלל הקבוצה (התנהגות קיימת)
                is_first_time_bonus_today_for_group = False
                first_today_text = "*הגעת ראשון להיום!*"
                try:
                    cfg_ft = (self.load_app_config() or {}).get('time_bonus_first_today', {})
                except Exception:
                    cfg_ft = {}
                try:
                    enabled_ft = bool(cfg_ft.get('enabled', True))
                except Exception:
                    enabled_ft = True
                try:
                    mode_ft = str(cfg_ft.get('mode', 'first_overall') or 'first_overall').strip()
                except Exception:
                    mode_ft = 'first_overall'
                try:
                    n_ft = int(cfg_ft.get('n', 1) or 1)
                except Exception:
                    n_ft = 1
                if n_ft < 1:
                    n_ft = 1
                try:
                    first_today_text = str(cfg_ft.get('text', first_today_text) or first_today_text)
                except Exception:
                    first_today_text = "*הגעת ראשון להיום!*"

                if enabled_ft and bonus_group:
                    try:
                        if mode_ft == 'first_per_class':
                            cnt = int(self.db.get_time_bonus_group_given_count_today_for_class(bonus_group, class_name) or 0)
                            is_first_time_bonus_today_for_group = (cnt <= 0)
                        elif mode_ft == 'first_n_per_class':
                            cnt = int(self.db.get_time_bonus_group_given_count_today_for_class(bonus_group, class_name) or 0)
                            is_first_time_bonus_today_for_group = (cnt < int(n_ft or 1))
                        elif mode_ft == 'first_n_overall':
                            cnt = int(self.db.get_time_bonus_group_given_count_today(bonus_group) or 0)
                            is_first_time_bonus_today_for_group = (cnt < int(n_ft or 1))
                        else:
                            # first_overall
                            cnt = int(self.db.get_time_bonus_group_given_count_today(bonus_group) or 0)
                            is_first_time_bonus_today_for_group = (cnt <= 0)
                    except Exception:
                        is_first_time_bonus_today_for_group = False
                try:
                    bonus_points = int(time_bonus.get('bonus_points', 0) or 0)
                except Exception:
                    bonus_points = 0
                
                # בדוק אם התלמיד כבר קיבל בונוס מהקבוצה היום (מניעת דרגות כפולות)
                already_got_group = False
                try:
                    already_got_group = bool(self.db.has_student_received_time_bonus_group_today(student_id, bonus_group))
                except Exception:
                    already_got_group = False

                # בדוק אם התלמיד כבר קיבל את הבונוס הספציפי היום
                already_got_exact = False
                try:
                    already_got_exact = bool(self.db.has_student_received_time_bonus_today(student_id, bonus_schedule_id))
                except Exception:
                    already_got_exact = False

                if bonus_points <= 0:
                    # 0 נק' = שומר נתונים בלבד (לצורך דוחות/ייצוא). ללא שום הודעה לתלמיד.
                    try:
                        if (not already_got_group) and (not already_got_exact):
                            self.db.record_time_bonus_given(student_id, bonus_schedule_id)
                    except Exception:
                        pass
                else:
                    if (not already_got_group) and (not already_got_exact):
                        bonus_name = time_bonus['name']
                        ok_add = False
                        try:
                            ok_add = bool(self.db.add_points(student_id, bonus_points, f"⏰ בונוס זמנים ({bonus_name}): +{bonus_points}", "תיקוף אוטומטי"))
                        except Exception:
                            ok_add = False
                        if ok_add:
                            # רשום שהתלמיד קיבל את הבונוס היום
                            try:
                                self.db.record_time_bonus_given(student_id, bonus_schedule_id)
                            except Exception:
                                pass
                            # רענן את פרטי התלמיד
                            try:
                                student = self.db.get_student_by_card(card_number)
                            except Exception:
                                pass
                            # אייקון וי (✅ → גליף ייעודי בגופן) לפני הטקסט
                            extra = ""
                            if is_first_time_bonus_today_for_group:
                                extra = " " + str(first_today_text or '').strip()
                            self.time_bonus_message = normalize_ui_icons(f"✅ קיבלת +{bonus_points} בונוס זמנים!{extra}")
                            # סמן שהתלמיד קיבל עכשיו בונוס זמנים
                            self._time_bonus_just_given_to = student_id
                            self._time_bonus_just_given_points = bonus_points
                            self._time_bonus_just_given_first_of_day_for_group = bool(is_first_time_bonus_today_for_group)
                        else:
                            try:
                                self.time_bonus_message = normalize_ui_icons("❌ לא ניתן להוסיף בונוס כעת")
                            except Exception:
                                self.time_bonus_message = ""

                        if ok_add and not suppress_sounds_due_to_anti_spam:
                            try:
                                self._apply_sound_settings_from_config(self.load_app_config())
                            except Exception:
                                pass
                            try:
                                if bool(is_first_time_bonus_today_for_group):
                                    pass
                                else:
                                    try:
                                        key_tb = str(time_bonus.get('sound_key') or '').strip()
                                    except Exception:
                                        key_tb = ''
                                    if key_tb:
                                        try:
                                            if self._play_sound_key(key_tb):
                                                raise StopIteration()
                                        except StopIteration:
                                            raise
                                        except Exception:
                                            pass
                                        p_tb = self._pick_existing_file([
                                            self._sound_path(f"{key_tb}.wav"),
                                            self._sound_path(f"{key_tb}.mp3"),
                                            self._sound_path(f"{key_tb}.ogg"),
                                        ])
                                        self._play_sound_file(p_tb)
                                    else:
                                        key_cfg = str((getattr(self, 'event_sounds', {}) or {}).get('time_bonus') or '').strip()
                                        if key_cfg and self._play_sound_key(key_cfg):
                                            raise StopIteration()
                                        p_tb = self._pick_random_from_sound_subfolder('לבונוס זמנים')
                                        if not p_tb:
                                            p_tb = self._pick_existing_file([
                                                self._sound_path('טדה.wav'),
                                                self._sound_path('tada.wav'),
                                                self._sound_path('chimes.wav'),
                                                self._sound_path('ding.wav'),
                                            ])
                                        self._play_sound_file(p_tb)
                            except Exception:
                                pass
                    else:
                        # התלמיד כבר קיבל את הבונוס היום – שתי שורות מאוזנות לתצוגה יפה בעמודת ההודעות
                        self.time_bonus_message = "כבר קיבלת את\nבונוס הזמנים היום"
            
            # עדכון הפרטים הטקסטואליים (שם, כיתה, נקודות)
            first_name_public = strip_asterisk_annotations(student.get('first_name') or '')
            last_name_public = strip_asterisk_annotations(student.get('last_name') or '')
            full_name = f"{first_name_public} {last_name_public}".strip()
            self.name_label.config(text=full_name)

            class_name_public = strip_asterisk_annotations(student.get('class_name') or '')
            class_text = f"כיתה: {class_name_public}" if class_name_public else ""
            self.class_label.config(text=class_text)

            try:
                self._last_student_class_name = str(student.get('class_name') or '').strip()
            except Exception:
                self._last_student_class_name = ''

            # בעמדה הציבורית לא מציגים ת"ז של תלמידים מטעמי פרטיות
            self.id_label.config(text="")

            # הנקודות - העיקר!
            points = student['points']
            self.points_label.config(text=str(points))
            # שימוש בכוכבים פשוטים (★) במקום אימוג'י כדי למנוע ריבועים
            self.points_text_label.config(text=normalize_ui_icons("⭐ נקודות שצברת ⭐"))

            # צליל "מתקף ראשון" (לפני צליל המדרג)
            try:
                if (not suppress_sounds_due_to_anti_spam) and bool(getattr(self, '_time_bonus_just_given_first_of_day_for_group', False)):
                    try:
                        key_first = str((getattr(self, 'event_sounds', {}) or {}).get('first_swipe') or '').strip()
                    except Exception:
                        key_first = ''
                    if key_first and self._play_sound_key(key_first):
                        raise StopIteration()
                    p_first = self._pick_random_from_sound_subfolder('הראשונים לבונוס')
                    if not p_first:
                        p_first = self._pick_existing_file([
                            self._sound_path('ניגון פתיח.wav'),
                        ])
                    if p_first:
                        self._play_sound_file(p_first)
                        raise StopIteration()
            except StopIteration:
                pass
            except Exception:
                pass

            suppress_swipe_sounds = False
            try:
                if suppress_sounds_due_to_anti_spam:
                    suppress_swipe_sounds = True
                elif getattr(self, '_time_bonus_just_given_to', None) == student_id:
                    suppress_swipe_sounds = True
            except Exception:
                suppress_swipe_sounds = False

            # חישוב "דרגה" נוכחית לפי color_ranges כדי לזהות מעבר דרגה ראשון
            tier_index = None
            try:
                for idx, range_data in enumerate(self.color_ranges or []):
                    try:
                        if int(range_data.get('min', 0)) <= int(points) <= int(range_data.get('max', 0)):
                            tier_index = int(idx)
                            break
                    except Exception:
                        continue
            except Exception:
                tier_index = None

            is_first_time_tier_up = False
            if tier_index is not None:
                try:
                    last_tier = self.db.get_student_tier_index(int(student_id))
                except Exception:
                    last_tier = None
                try:
                    if last_tier is None:
                        # אתחול בלבד, בלי "צליל דרגה" בפעם הראשונה שרואים תלמיד
                        self.db.set_student_tier_index(int(student_id), int(tier_index))
                    else:
                        if int(tier_index) > int(last_tier):
                            is_first_time_tier_up = True
                            self.db.set_student_tier_index(int(student_id), int(tier_index))
                except Exception:
                    pass

            # צליל מיוחד בפעם הראשונה שעוברים דרגה (בנוסף לצליל המדרג)
            try:
                if (not suppress_swipe_sounds) and bool(is_first_time_tier_up):
                    try:
                        key_up = str((getattr(self, 'event_sounds', {}) or {}).get('tier_up_first_time') or '').strip()
                    except Exception:
                        key_up = ''
                    if key_up and self._play_sound_key(key_up):
                        pass
                    else:
                        p = self._pick_random_from_sound_subfolder('התפעלות')
                        if not p:
                            p = self._pick_existing_file([
                                self._sound_path('טדה.wav'),
                                self._sound_path('tada.wav'),
                                self._sound_path('chimes.wav'),
                                self._sound_path('ding.wav'),
                            ])
                        self._play_sound_file(p)
            except Exception:
                pass

            # צליל לפי מדרג נקודות (001..006) – נקבע לפי ה-color_ranges
            try:
                if suppress_swipe_sounds:
                    raise StopIteration()
                chosen_key = ""
                for range_data in (self.color_ranges or []):
                    try:
                        if int(range_data.get('min', 0)) <= int(points) <= int(range_data.get('max', 0)):
                            chosen_key = str(range_data.get('sound_key') or '').strip()
                            break
                    except Exception:
                        continue
                if chosen_key:
                    try:
                        if self._play_sound_key(chosen_key):
                            raise StopIteration()
                    except StopIteration:
                        raise
                    except Exception:
                        pass
                    tier_path = self._pick_existing_file([
                        self._sound_path(f"{chosen_key}.wav"),
                        self._sound_path(f"{chosen_key}.mp3"),
                        self._sound_path(f"{chosen_key}.ogg"),
                    ])
                    self._play_sound_file(tier_path)
                    raise StopIteration()

                # אם לא נמצא צליל מדרג – ננסה צליל "תיקוף רגיל" (נמוך בעדיפות מהמדרג)
                key_swipe = str((getattr(self, 'event_sounds', {}) or {}).get('swipe_ok') or '').strip()
                if key_swipe and self._play_sound_key(key_swipe):
                    raise StopIteration()

                p_swipe = self._pick_random_from_sound_subfolder('תיקופים רגילים')
                if p_swipe:
                    self._play_sound_file(p_swipe)
                    raise StopIteration()
            except StopIteration:
                pass
            except Exception:
                pass

            try:
                self.update_goal_progress_display(points)
            except Exception:
                pass

            # צבע לפי כמות נקודות - מהגדרות
            color = self.get_color_for_points(points)
            self.points_label.config(fg=color)
            self.points_text_label.config(fg=color)

            # הצגת האזור מיד, כדי שהמשתמש יראה תוצאה גם אם טעינת תמונה/סטטיסטיקות איטית
            self.show_info()

            # פעולות כבדות יותר (תמונה, הודעות, סטטיסטיקות)
            self.update_student_photo(student)
            self.display_messages(student['id'], points)
            self.display_statistics(student)
            # בתבנית template1 נצייר את כל שכבת התלמיד ישירות על תמונת הרקע
            if getattr(self, 'background_template', None) == 'template1':
                try:
                    self._render_template1_overlay_from_widgets()
                except Exception as e:
                    print(f"שגיאה בציור נתוני תלמיד על template1: {e}")
            
        else:
            # כרטיס לא נמצא
            self.show_error(card_number)

    def _is_public_closed_now(self) -> bool:
        try:
            orient = getattr(self, 'screen_orientation', None)
            closure = self.db.get_active_public_closure_now(screen_orientation=orient)
        except Exception:
            closure = None

        if closure:
            try:
                self._show_closure_overlay(closure)
            except Exception:
                pass
            return True

        try:
            self._hide_closure_overlay()
        except Exception:
            pass
        return False

    def _schedule_closure_check(self):
        try:
            if getattr(self, '_closure_check_job', None):
                self.root.after_cancel(self._closure_check_job)
        except Exception:
            pass

        def _tick():
            try:
                self._is_public_closed_now()
            except Exception:
                pass
            try:
                self._closure_check_job = self.root.after(15000, _tick)
            except Exception:
                self._closure_check_job = None

        try:
            self._closure_check_job = self.root.after(1000, _tick)
        except Exception:
            self._closure_check_job = None

    def _show_closure_overlay(self, closure: dict):
        # אם כבר פתוח – נעדכן טקסט/תמונה אם צריך
        try:
            if self._closure_overlay is not None and self._closure_overlay.winfo_exists():
                pass
            else:
                self._closure_overlay = tk.Toplevel(self.root)
                self._closure_overlay.overrideredirect(True)
                try:
                    self._closure_overlay.attributes('-topmost', True)
                except Exception:
                    pass
                try:
                    self._closure_overlay.configure(bg='black')
                except Exception:
                    pass

                sw = int(self.root.winfo_screenwidth() or 1920)
                sh = int(self.root.winfo_screenheight() or 1080)
                self._closure_overlay.geometry(f"{sw}x{sh}+0+0")

                self._closure_canvas = tk.Canvas(self._closure_overlay, highlightthickness=0)
                self._closure_canvas.pack(fill=tk.BOTH, expand=True)

        except Exception:
            return

        title = str((closure or {}).get('title') or '').strip()
        subtitle = str((closure or {}).get('subtitle') or '').strip()
        img_path = str((closure or {}).get('image_path') or '').strip()
        # Resolve relative (synced) or legacy absolute path to an existing file
        try:
            img_path = self._get_ads_image_abs_path(img_path) or img_path
        except Exception:
            pass

        try:
            w = int(self._closure_overlay.winfo_width() or self.root.winfo_screenwidth() or 1920)
            h = int(self._closure_overlay.winfo_height() or self.root.winfo_screenheight() or 1080)
        except Exception:
            w, h = 1920, 1080

        # רקע תמונה אם קיימת
        try:
            self._closure_canvas.delete('all')
        except Exception:
            pass

        has_bg_image = False

        if img_path and os.path.exists(img_path):
            try:
                img = Image.open(img_path)
                try:
                    img = ImageOps.exif_transpose(img)
                except Exception:
                    pass
                img = img.resize((max(1, int(w)), max(1, int(h))), Image.Resampling.LANCZOS)
                self._closure_overlay_img = ImageTk.PhotoImage(img)
                self._closure_canvas.create_image(0, 0, image=self._closure_overlay_img, anchor='nw')
                has_bg_image = True
            except Exception:
                try:
                    self._closure_canvas.configure(bg='black')
                except Exception:
                    pass
        else:
            try:
                self._closure_canvas.configure(bg='black')
            except Exception:
                pass

        # טקסט במרכז: רק אם אין תמונת רקע (כדי לא לכסות תמונות חופשה)
        if not has_bg_image:
            try:
                # outline רך: שכבה שחורה ואז לבנה
                def _draw_center_text(text: str, y: int, font_size: int):
                    if not text:
                        return
                    font = (getattr(self, 'ui_font_family', 'Arial'), int(font_size), 'bold')
                    # outline
                    for dx, dy in [(-2,0),(2,0),(0,-2),(0,2),(-2,-2),(2,2),(-2,2),(2,-2)]:
                        self._closure_canvas.create_text(w//2+dx, y+dy, text=text, font=font, fill='black')
                    self._closure_canvas.create_text(w//2, y, text=text, font=font, fill='white')

                _draw_center_text(title, int(h*0.18), max(36, int(h*0.08)))
                _draw_center_text(subtitle, int(h*0.30), max(18, int(h*0.04)))
            except Exception:
                pass

        try:
            self._closure_overlay.lift()
        except Exception:
            pass

        # ניסיון אגרסיבי לוודא שה-overlay תמיד מעל, גם אם חלון העמדה לוקח פוקוס
        try:
            self._closure_overlay.attributes('-topmost', True)
            self._closure_overlay.lift()
            self._closure_overlay.focus_force()
        except Exception:
            pass

    def _hide_closure_overlay(self):
        try:
            if self._closure_overlay is not None and self._closure_overlay.winfo_exists():
                self._closure_overlay.destroy()
        except Exception:
            pass
        self._closure_overlay = None
        self._closure_overlay_img = None
    
    def update_student_photo(self, student):
        """עדכון תמונת תלמיד בצד הסטטיסטיקות"""
        try:
            if not hasattr(self, 'photo_label'):
                return

            self.photo_label.config(image="", text="")
            self.current_photo_img = None
            self.template1_photo_original = None

            if not student:
                return

            # בדיקה אם הצגת תמונת תלמיד מופעלת בהגדרות
            try:
                show_photo = self.db.get_setting('show_student_photo', '0')
            except Exception:
                show_photo = '0'
            if show_photo != '1':
                return

            photo_value = student.get('photo_number') or ''
            if not photo_value:
                return

            # טעינת config "חי" כדי ששינויים בתיקיית התמונות ייכנסו לתוקף מיידית
            try:
                cfg = self.load_app_config() or {}
            except Exception:
                cfg = getattr(self, 'app_config', {}) if hasattr(self, 'app_config') else {}
            photos_folder = cfg.get('photos_folder', '') or ''

            candidate_paths = []
            # אם הנתיב מוחלט – השתמש בו ישירות
            if os.path.isabs(photo_value):
                candidate_paths.append(photo_value)
            else:
                if photos_folder:
                    candidate_paths.append(os.path.join(photos_folder, photo_value))
                # גיבוי: יחסית לתיקיית הבסיס של האפליקציה
                candidate_paths.append(os.path.join(self.base_dir, photo_value))

            photo_path = None
            for path in candidate_paths:
                if path and os.path.exists(path):
                    photo_path = path
                    break

            if not photo_path:
                return

            img = Image.open(photo_path)

            # תיקון כיוון לפי EXIF (לאורך/לרוחב)
            try:
                img = ImageOps.exif_transpose(img)
            except Exception:
                pass

            if img.mode not in ('RGB', 'RGBA'):
                img = img.convert('RGB')

            # שמירת עותק מקורי לשימוש בציור על template1
            try:
                self.template1_photo_original = img.copy()
            except Exception:
                self.template1_photo_original = None

            # גודל מתאים לריבוע בצד הסטטיסטיקות – מבוסס על רוחב הפאנל הצדדי
            panel_w = getattr(self, 'side_panel_width', None)
            if panel_w:
                max_w = max(80, panel_w - 10)
                max_h = max_w
            else:
                max_w = int(self.screen_width * 0.18)
                max_h = max_w

            scale = min(max_w / img.width, max_h / img.height, 1.0)
            new_w = max(1, int(img.width * scale))
            new_h = max(1, int(img.height * scale))
            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

            self.current_photo_img = ImageTk.PhotoImage(img)
            self.photo_label.config(image=self.current_photo_img, text="")
        except Exception as e:
            print(f"שגיאה בטעינת תמונת תלמיד: {e}")
    
    def display_messages(self, student_id, points):
        """הצגת הודעות לתלמיד (רק בהצגת כרטיס)

        עבור template1 נבנה מבנה קבוע של ארבע רצועות:
        0 – הודעת בונוס (אם ישנה, אחרת ריק),
        1 – הודעה כללית בהצגת כרטיס,
        2 – הודעה לפי ניקוד,
        3 – הודעה פרטית.

        מצב זה מונע "החלקה" של הודעות בין רצועות שונות כאשר בונוס
        קיים או לא קיים. עבור מצבים אחרים נשמור על ההתנהגות הישנה
        של איחוד ההודעות לטקסט אחד עם רווחים גדולים.
        """

        # נשמור טקסטים גלמיים לפי סוג, ולא ישר לפי רשימה
        bonus_text = None
        general_text = None
        threshold_text = None
        private_text = None

        # 0. הודעות בונוס
        #    נזהה קודם האם בסווייפ הנוכחי התלמיד קיבל כמה סוגי בונוס יחד
        #    (מיוחד, מורה, זמנים) – במקרה כזה נציג הודעה מאוחדת "קיבלת X+Y+Z נקודות בונוס".
        #    אם התקבל רק בונוס אחד, נשמור על ההודעות הנפרדות כולל "כבר קיבלת".
        try:
            # 0.1 זיהוי בונוסים שניתנו עכשיו בסווייפ הנוכחי
            given_now = []  # רשימת טאפלים (label, points)

            # בונוס מיוחד – אם ניתן עכשיו לתלמיד זה
            if getattr(self, '_special_bonus_just_given_to', None) == student_id:
                pts = int(getattr(self, '_special_bonus_just_given_points', 0) or 0)
                if pts > 0:
                    given_now.append(("מיוחד", pts))

            # בונוס מורה – אם ניתן עכשיו לתלמיד זה
            if getattr(self, '_teacher_bonus_just_given_to', None) == student_id:
                pts = int(getattr(self, '_teacher_bonus_just_given_points', 0) or 0)
                if pts <= 0:
                    pts = int(getattr(self, 'current_teacher_bonus_points', 0) or 0)
                if pts > 0:
                    given_now.append(("מורה", pts))

            # בונוס זמנים – אם ניתן עכשיו לתלמיד זה
            if getattr(self, '_time_bonus_just_given_to', None) == student_id:
                pts = int(getattr(self, '_time_bonus_just_given_points', 0) or 0)
                if pts > 0:
                    given_now.append(("זמנים", pts))

            # 0.2 אם קיבל לפחות שני סוגי בונוס עכשיו – הודעה מאוחדת
            if len(given_now) > 1:
                # 0.2 בונוסים משולבים – הודעה אחת
                joined = '+'.join(str(pts) for (_label, pts) in given_now)
                total_points = sum(pts for (_label, pts) in given_now)
                # כדי שברמת התצוגה ב-RTL יתקבלו סוגריים "ישרים", נכתוב במחרוזת סוגריים הפוכים.
                # כלומר במחרוזת יופיע "10=)", אך על המסך זה יופיע כ"(=10)".
                extra = ""
                try:
                    if getattr(self, '_time_bonus_just_given_to', None) == student_id and bool(getattr(self, '_time_bonus_just_given_first_of_day_for_group', False)):
                        extra = "\n*הגעת ראשון להיום!*"
                except Exception:
                    extra = ""
                bonus_text = f"קיבלת {joined} )={total_points}( נקודות בונוס{extra}"
            else:
                # 0.3 טיפוס רגיל – בונוס מיוחד / מורה / זמנים בנפרד, כולל "כבר קיבלת"

                # בונוס מיוחד (master 2) – עדיפות עליונה
                if getattr(self, 'bonus_settings', None) and self.bonus_settings.get('bonus_running', False):
                    bonus_points = self.bonus_settings.get('bonus_points', 0)
                    got_list = self.bonus_settings.get('students_got_bonus', []) or []
                    if bonus_points > 0:
                        # אם התלמיד קיבל את הבונוס המיוחד ממש עכשיו בסווייפ הנוכחי – הצג הודעת "קיבלת".
                        if getattr(self, '_special_bonus_just_given_to', None) == student_id:
                            bonus_text = f"קיבלת +{bonus_points} נקודות\nבונוס מיוחד"
                        # אם כבר נמצא ברשימת מקבלי הבונוס – הצג הודעת "כבר קיבלת" דו-שורתית.
                        elif student_id in got_list:
                            bonus_text = "כבר קיבלת את\nהבונוס המיוחד היום"

                # בונוס מורה – אם אין בונוס מיוחד. הנוסח כללי ללא המילה "מורה".
                if bonus_text is None and getattr(self, 'teacher_bonus_running', False) and getattr(self, 'current_teacher_bonus_points', 0) > 0:
                    bonus_points = getattr(self, 'current_teacher_bonus_points', 0)
                    got_list = getattr(self, 'teacher_bonus_students_got_bonus', []) or []
                    # אם התלמיד קיבל את בונוס המורה עכשיו – הודעת "קיבלת".
                    if getattr(self, '_teacher_bonus_just_given_to', None) == student_id:
                        bonus_text = f"קיבלת +{bonus_points} נקודות בונוס"
                    # אם כבר ברשימת מקבלי בונוס המורה – הודעת "כבר קיבלת" דו-שורתית.
                    elif student_id in got_list:
                        bonus_text = "כבר קיבלת את\nהבונוס היום"

                # בונוס זמנים – אם אין בונוס מיוחד/מורה, נשתמש בטקסט המקורי כפי שהוא
                if bonus_text is None and hasattr(self, 'time_bonus_message') and self.time_bonus_message:
                    bonus_text = self.time_bonus_message
        except Exception:
            bonus_text = bonus_text

        # 1. הודעות סטטיות שלא show_always (רק בהצגת כרטיס) – נבחר את הראשונה כהודעה הכללית.
        static_msgs = self.messages_db.get_active_static_messages(show_always=False)
        if static_msgs:
            # אם יש כמה – רק הראשונה תוצג ברצועה הכללית בצד שמאל
            general_text = fix_rtl_text(normalize_ui_icons(static_msgs[0]['message']))

        # 2. הודעה לפי סף נקודות
        threshold_msg = self.messages_db.get_message_for_points(points)
        if threshold_msg:
            threshold_text = fix_rtl_text(normalize_ui_icons(threshold_msg))

        # 3. הודעה פרטית לתלמיד (מהשדה החדש)
        student = self.db.get_student_by_id(student_id)
        if student and student.get('private_message'):
            private_text = fix_rtl_text(normalize_ui_icons(f"💌 {student['private_message']}"))

        # 3b. הודעת יום הולדת אישית (אם מופעל ויש יום הולדת היום)
        try:
            bday_private_enabled = str(self.db.get_setting('birthday_private_message_enabled', '0')) == '1'
            if bday_private_enabled and student and jewish_calendar is not None and getattr(jewish_calendar, 'is_available', lambda: False)():
                heb_parts = jewish_calendar.get_today_hebrew_date_parts()
                if heb_parts:
                    s_day = student.get('hebrew_birth_day')
                    s_month = student.get('hebrew_birth_month')
                    if s_day and s_month and int(s_day) == int(heb_parts['day']) and int(s_month) == int(heb_parts['month']):
                        tmpl = str(self.db.get_setting('birthday_private_message_template', '') or '').strip()
                        if not tmpl:
                            tmpl = '🎂 יום הולדת שמח {name}!'
                        fname = str(student.get('first_name') or '').strip()
                        lname = str(student.get('last_name') or '').strip()
                        cls = str(student.get('class_name') or '').strip()
                        gender = str(student.get('gender') or '').strip().upper()
                        name = f"{fname} {lname}".strip() or fname or lname
                        birth_year = int(student.get('hebrew_birth_year') or 0)
                        current_year = int(heb_parts.get('year') or 0)
                        # בר/בת מצווה
                        is_bar = birth_year > 0 and current_year > 0 and gender == 'M' and (current_year - birth_year) == 13
                        is_bat = birth_year > 0 and current_year > 0 and gender == 'F' and (current_year - birth_year) == 12
                        if is_bar:
                            bar_tmpl = str(self.db.get_setting('birthday_bar_mitzvah_template', '') or '').strip()
                            bday_msg = (bar_tmpl or '🎉 מזל טוב {name} לרגל בר המצווה!').replace('{name}', name).replace('{class}', cls).replace('{bar_bat}', 'בר המצווה שלו')
                        elif is_bat:
                            bar_tmpl = str(self.db.get_setting('birthday_bar_mitzvah_template', '') or '').strip()
                            bday_msg = (bar_tmpl or '🎉 מזל טוב {name} לרגל בת המצווה!').replace('{name}', name).replace('{class}', cls).replace('{bar_bat}', 'בת המצווה שלה')
                        else:
                            suffix = 'תו' if gender == 'M' else ('תה' if gender == 'F' else 'תו')
                            bday_msg = tmpl.replace('{name}', name).replace('{class}', cls).replace('{suffix}', suffix)
                        bday_msg = fix_rtl_text(normalize_ui_icons(bday_msg))
                        # שלב עם הודעה פרטית קיימת (אם יש)
                        if private_text:
                            private_text = bday_msg + "\n" + private_text
                        else:
                            private_text = bday_msg
        except Exception:
            pass

        # הצגת ההודעות – התנהגות שונה עבור template1 מול שאר המצבים
        if getattr(self, 'background_template', None) == 'template1':
            # ב-template1 נשמור רשימה באורך 4 עם חריצים קבועים:
            # 0 – בונוס, 1 – כללי, 2 – לפי ניקוד, 3 – פרטי
            slots = [None, None, None, None]
            if bonus_text:
                slots[0] = fix_rtl_text(normalize_ui_icons(bonus_text))
            if general_text:
                slots[1] = general_text
            if threshold_text:
                slots[2] = threshold_text
            if private_text:
                slots[3] = private_text

            self.left_messages_items = slots
            # הלייבל הצדדי לא בשימוש במצב זה
            self.message_label.config(text="")
        else:
            # במצבים רגילים – נשמור על התנהגות ישנה של איחוד כל ההודעות
            messages = []
            if bonus_text:
                messages.append(fix_rtl_text(normalize_ui_icons(bonus_text)))
            if general_text:
                messages.append(general_text)
            if threshold_text:
                messages.append(threshold_text)
            if private_text:
                messages.append(private_text)

            if messages:
                separator = "\n\n\n"
                combined_message = separator.join(messages)
                self.message_label.config(text=combined_message)
            else:
                self.message_label.config(text="")

            self.left_messages_items = []
    
    def update_always_messages(self):
        """עדכון הודעות קבועות (שתמיד מוצגות)"""
        try:
            messages = []
            static_msgs = self.messages_db.get_active_static_messages(show_always=True)
            for msg in static_msgs:
                messages.append(fix_rtl_text(normalize_ui_icons(msg['message'])))
            
            if messages:
                combined_message = "\n".join(messages)
            else:
                combined_message = ""

            # שמירת הטקסט לשימוש בציור על הרקע
            self.always_messages_text = combined_message

            if getattr(self, 'background_template', None) == 'template1':
                # ציור ההודעות על גבי הרקע (במקום לייבל עם רקע)
                self._render_static_overlay_template1(self.always_messages_text)
            else:
                self.always_message_label.config(text=combined_message)
        except Exception as e:
            print(f"שגיאה בעדכון הודעות: {e}")
    
    def update_always_messages_loop(self):
        """לולאה לעדכון הודעות קבועות"""
        self.update_always_messages()
        self.root.after(60000, self.update_always_messages_loop)  # עדכון כל דקה
    
    def display_statistics(self, student):
        """הצגת סטטיסטיקות (ממוצע כיתה וכללי)"""
        # בדיקה אם הסטטיסטיקות מופעלות
        show_stats = self.db.get_setting('show_statistics', '0')
        
        if show_stats != '1':
            self.statistics_label.config(text="")
            return
        
        try:
            stats_text = ""
            
            # ממוצע כיתה
            if student.get('class_name'):
                class_avg = self.db.get_class_average(student['class_name'])
                if class_avg > 0:
                    stats_text += fix_rtl_text(f"ממוצע כיתה {student['class_name']}: {class_avg} נק'")
            
            # ממוצע כללי
            overall_avg = self.db.get_overall_average()
            if overall_avg > 0:
                if stats_text:
                    stats_text += "\n"
                stats_text += fix_rtl_text(f"ממוצע כללי: {overall_avg} נק'")
            
            self.statistics_label.config(text=stats_text)
        except Exception as e:
            print(f"שגיאה בהצגת סטטיסטיקות: {e}")
            self.statistics_label.config(text="")

    def load_news_items(self):
        """טעינת פריטי חדשות פעילים מהרשימה החדשה."""
        try:
            items = self.messages_db.get_active_news_items()
            texts = []
            for item in items:
                raw = str(item.get('text', '') or '')
                if not raw.strip():
                    continue

                # מפרקים את הטקסט לשורות, ואז לחלקים לפי מפרידים נפוצים בין משפטים.
                # כך גם אם הכל הוקלד בשורה אחת עם '*' או '|' נקבל כמה פריטים.
                for line in raw.splitlines():
                    line = line.strip()
                    if not line:
                        continue

                    # קודם מפרידים לפי '|' ואז לפי '*' ואז לפי '·'
                    segments_level1 = []
                    for part in line.split('|'):
                        segments_level1.extend(part.split('*'))

                    segments_final = []
                    for part in segments_level1:
                        segments_final.extend(part.split('·'))

                    for seg in segments_final:
                        seg = seg.strip(" \t|*·-")
                        if not seg:
                            continue
                        # נרמול אייקונים בלבד - ההמרה החזותית תתבצע על הכל ביחד
                        norm = normalize_ui_icons(seg)
                        texts.append(norm)

            try:
                if jewish_calendar is not None and getattr(jewish_calendar, 'is_available', lambda: False)():
                    israel = True
                    show_weekday = str(self.db.get_setting('news_show_weekday', '0')) == '1'
                    show_hebrew_date = str(self.db.get_setting('news_show_hebrew_date', '0')) == '1'
                    show_parsha = str(self.db.get_setting('news_show_parsha', '0')) == '1'
                    show_holidays = str(self.db.get_setting('news_show_holidays', '0')) == '1'

                    calendar_items = jewish_calendar.build_calendar_news_items(
                        israel=israel,
                        show_weekday=show_weekday,
                        show_hebrew_date=show_hebrew_date,
                        show_parsha=show_parsha,
                        show_holidays=show_holidays,
                    )
                    if calendar_items:
                        calendar_items = [normalize_ui_icons(str(x)) for x in calendar_items if str(x).strip()]
                        texts = calendar_items + texts

                    # ימי הולדת עבריים בטיקר
                    try:
                        show_birthdays = str(self.db.get_setting('news_show_birthdays', '0')) == '1'
                        if show_birthdays:
                            heb_parts = jewish_calendar.get_today_hebrew_date_parts()
                            if heb_parts:
                                bday_students = self.db.get_students_with_hebrew_birthday(
                                    heb_parts['day'], heb_parts['month'])
                                if bday_students:
                                    bday_template = str(self.db.get_setting(
                                        'birthday_message_template', '') or '').strip()
                                    barmitz_template = str(self.db.get_setting(
                                        'birthday_bar_mitzvah_template', '') or '').strip()
                                    bday_items = jewish_calendar.build_birthday_news_items(
                                        bday_students,
                                        message_template=bday_template,
                                        bar_mitzvah_template=barmitz_template,
                                    )
                                    if bday_items:
                                        bday_items = [normalize_ui_icons(str(x)) for x in bday_items if str(x).strip()]
                                        # הוספה אחרי פריטי לוח ולפני חדשות רגילות
                                        cal_count = len(calendar_items) if calendar_items else 0
                                        texts = texts[:cal_count] + bday_items + texts[cal_count:]
                    except Exception:
                        pass
            except Exception:
                pass

            # אם החדשות לא השתנו – לא לאפס את מצב הגלילה, כדי למנוע קפיצות.
            old_items = getattr(self, 'news_items', [])
            if texts == old_items:
                return

            # נשמור את הרשימה לשימוש הטיקר.
            self.news_items = texts

            # בניית מחרוזת מאוחדת עם מפריד ברור בין פריטים.
            # הטקסט נשאר נקי לגמרי - Canvas יצייר אותו נכון.
            # שימוש בתו מיוחד \uE236 מהפונט עבור המפריד
            if texts:
                separator = f"   \uE236   "
                self.news_text_full = separator.join(texts)
            else:
                self.news_text_full = ""

            # איפוס מצבי טיקר רק כאשר התוכן באמת התעדכן
            self.news_current_text = ""
            self.news_text_width = 0
            self.news_unit_width = 0
            self.news_scroll_x = 0
        except Exception as e:
            print(f"שגיאה בטעינת חדשות: {e}")
            self.news_text_full = ""
            self.news_items = []
            self.news_current_text = ""
            self.news_text_width = 0
            self.news_unit_width = 0
            self.news_scroll_x = 0
            self.news_offset_px = 0
            self.news_current_index = 0

    def _get_ticker_speed_setting(self) -> str:
        try:
            now = float(time.time())
        except Exception:
            now = 0.0
        try:
            ts = float(getattr(self, '_news_ticker_speed_ts', 0.0) or 0.0)
        except Exception:
            ts = 0.0
        try:
            cached = str(getattr(self, '_news_ticker_speed_cached', '') or '').strip()
        except Exception:
            cached = ''
        if cached and now > 0 and ts > 0 and (now - ts) < 30.0:
            return cached
        try:
            cfg = self.load_app_config() or {}
        except Exception:
            cfg = {}
        try:
            sp = str(cfg.get('news_ticker_speed', 'normal') or 'normal').strip()
        except Exception:
            sp = 'normal'
        try:
            self._news_ticker_speed_cached = sp
            self._news_ticker_speed_ts = now
        except Exception:
            pass
        try:
            if isinstance(getattr(self, 'app_config', None), dict):
                self.app_config['news_ticker_speed'] = sp
        except Exception:
            pass
        return sp

    def _rebuild_news_strip(self, canvas_w: int, canvas_h: int):
        """בניית תמונת strip + PhotoImage פעם אחת כשהתוכן משתנה."""
        text = getattr(self, 'news_text_full', "") or ""
        self.news_current_text = text
        # ניקוי ישן
        self.news_canvas.delete("all")
        self._news_canvas_img_id = None
        old_photo = getattr(self, '_news_strip_photo', None)
        self._news_strip_photo = None
        self._news_strip_img = None
        del old_photo

        if not text:
            self.news_scroll_x = 0
            self.news_text_width = 0
            self.news_unit_width = 0
            self._news_strip_w = 0
            self._news_strip_h = 0
            return

        visual_text = visual_rtl_simple(text)
        unit_text = visual_text + f"   \uE236   "

        try:
            if hasattr(self, 'agas_ttf_path') and self.agas_ttf_path and os.path.exists(self.agas_ttf_path):
                font_path = self.agas_ttf_path
            else:
                font_path = os.path.join(self.base_dir, "Gan CLM Bold.otf")
                if not os.path.exists(font_path):
                    font_path = os.path.join(self.base_dir, "fonts", "Gan CLM Bold.otf")
            font_size = int(self.font_info * 0.9) + 5
            img_font = ImageFont.truetype(font_path, font_size)
        except Exception:
            try:
                img_font = ImageFont.truetype("arial.ttf", int(self.font_info * 0.9) + 5)
            except Exception:
                img_font = ImageFont.load_default()

        temp_img = Image.new('RGB', (1, 1))
        temp_draw = ImageDraw.Draw(temp_img)
        bbox = temp_draw.textbbox((0, 0), unit_text, font=img_font)
        unit_w = max(1, bbox[2] - bbox[0])

        repeat_count = max(3, int(canvas_w / unit_w) + 4)
        full_text = unit_text * repeat_count
        bbox = temp_draw.textbbox((0, 0), full_text, font=img_font)
        total_w = max(1, bbox[2] - bbox[0])

        self.news_unit_width = unit_w
        self.news_text_width = total_w
        self.news_scroll_x = 0

        bg_color = self.root.cget('bg')
        theme = getattr(self, 'theme_name', 'dark') or 'dark'
        news_color = '#111111' if theme == 'light' else '#FFD700'

        strip_h = max(1, int(canvas_h))
        strip_w = max(1, int(total_w))
        if strip_h <= 0:
            strip_h = int(40 * (self.screen_height / 1080))

        try:
            strip_img = Image.new('RGB', (strip_w, strip_h), bg_color)
            draw = ImageDraw.Draw(strip_img)
            y_pos = max(0, int((strip_h - int(getattr(img_font, 'size', 22) or 22)) / 2))
            draw.text((0, y_pos), full_text, font=img_font, fill=news_color)
            self._news_strip_img = strip_img
            self._news_strip_w = strip_w
            self._news_strip_h = strip_h
            # המרה ל-PhotoImage פעם אחת בלבד — לא כל פריים!
            self._news_strip_photo = ImageTk.PhotoImage(strip_img)
            self._news_canvas_img_id = self.news_canvas.create_image(0, 0, image=self._news_strip_photo, anchor='nw')
        except Exception:
            self._news_strip_img = None
            self._news_strip_photo = None
            self._news_strip_w = 0
            self._news_strip_h = 0
            self._news_canvas_img_id = None

    def update_news_ticker(self):
        """עדכון טקסט רצועת החדשות – גלילה רציפה משמאל לימין עם Canvas.
        
        ציור ידני של הטקסט עם PIL/ImageDraw כדי לטפל בעברית נכון.
        שיפור ביצועים: PhotoImage נוצר פעם אחת כשהתוכן משתנה,
        כל פריים רק מזיז את האלמנט ב-Canvas (ללא הקצאת זיכרון).
        """
        try:
            try:
                self._news_ticker_job = None
            except Exception:
                pass

            if not getattr(self, 'news_canvas', None):
                return

            canvas_w = self.news_canvas.winfo_width() or self.screen_width
            canvas_h = self.news_canvas.winfo_height() or int(40 * (self.screen_height / 1080))
            if canvas_w <= 0:
                canvas_w = self.screen_width
            if canvas_h <= 0:
                canvas_h = int(40 * (self.screen_height / 1080))

            text = getattr(self, 'news_text_full', "") or ""

            # בנייה מחדש כשהתוכן משתנה, או כשהרצועה נבנתה בגודל שגוי (1px בזמן init)
            need_rebuild = (text != getattr(self, 'news_current_text', ""))
            if not need_rebuild and text:
                old_strip_h = getattr(self, '_news_strip_h', 0) or 0
                if old_strip_h < 2 and canvas_h > 1:
                    need_rebuild = True
            if need_rebuild:
                self._rebuild_news_strip(canvas_w, canvas_h)

            if not text:
                # אין חדשות — לא ממשיכים אנימציה, נבדוק שוב בעוד שנייה
                try:
                    self._news_ticker_last_ts = float(time.time())
                except Exception:
                    self._news_ticker_last_ts = 0.0
                try:
                    self._news_ticker_job = self.root.after(1000, self.update_news_ticker)
                except Exception:
                    self._news_ticker_job = None
                return

            # הזזה — מהירות לפי הגדרות
            speed_setting = self._get_ticker_speed_setting()
            if speed_setting == 'very_fast':
                step = max(3, int(canvas_w / 320))
            elif speed_setting == 'fast':
                step = max(2, int(canvas_w / 480))
            else:  # normal
                step = max(1, int(canvas_w / 960))

            unit_w = max(1, int(getattr(self, 'news_unit_width', 1) or 1))
            self.news_scroll_x = (self.news_scroll_x - step) % unit_w

            # הזזת האלמנט הקיים ב-Canvas — אפס הקצאות זיכרון!
            if getattr(self, '_news_canvas_img_id', None) is not None:
                try:
                    self.news_canvas.coords(self._news_canvas_img_id, -self.news_scroll_x, 0)
                except Exception:
                    pass

            # קצב רענון
            if speed_setting == 'very_fast':
                refresh_ms = 15
            elif speed_setting == 'fast':
                refresh_ms = 20
            else:
                refresh_ms = 30

            try:
                self._news_ticker_last_ts = float(time.time())
            except Exception:
                self._news_ticker_last_ts = 0.0

            try:
                self._news_ticker_job = self.root.after(refresh_ms, self.update_news_ticker)
            except Exception:
                self._news_ticker_job = None
        except Exception as e:
            print(f"שגיאה בעדכון טיקר חדשות: {e}")
            try:
                self._news_ticker_job = self.root.after(300, self.update_news_ticker)
            except Exception:
                self._news_ticker_job = None

    def _news_ticker_watchdog(self):
        try:
            self._news_ticker_watchdog_job = None
        except Exception:
            pass

        try:
            last = float(getattr(self, '_news_ticker_last_ts', 0.0) or 0.0)
        except Exception:
            last = 0.0

        try:
            now = float(time.time())
        except Exception:
            now = 0.0

        try:
            # אם לא התעדכן יותר מ-6 שניות, נאתחל מחדש מצב ותזמון
            if last > 0 and now > 0 and (now - last) > 6.0:
                try:
                    self.news_current_text = ""
                    self.news_scroll_x = 0
                    self._news_strip_img = None
                    self._news_strip_w = 0
                    self._news_strip_h = 0
                except Exception:
                    pass
                try:
                    if getattr(self, '_news_ticker_job', None) is None:
                        self._news_ticker_job = self.root.after(200, self.update_news_ticker)
                except Exception:
                    self._news_ticker_job = None
        except Exception:
            pass

        try:
            self._news_ticker_watchdog_job = self.root.after(4000, self._news_ticker_watchdog)
        except Exception:
            self._news_ticker_watchdog_job = None

    def _ui_freeze_watchdog(self):
        """Watchdog: detects UI freeze and forces restart.
        A background thread sets _watchdog_ping_ts periodically.
        If the main thread can't process after() callbacks for >120s, the UI is frozen."""
        try:
            now = time.time()
            self._watchdog_main_ts = now  # main thread is alive if this runs
            last_bg = float(getattr(self, '_watchdog_bg_ts', 0) or 0)
            # Background thread updates _watchdog_bg_ts every 10s
            # If main thread hasn't run this callback in >120s, we're frozen
            # But we can only detect this FROM the main thread, so we use a
            # background thread that checks if _watchdog_main_ts is stale
        except Exception:
            pass
        try:
            self.root.after(10000, self._ui_freeze_watchdog)
        except Exception:
            pass

    def _start_watchdog_thread(self):
        """Start background thread that monitors UI responsiveness."""
        import threading
        def _watchdog_loop():
            while True:
                try:
                    time.sleep(30)
                    last_main = float(getattr(self, '_watchdog_main_ts', 0) or 0)
                    now = time.time()
                    if last_main > 0 and (now - last_main) > 120:
                        # UI frozen for >120 seconds - force restart
                        print(f"[WATCHDOG] UI frozen for {now - last_main:.0f}s - forcing restart!")
                        try:
                            os.execv(sys.executable, [sys.executable] + sys.argv)
                        except Exception:
                            os._exit(99)  # Last resort
                except Exception:
                    pass
        t = threading.Thread(target=_watchdog_loop, daemon=True)
        t.start()

    def _periodic_gc(self):
        """Periodic garbage collection to prevent memory accumulation over long runs."""
        try:
            import gc
            gc.collect()
        except Exception:
            pass
        try:
            self.root.after(300000, self._periodic_gc)  # every 5 minutes
        except Exception:
            pass

    def refresh_news_items_loop(self):
        """ריענון רשימת החדשות (לשינויים מעמדת הניהול)."""
        try:
            self.load_news_items()
        except Exception:
            pass
        self.root.after(30000, self.refresh_news_items_loop)

    def update_background_slideshow(self):
        """עדכון תמונת הרקע במצב מצגת (אם הוגדר)"""
        try:
            if not getattr(self, 'bg_files', None):
                return
            mode = getattr(self, 'slideshow_mode', 'single')

            if mode == 'single':
                # מצגת רגילה - תמונה אחת בכל פעם
                path = self.bg_files[self.bg_index % len(self.bg_files)]
                self.bg_index = (self.bg_index + 1) % len(self.bg_files)
                if os.path.exists(path):
                    img = Image.open(path)
                    # כיבוד כיוון התמונה לפי EXIF (כמו בצפייה רגילה בקבצים)
                    try:
                        img = ImageOps.exif_transpose(img)
                    except Exception:
                        pass
                    img = self._prepare_background_image(img)
                    # שמירת תמונת בסיס לשימוש בתבנית הגרפית (template1)
                    self.bg_base_image = img
                    # שחרור PhotoImage ישן לפני יצירת חדש — מונע דליפת זיכרון
                    old_bg = getattr(self, 'bg_image', None)
                    if getattr(self, 'background_template', None) == 'template1':
                        # במצב template1 נצייר את הכיתוב על כל שקופית באותו סגנון
                        try:
                            has_student = False
                            if hasattr(self, 'name_label') and hasattr(self, 'points_label'):
                                has_student = bool(self.name_label.cget('text') or self.points_label.cget('text'))
                        except Exception:
                            has_student = False

                        try:
                            if has_student:
                                self._render_template1_overlay_from_widgets()
                            else:
                                always_text = getattr(self, 'always_messages_text', "")
                                self._render_static_overlay_template1(always_text)
                        except Exception:
                            # במקרה של כשל נציג לפחות את התמונה הבסיסית
                            self.bg_image = ImageTk.PhotoImage(img)
                            if getattr(self, 'bg_label', None):
                                self.bg_label.config(image=self.bg_image)
                    else:
                        self.bg_image = ImageTk.PhotoImage(img)
                        if getattr(self, 'bg_label', None):
                            self.bg_label.config(image=self.bg_image)
                    del old_bg
            elif mode in ('grid_static', 'grid_dynamic'):
                # מונטאז' ריבועים - סטטי או מתחלף
                self._render_montage_background(static=(mode == 'grid_static'))
                if mode == 'grid_static':
                    return

            # עדכון מחודש לפי זמן שהוגדר (למעט מונטאז' סטטי)
            interval = getattr(self, 'bg_interval_ms', 15000)
            self.root.after(interval, self.update_background_slideshow)
        except Exception as e:
            print(f"שגיאה בעדכון מצגת רקע: {e}")
            # תמיד תזמן מחדש גם אחרי שגיאה
            try:
                interval = getattr(self, 'bg_interval_ms', 15000)
                self.root.after(interval, self.update_background_slideshow)
            except Exception:
                pass

    def _render_montage_background(self, static: bool = False):
        """בניית תמונת רקע מונטאז' (Grid) על כל המסך מתוך bg_files."""
        try:
            files = getattr(self, 'bg_files', None)
            if not files:
                return

            screen_w, screen_h = self.screen_width, self.screen_height
            cols = max(1, getattr(self, 'slideshow_grid_cols', 4))
            if cols > 10:
                cols = 10

            # גובה אזור המונטאז' בפועל – לפי גובה חלון השורש פחות רצועת החדשות התחתונה.
            try:
                root_h = self.root.winfo_height() or screen_h
            except Exception:
                root_h = screen_h

            news_h = 0
            if hasattr(self, 'news_frame'):
                try:
                    news_h = self.news_frame.winfo_height() or 0
                except Exception:
                    news_h = 0
            if news_h <= 0:
                news_h = int(40 * (root_h / 1080))

            # נוסיף גם מרווח קטן מעל רצועת החדשות כדי שלא תהיה חפיפה.
            margin_h = max(2, int(4 * (root_h / 1080)))
            available_h = max(1, root_h - news_h - margin_h)

            # גודל ריבוע לפי רוחב המסך ומספר העמודות
            cell_size = max(1, screen_w // cols)
            # מספר שורות מירבי שיכול להיכנס בגובה הזמין, כאשר כל ריבוע נכנס בשלמותו
            rows = max(1, available_h // cell_size)

            bg_color = self.root_bg_color or '#000000'
            montage = Image.new('RGB', (screen_w, screen_h), bg_color)

            index = self.bg_index if hasattr(self, 'bg_index') else 0
            total = len(files)
            if total == 0:
                return

            for row in range(rows):
                for col in range(cols):
                    path = files[index % total]
                    index += 1
                    if not os.path.exists(path):
                        continue
                    try:
                        img = Image.open(path)
                        # כיבוד כיוון התמונה לפי EXIF (כמו בצפייה רגילה בקבצים)
                        try:
                            img = ImageOps.exif_transpose(img)
                        except Exception:
                            pass

                        if img.mode not in ('RGB', 'RGBA'):
                            img = img.convert('RGB')

                        # התאמת התמונה לגודל ריבוע cell_size×cell_size בהתאם ל-background_layout.
                        layout = getattr(self, 'bg_layout', 'cover')
                        if layout in ('contain', 'center', 'tile'):
                            layout = 'cover'

                        if layout in ('stretch',):
                            # מתיחה לא אחידה – ממלאת את כל הריבוע ללא שוליים (עלולה לעוות מעט).
                            img_resized = img.resize((cell_size, cell_size), Image.Resampling.LANCZOS)
                            tile = img_resized
                        elif layout in ('cover',):
                            # כיסוי מלא של הריבוע תוך שמירת יחס – עלול לחתוך מעט מהקצוות, בלי פסים שחורים.
                            scale_ratio = max(cell_size / max(1, img.width), cell_size / max(1, img.height))
                            new_w = max(1, int(img.width * scale_ratio))
                            new_h = max(1, int(img.height * scale_ratio))
                            img_resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

                            # חיתוך מרכזי לריבוע מדויק בגודל cell_size×cell_size
                            left = max(0, (new_w - cell_size) // 2)
                            top = max(0, (new_h - cell_size) // 2)
                            right = left + cell_size
                            bottom = top + cell_size
                            if right > new_w:
                                right = new_w
                                left = max(0, right - cell_size)
                            if bottom > new_h:
                                bottom = new_h
                                top = max(0, bottom - cell_size)
                            tile = img_resized.crop((left, top, right, bottom))
                        else:
                            # contain / center / tile / ברירת מחדל – התמונה כולה נכנסת לריבוע, עם שוליים במידת הצורך.
                            scale_ratio = min(cell_size / max(1, img.width), cell_size / max(1, img.height))
                            new_w = max(1, int(img.width * scale_ratio))
                            new_h = max(1, int(img.height * scale_ratio))
                            img_resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

                            # יצירת ריבוע רקע ובו נמרכז את התמונה המוקטנת
                            tile = Image.new('RGB', (cell_size, cell_size), bg_color)
                            offset_x = max(0, (cell_size - new_w) // 2)
                            offset_y = max(0, (cell_size - new_h) // 2)
                            tile.paste(img_resized, (offset_x, offset_y))

                        x0 = col * cell_size
                        y0 = row * cell_size

                        # לא נצייר אריחים שמתחת לאזור המונטאז' – שם יושבת רצועת החדשות
                        if x0 >= screen_w or (y0 + cell_size) > available_h:
                            continue

                        montage.paste(tile, (x0, y0))
                    except Exception as e:
                        print(f"שגיאה בבניית מונטאז': {e}")
                        continue

            # עדכון אינדקס בסיסי להמשך רצף התמונות
            self.bg_index = index % total

            # שמירת תמונת בסיס למונטאז' לציור overlay של template1
            self.bg_base_image = montage
            if getattr(self, 'background_template', None) == 'template1':
                try:
                    has_student = False
                    if hasattr(self, 'name_label') and hasattr(self, 'points_label'):
                        has_student = bool(self.name_label.cget('text') or self.points_label.cget('text'))
                except Exception:
                    has_student = False

                try:
                    if has_student:
                        self._render_template1_overlay_from_widgets()
                    else:
                        always_text = getattr(self, 'always_messages_text', "")
                        self._render_static_overlay_template1(always_text)
                except Exception:
                    self.bg_image = ImageTk.PhotoImage(montage)
                    if getattr(self, 'bg_label', None):
                        self.bg_label.config(image=self.bg_image)
            else:
                self.bg_image = ImageTk.PhotoImage(montage)
                if getattr(self, 'bg_label', None):
                    self.bg_label.config(image=self.bg_image)
        except Exception as e:
            print(f"שגיאה כללית בבניית מונטאז': {e}")

    def _prepare_background_image(self, img: Image.Image) -> Image.Image:
        """התאמת תמונת רקע לפי מצב הפריסה (background_layout)."""
        layout = getattr(self, 'bg_layout', 'cover')
        screen_w, screen_h = self.screen_width, self.screen_height

        # הבטחת מצב RGB
        if img.mode not in ('RGB', 'RGBA'):
            img = img.convert('RGB')

        if layout in ('stretch',):
            # מתיחה מלאה למסך
            return img.resize((screen_w, screen_h), Image.Resampling.LANCZOS)

        if layout in ('center',):
            # מרכזי בלי שינוי גודל - רקע מסך בצבע הרקע
            bg = Image.new('RGB', (screen_w, screen_h), self.root_bg_color or '#000000')
            x = (screen_w - img.width) // 2
            y = (screen_h - img.height) // 2
            bg.paste(img, (x, y))
            return bg

        if layout in ('tile',):
            # אריחים
            bg = Image.new('RGB', (screen_w, screen_h), self.root_bg_color or '#000000')
            for x in range(0, screen_w, img.width):
                for y in range(0, screen_h, img.height):
                    bg.paste(img, (x, y))
            return bg

        try:
            if int(screen_w) <= 0 or int(screen_h) <= 0:
                return img
        except Exception:
            return img

        if layout == 'contain':
            try:
                img_resized = ImageOps.contain(img, (int(screen_w), int(screen_h)), method=Image.Resampling.LANCZOS)
            except Exception:
                img_resized = img

            bg = Image.new('RGB', (int(screen_w), int(screen_h)), self.root_bg_color or '#000000')
            x = (int(screen_w) - int(img_resized.width)) // 2
            y = (int(screen_h) - int(img_resized.height)) // 2
            bg.paste(img_resized, (x, y))
            return bg

        try:
            return ImageOps.fit(
                img,
                (int(screen_w), int(screen_h)),
                method=Image.Resampling.LANCZOS,
                centering=(0.5, 0.5),
            )
        except Exception:
            return img.resize((int(screen_w), int(screen_h)), Image.Resampling.LANCZOS)
    
    def _update_bg_label(self, img: Image.Image) -> None:
        """עדכון תווית הרקע מתמונת PIL נתונה (שימושי במיוחד עבור template1)."""
        try:
            if img is None:
                return
            # אם יש לוגו כללי כ-PIL ולא עובדים במצב template1 – נצייר אותו על גבי הרקע, עם שקיפות מלאה
            try:
                if getattr(self, 'background_template', None) != 'template1':
                    logo = getattr(self, 'logo_image_pil', None)
                    logo_top = getattr(self, 'logo_top_pos', None)
                    if logo is not None and logo_top is not None:
                        img_w, img_h = img.size
                        lw, lh = logo.size
                        x = (img_w - lw) // 2
                        y = int(logo_top)
                        # וידוא פורמט עם אלפא
                        if logo.mode not in ('RGBA', 'LA'):
                            logo = logo.convert('RGBA')
                        # כאשר יש אלפא – נשתמש בלוגו כמסיכת שקיפות
                        img.paste(logo, (x, y), logo)
            except Exception:
                pass

            # המרה ל-PhotoImage ושמירת רפרנס למניעת איסוף זבל
            self.bg_image = ImageTk.PhotoImage(img)

            if getattr(self, 'bg_label', None) is None:
                # תווית רקע המכסה את כל החלון ונמצאת בשכבה התחתונה
                self.bg_label = tk.Label(self.root, bg=self.root_bg_color or '#000000')
                self.bg_label.place(x=0, y=0, relwidth=1, relheight=1)
                self.bg_label.lower()

            self.bg_label.config(image=self.bg_image)
        except Exception as e:
            print(f"שגיאה בעדכון תווית רקע: {e}")
    
    def _compose_template1_image(
        self,
        always_text: str = "",
        name_text: str = "",
        class_text: str = "",
        id_text: str = "",
        points_str: str = "",
        points_label: str = "",
        left_messages: str = "",
        stats_text: str = "",
        photo_img=None,
        points_color=None,
        points_label_color=None,
    ):
        """בניית תמונת template1 מלאה (טקסטים קבועים + פרטי תלמיד אופציונליים)."""
        base = getattr(self, 'bg_base_image', None)
        if base is None:
            # אם משום מה אין תמונת בסיס (למשל במצב צבע אחיד), ניצור אחת בצבע רקע החלון
            screen_w, screen_h = self.screen_width, self.screen_height
            bg_color = self.root_bg_color or '#000000'
            try:
                base = Image.new('RGB', (screen_w, screen_h), bg_color)
                self.bg_base_image = base
            except Exception:
                return None

        # עבודה על עותק כדי לשמור על תמונת הבסיס נקייה
        img = base.copy()
        img_w, img_h = img.size
        draw = ImageDraw.Draw(img)

        orientation = getattr(self, 'screen_orientation', 'landscape')

        # ציור לוגו template1 (אם קיים) ישירות על הרקע, עם שקיפות מלאה
        logo_img = getattr(self, 'template1_logo_original', None)
        logo_top = getattr(self, 'template1_logo_top', None)
        if logo_img is not None and logo_top is not None:
            try:
                logo = logo_img.copy()
                lw, lh = logo.size
                # מיקום הלוגו במרכז החלק העליון
                x = (img_w - lw) // 2
                y = int(logo_top)
                if logo.mode in ('RGBA', 'LA'):
                    img.paste(logo, (x, y), logo)
                else:
                    img.paste(logo, (x, y))
            except Exception:
                pass

        # פונקציה פנימית לטעינת פונט בגודל נתון
        def _load_font(size: int):
            """טעינת פונט עבור ציור על template1.

            עדיפות לפונט גרפי מקומי (למשל Gan CLM Bold) שמוגדר ב-__init__.
            אם אינו קיים או לא נטען – ננסה Arial, ואז ברירת מחדל של Pillow.
            """
            # 1. קובץ פונט מקומי (אם הוגדר ב-__init__)
            font_path = getattr(self, 'agas_ttf_path', None)
            if font_path:
                try:
                    return ImageFont.truetype(font_path, size)
                except Exception:
                    pass

            # 2. Arial מערכתית
            try:
                return ImageFont.truetype("arial.ttf", size)
            except Exception:
                # 3. ברירת מחדל – לעולם לא מפיל את הציור
                return ImageFont.load_default()

        # התאמת גדלי פונטים – מתבסס על פונטים שכבר חושבו למסך, עם חיזוק כדי שיתאימו למוקאפ
        title_size = max(42, int(self.font_title * 1.25))
        instr_size = max(24, int(self.font_instruction * 1.0))
        # הודעה כללית קבועה – גדולה ובולטת מאוד
        always_size = max(30, int(self.font_info * 1.35))
        # שם וכיתה – גדולים יותר
        center_name_size = max(36, int(self.font_name * 1.22))
        center_class_size = max(24, int(self.font_info * 1.15))
        # נקודות – ערך וטקסט
        points_num_size = max(70, int(self.font_points * 1.05) - 3)
        points_lbl_size = max(32, int(self.font_points_text * 1.20))
        # הודעות צד – משמעותית גדולים, סטטיסטיקות מעט קטנות יותר
        side_msg_size = max(30, int(self.font_info * 1.35))
        stats_size = max(22, int(self.font_info * 0.95))

        if orientation == 'portrait':
            # במסך לאורך הכותרת וההודעה הקבועה קטנות יותר, ושם התלמיד בולט הרבה יותר
            title_size = max(26, int(title_size * 0.72))
            always_size = max(22, int(always_size * 0.92))
            # שם תלמיד – קטן מעט ממספר הנקודות (≈80%) במצב אורך
            center_name_size = int(points_num_size * 0.8)
            center_class_size = int(center_class_size * 1.45)

        font_title_pil = _load_font(title_size)
        font_instr_pil = _load_font(instr_size)
        font_always_pil = _load_font(always_size)
        font_center_name = _load_font(center_name_size)
        font_center_class = _load_font(center_class_size)
        font_points_num = _load_font(points_num_size)
        font_points_lbl = _load_font(points_lbl_size)
        font_side_msg = _load_font(side_msg_size)
        font_stats = _load_font(stats_size)

        # צבעים לפי ערכת נושא (כהה/בהיר)
        theme = getattr(self, 'theme_name', 'dark') or 'dark'
        is_light_theme = (theme == 'light')

        if is_light_theme:
            col_title = (0, 0, 0)
            col_always = (0, 0, 0)
            col_name = (0, 0, 0)
            col_class = (40, 40, 40)
            col_id = (80, 80, 80)
            col_side = (0, 0, 0)
            col_stats = (0, 0, 0)
            col_points_num = (0, 160, 0)
            col_points_lbl = (0, 130, 0)
        else:
            col_title = (255, 255, 255)
            col_always = (255, 255, 255)
            col_name = (255, 255, 255)
            col_class = (230, 230, 230)
            col_id = (200, 200, 200)
            col_side = (255, 255, 255)
            col_stats = (224, 224, 224)
            col_points_num = (0, 255, 0)
            col_points_lbl = (0, 255, 0)

        # צבע קבוע להודעות "קיבלת בונוס" – זהב
        col_bonus = (255, 215, 0)

        # אם התקבלו צבעים דינמיים ללוח הנקודות – נשתמש בהם (מגיעים מ-Tk)
        if points_color:
            col_points_num = points_color
        if points_label_color:
            col_points_lbl = points_label_color

        # צבע מסגרת הטקסט (stroke): לבן על רקע בהיר, שחור על רקע כהה
        stroke_outline = (255, 255, 255) if is_light_theme else (0, 0, 0)

        # טקסטים בסיסיים
        campaign_name = getattr(self, 'app_config', {}).get('campaign_name', 'אשראיכם') if hasattr(self, 'app_config') else 'אשראיכם'
        title_text = f"ברוכים הבאים למבצע {campaign_name}"

        # פריסת טמפלייט לפי כיוון המסך – landscape מול portrait
        orientation = getattr(self, 'screen_orientation', 'landscape')

        if orientation == 'portrait':
            # מיקומים יחסיים למסך גבוה (כמו במוקאפ האנכי ששלחת)
            title_y_factor = 0.245

            # פורטרייט – תמונה גבוהה: נגדיל את המרווחים האנכיים כדי לשמור על איזון
            # הודעות כלליות (always_text) ימוקמו מתחת לכותרת, ברצועה נוחה לעין
            # הרמה של 2% למעלה
            always_y_factor = 0.30

            # שם וכיתה – הרמה של כ~20% למעלה במסך בפורטרייט
            name_y_factor = 0.35
            class_y_factor = 0.41

            # בלוק הנקודות – גרסת הפורטרייט שהעלתה אותו קצת כלפי מעלה
            points_base_y_factor = 0.475  # "יש לך" מעט למעלה
            points_val_y_factor = 0.515   # המספר מעט למטה
            # "נקודות שצברת" – הרמה של 2% נוספים למעלה
            points_lbl_y_factor = 0.57

            # הודעות שמאל – מיקום אנכי מכוייל לכל ארבע השורות (הוזז מעט ימינה)
            left_x_factor = 0.48
            left_first_center_factor = 0.48
            left_slot_gap_factor = 0.13

            # סטטיסטיקות – נשארות ימינה בפורטרייט
            stats_right_x_factor = 0.93
            stats_top_y_factor = 0.63

            # תמונת תלמיד – מעט שמאלה ובגובה ביניים בתוך המלבן
            photo_box_w_factor = 0.26
            photo_box_h_factor = 0.20
            photo_center_x_factor = 0.74
            # הורדה קלה של התמונה (≈2% מגובה המסך) כדי שתשב נמוך יותר בתוך הריבוע
            photo_center_y_factor = 0.805
        else:
            # פריסה קיימת למסך לרוחב
            title_y_factor = 0.33
            always_y_factor = 0.40
            name_y_factor = 0.55
            class_y_factor = 0.62
            points_base_y_factor = 0.74
            points_val_y_factor = 0.80
            # הורדה קלה של "נקודות שצברת" בלנדסקייפ
            points_lbl_y_factor = 0.88

            # הודעות שמאל במסך לרוחב – הוזזו מעט ימינה בהתאם לבקשה
            left_x_factor = 0.325
            left_first_center_factor = 0.56
            left_slot_gap_factor = 0.10

            stats_right_x_factor = 0.87
            stats_top_y_factor = 0.50

            photo_box_w_factor = 0.15
            photo_box_h_factor = 0.26
            photo_center_x_factor = 0.78
            photo_center_y_factor = 0.755

        # פונקציות עזר לטקסט – לציור על תמונה לא נשתמש ב-BIDI control (Pillow לא מטפל בזה היטב)
        def _clean_for_pil(text: str) -> str:
            if not text:
                return ""
            # הסרת סימוני RLE/RLM/PDF אם קיימים בטקסט שהוכן עבור Tkinter
            return text.replace(RLE, "").replace(PDF, "").replace(RLM, "")

        def _visual_rtl(text: str) -> str:
            """המרה חזותית פשוטה ל-RTL: שומרת מספרים בסדרם והופכת את רצפי האותיות, וכן מהפכת את סדר המילים.

            זו לא מימוש מלא של אלגוריתם BIDI, אבל מספיקה עבור טקסטי הממשק (ללא סימונים מורכבים).
            """
            t = _clean_for_pil(text)
            if not t:
                return ""

            # פיצול לטוקנים של "מספרים/סימני ניקוד" מול "אותיות" לפי isdigit
            tokens = []
            current = []
            current_is_num = None
            for ch in t:
                is_num = ch.isdigit() or ch in ",.:;+-/%"  # ספרות וסימני ניקוד שכיחים
                if current_is_num is None:
                    current_is_num = is_num
                    current.append(ch)
                elif is_num == current_is_num:
                    current.append(ch)
                else:
                    # סגירת טוקן קודם
                    token_str = ''.join(current)
                    if current_is_num:
                        tokens.append(token_str)  # מספרים נשמרים כמות שהם
                    else:
                        tokens.append(token_str[::-1])  # אותיות - הפיכת סדר
                    current = [ch]
                    current_is_num = is_num

            if current:
                token_str = ''.join(current)
                if current_is_num:
                    tokens.append(token_str)
                else:
                    tokens.append(token_str[::-1])

            # כעת נהפוך את סדר הטוקנים כדי לקבל RTL חזותי
            tokens.reverse()
            return ''.join(tokens)

        # פונקציית עזר למדידת טקסט – תואמת לגרסאות Pillow חדשות (textbbox) וישנות (getsize)
        def _measure_text(t: str, font) -> tuple:
            if not t:
                return 0, 0
            try:
                bbox = draw.textbbox((0, 0), t, font=font)
                return max(0, bbox[2] - bbox[0]), max(0, bbox[3] - bbox[1])
            except Exception:
                try:
                    return font.getsize(t)
                except Exception:
                    approx_h = getattr(font, 'size', 20)
                    return len(t) * approx_h // 2, approx_h

        # פונקציות עזר לציור טקסט
        def draw_centered(text: str, center_y: int, font, fill=(255, 255, 255), stroke_fill=(0, 0, 0), rtl: bool = True):
            if not text:
                return
            t = _visual_rtl(text) if rtl else _clean_for_pil(text)
            w, h = _measure_text(t, font)
            x = (img_w - w) // 2
            y = center_y - h // 2
            try:
                draw.text((x, y), t, font=font, fill=fill, stroke_width=2, stroke_fill=stroke_fill)
            except TypeError:
                draw.text((x, y), t, font=font, fill=fill)

        def draw_rtl_block(text: str, right_x: int, top_y: int, font, line_spacing: int, fill=(255, 255, 255), stroke_fill=(0, 0, 0)):
            if not text:
                return
            y = top_y
            for raw_line in str(text).splitlines():
                line = raw_line.strip()
                if not line:
                    y += line_spacing // 2
                    continue
                t = _visual_rtl(line)
                w, h = _measure_text(t, font)
                x = right_x - w
                try:
                    draw.text((x, y), t, font=font, fill=fill, stroke_width=2, stroke_fill=stroke_fill)
                except TypeError:
                    draw.text((x, y), t, font=font, fill=fill)
                y += line_spacing

        # 1. כותרת עליונה
        title_y = int(img_h * title_y_factor)  # מעט נמוך יותר מתחת ללוגו
        draw_centered(title_text, title_y, font_title_pil, fill=col_title, stroke_fill=stroke_outline)

        # 2. הודעות כלליות (ללא כרטיס) – רצועה בין הכותרת לבין כרטיס התלמיד
        if always_text:
            combined_always = "   |   ".join([ln.strip() for ln in str(always_text).splitlines() if ln.strip()])
            always_y = int(img_h * always_y_factor)
            draw_centered(combined_always, always_y, font_always_pil, fill=col_always, stroke_fill=stroke_outline)

        # 3. כרטיס תלמיד מרכזי (שם, כיתה, נקודות) – רק אם יש שם תלמיד
        if name_text:
            name_disp = name_text.strip()
            class_disp = class_text.strip() if class_text else ""
            id_disp = id_text.strip() if id_text else ""

            # שם וכיתה – מעט נמוך יותר
            name_y = int(img_h * name_y_factor)
            class_y = int(img_h * class_y_factor)

            # התאמת שם ארוך – מדידת רוחב. בלנדסקייפ נקטין במידת הצורך; בפורטרט נשמור על גודל קבוע.
            name_visual = _visual_rtl(name_disp)
            name_w, name_h = _measure_text(name_visual, font_center_name)
            # רוחב מקסימלי כדי שלא נעבור את גבולות הקפסולה
            if orientation == 'portrait':
                # במסך לאורך לא מקטינים את הפונט עבור שם ארוך – כל השמות באותו גודל גדול.
                name_max_w = int(img_w * 0.46)
            else:
                name_max_w = int(img_w * 0.22)
                # בלנדסקייפ בלבד נכווץ פונט אם השם חורג מהרוחב המרבי
                if name_w > name_max_w and name_w > 0:
                    scale = name_max_w / name_w
                    adj_size = max(22, int(center_name_size * scale))
                    font_center_name = _load_font(adj_size)
                    name_visual = _visual_rtl(name_disp)
                    name_w, name_h = _measure_text(name_visual, font_center_name)

            parts = name_disp.split()
            if orientation == 'portrait' or name_w <= name_max_w or len(parts) <= 1:
                draw_centered(name_disp, name_y, font_center_name, fill=col_name, stroke_fill=stroke_outline)
            else:
                first_line = " ".join(parts[:-1])
                second_line = parts[-1]
                base_small_size = int(center_name_size * 0.9)
                font_name_small = _load_font(base_small_size)
                # בלנדסקייפ בלבד: מרווח קטן יותר בין שתי השורות והורדה קלה של השורה העליונה,
                # כך שהשורה התחתונה כמעט לא זזה.
                line_gap = int(center_name_size * 0.19)

                first_vis = _visual_rtl(first_line)
                second_vis = _visual_rtl(second_line)
                w1, h1 = _measure_text(first_vis, font_name_small)
                w2, h2 = _measure_text(second_vis, font_name_small)

                # אם אחת השורות עדיין רחבה מדי – כווץ את הפונט פרופורציונלית עד ששתיהן ייכנסו
                max_line_w = max(w1, w2)
                if max_line_w > name_max_w and max_line_w > 0:
                    scale = name_max_w / max_line_w
                    adj_size = max(10, int(base_small_size * scale))
                    font_name_small = _load_font(adj_size)
                    w1, h1 = _measure_text(first_vis, font_name_small)
                    w2, h2 = _measure_text(second_vis, font_name_small)

                total_h = h1 + line_gap + h2
                # היסט כלפי מטה – מקרב את השורה העליונה לשורה התחתונה,
                # ומוריד עוד כ~1% מגובה המסך ביחס לגרסה הקודמת.
                name_two_line_offset = int(center_name_size * 0.08) + int(img_h * 0.01)
                y_start = name_y - total_h // 2 + name_two_line_offset

                x1 = (img_w - w1) // 2
                x2 = (img_w - w2) // 2
                try:
                    draw.text((x1, y_start), first_vis, font=font_name_small, fill=col_name, stroke_width=2, stroke_fill=stroke_outline)
                except TypeError:
                    draw.text((x1, y_start), first_vis, font=font_name_small, fill=col_name)
                try:
                    draw.text((x2, y_start + h1 + line_gap), second_vis, font=font_name_small, fill=col_name, stroke_width=2, stroke_fill=stroke_outline)
                except TypeError:
                    draw.text((x2, y_start + h1 + line_gap), second_vis, font=font_name_small, fill=col_name)

            if class_disp:
                draw_centered(class_disp, class_y, font_center_class, fill=col_class, stroke_fill=stroke_outline)
            if id_disp:
                id_y = class_y + int(center_class_size * 1.2)
                draw_centered(id_disp, id_y, font_center_class, fill=col_id, stroke_fill=stroke_outline)

            # בלוק הנקודות – "יש לך", הערך, וטקסט הנקודות
            # הסרת כוכבים סביב הטקסט (⭐) כדי שלא יופיעו כריבועים בפונט הגרפי
            if points_label:
                points_label = points_label.replace("⭐", "").strip()
            label_line = points_label or "נקודות שצברת"
            if points_str:
                y_top = int(img_h * points_base_y_factor)
                y_mid = int(img_h * points_val_y_factor)
                y_bottom = int(img_h * points_lbl_y_factor)

                # שורה ראשונה – טקסט קבוע "יש לך". נשתמש ב-python-bidi (visual_rtl_simple)
                # כדי לייצר מחרוזת חזותית נכונה עבור Pillow, ואז נצייר בלי המרת RTL פנימית.
                raw_small = "יש לך"
                if BIDI_AVAILABLE:
                    try:
                        small_text = visual_rtl_simple(raw_small)
                    except Exception:
                        small_text = _clean_for_pil(raw_small)
                else:
                    small_text = _clean_for_pil(raw_small)

                coins_cfg = getattr(self, 'coins_config', None) or []
                # רשימת סמלים לציור: כל פריט הוא (צבע, kind) כאשר kind הוא 'coin' או 'diamond'
                coins_to_draw = []
                remaining_points = 0
                total_points_int = None
                try:
                    total_points_int = int(str(points_str))
                except Exception:
                    total_points_int = None
                if coins_cfg and total_points_int is not None and total_points_int > 0:
                    remaining = total_points_int
                    for coin in coins_cfg:
                        try:
                            value = int(coin.get('value', 0))
                        except Exception:
                            continue
                        if value <= 0:
                            continue
                        count = remaining // value
                        if count <= 0:
                            continue
                        remaining -= count * value
                        color = _hex_to_rgb(coin.get('color'))
                        kind = coin.get('kind') or 'coin'
                        for _ in range(count):
                            coins_to_draw.append((color, kind))
                    if coins_to_draw:
                        remaining_points = remaining

                # שורה ראשונה – "יש לך" (ללא המרת RTL נוספת בתוך draw_centered)
                draw_centered(small_text, y_top, font_points_lbl, fill=col_side, stroke_fill=stroke_outline, rtl=False)

                # קביעת הערך לשורה השנייה
                if coins_to_draw:
                    plus_value = remaining_points
                else:
                    try:
                        plus_value = int(str(points_str))
                    except Exception:
                        plus_value = 0

                # שורה שנייה – "+<מספר>" ללא רווח, ולאחריו מטבעות (אם קיימים), ללא המילה "נקודות"
                second_text = f"+{plus_value}"
                second_vis = _clean_for_pil(second_text)

                # נשתמש בגודל פונט דינמי לשורה כדי שלא תחרוג לרוחב מחוץ לקפסולה (הפסים הימני והשמאלי).
                # הרוחב המקסימלי יוגבל לרוחב הקפסולה – אותו רוחב כמו שם התלמיד – כך שגם עם 3 מטבעות
                # השורה לא תיגע או תחרוג מהפסים, ובמקרה של יותר מטבעות הפונט יוקטן בהתאם.
                font_points_num_line = font_points_num
                size_points_num_line = points_num_size

                coin_icon = "\U0001F7E0"     # מטבע רגיל
                diamond_icon = "\U0001F7E1"  # יהלום
                w_second, h_second = _measure_text(second_vis, font_points_num_line)
                w_coin, h_coin = _measure_text(coin_icon, font_points_num_line)
                w_diamond, h_diamond = _measure_text(diamond_icon, font_points_num_line)
                icon_h = max(h_coin, h_diamond)
                gap_coin = max(1, int(size_points_num_line * 0.02))

                coins_width = 0
                if coins_to_draw:
                    coins_width = (
                        sum(w_diamond if kind == 'diamond' else w_coin for _, kind in coins_to_draw)
                        + max(0, len(coins_to_draw) - 1) * gap_coin
                    )

                if coins_to_draw:
                    total_w = w_second + gap_coin + coins_width
                else:
                    total_w = w_second

                # רוחב מקסימלי – רוחב הקפסולה (כמו עבור שם התלמיד), כדי לא לחרוג משני הפסים.
                if orientation == 'portrait':
                    max_width = int(img_w * 0.46)
                else:
                    max_width = int(img_w * 0.22)

                if total_w > max_width and total_w > 0:
                    scale = max_width / float(total_w)
                    # לא נרד מתחת לכ~50% מגודל הפונט המקורי כדי לשמור על קריאות
                    min_size = max(28, int(points_num_size * 0.50))
                    new_size = max(min_size, int(size_points_num_line * scale))
                    if new_size < size_points_num_line:
                        size_points_num_line = new_size
                        font_points_num_line = _load_font(size_points_num_line)
                        w_second, h_second = _measure_text(second_vis, font_points_num_line)
                        w_coin, h_coin = _measure_text(coin_icon, font_points_num_line)
                        w_diamond, h_diamond = _measure_text(diamond_icon, font_points_num_line)
                        icon_h = max(h_coin, h_diamond)
                        gap_coin = max(1, int(size_points_num_line * 0.02))
                        coins_width = 0
                        if coins_to_draw:
                            coins_width = (
                                sum(w_diamond if kind == 'diamond' else w_coin for _, kind in coins_to_draw)
                                + max(0, len(coins_to_draw) - 1) * gap_coin
                            )
                        if coins_to_draw:
                            total_w = w_second + gap_coin + coins_width
                        else:
                            total_w = w_second

                if coins_to_draw:
                    x_start = (img_w - total_w) // 2

                    # קודם טקסט "+<מספר>"
                    x_second = x_start
                    y_second = y_mid - h_second // 2
                    draw.text((x_second, y_second), second_vis, font=font_points_num_line, fill=col_points_num)

                    # אחריו – המטבעות
                    x_coins = x_second + w_second + gap_coin
                    y_coins = y_mid - icon_h // 2
                    for color, kind in reversed(coins_to_draw):
                        glyph = diamond_icon if kind == 'diamond' else coin_icon
                        draw.text((x_coins, y_coins), glyph, font=font_points_num_line, fill=color)
                        advance = w_diamond if kind == 'diamond' else w_coin
                        x_coins += advance + gap_coin
                else:
                    # ללא מטבעות – רק "+<מספר>" ממורכז
                    x_second = (img_w - w_second) // 2
                    y_second = y_mid - h_second // 2
                    draw.text((x_second, y_second), second_vis, font=font_points_num_line, fill=col_points_num)

                # שורה שלישית – "נקודות שצברת" (או טקסט מותאם) – מיקום מוחלט לפי יחס גובה בלבד
                label_y = int(img_h * points_lbl_y_factor)
                draw_centered(label_line, label_y, font_points_lbl, fill=col_points_lbl, stroke_fill=stroke_outline)

                # פס יעד (Goals) – ב-template1 מצויר ישירות על התמונה
                try:
                    goal = getattr(self, 'goal_settings', None) or {}
                    if int(goal.get('enabled', 0) or 0) == 1:
                        target_pts = 0
                        try:
                            target_pts = int(self._compute_goal_target_points() or 0)
                        except Exception:
                            target_pts = 0
                        cur_pts = 0
                        try:
                            cur_pts = int(str(points_str))
                        except Exception:
                            cur_pts = 0
                        if target_pts > 0 and cur_pts >= 0:
                            progress = cur_pts / float(target_pts) if target_pts > 0 else 0.0
                            if progress < 0:
                                progress = 0.0
                            if progress > 1:
                                progress = 1.0

                            filled_rgb = _hex_to_rgb(goal.get('filled_color') or '#2ecc71')
                            empty_rgb = _hex_to_rgb(goal.get('empty_color') or '#ecf0f1')
                            border_rgb = _hex_to_rgb(goal.get('border_color') or '#2c3e50')
                            show_percent = int(goal.get('show_percent', 0) or 0) == 1

                            bar_w = max_width
                            bar_h = max(14, int(img_h * 0.018))
                            # מיקום: מתחת לקפסולת הכיתה (כמו בצילום היעד)
                            bar_y = class_y + int(center_class_size * 1.55)
                            bar_x0 = (img_w - bar_w) // 2
                            bar_y0 = bar_y - bar_h // 2
                            bar_x1 = bar_x0 + bar_w
                            bar_y1 = bar_y0 + bar_h

                            # רקע
                            draw.rectangle([bar_x0, bar_y0, bar_x1, bar_y1], fill=empty_rgb)
                            # מלא
                            fill_w = int(bar_w * progress)
                            if fill_w > 0:
                                draw.rectangle([bar_x1 - fill_w, bar_y0, bar_x1, bar_y1], fill=filled_rgb)
                            # מסגרת
                            draw.rectangle([bar_x0, bar_y0, bar_x1, bar_y1], outline=border_rgb, width=1)

                            if show_percent:
                                pct = int(round(progress * 100))
                                pct_text = _clean_for_pil(f"{pct}%")
                                pct_font = _load_font(max(10, int(points_lbl_size * 0.72)))
                                tw, th = _measure_text(pct_text, pct_font)
                                tx = (img_w - tw) // 2
                                ty = bar_y0 + (bar_h - th) // 2
                                try:
                                    draw.text((tx, ty), pct_text, font=pct_font, fill=border_rgb, stroke_width=1, stroke_fill=(0, 0, 0))
                                except TypeError:
                                    draw.text((tx, ty), pct_text, font=pct_font, fill=border_rgb)
                except Exception:
                    pass

        # 4. הודעות משמאל – רצועות קבועות, כל אחת עד 2 שורות שלא דוחפות זו את זו
        # עבור template1 אנו מצפים ש-left_messages תהיה רשימה באורך 4:
        #   0 – הודעת בונוס (אם יש), 1 – הודעה כללית, 2 – הודעה לפי ניקוד, 3 – הודעה פרטית.
        # אם התקבל טקסט בודד או רשימה חופשית – נהפוך לרשימה עד 4 פריטים לפי סדר נתון.
        if left_messages:
            left_right_x = int(img_w * left_x_factor)

            slots = [None, None, None, None]

            if isinstance(left_messages, (list, tuple)):
                # אם זו כבר רשימה – נעתיק עד 4 פריטים כפי שהם (כולל None)
                for i in range(min(4, len(left_messages))):
                    val = left_messages[i]
                    if val is not None:
                        s = str(val).strip()
                        slots[i] = s if s else None
            elif isinstance(left_messages, str):
                # מחרוזת רב-שורתית – נחלק לשורות עד 4 לפי הסדר
                lines = [ln.strip() for ln in str(left_messages).splitlines() if ln.strip()]
                for i in range(min(4, len(lines))):
                    slots[i] = lines[i]

            # לאחר הנרמול – אם כל החריצים ריקים, אין מה לצייר
            if any(slots):
                # נשתמש עד 3 רצועות שמאל רגילות + רצועה רביעית להודעה האישית (אם קיימת)
                if orientation == 'portrait':
                    # במצב אורך נגדיר ידנית את הגבהים לכל אחת מארבע הרצועות:
                    # 0 - רצועה עליונה (מיועדת לבונוס זמנים/מיוחד/מורה),
                    # 1 - הודעה כללית בהצגת כרטיס ("ברוכים הבאים"),
                    # 2 - הודעת ניקוד ("מהראשונים! אלוף"),
                    # 3 - הודעה אישית ("מתמיד") – הכי למטה.
                    # התאמה: הנמכת שורת הבונוס בכ~5% לגובה 0.66, שאר השורות נשארות קבועות.
                    slot_center_factors = [0.66, 0.71, 0.78, 0.85]
                    # שלושת החריצים הראשיים (בונוס / כללי / ניקוד)
                    main_slot_centers = [int(img_h * f) for f in slot_center_factors[:3]]
                    # חריץ רביעי קבוע להודעה האישית
                    private_slot_center = int(img_h * slot_center_factors[3])
                else:
                    first_center_y = int(img_h * left_first_center_factor)
                    slot_gap = int(img_h * left_slot_gap_factor)
                    main_slot_centers = [first_center_y + i * slot_gap for i in range(3)]
                    private_slot_center = first_center_y + 3 * slot_gap

                # פונטים נפרדים להודעה חד-שורתית מול הודעה דו-שורתית
                font_side_single = _load_font(side_msg_size)
                font_side_double = _load_font(int(side_msg_size * 0.9))
                line_gap = int(side_msg_size * 0.25)

                def _draw_left_slot(
                    text_block: str,
                    center_y: int,
                    is_time_bonus_already: bool = False,
                    fill_color=None,
                    two_line_offset: int = 0,
                ):
                    """ציור הודעה באחת מהרצועות השמאליות.

                    אם הטקסט ארוך (מעל ~20 תווים) וללא שובר שורה מפורש,
                    נחלק אותו אוטומטית לשתי שורות, נקטין מעט את הגופן
                    ונמקם את השורה העליונה כך שהשורה התחתונה לא תרד נמוך
                    יותר מהמיקום המקורי של שורה בודדת.
                    """

                    raw = _clean_for_pil(str(text_block))
                    if not raw.strip():
                        return

                    lines: list[str]
                    auto_wrapped = False

                    # שבירת שורה אוטומטית לטקסטים ארוכים ללא '\n'
                    if '\n' not in raw and len(raw) > 20:
                        auto_wrapped = True
                        text = raw.strip()
                        n = len(text)
                        split_pos = None
                        target = n // 2
                        # חיפוש רווח הקרוב לאמצע – קודם שמאלה ואז ימינה
                        for i in range(target, -1, -1):
                            if text[i].isspace():
                                split_pos = i
                                break
                        if split_pos is None:
                            for i in range(target + 1, n):
                                if text[i].isspace():
                                    split_pos = i
                                    break
                        if split_pos is None:
                            first_line = text[:20].rstrip()
                            second_line = text[20:].lstrip()
                        else:
                            first_line = text[:split_pos].rstrip()
                            second_line = text[split_pos + 1 :].lstrip()
                        lines = [ln for ln in (first_line, second_line) if ln]
                    else:
                        lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]

                    if not lines:
                        return

                    # צבע ברירת מחדל – צבע הצד, אלא אם הועבר fill_color ייעודי
                    fill = fill_color if fill_color is not None else col_side

                    if len(lines) == 1:
                        t = _visual_rtl(lines[0])
                        w, h = _measure_text(t, font_side_single)
                        x = left_right_x - w
                        y = center_y - h // 2
                        try:
                            draw.text((x, y), t, font=font_side_single, fill=fill, stroke_width=2, stroke_fill=stroke_outline)
                        except TypeError:
                            draw.text((x, y), t, font=font_side_single, fill=fill)
                    else:
                        first_raw = lines[0]
                        second_raw = lines[1]
                        first = _visual_rtl(first_raw)
                        second = _visual_rtl(second_raw)

                        # במצב שתי שורות – גופן מעט קטן יותר
                        font_two = font_side_double
                        w1, h1 = _measure_text(first, font_two)
                        w2, h2 = _measure_text(second, font_two)

                        # מיקום השורה התחתונה: נשמור אותה בערך באותו גובה
                        # שבו היתה שורה בודדת (לא תרד למטה יותר), עם היסט
                        # עדין לפי סוג החריץ (two_line_offset).
                        y_second = center_y - h2 // 2 + two_line_offset
                        if is_time_bonus_already:
                            # הודעות "כבר קיבלת את הבונוס..." יועלו כמעט בגובה שורה
                            y_second -= (h1 + line_gap)
                        y_first = y_second - (h1 + line_gap)

                        x1 = left_right_x - w1
                        x2 = left_right_x - w2
                        try:
                            draw.text((x1, y_first), first, font=font_two, fill=fill, stroke_width=2, stroke_fill=stroke_outline)
                        except TypeError:
                            draw.text((x1, y_first), first, font=font_two, fill=fill)
                        try:
                            draw.text((x2, y_second), second, font=font_two, fill=fill, stroke_width=2, stroke_fill=stroke_outline)
                        except TypeError:
                            draw.text((x2, y_second), second, font=font_two, fill=fill)

                # שליפת פריטים מכל אחד מארבעת החריצים
                bonus_item = slots[0]
                general_item = slots[1]
                points_item = slots[2]
                private_item = slots[3]

                if orientation == 'portrait':
                    # ציור כל אחד בחריץ הקבוע שלו: בונוס → חריץ 0, כללי → 1, ניקוד → 2, פרטי → 3
                    if bonus_item:
                        is_time_bonus_already = (
                            "כבר קיבלת" in bonus_item and (
                                "בונוס הזמנים היום" in bonus_item or
                                "הבונוס היום" in bonus_item or
                                "הבונוס המיוחד היום" in bonus_item
                            )
                        )
                        # זיהוי הודעת "קיבלת ... בונוס" (פעם ראשונה) – לצביעה בזהב
                        is_bonus_receive = (
                            "קיבלת" in bonus_item and
                            "כבר קיבלת" not in bonus_item and
                            "בונוס" in bonus_item
                        )
                        # זיהוי ספציפי של "קיבלת" בונוס מיוחד דו-שורתית, כדי ליישר
                        # אותה בדיוק לאותו גובה של "כבר קיבלת את הבונוס המיוחד היום".
                        is_special_receive_two_line = (
                            "בונוס מיוחד" in bonus_item and
                            "כבר קיבלת" not in bonus_item
                        )

                        bonus_center_y = main_slot_centers[0]
                        # בפורטרייט נרים הודעות "קיבלת ... בונוס" חד-שורתיות (מורה/זמנים)
                        # בכ~2% מגובה המסך. לבונוס מיוחד דו-שורתית נשמור את המרכז המקורי,
                        # כדי שתתיישר בדיוק כמו הודעת "כבר קיבלת את הבונוס המיוחד היום".
                        if is_bonus_receive and not is_special_receive_two_line:
                            bonus_center_y = int(bonus_center_y - img_h * 0.02)

                        _draw_left_slot(
                            bonus_item,
                            bonus_center_y,
                            # עבור בונוס מיוחד דו-שורתית נתייחס כמו ל"כבר קיבלת" לצורך ההזזה האנכית
                            is_time_bonus_already=(is_time_bonus_already or is_special_receive_two_line),
                            fill_color=col_bonus if is_bonus_receive else None,
                            two_line_offset=10,
                        )

                    if general_item:
                        _draw_left_slot(general_item, main_slot_centers[1], two_line_offset=10)

                    if points_item:
                        _draw_left_slot(points_item, main_slot_centers[2], two_line_offset=7)

                    if private_item:
                        _draw_left_slot(private_item, private_slot_center, two_line_offset=6)
                else:
                    # במצבים שאינם פורטרייט – שלושת החריצים הראשיים יישארו קבועים
                    if bonus_item:
                        is_bonus_receive = (
                            "קיבלת" in bonus_item and
                            "כבר קיבלת" not in bonus_item and
                            "בונוס" in bonus_item
                        )
                        # גם הודעת "קיבלת ... בונוס" וגם "כבר קיבלת את הבונוס..." יתנהגו אותו דבר
                        # מבחינת יישור אנכי של שתי שורות – כדי שהן יופיעו בדיוק באותו גובה.
                        is_time_bonus_already = (
                            "כבר קיבלת" in bonus_item and (
                                "בונוס הזמנים היום" in bonus_item or
                                "הבונוס היום" in bonus_item or
                                "הבונוס המיוחד היום" in bonus_item
                            )
                        ) or is_bonus_receive
                        _draw_left_slot(
                            bonus_item,
                            main_slot_centers[0],
                            is_time_bonus_already=is_time_bonus_already,
                            fill_color=col_bonus if is_bonus_receive else None,
                            two_line_offset=30,
                        )

                    if general_item:
                        _draw_left_slot(general_item, main_slot_centers[1])

                    if points_item:
                        _draw_left_slot(points_item, main_slot_centers[2], two_line_offset=14)

                    if private_item:
                        _draw_left_slot(private_item, private_slot_center, two_line_offset=16)

        # 5. סטטיסטיקות בצד ימין (למעלה) – גבוהות יותר מעל התמונה
        if stats_text:
            stats_right_x = int(img_w * stats_right_x_factor)
            stats_top_y = int(img_h * stats_top_y_factor)
            line_spacing_stats = int(stats_size * 1.3)
            draw_rtl_block(stats_text, stats_right_x, stats_top_y, font_stats, line_spacing_stats, fill=col_stats, stroke_fill=stroke_outline)

        # 6. תמונת תלמיד בצד ימין (במרכז הריבוע הימני)
        if photo_img is not None:
            try:
                if photo_img.mode not in ('RGB', 'RGBA'):
                    photo_img = photo_img.convert('RGB')
            except Exception:
                pass

            # תמונה מעט קטנה יותר
            photo_box_w = int(img_w * photo_box_w_factor)
            photo_box_h = int(img_h * photo_box_h_factor)
            if photo_box_w > 0 and photo_box_h > 0 and photo_img.width > 0 and photo_img.height > 0:
                scale = min(photo_box_w / photo_img.width, photo_box_h / photo_img.height)
                new_w = max(1, int(photo_img.width * scale))
                new_h = max(1, int(photo_img.height * scale))
                thumb = photo_img.resize((new_w, new_h), Image.Resampling.LANCZOS)

                center_x = int(img_w * photo_center_x_factor)
                # מעט יותר למטה בתוך הריבוע
                center_y = int(img_h * photo_center_y_factor)
                x0 = center_x - new_w // 2
                y0 = center_y - new_h // 2
                img.paste(thumb, (x0, y0))

        return img

    def _render_static_overlay_template1(self, always_text: str = "") -> None:
        """ציור שכבת רקע סטטית (כותרת + הודעות קבועות) על template1."""
        try:
            text = always_text or getattr(self, 'always_messages_text', "")
            img = self._compose_template1_image(always_text=text)
            if img is not None:
                self._update_bg_label(img)
        except Exception as e:
            print(f"שגיאה בציור שכבת טקסט על template1: {e}")

    def _render_template1_overlay_from_widgets(self) -> None:
        """בניית תמונת template1 מלאה לפי הטקסטים שכבר חושבו בווידג'טים (שם, נקודות, הודעות, סטטיסטיקות ותמונה)."""
        try:
            always_text = getattr(self, 'always_messages_text', "")
            name_text = self.name_label.cget('text') if hasattr(self, 'name_label') else ""
            class_text = self.class_label.cget('text') if hasattr(self, 'class_label') else ""
            id_text = self.id_label.cget('text') if hasattr(self, 'id_label') else ""
            points_str = self.points_label.cget('text') if hasattr(self, 'points_label') else ""
            points_label = self.points_text_label.cget('text') if hasattr(self, 'points_text_label') else ""
            # צבעים דינמיים ללוח הנקודות – מגיעים מהגדרות הצבעים (color_ranges)
            points_color = None
            points_label_color = None
            try:
                if hasattr(self, 'points_label'):
                    points_color = self.points_label.cget('fg')
                if hasattr(self, 'points_text_label'):
                    points_label_color = self.points_text_label.cget('fg')
            except Exception:
                points_color = None
                points_label_color = None
            # עבור template1 נעדיף את הרשימה המעובדת של הודעות שמאל אם קיימת
            left_messages = getattr(self, 'left_messages_items', None)
            if left_messages is None:
                left_messages = self.message_label.cget('text') if hasattr(self, 'message_label') else ""
            stats_text = self.statistics_label.cget('text') if hasattr(self, 'statistics_label') else ""
            photo_img = getattr(self, 'template1_photo_original', None)

            img = self._compose_template1_image(
                always_text=always_text,
                name_text=name_text,
                class_text=class_text,
                id_text=id_text,
                points_str=points_str,
                points_label=points_label,
                left_messages=left_messages,
                stats_text=stats_text,
                photo_img=photo_img,
                points_color=points_color,
                points_label_color=points_label_color,
            )
            if img is not None:
                self._update_bg_label(img)
        except Exception as e:
            print(f"שגיאה בציור שכבת תלמיד על template1: {e}")
    
    def show_info(self):
        """הצגת אזור הפרטים"""
        # בתבנית template1 המידע נצבע ישירות על תמונת הרקע, ללא ריבוע info_frame
        if getattr(self, 'background_template', None) == 'template1':
            return
        fill_mode = getattr(self, '_panel_fill', tk.BOTH)
        expand_mode = getattr(self, '_panel_expand', True)
        self.info_frame.pack(pady=40, padx=50, fill=fill_mode, expand=expand_mode)
        self.instruction_label.config(text="")
    
    def hide_info(self):
        """הסתרת אזור הפרטים"""
        try:
            if hasattr(self, 'info_frame'):
                self.info_frame.pack_forget()
        except Exception:
            pass

        self.name_label.config(text="")
        self.class_label.config(text="")
        self.id_label.config(text="")
        self.points_label.config(text="")
        self.points_text_label.config(text="")
        self.message_label.config(text="")
        self.statistics_label.config(text="")
        try:
            if hasattr(self, 'goal_bar_canvas') and self.goal_bar_canvas is not None:
                self.goal_bar_canvas.pack_forget()
        except Exception:
            pass
        if hasattr(self, 'photo_label'):
            self.photo_label.config(image="", text="")
        self.current_photo_img = None
        self.template1_photo_original = None
        # במצב template1 ההנחיה והטקסטים הקבועים מצוירים ישירות על הרקע
        if getattr(self, 'background_template', None) != 'template1':
            self.instruction_label.config(text="⬇️ הצג את כרטיסך על הקורא ⬇️")
        else:
            try:
                always_text = getattr(self, 'always_messages_text', "")
                self._render_static_overlay_template1(always_text)
            except Exception:
                pass
    
    def show_error(self, card_number):
        """הצגת שגיאה כאשר כרטיס לא נמצא"""
        try:
            if hasattr(self, 'photo_label'):
                self.photo_label.config(image="", text="")
        except Exception:
            pass
        self.current_photo_img = None
        self.template1_photo_original = None
        self.name_label.config(text="❌ כרטיס לא נמצא", fg='#e74c3c')
        self.class_label.config(text="")
        self.id_label.config(text=f"מספר כרטיס: {card_number}")
        self.points_label.config(text="")
        self.points_text_label.config(text="פנה למזכירות לשיוך כרטיס", fg='#e74c3c')
        try:
            self._apply_sound_settings_from_config(self.load_app_config())
        except Exception:
            pass
        try:
            try:
                self.event_sounds = self.load_event_sounds()
            except Exception:
                pass
            key = str((getattr(self, 'event_sounds', {}) or {}).get('unknown_card') or '').strip()
            if key and self._play_sound_key(key):
                pass
            else:
                p = self._pick_random_from_sound_subfolder('כרטיס לא מזוהה')
                if not p:
                    p = self._pick_existing_file([
                        self._sound_path('נכשל.wav'),
                        self._sound_path('כרטיס לא מזוהה.wav'),
                    ])
                self._play_sound_file(p)
        except Exception:
            pass
        try:
            if hasattr(self, 'goal_bar_canvas') and self.goal_bar_canvas is not None:
                self.goal_bar_canvas.pack_forget()
        except Exception:
            pass
        # ניקוי הודעות וסטטיסטיקות קודמות כדי שלא יוצגו הודעות של התלמיד האחרון
        try:
            self.message_label.config(text="")
        except Exception:
            pass
        try:
            self.statistics_label.config(text="")
        except Exception:
            pass
        # ברשימת ההודעות לשמאל (template1) לא יוצגו הודעות תלמיד קודם
        self.left_messages_items = []
        # לא מוצגים טקסטי בונוס זמנים עבור כרטיס לא מוכר
        self.time_bonus_message = ""
        
        self.show_info()
        if getattr(self, 'background_template', None) == 'template1':
            try:
                self._render_template1_overlay_from_widgets()
            except Exception as e:
                print(f"שגיאה בציור הודעת שגיאה על template1: {e}")
        
        # איפוס התצוגה אחרי 10 שניות
        self._schedule_hide_info(10000, reset_name_color=True)
    
    def load_master_card(self):
        """טעינת כרטיס מאסטר מקובץ"""
        # 1. קובץ משותף בתיקיית הרשת (אם הוגדרה)
        try:
            cfg = self.load_app_config()
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

        # 2. קובץ "חי" בתיקיית הנתונים (אותה תיקייה של config.json החי)
        try:
            config_file = self._get_config_file_path()
            data_dir = os.path.dirname(config_file) or self.base_dir
            master_file = os.path.join(data_dir, 'master_card.txt')
            if os.path.exists(master_file):
                with open(master_file, 'r', encoding='utf-8') as f:
                    card = f.read().strip()
                    if card:
                        return card
        except Exception:
            pass

        # 3. נפילה חזרה לקובץ שבתיקיית ההתקנה (בעיקר בסביבת פיתוח)
        try:
            master_file = os.path.join(self.base_dir, 'master_card.txt')
            if os.path.exists(master_file):
                with open(master_file, 'r', encoding='utf-8') as f:
                    card = f.read().strip()
                    if card:
                        return card
        except Exception:
            pass

        # 4. ברירת מחדל אם אין קובץ
        return "9999"
    
    def _get_config_file_path(self) -> str:
        """החזרת נתיב קובץ ההגדרות ה"חי" מחוץ ל-Program Files במידת האפשר."""
        for env_name in ("LOCALAPPDATA", "APPDATA", "PROGRAMDATA"):
            root = os.environ.get(env_name)
            if not root or not os.path.isdir(root):
                continue
            try:
                cfg_dir = os.path.join(root, "SchoolPoints")
                os.makedirs(cfg_dir, exist_ok=True)
                _test = os.path.join(cfg_dir, '.write_test')
                with open(_test, 'w') as _f:
                    _f.write('ok')
                os.remove(_test)
                return os.path.join(cfg_dir, "config.json")
            except Exception:
                continue

        return os.path.join(self.base_dir, 'config.json')

    def load_app_config(self):
        """טעינת הגדרות יישום מקובץ הגדרות חיצוני, עם נפילה חזרה לקובץ המובנה."""
        # קאש קצר (5 שניות) — מונע 4-5 קריאות דיסק/רשת בכל תיקוף
        try:
            _cache = getattr(self, '_app_config_cache', None)
            if isinstance(_cache, dict) and _cache.get('cfg') is not None:
                if (time.time() - float(_cache.get('ts', 0))) < 5.0:
                    return _cache['cfg']
        except Exception:
            pass
        try:
            live_config = self._get_config_file_path()
            base_config = os.path.join(self.base_dir, 'config.json')

            # אם עדיין אין קובץ "חי" אבל יש קובץ ברירת-מחדל מותקן – ננסה להעתיקו
            if not os.path.exists(live_config) and os.path.exists(base_config):
                try:
                    shutil.copy2(base_config, live_config)
                except Exception:
                    pass

            # קריאת ההגדרות המקומיות (משמש גם לאיתור תיקיית הרשת)
            local_cfg = {}
            if os.path.exists(live_config):
                with open(live_config, 'r', encoding='utf-8') as f:
                    local_cfg = json.load(f)

            # אם מוגדרת תיקיית רשת משותפת – ננסה להשתמש בקובץ config.json משותף בתיקייה זו
            shared_folder = None
            if isinstance(local_cfg, dict):
                shared_folder = local_cfg.get('shared_folder') or local_cfg.get('network_root')

            def _is_dir_with_timeout(path, timeout=3.0):
                """os.path.isdir on a UNC path can block indefinitely if network is down. Run with timeout."""
                result = [False]
                def _check():
                    try:
                        result[0] = os.path.isdir(path)
                    except Exception:
                        result[0] = False
                t = threading.Thread(target=_check, daemon=True)
                t.start()
                t.join(timeout)
                return result[0]

            if shared_folder and _is_dir_with_timeout(shared_folder):
                shared_config_path = os.path.join(shared_folder, 'config.json')
                shared_cfg = None

                if os.path.exists(shared_config_path):
                    try:
                        with open(shared_config_path, 'r', encoding='utf-8') as f:
                            shared_cfg = json.load(f)
                    except Exception:
                        shared_cfg = None

                # אם אין קובץ משותף תקין – ניצור אחד על בסיס ההגדרות המקומיות
                if not isinstance(shared_cfg, dict):
                    shared_cfg = dict(local_cfg) if isinstance(local_cfg, dict) else {}
                    try:
                        os.makedirs(shared_folder, exist_ok=True)
                    except Exception:
                        pass
                    try:
                        with open(shared_config_path, 'w', encoding='utf-8') as f:
                            json.dump(shared_cfg, f, ensure_ascii=False, indent=4)
                    except Exception:
                        pass

                self._app_config_cache = {'cfg': shared_cfg, 'ts': time.time()}
                return shared_cfg

            # ללא תיקיית רשת – החזר את ההגדרות המקומיות או קובץ ברירת המחדל
            if local_cfg:
                self._app_config_cache = {'cfg': local_cfg, 'ts': time.time()}
                return local_cfg

            if os.path.exists(base_config):
                with open(base_config, 'r', encoding='utf-8') as f:
                    result = json.load(f)
                    self._app_config_cache = {'cfg': result, 'ts': time.time()}
                    return result
        except Exception as e:
            print(f"שגיאה בטעינת config.json: {e}")
        return {}

    def _maybe_start_sync_agent(self) -> None:
        try:
            if bool(getattr(self, '_sync_agent_started', False)):
                return
        except Exception:
            pass

        try:
            cfg = self.load_app_config() or {}
        except Exception:
            cfg = {}

        try:
            mode = str(cfg.get('deployment_mode') or 'local').strip().lower()
        except Exception:
            mode = 'local'
        sync_agent_mod = None
        try:
            import sync_agent
            sync_agent_mod = sync_agent
            local_sync_enabled = sync_agent._local_sync_enabled_from_cfg(cfg)
        except Exception:
            try:
                local_sync_enabled = str(cfg.get('local_sync_enabled') or '').strip().lower() in ('1', 'true', 'on', 'yes')
            except Exception:
                local_sync_enabled = False

        local_sync_url = ''
        if local_sync_enabled and sync_agent_mod is not None:
            try:
                local_sync_url = sync_agent_mod._local_sync_url_from_cfg(cfg)
            except Exception:
                local_sync_url = ''

        local_sync_role = ''
        try:
            local_sync_role = str(cfg.get('local_sync_role') or '').strip().lower()
        except Exception:
            local_sync_role = ''
        if not local_sync_role and local_sync_enabled and sync_agent_mod is not None:
            try:
                shared_folder = cfg.get('shared_folder') or cfg.get('network_root')
            except Exception:
                shared_folder = None
            try:
                host = sync_agent_mod._unc_host(str(shared_folder or '').strip())
                if host and sync_agent_mod._is_local_host(host):
                    local_sync_role = 'master'
                elif host:
                    local_sync_role = 'client'
            except Exception:
                pass

        if local_sync_enabled and not local_sync_url and mode not in ('hybrid', 'cloud'):
            return

        if mode == 'local' and local_sync_enabled and local_sync_role != 'client':
            return

        if mode not in ('hybrid', 'cloud') and not local_sync_enabled:
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

        if not local_sync_enabled:
            if not (tenant_id and api_key and push_url):
                return

        try:
            interval_sec = int(cfg.get('sync_interval_sec') or 15)
        except Exception:
            interval_sec = 15
        interval_sec = max(10, int(interval_sec or 15))

        def _run_sync_loop():
            try:
                _debug_log(f'sync_agent thread started, interval={interval_sec}')
                import sync_agent
                sync_agent.main_loop(interval_sec=interval_sec)
                _debug_log('sync_agent main_loop returned normally')
            except SystemExit as se:
                _debug_log(f'sync_agent SystemExit: {se}')
            except Exception as e:
                _debug_log(f'sync_agent exception: {type(e).__name__}: {e}')
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

    def _is_local_sync_server_running(self, port: int, validate_pull: bool = False) -> bool:
        try:
            url = f"http://127.0.0.1:{int(port)}/sync/status"
            req = urllib.request.Request(url, headers={'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=0.5) as resp:
                data = json.loads(resp.read().decode('utf-8', errors='ignore') or '{}')
                if not bool(data.get('ok')):
                    return False
        except Exception:
            return False
        if not validate_pull:
            return True
        # Validate server can actually serve pulls (not just status)
        try:
            cfg = self.load_app_config() or {}
            api_key = str(cfg.get('local_sync_key') or 'local').strip()
            url2 = f"http://127.0.0.1:{int(port)}/sync/pull?since_id=999999999&limit=1"
            req2 = urllib.request.Request(url2, headers={'Accept': 'application/json', 'api-key': api_key})
            with urllib.request.urlopen(req2, timeout=2) as resp2:
                data2 = json.loads(resp2.read().decode('utf-8', errors='ignore') or '{}')
                if data2.get('ok'):
                    return True
                else:
                    try:
                        print(f"[PUBLIC] Sync server pull validation FAILED: {data2}")
                    except Exception:
                        pass
                    return False
        except Exception as e:
            try:
                print(f"[PUBLIC] Sync server pull validation ERROR: {e}")
            except Exception:
                pass
            return False

    def _maybe_start_local_sync_server(self) -> None:
        try:
            print("[PUBLIC] _maybe_start_local_sync_server called")
        except Exception:
            pass
        try:
            if bool(getattr(self, '_local_sync_server_started', False)):
                # וידוא שהשרת באמת רץ (לא רק שהדגל מסומן)
                try:
                    port = int((self.load_app_config() or {}).get('local_sync_port') or 8765)
                except Exception:
                    port = 8765
                if self._is_local_sync_server_running(port, validate_pull=True):
                    try:
                        print(f"[PUBLIC] Sync server confirmed running on port {port}")
                    except Exception:
                        pass
                    return
                else:
                    try:
                        print(f"[PUBLIC] Sync server flag was set but server NOT responding on port {port}, retrying...")
                    except Exception:
                        pass
                    self._local_sync_server_started = False
        except Exception:
            pass

        try:
            cfg = self.load_app_config() or {}
        except Exception:
            cfg = {}

        try:
            import sync_agent
            local_sync_enabled = sync_agent._local_sync_enabled_from_cfg(cfg)
        except Exception:
            try:
                local_sync_enabled = str(cfg.get('local_sync_enabled') or '').strip().lower() in ('1', 'true', 'on', 'yes')
            except Exception:
                local_sync_enabled = False
        try:
            print(f"[PUBLIC] local_sync_enabled={local_sync_enabled}")
        except Exception:
            pass
        if not local_sync_enabled:
            return

        try:
            role = str(cfg.get('local_sync_role') or '').strip().lower()
        except Exception:
            role = ''

        if role and role != 'master':
            try:
                print(f"[PUBLIC] role={role}, not master, returning")
            except Exception:
                pass
            return

        try:
            shared_folder = cfg.get('shared_folder') or cfg.get('network_root')
        except Exception:
            shared_folder = None
        host = None
        try:
            import sync_agent
            host = sync_agent._unc_host(str(shared_folder or '').strip())
            try:
                is_local = sync_agent._is_local_host(host) if host else False
                print(f"[PUBLIC] shared_folder={shared_folder}, host={host}, is_local={is_local}, role={role}")
            except Exception:
                pass
            if role != 'master' and host and not sync_agent._is_local_host(host):
                try:
                    print("[PUBLIC] Host is not local, returning")
                except Exception:
                    pass
                return
        except Exception as e:
            try:
                print(f"[PUBLIC] host detection error: {e}")
            except Exception:
                pass
            host = None

        try:
            port = int(cfg.get('local_sync_port') or 8765)
        except Exception:
            port = 8765

        if self._is_local_sync_server_running(port, validate_pull=True):
            try:
                self._local_sync_server_started = True
                print(f"[PUBLIC] Sync server already running and healthy on port {port}")
            except Exception:
                pass
            return
        elif self._is_local_sync_server_running(port, validate_pull=False):
            try:
                print(f"[PUBLIC] Stale sync server detected on port {port} (status OK but pull FAILS) - sending reconnect")
            except Exception:
                pass
            try:
                reconnect_url = f"http://127.0.0.1:{int(port)}/sync/reconnect"
                req = urllib.request.Request(reconnect_url, headers={'Accept': 'application/json'})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read().decode('utf-8', errors='ignore') or '{}')
                    try:
                        print(f"[PUBLIC] Reconnect response: {data}")
                    except Exception:
                        pass
                    if data.get('ok'):
                        import time as _time
                        _time.sleep(0.5)
                        if self._is_local_sync_server_running(port, validate_pull=True):
                            try:
                                print("[PUBLIC] Sync server recovered after reconnect!")
                            except Exception:
                                pass
                            self._local_sync_server_started = True
                            return
                        else:
                            try:
                                print("[PUBLIC] Sync server still failing after reconnect")
                            except Exception:
                                pass
            except Exception as re_err:
                try:
                    print(f"[PUBLIC] Reconnect failed: {re_err}")
                except Exception:
                    pass

        try:
            api_key = str(cfg.get('local_sync_key') or 'local').strip()
        except Exception:
            api_key = 'local'
        try:
            tenant_id = str(cfg.get('local_sync_tenant_id') or 'local').strip()
        except Exception:
            tenant_id = 'local'

        db_path = None
        try:
            db_path = self.db.db_path if hasattr(self, 'db') else None
        except Exception:
            db_path = None
        try:
            print(f"[PUBLIC] Starting sync server: port={port}, db_path={db_path}")
        except Exception:
            pass

        try:
            import local_sync_server
            t = local_sync_server.start_in_thread(
                host='0.0.0.0',
                port=port,
                db_path=db_path,
                api_key=api_key,
                tenant_id=tenant_id
            )
            try:
                self._local_sync_server_thread = t
                self._local_sync_server_started = True
                print(f"[PUBLIC] Sync server started successfully on port {port}")
            except Exception:
                pass
        except Exception as e:
            try:
                print(f"[PUBLIC] ERROR starting sync server: {e}")
            except Exception:
                pass

    def save_app_config(self, config: dict) -> bool:
        """שמירת הגדרות יישום לקובץ הגדרות חיצוני במיקום כתיב."""
        try:
            # קודם כל – שמירה לקובץ המקומי (שמשמש גם לאיתור תיקיית הרשת)
            config_file = self._get_config_file_path()
            cfg_dir = os.path.dirname(config_file) or '.'
            try:
                os.makedirs(cfg_dir, exist_ok=True)
            except Exception:
                pass

            local_cfg = dict(config) if isinstance(config, dict) else {}
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(local_cfg, f, ensure_ascii=False, indent=4)

            # אם מוגדרת תיקיית רשת משותפת – נשמור גם קובץ config.json משותף בתיקייה זו
            shared_folder = None
            if isinstance(local_cfg, dict):
                shared_folder = local_cfg.get('shared_folder') or local_cfg.get('network_root')

            if shared_folder and os.path.isdir(shared_folder):
                shared_config_path = os.path.join(shared_folder, 'config.json')
                try:
                    os.makedirs(shared_folder, exist_ok=True)
                except Exception:
                    pass
                try:
                    with open(shared_config_path, 'w', encoding='utf-8') as f:
                        shared_cfg = dict(local_cfg) if isinstance(local_cfg, dict) else {}
                        try:
                            shared_cfg.pop('db_path', None)
                        except Exception:
                            pass
                        json.dump(shared_cfg, f, ensure_ascii=False, indent=4)
                except Exception:
                    # כשל בשמירת הקובץ המשותף לא צריך להפיל את האפליקציה
                    pass

            return True
        except Exception as e:
            print(f"שגיאה בשמירת config.json: {e}")
            return False

    def _seed_shared_sounds_folder(self, shared_folder: str) -> None:
        try:
            folder = str(shared_folder or '').strip()
            if not folder:
                return
            if not os.path.isdir(folder):
                return
            src_root = os.path.join(self.base_dir, 'sounds')
            dst_root = os.path.join(folder, 'sounds')
            try:
                os.makedirs(dst_root, exist_ok=True)
            except Exception:
                pass
            if not os.path.isdir(src_root):
                return
            for root, _, files in os.walk(src_root):
                rel = os.path.relpath(root, src_root)
                if rel == '.':
                    rel = ''
                dst_dir = os.path.join(dst_root, rel)
                try:
                    os.makedirs(dst_dir, exist_ok=True)
                except Exception:
                    pass
                for fn in (files or []):
                    try:
                        if not str(fn).lower().endswith(('.wav', '.mp3', '.ogg')):
                            continue
                        sp = os.path.join(root, fn)
                        dp = os.path.join(dst_dir, fn)
                        if os.path.exists(dp):
                            continue
                        try:
                            shutil.copy2(sp, dp)
                        except Exception:
                            pass
                    except Exception:
                        continue
        except Exception:
            return

    def _open_cloud_credentials_dialog(self, cfg: dict) -> bool:
        """Show a dialog to collect cloud sync credentials and write them into cfg. Returns True if saved."""
        result = {'ok': False}
        try:
            dlg = tk.Toplevel(self.root)
            dlg.title("הגדרות חיבור לענן")
            dlg.configure(bg='#1e2a38')
            dlg.resizable(False, False)
            dlg.grab_set()
            dlg.lift()
            dlg.focus_force()
            try:
                dlg.geometry("560x420")
            except Exception:
                pass

            def _lbl(parent, text, size=11, fg='#ecf0f1', bold=False):
                font = ('Arial', size, 'bold') if bold else ('Arial', size)
                tk.Label(parent, text=text, font=font, bg='#1e2a38', fg=fg).pack(anchor='e', padx=24, pady=(6, 0))

            def _entry(parent, default='', show=None):
                v = tk.StringVar(value=str(default or ''))
                kw = {'textvariable': v, 'font': ('Arial', 11), 'width': 42, 'relief': 'flat', 'bd': 4}
                if show:
                    kw['show'] = show
                e = tk.Entry(parent, **kw)
                e.pack(anchor='e', padx=24, pady=(2, 0))
                return v

            tk.Label(dlg, text="חיבור לחשבון ענן SchoolPoints",
                     font=('Arial', 14, 'bold'), bg='#1e2a38', fg='#3498db').pack(pady=(20, 4))
            tk.Label(dlg, text="הזן את פרטי החשבון מהמייל שקיבלת בעת ההרשמה.",
                     font=('Arial', 9), bg='#1e2a38', fg='#95a5a6').pack(pady=(0, 10))

            _lbl(dlg, "מזהה מוסד (Tenant ID):", bold=True)
            v_tid = _entry(dlg, cfg.get('sync_tenant_id') or '')

            _lbl(dlg, "מפתח API:", bold=True)
            v_api = _entry(dlg, cfg.get('sync_api_key') or '', show='*')

            _lbl(dlg, "כתובת שרת (ברירת מחדל: מלא אוטומטית):", fg='#95a5a6')
            v_url = _entry(dlg, cfg.get('sync_push_url') or 'https://schoolpoints.co.il/sync/push2')

            def _save():
                tid = v_tid.get().strip()
                key = v_api.get().strip()
                url = v_url.get().strip() or 'https://schoolpoints.co.il/sync/push2'
                if not tid or not key:
                    try:
                        messagebox.showwarning("שדות חסרים", "יש למלא Tenant ID ומפתח API.", parent=dlg)
                    except Exception:
                        pass
                    return
                cfg['sync_tenant_id'] = tid
                cfg['sync_api_key'] = key
                cfg['sync_push_url'] = url
                result['ok'] = True
                dlg.destroy()

            def _skip():
                dlg.destroy()

            btn_frame = tk.Frame(dlg, bg='#1e2a38')
            btn_frame.pack(pady=20)
            tk.Button(btn_frame, text="שמור וחבר", font=('Arial', 11, 'bold'),
                      bg='#2980b9', fg='white', relief='flat', padx=20, pady=6,
                      command=_save, cursor='hand2').pack(side=tk.RIGHT, padx=8)
            tk.Button(btn_frame, text="דלג (הגדר מאוחר יותר)", font=('Arial', 9),
                      bg='#7f8c8d', fg='white', relief='flat', padx=12, pady=4,
                      command=_skip, cursor='hand2').pack(side=tk.RIGHT, padx=4)

            self.root.wait_window(dlg)
        except Exception as e:
            _debug_log(f'_open_cloud_credentials_dialog error: {e}')
        return result['ok']

    def _open_deployment_wizard(self, cfg: dict) -> str:
        """
        wizard בחירת סוג התקנה ראשוני לעמדה הציבורית.
        מחזיר: 'local', 'hybrid' — או '' אם ביטל.
        נקרא רק בפעם הראשונה (אין deployment_mode ואין shared_folder).
        """
        result = {'mode': ''}
        try:
            dlg = tk.Toplevel(self.root)
            dlg.title("ברוכים הבאים — בחר סוג התקנה")
            dlg.configure(bg='#2c3e50')
            dlg.resizable(False, False)
            dlg.grab_set()
            dlg.lift()
            dlg.focus_force()
            try:
                dlg.geometry("660x400")
            except Exception:
                pass

            tk.Label(dlg, text="ברוכים הבאים לעמדה הציבורית",
                     font=('Arial', 16, 'bold'), bg='#2c3e50', fg='#ecf0f1').pack(pady=(28, 4))
            tk.Label(dlg, text="כיצד העמדה הציבורית מחוברת למסד הנתונים?",
                     font=('Arial', 11), bg='#2c3e50', fg='#bdc3c7').pack(pady=(0, 18))

            cards = tk.Frame(dlg, bg='#2c3e50')
            cards.pack(padx=30, fill=tk.X)

            def _card(parent, title, subtitle, color, cmd):
                c = tk.Frame(parent, bg=color, cursor='hand2')
                c.pack(side=tk.LEFT, expand=True, fill=tk.BOTH, padx=10, ipady=10)
                tk.Label(c, text=title, font=('Arial', 12, 'bold'), bg=color, fg='white').pack(pady=(12, 4))
                tk.Label(c, text=subtitle, font=('Arial', 9), bg=color, fg='#ecf0f1',
                         wraplength=210, justify='center').pack(padx=8, pady=(0, 8))
                tk.Button(c, text="בחר →", font=('Arial', 10, 'bold'),
                          bg='white', fg=color, relief='flat', padx=14, pady=5,
                          command=cmd, cursor='hand2').pack(pady=(4, 12))
                c.bind('<Button-1>', lambda _e: cmd())

            def _local():
                result['mode'] = 'local'
                dlg.destroy()

            def _cloud():
                result['mode'] = 'hybrid'
                dlg.destroy()

            _card(cards, "🏫  רשת מקומית",
                  "מחוברת לתיקייה משותפת ברשת הבית-ספרית.\nרגיל — ברוב ההתקנות.",
                  '#27ae60', _local)
            _card(cards, "🌐  מקוון / היברידי",
                  "מחוברת לחשבון ענן.\nנדרש חשבון מקוון פעיל.",
                  '#2980b9', _cloud)

            tk.Label(dlg, text="ניתן לשנות בהגדרות המערכת בכל עת.",
                     font=('Arial', 8), bg='#2c3e50', fg='#7f8c8d').pack(pady=(14, 0))
            tk.Button(dlg, text="ביטול", font=('Arial', 9), bg='#7f8c8d', fg='white',
                      relief='flat', padx=12, pady=3, command=dlg.destroy).pack(pady=(5, 0))

            self.root.wait_window(dlg)
        except Exception:
            pass
        return result['mode']

    # ------------------------------------------------------------------
    # Deployment wizard & cloud credentials dialog
    # ------------------------------------------------------------------

    def _open_deployment_wizard(self, cfg: dict) -> str:
        """Ask user: local-network or cloud? Returns 'local' / 'cloud' / ''."""
        result = {'mode': ''}
        dialog = tk.Toplevel(self.root)
        dialog.title("הגדרת עמדה ציבורית — סוג חיבור")
        dialog.geometry("520x320")
        dialog.configure(bg='#ecf0f1')
        dialog.transient(self.root)
        dialog.grab_set()

        tk.Label(dialog, text="ברוכים הבאים לעמדה הציבורית", font=('Arial', 15, 'bold'), bg='#ecf0f1').pack(pady=(20, 6))
        tk.Label(dialog, text="בחר כיצד לחבר עמדה זו לנתונים:", font=('Arial', 11), bg='#ecf0f1').pack(pady=(0, 14))

        btn_frame = tk.Frame(dialog, bg='#ecf0f1')
        btn_frame.pack(padx=30, fill=tk.X)

        def choose(mode):
            result['mode'] = mode
            dialog.destroy()

        tk.Button(btn_frame, text="🌐  חיבור מקוון (ענן)", font=('Arial', 12, 'bold'),
                  bg='#2980b9', fg='white', padx=16, pady=10, width=26,
                  command=lambda: choose('cloud')).pack(pady=4)
        tk.Label(btn_frame, text="אינטרנט בלבד — ללא רשת מקומית", font=('Arial', 9),
                 bg='#ecf0f1', fg='#555').pack()

        tk.Button(btn_frame, text="🖧  רשת מקומית (תיקייה משותפת)", font=('Arial', 11),
                  bg='#7f8c8d', fg='white', padx=16, pady=9, width=26,
                  command=lambda: choose('local')).pack(pady=(12, 4))
        tk.Label(btn_frame, text="מחובר לתיקיית רשת משותפת מהמחשב המרכזי", font=('Arial', 9),
                 bg='#ecf0f1', fg='#555').pack()

        dialog.wait_window()
        return result['mode']

    def _open_cloud_credentials_dialog(self, cfg: dict) -> bool:
        """Dialog: import connection JSON file or enter credentials manually.
        Updates cfg in-place with sync_tenant_id / sync_api_key / sync_push_url.
        Returns True on success."""
        result = {'ok': False}
        dialog = tk.Toplevel(self.root)
        dialog.title("חיבור לענן — פרטי חיבור")
        dialog.geometry("640x420")
        dialog.configure(bg='#ecf0f1')
        dialog.transient(self.root)
        dialog.grab_set()

        tk.Label(dialog, text="חיבור עמדה ציבורית לענן", font=('Arial', 14, 'bold'), bg='#ecf0f1').pack(pady=(16, 4))
        tk.Label(dialog, text="ייבא קובץ חיבור שהורדת מאתר הניהול, או הזן פרטים ידנית.",
                 font=('Arial', 10), bg='#ecf0f1', fg='#555').pack()

        form = tk.Frame(dialog, bg='#ecf0f1')
        form.pack(fill=tk.X, padx=24, pady=10)

        LW = 22
        FW = 38
        tenant_var = tk.StringVar(value=str(cfg.get('sync_tenant_id') or ''))
        apikey_var  = tk.StringVar(value=str(cfg.get('sync_api_key')   or ''))
        pushurl_var = tk.StringVar(value=str(cfg.get('sync_push_url')  or ''))

        for label, var in [("קוד מוסד (tenant_id):", tenant_var),
                            ("מפתח API (api_key):",   apikey_var),
                            ("Push URL:",              pushurl_var)]:
            row = tk.Frame(form, bg='#ecf0f1')
            row.pack(fill=tk.X, pady=2)
            tk.Label(row, text=fix_rtl_text(label), font=('Arial', 10), bg='#ecf0f1', anchor='e', width=LW).pack(side=tk.RIGHT, padx=4)
            tk.Entry(row, textvariable=var, font=('Arial', 10), width=FW, justify='left').pack(side=tk.RIGHT, padx=4)

        def browse_file():
            path = filedialog.askopenfilename(
                title='ייבוא קובץ הרשמה',
                filetypes=[('קובץ חיבור SchoolPoints', '*.json'), ('הכל', '*.*')],
                parent=dialog)
            if not path:
                return
            try:
                with open(path, 'r', encoding='utf-8') as _f:
                    creds = json.load(_f)
                tid  = str(creds.get('sync_tenant_id') or '').strip()
                akey = str(creds.get('sync_api_key')   or '').strip()
                purl = str(creds.get('sync_push_url')  or '').strip()
                base_url = str(creds.get('cloud_base_url') or '').strip()
                if not (tid and akey and purl):
                    messagebox.showerror('שגיאה', 'הקובץ לא מכיל פרטי חיבור תקינים.', parent=dialog)
                    return
                tenant_var.set(tid)
                apikey_var.set(akey)
                pushurl_var.set(purl)
                if base_url:
                    cfg['cloud_base_url'] = base_url
            except Exception as e:
                messagebox.showerror('שגיאה', f'לא ניתן לקרוא את הקובץ:\n{e}', parent=dialog)

        def save_and_close():
            tid  = tenant_var.get().strip()
            akey = apikey_var.get().strip()
            purl = pushurl_var.get().strip()
            if not (tid and akey and purl):
                messagebox.showerror('שגיאה', 'יש למלא את כל השדות (tenant_id, api_key, push_url).', parent=dialog)
                return
            cfg['sync_tenant_id'] = tid
            cfg['sync_api_key']   = akey
            cfg['sync_push_url']  = purl
            cfg['deployment_mode'] = 'cloud'
            result['ok'] = True
            dialog.destroy()

        btn_row = tk.Frame(dialog, bg='#ecf0f1')
        btn_row.pack(pady=8)
        tk.Button(btn_row, text="📂 ייבא קובץ הרשמה", command=browse_file,
                  font=('Arial', 10), bg='#27ae60', fg='white', padx=12, pady=5).pack(side=tk.RIGHT, padx=6)
        tk.Button(btn_row, text="✓ שמור וחבר", command=save_and_close,
                  font=('Arial', 10, 'bold'), bg='#2980b9', fg='white', padx=12, pady=5).pack(side=tk.RIGHT, padx=6)
        tk.Button(btn_row, text="ביטול", command=dialog.destroy,
                  font=('Arial', 10), bg='#95a5a6', fg='white', padx=12, pady=5).pack(side=tk.RIGHT, padx=6)

        dialog.wait_window()
        return result['ok']

    # ------------------------------------------------------------------

    def ensure_shared_folder_config(self) -> bool:
        """בדיקה/הגדרה של תיקיית רשת משותפת לפי קובץ ההגדרות החי."""
        try:
            cfg = self.load_app_config() or {}
            shared = cfg.get('shared_folder') or cfg.get('network_root')
            previously_configured = bool(shared)

            # wizard סוג התקנה — רק בפעם הראשונה
            existing_mode = str(cfg.get('deployment_mode') or '').strip().lower()
            if not existing_mode and not shared:
                chosen = self._open_deployment_wizard(cfg)
                if not chosen:
                    return False
                cfg['deployment_mode'] = chosen
                try:
                    self.save_app_config(cfg)
                except Exception:
                    pass
                if chosen in ('hybrid', 'cloud'):
                    try:
                        self._open_cloud_credentials_dialog(cfg)
                        self.save_app_config(cfg)
                    except Exception:
                        pass
                    return True

            # In cloud mode: no shared folder needed — skip folder check
            if existing_mode in ('cloud', 'hybrid'):
                tid  = str(cfg.get('sync_tenant_id') or '').strip()
                akey = str(cfg.get('sync_api_key')   or '').strip()
                purl = str(cfg.get('sync_push_url')  or '').strip()
                if tid and akey and purl:
                    self.app_config = cfg
                    return True
                # Credentials missing — re-open credentials dialog
                try:
                    ok = self._open_cloud_credentials_dialog(cfg)
                    if ok:
                        self.save_app_config(cfg)
                        self.app_config = cfg
                        return True
                except Exception:
                    pass
                return False

            if shared and not _safe_isdir(shared):
                try:
                    messagebox.showwarning(
                        "תיקייה משותפת לא זמינה",
                        "נראה שהעמדה הציבורית כבר הוגדרה בעבר לתיקיית נתונים משותפת, אך כרגע אין גישה אליה.\n\n"
                        "בדרך כלל זו בעיית רשת/חיבור למחשב המרכזי/הרשאות.\n"
                        "לא מומלץ ליצור תיקייה משותפת חדשה לפני שבודקים את החיבור, כדי לא ליצור פיצול נתונים."
                    )
                except Exception:
                    pass

            if shared and _safe_isdir(shared):
                self.app_config = cfg
                try:
                    self._seed_shared_sounds_folder(shared)
                except Exception:
                    pass
                return True

            return self._open_shared_folder_dialog(
                cfg,
                first_run=not previously_configured,
                previous_shared_folder=shared if previously_configured else None,
                previously_configured=previously_configured,
            )
        except Exception as e:
            print(f"שגיאה בהגדרת תיקיית רשת: {e}")
            return False

    def open_public_settings_dialog(self):
        """פתיחת חלון הגדרות לעמדה הציבורית (תיקיית רשת / חיבור ענן)."""
        cfg = self.load_app_config() or {}
        existing_mode = str(cfg.get('deployment_mode') or 'local').strip().lower()

        dialog = tk.Toplevel(self.root)
        dialog.title("הגדרות עמדה ציבורית")
        dialog.geometry("420x220")
        dialog.configure(bg='#ecf0f1')
        dialog.transient(self.root)
        dialog.grab_set()

        tk.Label(dialog, text="הגדרות חיבור", font=('Arial', 13, 'bold'), bg='#ecf0f1').pack(pady=(16, 6))
        mode_lbl = "מצב נוכחי: " + ("ענן ☁" if existing_mode in ('cloud', 'hybrid') else "רשת מקומית 🖧")
        tk.Label(dialog, text=mode_lbl, font=('Arial', 10), bg='#ecf0f1', fg='#555').pack(pady=(0, 10))

        btn_frame = tk.Frame(dialog, bg='#ecf0f1')
        btn_frame.pack()

        def open_cloud():
            dialog.destroy()
            ok = self._open_cloud_credentials_dialog(cfg)
            if ok:
                self.save_app_config(cfg)
                messagebox.showinfo("הצלחה", "פרטי חיבור הענן נשמרו. העמדה תסתנכרן בפעם הבאה.")

        def open_local():
            dialog.destroy()
            shared = cfg.get('shared_folder') or cfg.get('network_root')
            self._open_shared_folder_dialog(cfg, first_run=False,
                                             previous_shared_folder=shared,
                                             previously_configured=bool(shared))

        tk.Button(btn_frame, text="🌐  חיבור מקוון (ענן)", font=('Arial', 11, 'bold'),
                  bg='#2980b9', fg='white', padx=14, pady=8, width=24,
                  command=open_cloud).pack(pady=4)
        tk.Button(btn_frame, text="🖧  רשת מקומית (תיקיית שיתוף)", font=('Arial', 10),
                  bg='#7f8c8d', fg='white', padx=14, pady=7, width=24,
                  command=open_local).pack(pady=4)

        dialog.wait_window()

    def _open_shared_folder_dialog(self, cfg: dict, first_run: bool, previous_shared_folder: str = None, previously_configured: bool = False) -> bool:
        """חלון בחירת תיקיית רשת משותפת. מחזיר True אם נשמרה הגדרה."""
        dialog = tk.Toplevel(self.root)
        dialog.title("הגדרת עמדה ציבורית - תיקיית רשת משותפת")
        dialog.geometry("820x320")
        dialog.configure(bg='#ecf0f1')
        dialog.transient(self.root)
        dialog.grab_set()

        title_text = "ברוכים הבאים לעמדה הציבורית" if first_run else "חיבור לתיקיית נתונים משותפת"
        tk.Label(
            dialog,
            text=title_text,
            font=('Arial', 16, 'bold'),
            bg='#ecf0f1'
        ).pack(pady=(15, 5))

        tk.Label(
            dialog,
            text=(
                "בחר או הדבק נתיב תיקיית הנתונים המשותפת של המערכת.\n"
                "אם אינך בטוח – אפשר ליצור שיתוף אוטומטי (דורש הרשאות מנהל)."
            ),
            font=('Arial', 11),
            bg='#ecf0f1'
        ).pack(pady=(0, 10))

        if previously_configured and previous_shared_folder:
            try:
                tk.Label(
                    dialog,
                    text=(
                        "שימו לב: העמדה כבר הוגדרה בעבר. שינוי תיקיית הנתונים עלול ליצור פיצול נתונים.\n"
                        f"תיקייה קודמת: {previous_shared_folder}"
                    ),
                    font=('Arial', 9),
                    bg='#ecf0f1',
                    fg='#c0392b',
                    justify='right'
                ).pack(pady=(0, 8))
            except Exception:
                pass

        frame = tk.Frame(dialog, bg='#ecf0f1')
        frame.pack(fill=tk.X, padx=20, pady=5)

        shared_var = tk.StringVar(value=cfg.get('shared_folder') or cfg.get('network_root') or "")
        entry = tk.Entry(frame, textvariable=shared_var, font=('Arial', 11), width=40)
        entry.pack(side=tk.RIGHT, padx=5, pady=5, fill=tk.X, expand=True)

        def browse():
            folder = filedialog.askdirectory(title="בחר תיקיית רשת משותפת")
            if folder:
                shared_var.set(folder)

        def auto_create_share():
            folder = ""
            try:
                folder = shared_var.get().strip()
            except Exception:
                folder = ""
            if not folder:
                try:
                    system_drive = os.environ.get("SystemDrive") or "C:"
                except Exception:
                    system_drive = "C:"
                if not system_drive.endswith("\\") and not system_drive.endswith("/"):
                    system_drive = system_drive + "\\"
                try:
                    folder = os.path.join(system_drive, "SchoolPointsShare")
                except Exception:
                    folder = system_drive + "SchoolPointsShare"

            if folder.startswith("\\\\"):
                shared_var.set(folder)
                try:
                    messagebox.showinfo("תיקיית רשת קיימת", "נבחרה כבר תיקיית רשת משותפת (נתיב UNC).")
                except Exception:
                    pass
                return

            try:
                os.makedirs(folder, exist_ok=True)
            except Exception as e:
                messagebox.showerror("שגיאה", f"לא ניתן ליצור תיקייה משותפת:\n{e}")
                return

            share_name = "SchoolPoints$"
            try:
                computer = os.environ.get("COMPUTERNAME") or socket.gethostname() or ""
            except Exception:
                computer = ""
            unc_path = f"\\\\{computer}\\{share_name}" if computer else None

            def _run_share(cmd_args):
                try:
                    completed = subprocess.run(cmd_args, capture_output=True, text=True, shell=False)
                    if completed.returncode != 0:
                        return completed.stderr or completed.stdout or str(completed.returncode)
                    return None
                except Exception as e:
                    return str(e)

            base_cmd = ["net", "share", f"{share_name}={folder}"]
            cmd_args = base_cmd + ["/GRANT:Everyone,CHANGE"]
            error_text = _run_share(cmd_args)
            if error_text:
                fallback_error = _run_share(base_cmd)
                if not fallback_error:
                    error_text = None
                    cmd_args = base_cmd
                else:
                    error_text = fallback_error

            if error_text:
                msg_lines = [
                    "לא ניתן ליצור את השיתוף אוטומטית.",
                    "",
                    "בדרך כלל יש להפעיל את התוכנה עם הרשאות מנהל.",
                    "ניתן להריץ ידנית את הפקודה הבאה בחלון 'שורת הפקודה' כמנהל:",
                    "",
                    " ".join(cmd_args),
                    "",
                    f"שגיאה:\n{error_text}",
                ]
                msg = "\n".join(msg_lines)
                try:
                    self.root.clipboard_clear()
                    self.root.clipboard_append(" ".join(cmd_args))
                except Exception:
                    pass
                try:
                    messagebox.showwarning("שיתוף לא נוצר", msg)
                except Exception:
                    pass
            else:
                if unc_path:
                    shared_var.set(unc_path)
                else:
                    shared_var.set(folder)
                try:
                    info_msg = "תיקיית השיתוף נוצרה בהצלחה."
                    if unc_path:
                        info_msg += f"\n\nנתיב השיתוף:\n{unc_path}"
                    messagebox.showinfo("שיתוף נוצר", info_msg)
                except Exception:
                    pass

        def restart_as_admin():
            if _is_running_as_admin():
                try:
                    messagebox.showinfo("הרצה כמנהל", "היישום כבר פועל עם הרשאות מנהל.")
                except Exception:
                    pass
                return
            ok = _restart_as_admin()
            if not ok:
                try:
                    messagebox.showerror("שגיאה", "לא ניתן להפעיל מחדש עם הרשאות מנהל.\nניתן לנסות ללחוץ על הקיצור עם 'הפעל כמנהל'.")
                except Exception:
                    pass
                return
            try:
                dialog.destroy()
            except Exception:
                pass
            try:
                self.root.after(100, self.root.destroy)
            except Exception:
                try:
                    self.root.destroy()
                except Exception:
                    pass

        tk.Button(
            frame,
            text="בחר...",
            command=browse,
            font=('Arial', 10),
            bg='#3498db',
            fg='white',
            padx=10,
            pady=4
        ).pack(side=tk.LEFT, padx=5)

        if first_run:
            tk.Button(
                frame,
                text="צור תיקיית שיתוף אוטומטית",
                command=auto_create_share,
                font=('Arial', 9),
                bg='#2ecc71',
                fg='white',
                padx=8,
                pady=4
            ).pack(side=tk.LEFT, padx=5)

        btn_frame = tk.Frame(dialog, bg='#ecf0f1')
        btn_frame.pack(pady=20)

        result = {'ok': False}

        def save_and_close():
            folder = shared_var.get().strip()
            if not folder:
                messagebox.showerror("שגיאה", "יש לבחור תיקיית רשת משותפת.")
                return

            if previously_configured and previous_shared_folder:
                try:
                    old_s = str(previous_shared_folder or '').strip()
                    new_s = str(folder or '').strip()
                except Exception:
                    old_s = str(previous_shared_folder or '')
                    new_s = str(folder or '')
                if old_s and new_s and old_s != new_s:
                    try:
                        ok = messagebox.askyesno(
                            "אישור שינוי תיקייה משותפת",
                            "העמדה הציבורית כבר הייתה מחוברת בעבר לתיקיית נתונים משותפת.\n\n"
                            "שינוי התיקייה המשותפת עלול ליצור פיצול נתונים (\"מערכת חדשה\")\n"
                            "ולגרום לכך שעמדות אחרות ימשיכו לעבוד על נתונים ישנים.\n\n"
                            "האם לבצע שינוי בכל זאת?"
                        )
                    except Exception:
                        ok = False
                    if not ok:
                        return
            try:
                os.makedirs(folder, exist_ok=True)
            except Exception as e:
                messagebox.showerror("שגיאה", f"לא ניתן להשתמש בתיקייה:\n{e}")
                return

            # אם כבר קיימת תיקיית רשת עם config.json – נטען אותה ונעדיף את ההגדרות המשותפות
            base_cfg = dict(cfg) if isinstance(cfg, dict) else {}
            shared_cfg_path = os.path.join(folder, 'config.json')
            merged_cfg = None
            if os.path.exists(shared_cfg_path):
                try:
                    with open(shared_cfg_path, 'r', encoding='utf-8') as f:
                        shared_cfg = json.load(f)
                    if isinstance(shared_cfg, dict):
                        merged_cfg = dict(shared_cfg)
                        for k, v in base_cfg.items():
                            merged_cfg.setdefault(k, v)
                except Exception:
                    merged_cfg = None
            if merged_cfg is None:
                merged_cfg = base_cfg

            try:
                self._seed_shared_sounds_folder(folder)
            except Exception:
                pass

            merged_cfg['shared_folder'] = folder
            if 'network_root' in merged_cfg:
                merged_cfg.pop('network_root', None)
            if not merged_cfg.get('excel_path'):
                merged_cfg['excel_path'] = os.path.join(folder, "טבלה למבצע אשראי.xlsx")

            if not self.save_app_config(merged_cfg):
                return

            self.app_config = merged_cfg
            result['ok'] = True
            dialog.destroy()

        def cancel():
            dialog.destroy()

        if first_run:
            tk.Button(
                btn_frame,
                text="הפעל מחדש כמנהל",
                command=restart_as_admin,
                font=('Arial', 10),
                bg='#e67e22',
                fg='white',
                padx=16,
                pady=6
            ).pack(side=tk.LEFT, padx=10)

        tk.Button(
            btn_frame,
            text="💾 שמור והפעל",
            command=save_and_close,
            font=('Arial', 12, 'bold'),
            bg='#27ae60',
            fg='white',
            padx=25,
            pady=8
        ).pack(side=tk.RIGHT, padx=10)

        tk.Button(
            btn_frame,
            text="ביטול",
            command=cancel,
            font=('Arial', 11),
            bg='#95a5a6',
            fg='white',
            padx=20,
            pady=8
        ).pack(side=tk.LEFT, padx=10)

        self.root.wait_window(dialog)
        return result['ok']

    def load_color_settings(self):
        """טעינת הגדרות צבעים מקובץ JSON"""
        try:
            settings_file = _get_color_settings_file(self.base_dir)
            if os.path.exists(settings_file):
                with open(settings_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get('color_ranges', [])
        except Exception as e:
            print(f"שגיאה בטעינת צבעים: {e}")
        
        # ברירת מחדל
        return [
            {"min": 0, "max": 49, "color": "#95a5a6", "name": "אפור"},
            {"min": 50, "max": 99, "color": "#3498db", "name": "כחול"},
            {"min": 100, "max": 199, "color": "#2ecc71", "name": "ירוק"},
            {"min": 200, "max": 999999, "color": "#f39c12", "name": "זהב"}
        ]

    def load_event_sounds(self) -> dict:
        """טעינת צלילי אירועים מקובץ color_settings.json"""
        try:
            settings_file = _get_color_settings_file(self.base_dir)
            if os.path.exists(settings_file):
                with open(settings_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                ev = data.get('event_sounds') or {}
                return ev if isinstance(ev, dict) else {}
        except Exception:
            pass
        return {}
    
    def load_coin_settings(self):
        try:
            settings_file = _get_color_settings_file(self.base_dir)
            if os.path.exists(settings_file):
                with open(settings_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                coins = data.get('coins') or []
                result = []
                for coin in coins:
                    try:
                        value = int(coin.get('value', 0))
                    except Exception:
                        continue
                    if value <= 0:
                        continue
                    color = coin.get('color') or "#f1c40f"
                    name = coin.get('name') or ""
                    kind = coin.get('kind') or 'coin'
                    result.append({"value": value, "color": color, "name": name, "kind": kind})
                result.sort(key=lambda x: x.get('value', 0), reverse=True)
                return result
        except Exception as e:
            print(f"שגיאה בטעינת מטבעות: {e}")
        return []

    def load_goal_settings(self) -> dict:
        """טעינת הגדרות יעד (פס התקדמות) מקובץ JSON"""
        try:
            settings_file = _get_color_settings_file(self.base_dir)
            if os.path.exists(settings_file):
                with open(settings_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                goal = data.get('goal')
                if isinstance(goal, dict):
                    return goal
        except Exception as e:
            print(f"שגיאה בטעינת יעד: {e}")
        return {}

    def _compute_goal_target_points(self) -> int:
        try:
            goal = getattr(self, 'goal_settings', None) or {}
            if int(goal.get('enabled', 0) or 0) != 1:
                return 0
            mode = str(goal.get('mode') or 'absolute').strip().lower()
            if mode in ('max_points_possible', 'max_points', 'max_allowed'):
                try:
                    return max(0, int(self.db.compute_max_points_allowed() or 0))
                except Exception:
                    return 0
            if mode in ('relative_class', 'relative_by_class', 'class_relative'):
                try:
                    rel_pct = float(goal.get('relative_percent', 0) or 0)
                except Exception:
                    rel_pct = 0.0
                if rel_pct <= 0:
                    return 0
                if rel_pct > 100:
                    rel_pct = 100.0
                cn = ''
                try:
                    cn = str(getattr(self, '_last_student_class_name', '') or '').strip()
                except Exception:
                    cn = ''
                if not cn:
                    return 0
                max_points = 0
                try:
                    max_points = int(self.db.get_max_student_points_by_class(cn) if getattr(self, 'db', None) else 0)
                except Exception:
                    max_points = 0
                if max_points <= 0:
                    return 0
                target = int(round((max_points * rel_pct) / 100.0))
                return max(1, target)
            if mode == 'relative':
                try:
                    rel_pct = float(goal.get('relative_percent', 0) or 0)
                except Exception:
                    rel_pct = 0.0
                if rel_pct <= 0:
                    return 0
                if rel_pct > 100:
                    rel_pct = 100.0
                max_points = 0
                try:
                    max_points = int(self.db.get_max_student_points() if getattr(self, 'db', None) else 0)
                except Exception:
                    max_points = 0
                if max_points <= 0:
                    return 0
                target = int(round((max_points * rel_pct) / 100.0))
                return max(1, target)
            # absolute
            try:
                abs_points = int(goal.get('absolute_points', 0) or 0)
            except Exception:
                abs_points = 0
            return max(0, abs_points)
        except Exception:
            return 0

    def update_goal_progress_display(self, points: int):
        """עדכון פס היעד עבור נקודות תלמיד"""
        try:
            canvas = getattr(self, 'goal_bar_canvas', None)
            if not canvas:
                return
            goal = getattr(self, 'goal_settings', None) or {}
            if int(goal.get('enabled', 0) or 0) != 1:
                try:
                    canvas.pack_forget()
                except Exception:
                    pass
                return

            # ודא שהפס מוצג
            try:
                canvas.winfo_ismapped()
            except Exception:
                pass

            target = self._compute_goal_target_points()
            if target <= 0:
                try:
                    canvas.pack_forget()
                except Exception:
                    pass
                return

            try:
                cur = int(points or 0)
            except Exception:
                cur = 0
            if cur < 0:
                cur = 0

            progress = cur / float(target) if target > 0 else 0.0
            if progress < 0:
                progress = 0.0
            if progress > 1:
                progress = 1.0

            filled = goal.get('filled_color') or '#2ecc71'
            empty = goal.get('empty_color') or '#ecf0f1'
            border = goal.get('border_color') or '#2c3e50'
            show_percent = int(goal.get('show_percent', 0) or 0) == 1

            try:
                w = int(canvas.winfo_width() or canvas.cget('width'))
                h = int(canvas.winfo_height() or canvas.cget('height'))
            except Exception:
                w = int(canvas.cget('width'))
                h = int(canvas.cget('height'))

            if w <= 0 or h <= 0:
                return

            pad = 2
            inner_w = max(1, w - pad * 2)
            inner_h = max(1, h - pad * 2)
            filled_w = int(inner_w * progress)

            canvas.delete('all')
            canvas.create_rectangle(pad, pad, pad + inner_w, pad + inner_h, fill=empty, outline='')
            # חלק מלא
            if filled_w > 0:
                canvas.create_rectangle(pad + inner_w - filled_w, pad, pad + inner_w, pad + inner_h, fill=filled, outline='')
            canvas.create_rectangle(1, 1, w - 1, h - 1, outline=border, width=1)

            if show_percent:
                pct = int(round(progress * 100))
                text = f"{pct}%"
                try:
                    canvas.create_text(
                        w // 2,
                        h // 2,
                        text=fix_rtl_text(text),
                        fill=border,
                        font=(self.ui_font_family, int(self.font_info * 0.66), 'bold'),
                        stroke='black',
                        stroke_width=1
                    )
                except Exception:
                    # fallback ללא stroke אם אינו נתמך בגרסת Tk
                    canvas.create_text(w // 2, h // 2, text=text, fill=border, font=(self.ui_font_family, int(self.font_info * 0.66), 'bold'))
        except Exception:
            pass
    
    def get_color_for_points(self, points):
        """קביעת צבע לפי כמות נקודות"""
        for range_data in self.color_ranges:
            if range_data['min'] <= points <= range_data['max']:
                return range_data['color']
        
        # ברירת מחדל
        return '#3498db'

    def _apply_sound_settings_from_config(self, cfg: dict) -> None:
        if not getattr(self, 'sound_manager', None):
            return
        c = cfg if isinstance(cfg, dict) else {}

        enabled_raw = str(c.get('sounds_enabled', '1')).strip().lower()
        enabled = enabled_raw in ('1', 'true', 'yes', 'on')

        vol_raw = c.get('sound_volume', 80)
        try:
            vol_int = int(float(str(vol_raw).strip()))
        except Exception:
            vol_int = 80
        vol_int = max(0, min(100, vol_int))

        ranges_raw = c.get('quiet_mode_ranges')
        if isinstance(ranges_raw, str):
            try:
                ranges_raw = json.loads(ranges_raw)
            except Exception:
                ranges_raw = []
        ranges = list(ranges_raw) if isinstance(ranges_raw, list) else []

        if not ranges:
            quiet_enabled_raw = str(c.get('quiet_mode_enabled', '0')).strip().lower()
            quiet_enabled = quiet_enabled_raw in ('1', 'true', 'yes', 'on')
            quiet_start = str(c.get('quiet_mode_start', '') or '').strip()
            quiet_end = str(c.get('quiet_mode_end', '') or '').strip()
            quiet_volume_raw = c.get('quiet_mode_volume', vol_int)
            if quiet_enabled:
                ranges = [{
                    'start': quiet_start,
                    'end': quiet_end,
                    'mode': 'low',
                    'volume': quiet_volume_raw
                }]

        def _time_to_minutes(value: str):
            try:
                s = str(value or '').strip().replace('.', ':').replace(' ', '')
                if not s:
                    return None
                if ':' in s:
                    parts = s.split(':')
                    hh = int(parts[0])
                    mm = int(parts[1]) if len(parts) > 1 and parts[1] else 0
                elif len(s) == 4 and s.isdigit(): # 0800
                    hh = int(s[:2])
                    mm = int(s[2:])
                elif len(s) <= 2 and s.isdigit(): # 8 or 08
                    hh = int(s)
                    mm = 0
                else:
                    return None
                    
                if hh < 0 or hh > 23 or mm < 0 or mm > 59:
                    return None
                return hh * 60 + mm
            except Exception:
                return None

        active_range = None
        try:
            now = datetime.now()
            now_min = now.hour * 60 + now.minute
        except Exception:
            now_min = None

        if now_min is not None:
            for r in ranges:
                if not isinstance(r, dict):
                    continue
                start_min = _time_to_minutes(r.get('start'))
                end_min = _time_to_minutes(r.get('end'))
                if start_min is None or end_min is None:
                    continue
                if start_min <= end_min:
                    active = start_min <= now_min <= end_min
                else:
                    active = now_min >= start_min or now_min <= end_min
                if active:
                    active_range = r

        if active_range:
            mode_raw = str(active_range.get('mode') or '').strip().lower()
            mode = 'silent' if mode_raw in ('silent', 'quiet', 'mute', 'שקט') else 'low'
            if mode == 'silent':
                enabled = False
                vol_int = 0
            else:
                try:
                    quiet_int = int(float(str(active_range.get('volume', vol_int)).strip()))
                except Exception:
                    quiet_int = vol_int
                vol_int = max(0, min(100, quiet_int))
            
            # Fix for winsound (no volume control): Force mute if quiet mode is active and we can't lower volume
            if not USE_PYGAME and enabled:
                # If we are in quiet mode (even 'low'), winsound would play at 100%. 
                # Better to mute completely than disturb.
                enabled = False
                vol_int = 0

        vol = float(vol_int) / 100.0

        try:
            self.sound_manager.set_enabled(bool(enabled))
        except Exception:
            pass
        try:
            self.sound_manager.set_volume(vol)
        except Exception:
            pass

    def _sound_path(self, *parts: str) -> str:
        try:
            root_dir = getattr(self, '_sounds_root_dir', None) or os.path.join(self.base_dir, 'sounds')
            return os.path.join(root_dir, *parts)
        except Exception:
            return ""

    def _get_local_sounds_cache_dir(self) -> str:
        base_name = "SchoolPoints"
        for env_name in ("PROGRAMDATA", "LOCALAPPDATA", "APPDATA"):
            root = os.environ.get(env_name)
            if not root:
                continue
            try:
                if os.path.isdir(root) and os.access(root, os.W_OK):
                    d = os.path.join(root, base_name, "sounds_cache")
                    try:
                        os.makedirs(d, exist_ok=True)
                    except Exception:
                        pass
                    if os.path.isdir(d) and os.access(d, os.W_OK):
                        return d
            except Exception:
                continue

        try:
            tmp = os.environ.get('TEMP') or os.environ.get('TMP')
            if tmp and os.path.isdir(tmp) and os.access(tmp, os.W_OK):
                d = os.path.join(tmp, base_name, "sounds_cache")
                try:
                    os.makedirs(d, exist_ok=True)
                except Exception:
                    pass
                if os.path.isdir(d):
                    return d
        except Exception:
            pass

        return os.path.join(self.base_dir, 'sounds')

    def _sync_sounds_from_network(self, cfg: dict, cache_dir: str) -> bool:
        if not cache_dir:
            return False

        c = cfg if isinstance(cfg, dict) else {}
        src = str(c.get('sounds_folder') or '').strip()
        if not src:
            shared = str(c.get('shared_folder') or c.get('network_root') or '').strip()
            if shared:
                src = os.path.join(shared, 'sounds')

        if not src or not _safe_isdir(src):
            return False

        try:
            self._sounds_network_dir = src
        except Exception:
            pass

        out = {'ok': False}

        def _worker():
            try:
                for root, _, files in os.walk(src):
                    rel = os.path.relpath(root, src)
                    if rel == '.':
                        rel = ''
                    dst_root = os.path.join(cache_dir, rel)
                    try:
                        os.makedirs(dst_root, exist_ok=True)
                    except Exception:
                        pass

                    for fn in files:
                        try:
                            if not fn.lower().endswith(('.wav', '.mp3', '.ogg')):
                                continue
                            sp = os.path.join(root, fn)
                            dp = os.path.join(dst_root, fn)
                            try:
                                sst = os.stat(sp)
                            except Exception:
                                continue
                            need = True
                            try:
                                dst_st = os.stat(dp)
                                if int(dst_st.st_size) == int(sst.st_size) and int(dst_st.st_mtime) >= int(sst.st_mtime):
                                    need = False
                            except Exception:
                                need = True
                            if need:
                                try:
                                    shutil.copy2(sp, dp)
                                except Exception:
                                    pass
                        except Exception:
                            continue
                try:
                    marker_path = os.path.join(cache_dir, '.sounds_cache_ready')
                    with open(marker_path, 'w', encoding='utf-8') as mf:
                        mf.write(str(int(time.time())))
                except Exception:
                    pass
                out['ok'] = True
            except Exception:
                out['ok'] = False

        t = threading.Thread(target=_worker, daemon=True)
        try:
            self._sounds_sync_thread = t
        except Exception:
            pass
        t.start()
        return True

    def _pick_existing_file(self, candidates) -> str:
        for p in (candidates or []):
            try:
                if p and os.path.exists(p):
                    return p
            except Exception:
                continue
        return ""

    def _pick_random_from_folder(self, folder: str, filenames=None) -> str:
        try:
            if not folder or not os.path.isdir(folder):
                return ""
        except Exception:
            return ""

        files = []
        if filenames:
            for fn in filenames:
                try:
                    p = os.path.join(folder, fn)
                    if os.path.exists(p):
                        files.append(p)
                except Exception:
                    continue
        else:
            try:
                for fn in os.listdir(folder):
                    if fn.lower().endswith(('.wav', '.mp3', '.ogg')):
                        files.append(os.path.join(folder, fn))
            except Exception:
                files = []

        if not files:
            return ""

        # אם אין pygame (כלומר winsound בלבד), עדיף להימנע מ-MP3/OGG שלא נתמכים.
        try:
            if not bool(USE_PYGAME):
                wavs = [p for p in files if str(p).lower().endswith('.wav')]
                if wavs:
                    files = wavs
        except Exception:
            pass
        try:
            return random.choice(files)
        except Exception:
            return files[0]

    def _pick_random_from_sound_subfolder(self, folder_name: str, filenames=None) -> str:
        try:
            root_dir = getattr(self, '_sounds_root_dir', None) or os.path.join(self.base_dir, 'sounds')
        except Exception:
            root_dir = os.path.join(self.base_dir, 'sounds')
        try:
            folder = os.path.join(root_dir, str(folder_name))
        except Exception:
            folder = ""

        # לפעמים שמות תיקיות בעברית נשמרים עם תווי RTL/Control נסתרים.
        # ננסה לאתר תיקייה לפי השוואת שם מנורמל.
        try:
            if folder_name and root_dir and (not os.path.isdir(folder)) and os.path.isdir(root_dir):
                def _norm_dir_name(s: str) -> str:
                    try:
                        x = str(s or '')
                        for ch in (
                            '\u200e', '\u200f', '\u202a', '\u202b', '\u202c', '\u202d', '\u202e',
                            '\u2066', '\u2067', '\u2068', '\u2069',
                        ):
                            x = x.replace(ch, '')
                        return x.strip()
                    except Exception:
                        return str(s or '').strip()

                target = _norm_dir_name(folder_name)
                for entry in os.listdir(root_dir):
                    try:
                        p = os.path.join(root_dir, entry)
                        if os.path.isdir(p) and _norm_dir_name(entry) == target:
                            folder = p
                            break
                    except Exception:
                        continue
        except Exception:
            pass
        return self._pick_random_from_folder(folder, filenames=filenames)

    def _is_anti_spam_overlay_active(self) -> bool:
        try:
            return float(time.time()) < float(getattr(self, '_anti_spam_overlay_until_ts', 0.0) or 0.0)
        except Exception:
            return False

    def _hide_anti_spam_overlay(self) -> None:
        try:
            self._anti_spam_overlay_until_ts = 0.0
        except Exception:
            pass
        try:
            self._anti_spam_overlay_kind = ''
        except Exception:
            pass
        try:
            self._anti_spam_overlay_keep_name = False
        except Exception:
            pass
        try:
            if getattr(self, '_anti_spam_overlay_hide_job', None) is not None:
                try:
                    self.root.after_cancel(self._anti_spam_overlay_hide_job)
                except Exception:
                    pass
            self._anti_spam_overlay_hide_job = None
        except Exception:
            pass
        try:
            if getattr(self, '_anti_spam_overlay', None) is not None:
                self._anti_spam_overlay.place_forget()
        except Exception:
            pass

        try:
            self._anti_spam_overlay_body_img = None
        except Exception:
            pass

    def _position_anti_spam_overlay(self) -> None:
        # Note: update_idletasks removed to prevent reentrant Tkinter callbacks
        ov = getattr(self, '_anti_spam_overlay', None)
        if ov is None:
            return

        sw = int(getattr(self, 'screen_width', 0) or self.root.winfo_width() or 0)
        sh = int(getattr(self, 'screen_height', 0) or self.root.winfo_height() or 0)
        if sw <= 0:
            sw = int(self.root.winfo_screenwidth() or 1920)
        if sh <= 0:
            sh = int(self.root.winfo_screenheight() or 1080)

        try:
            kind = str(getattr(self, '_anti_spam_overlay_kind', '') or '').strip().lower()
        except Exception:
            kind = ''
        try:
            is_portrait = int(sh) > int(sw)
        except Exception:
            is_portrait = False
        if kind == 'block':
            w = max(520, int((0.94 if is_portrait else 0.86) * sw))
        elif kind == 'blocked':
            w = max(420, int((0.74 if is_portrait else 0.62) * sw))
        else:
            w = max(420, int((0.94 if is_portrait else 0.78) * sw))
        x = max(10, int((sw - w) / 2))

        keep_name = bool(getattr(self, '_anti_spam_overlay_keep_name', False))
        top_y = int(0.18 * sh)
        if keep_name:
            try:
                y0 = int(self.name_label.winfo_rooty() - self.root.winfo_rooty())
                h1 = int(self.name_label.winfo_height() or 0)
                h2 = int(self.class_label.winfo_height() or 0)
                gap = int(10 * (sh / 1080.0))
                top_y = max(top_y, y0 + h1 + h2 + gap)
            except Exception:
                pass

        bottom_margin = int(0.12 * sh)
        if kind == 'block':
            max_frac = 0.84 if is_portrait else 0.72
            h = max(260, min(int(max_frac * sh), max(260, sh - top_y - bottom_margin)))
        elif kind == 'blocked':
            max_frac = 0.32 if is_portrait else 0.26
            h = max(160, min(int(max_frac * sh), max(160, sh - top_y - bottom_margin)))
        else:
            max_frac = 0.70 if is_portrait else 0.55
            h = max(220, min(int(max_frac * sh), max(220, sh - top_y - bottom_margin)))

        try:
            ov.place(x=x, y=top_y, width=w, height=h)
            ov.lift()
        except Exception:
            pass

    def _show_anti_spam_overlay(self, text: str, *, kind: str, seconds: float, keep_name: bool) -> None:
        if not text:
            return

        try:
            self._anti_spam_overlay_kind = str(kind or '').strip().lower()
        except Exception:
            self._anti_spam_overlay_kind = ''

        try:
            if getattr(self, '_anti_spam_overlay', None) is None:
                self._anti_spam_overlay = tk.Frame(
                    self.root,
                    bg='#ffffff',
                    highlightbackground='#e74c3c',
                    highlightthickness=6,
                    bd=0,
                )
            try:
                if getattr(self, '_anti_spam_overlay_label', None) is not None:
                    try:
                        self._anti_spam_overlay_label.destroy()
                    except Exception:
                        pass
                    self._anti_spam_overlay_label = None
            except Exception:
                pass

            if getattr(self, '_anti_spam_overlay_title', None) is None:
                self._anti_spam_overlay_title = tk.Label(
                    self._anti_spam_overlay,
                    text='',
                    bg='#ffffff',
                    fg='#e74c3c',
                    justify='center',
                    anchor='center',
                )
                self._anti_spam_overlay_title.pack(fill=tk.X, padx=18, pady=(16, 6))
            if getattr(self, '_anti_spam_overlay_body', None) is None:
                self._anti_spam_overlay_body = tk.Label(
                    self._anti_spam_overlay,
                    text='',
                    bg='#ffffff',
                    fg='#e74c3c',
                    justify='center',
                    anchor='center',
                )
                self._anti_spam_overlay_body.pack(fill=tk.BOTH, expand=True, padx=18, pady=(0, 16))
        except Exception:
            return

        try:
            self._anti_spam_overlay_keep_name = bool(keep_name)
        except Exception:
            self._anti_spam_overlay_keep_name = False

        sh = int(getattr(self, 'screen_height', 0) or self.root.winfo_height() or 1080)
        if sh <= 0:
            sh = 1080
        sw = int(getattr(self, 'screen_width', 0) or self.root.winfo_width() or 1920)
        if sw <= 0:
            sw = 1920
        base_dim = int(min(sw, sh) or sh)
        try:
            k = str(kind or '').strip().lower()
        except Exception:
            k = ''
        if k == 'block1':
            border = '#f39c12'
            fg = '#f39c12'
            title_text = '!!! חסום'
            title_size = max(44, int(0.11 * base_dim))
            body_size = max(24, int(0.06 * base_dim))
        elif k == 'block':
            border = '#e74c3c'
            fg = '#e74c3c'
            title_text = '!!! חסום'
            title_size = max(44, int(0.11 * base_dim))
            body_size = max(24, int(0.06 * base_dim))
        elif k == 'blocked1':
            border = '#f39c12'
            fg = '#f39c12'
            title_text = 'חסום'
            title_size = max(28, int(0.055 * base_dim))
            body_size = max(18, int(0.038 * base_dim))
        elif k == 'blocked':
            border = '#e74c3c'
            fg = '#e74c3c'
            title_text = 'חסום'
            title_size = max(28, int(0.055 * base_dim))
            body_size = max(18, int(0.038 * base_dim))
        elif k == 'warning2':
            border = '#e74c3c'
            fg = '#e74c3c'
            title_text = 'אזהרה'
            title_size = max(34, int(0.075 * base_dim))
            body_size = max(20, int(0.05 * base_dim))
        else:
            border = '#f39c12'
            fg = '#f39c12'
            title_text = 'אזהרה'
            title_size = max(34, int(0.075 * base_dim))
            body_size = max(20, int(0.05 * base_dim))

        try:
            if k == 'block':
                title_size = int(min(title_size, 76))
                body_size = int(min(body_size, 64))
            else:
                title_size = int(min(title_size, 62))
                body_size = int(min(body_size, 54))
        except Exception:
            pass

        try:
            tlen = len(str(text or ''))
        except Exception:
            tlen = 0
        if tlen >= 220:
            body_size = max(18, int(body_size * 0.75))
        elif tlen >= 140:
            body_size = max(20, int(body_size * 0.85))

        try:
            self._anti_spam_overlay.configure(highlightbackground=border)
        except Exception:
            pass

        try:
            body_raw = str(text)
        except Exception:
            body_raw = ""
        try:
            body_raw = body_raw.replace('זו העבירה השניה', 'זו ההתראה השניה')
            body_raw = body_raw.replace('זו העבירה השנייה', 'זו ההתראה השניה')
            body_raw = body_raw.replace('העבירה', 'ההתראה')
        except Exception:
            pass
        try:
            title_raw = str(title_text)
        except Exception:
            title_raw = str(title_text)

        try:
            title_norm = normalize_ui_icons(title_raw)
        except Exception:
            title_norm = title_raw
        try:
            body_norm = normalize_ui_icons(body_raw)
        except Exception:
            body_norm = body_raw

        try:
            now = float(time.time())
            self._anti_spam_overlay_until_ts = now + float(seconds or 0.0)
        except Exception:
            self._anti_spam_overlay_until_ts = float(time.time()) + 6.0

        try:
            if getattr(self, '_anti_spam_overlay_hide_job', None) is not None:
                try:
                    self.root.after_cancel(self._anti_spam_overlay_hide_job)
                except Exception:
                    pass
        except Exception:
            pass

        self._position_anti_spam_overlay()

        try:
            w = int(self._anti_spam_overlay.winfo_width() or 0)
        except Exception:
            w = 0
        if w < 420:
            try:
                sw2 = int(getattr(self, 'screen_width', 0) or self.root.winfo_width() or 1920)
            except Exception:
                sw2 = 1920
            w = int(0.94 * sw2)
        try:
            wrap = int(max(260, int(w) - 80))
        except Exception:
            wrap = 900
        try:
            self._anti_spam_overlay_body.config(wraplength=int(wrap))
        except Exception:
            pass

        def _normalize_for_rtl(s: str) -> str:
            try:
                t = str(s or '')
            except Exception:
                return str(s or '')
            try:
                import re
                # הימנעות ממקפים בין עברית למספרים: בפונטים מסוימים זה יוצא כריבועים.
                t = re.sub(r'([א-ת])\s*[-–־]\s*(\d)', r'\1 \2', t)
                t = re.sub(r'(\d)\s*[-–־]\s*([א-ת])', r'\1 \2', t)
                # שמירת "מספר + יחידת זמן" יחד כדי להימנע מפיצול שורות ושיבוש RTL
                t = re.sub(r'(\d+)\s+(שעות|דקות|ימים|שעה|דקה|יום|שניות|שניה)', r'\1\u00a0\2', t)
            except Exception:
                pass
            return t

        def _rtl_line(s: str) -> str:
            t = _normalize_for_rtl(s)
            try:
                import re
                # עטיפת מספרים/שעות/טווחים ב-LRM...RLM כדי למנוע "קפיצה" לתחילת משפט RTL
                t2 = re.sub(
                    r'(\d+(?:[\.:]\d+)*(?:[־-]\d+(?:[\.:]\d+)*)*)',
                    rf'{LRM}\1{RLM}',
                    str(t or ''),
                )
            except Exception:
                t2 = str(t or '')

            # הצגה עם RTL מבלי להשאיר תווי BIDI נראים (שמופיעים כריבועים בפונטים מסוימים)
            try:
                disp = visual_rtl_simple(str(t2 or ''))
            except Exception:
                disp = str(t2 or '')
            try:
                for _m in (
                    '\u200e', '\u200f', '\u202a', '\u202b', '\u202c', '\u202d', '\u202e',
                    '\u2066', '\u2067', '\u2068', '\u2069', '\u061c',
                ):
                    disp = disp.replace(_m, '')
            except Exception:
                pass
            return disp

        try:
            # בכותרת קצרה ("אזהרה"/"חסום") אין צורך בהמרה חזותית – היא עלולה לשבש (למשל להציג "הורדה").
            title_disp = str(title_norm or '')
            if str(k or '').strip().lower() in ('block', 'blocked'):
                title_disp = fix_rtl_text(title_disp)
        except Exception:
            title_disp = title_norm

        try:
            self._anti_spam_overlay_title.config(
                text=title_disp,
                fg=fg,
                font=(self.ui_font_family, int(title_size), 'bold'),
            )
        except Exception:
            pass

        try:
            ov_h = int(self._anti_spam_overlay.winfo_height() or 0)
        except Exception:
            ov_h = 0
        try:
            title_h = int(self._anti_spam_overlay_title.winfo_height() or 0)
        except Exception:
            title_h = 0

        try:
            avail_h = int(max(60, ov_h - title_h - 90))
        except Exception:
            avail_h = 200

        def _wrap_lines(text_value: str, font_obj, wrap_px: int):
            try:
                raw_lines = str(text_value or '').split('\n')
            except Exception:
                raw_lines = [str(text_value or '')]
            out_lines = []
            for raw in raw_lines:
                s = str(raw or '').strip()
                if not s:
                    out_lines.append('')
                    continue
                words = s.split(' ')
                cur = ''
                for word in words:
                    test = (cur + ' ' + word).strip() if cur else word
                    try:
                        if int(font_obj.measure(test)) <= int(wrap_px) or not cur:
                            cur = test
                        else:
                            out_lines.append(cur)
                            cur = word
                    except Exception:
                        cur = test
                if cur:
                    out_lines.append(cur)
            return out_lines

        try:
            max_size = int(body_size)
        except Exception:
            max_size = 28

        final_text = None
        chosen_lines = None
        chosen_font_size = None
        for sz in range(max_size, 15, -2):
            try:
                fobj = tkfont.Font(family=self.ui_font_family, size=int(sz), weight='bold')
                lines = _wrap_lines(_normalize_for_rtl(body_norm), fobj, int(wrap))
                lh = int(fobj.metrics('linespace') or 1)
                need = int(max(1, len(lines)) * lh)
                if need <= int(avail_h):
                    try:
                        self._anti_spam_overlay_body.config(font=(self.ui_font_family, int(sz), 'bold'))
                    except Exception:
                        pass
                    try:
                        final_text = "\n".join(_rtl_line(ln) for ln in (lines or ['']))
                    except Exception:
                        final_text = _rtl_line(body_norm)
                    chosen_lines = list(lines or [''])
                    chosen_font_size = int(sz)
                    break
            except Exception:
                continue

        if final_text is None:
            try:
                final_text = _rtl_line(body_norm)
            except Exception:
                final_text = body_norm

        try:
            if chosen_lines is None:
                chosen_lines = [str(body_norm or '')]
            if chosen_font_size is None:
                try:
                    chosen_font_size = int(body_size)
                except Exception:
                    chosen_font_size = 24

            img_w = int(max(260, min(int(wrap), max(260, int(w) - 60))))
            pad = 8
            try:
                font_path = None
                if hasattr(self, 'agas_ttf_path') and self.agas_ttf_path and os.path.exists(self.agas_ttf_path):
                    font_path = self.agas_ttf_path
                if not font_path:
                    p1 = os.path.join(self.base_dir, "Gan CLM Bold.otf")
                    p2 = os.path.join(self.base_dir, "fonts", "Gan CLM Bold.otf")
                    if os.path.exists(p1):
                        font_path = p1
                    elif os.path.exists(p2):
                        font_path = p2
                if font_path:
                    pil_font = ImageFont.truetype(str(font_path), int(chosen_font_size))
                else:
                    pil_font = ImageFont.truetype("arial.ttf", int(chosen_font_size))
            except Exception:
                pil_font = ImageFont.load_default()

            try:
                tmp_img = Image.new('RGB', (img_w, 10), '#ffffff')
                tmp_draw = ImageDraw.Draw(tmp_img)
            except Exception:
                tmp_img = None
                tmp_draw = None

            vis_lines = []
            for ln in (chosen_lines or ['']):
                try:
                    vis_lines.append(_rtl_line(str(ln or '')))
                except Exception:
                    try:
                        v = visual_rtl_simple(str(ln or ''))
                        try:
                            for _m in (
                                '\u200e', '\u200f', '\u202a', '\u202b', '\u202c', '\u202d', '\u202e',
                                '\u2066', '\u2067', '\u2068', '\u2069', '\u061c'
                            ):
                                v = v.replace(_m, '')
                        except Exception:
                            pass
                        vis_lines.append(v)
                    except Exception:
                        vis_lines.append(str(ln or ''))

            line_h = 0
            try:
                ascent, descent = pil_font.getmetrics()
                line_h = int(max(1, int(ascent) + int(descent)))
            except Exception:
                try:
                    line_h = int(getattr(pil_font, 'size', 22) or 22)
                except Exception:
                    line_h = 22

            try:
                line_h = int(max(line_h, int((getattr(pil_font, 'size', 22) or 22) * 1.25)))
            except Exception:
                line_h = int(max(line_h, 24))

            img_h = int(max(1, (len(vis_lines) or 1) * line_h + pad * 2))
            try:
                img = Image.new('RGB', (img_w, img_h), '#ffffff')
                draw = ImageDraw.Draw(img)
                y = pad
                for vln in vis_lines:
                    try:
                        bb = draw.textbbox((0, 0), vln, font=pil_font)
                        tw = int(max(1, bb[2] - bb[0]))
                    except Exception:
                        tw = img_w
                    x0 = int(max(0, (img_w - tw) / 2))
                    try:
                        draw.text((x0, y), vln, font=pil_font, fill=str(fg))
                    except Exception:
                        pass
                    y += line_h
            except Exception:
                img = None

            if img is not None:
                try:
                    self._anti_spam_overlay_body_img = ImageTk.PhotoImage(img)
                except Exception:
                    self._anti_spam_overlay_body_img = None

                if getattr(self, '_anti_spam_overlay_body_img', None) is not None:
                    self._anti_spam_overlay_body.config(text='', image=self._anti_spam_overlay_body_img, fg=fg)
                else:
                    self._anti_spam_overlay_body.config(text=final_text, fg=fg)
            else:
                self._anti_spam_overlay_body.config(text=final_text, fg=fg)
        except Exception:
            try:
                self._anti_spam_overlay_body.config(text=str(text))
            except Exception:
                pass

        try:
            ms = int(max(200, float(seconds or 0.0) * 1000.0))
        except Exception:
            ms = 6000
        try:
            self._anti_spam_overlay_hide_job = self.root.after(ms, self._hide_anti_spam_overlay)
        except Exception:
            self._anti_spam_overlay_hide_job = None

    def _play_sound_file(self, path: str) -> None:
        try:
            if not getattr(self, 'sound_manager', None):
                return
            if path and os.path.exists(path):
                try:
                    ext = str(os.path.splitext(path)[1] or '').lower()
                except Exception:
                    ext = ''
                if (not USE_PYGAME) and ext in ('.mp3', '.ogg'):
                    try:
                        base, _ext = os.path.splitext(path)
                        wav_path = base + '.wav'
                        if not os.path.exists(wav_path):
                            _debug_log(f"play_sound_file unsupported_no_pygame path={path} (no wav alternative)")
                            return
                    except Exception:
                        try:
                            _debug_log(f"play_sound_file unsupported_no_pygame path={path}")
                        except Exception:
                            pass
                        return
                try:
                    _debug_log(
                        f"play_sound_file path={path} exists=1 enabled={getattr(self.sound_manager, 'enabled', None)} vol={getattr(self.sound_manager, 'volume', None)}"
                    )
                except Exception:
                    pass
                self.sound_manager.play_sound(path, async_play=True)
            else:
                try:
                    _debug_log(f"play_sound_file path={path} exists=0")
                except Exception:
                    pass
        except Exception:
            pass

    def _play_sound_key(self, sound_key: str) -> bool:
        try:
            if not getattr(self, 'sound_manager', None):
                return False
            k = str(sound_key or '').strip()
            if not k:
                return False
            path = self.sound_manager.resolve_sound([k])
            try:
                _debug_log(f"play_sound_key key={k} resolved={path}")
            except Exception:
                pass
            if path:
                self._play_sound_file(path)
                return True

            # אם לא נמצא – ייתכן שהעמדה עובדת על cache מקומי והקובץ החדש נמצא רק בתיקיית הרשת.
            # ננסה קודם לפתור מול תיקיית הרשת (אם קיימת), ואז ננסה טריגר sync.
            try:
                net_dir = str(getattr(self, '_sounds_network_dir', '') or '').strip()
            except Exception:
                net_dir = ''
            try:
                cache_dir = str(getattr(self, '_sounds_cache_dir', '') or '').strip()
            except Exception:
                cache_dir = ''

            if net_dir and os.path.isdir(net_dir):
                try:
                    tmp_mgr = SoundManager(self.base_dir, sounds_dir=net_dir)
                    try:
                        tmp_mgr.set_enabled(bool(getattr(self.sound_manager, 'enabled', True)))
                        tmp_mgr.set_volume(float(getattr(self.sound_manager, 'volume', 1.0) or 1.0))
                    except Exception:
                        pass
                    net_path = tmp_mgr.resolve_sound([k])
                except Exception:
                    net_path = None
                if net_path:
                    self._play_sound_file(net_path)
                    return True

            if cache_dir and os.path.isdir(cache_dir):
                try:
                    self._sync_sounds_from_network(self.load_app_config(), cache_dir)
                except Exception:
                    pass
        except Exception:
            return False
        return False
    
    def show_exit_dialog(self):
        """דיאלוג יציאה"""
        # חלון קטן למילוי קוד
        dialog = tk.Toplevel(self.root)
        dialog.title("יציאה מהמערכת")
        dialog.geometry("400x200")
        dialog.configure(bg='#ecf0f1')
        
        # מרכז את החלון
        dialog.transient(self.root)
        dialog.grab_set()
        
        tk.Label(
            dialog,
            text="הזן קוד יציאה:",
            font=('Arial', 14),
            bg='#ecf0f1'
        ).pack(pady=20)
        
        code_entry = tk.Entry(dialog, font=('Arial', 14), show='*', width=15)
        code_entry.pack(pady=10)
        code_entry.focus()
        
        def check_code():
            if code_entry.get() == self.exit_code:
                self.root.destroy()
            else:
                messagebox.showerror("שגיאה", "קוד שגוי!")
                dialog.destroy()
        
        tk.Button(
            dialog,
            text="יציאה",
            command=check_code,
            font=('Arial', 12),
            bg='#e74c3c',
            fg='white',
            padx=20,
            pady=10
        ).pack(pady=10)
        
        code_entry.bind('<Return>', lambda e: check_code())

    def open_admin_menu(self):
        """תפריט מנהל בעת סריקת כרטיס מאסטר 1 בעמדה הציבורית."""
        # אם כבר יש תפריט פתוח – סגור אותו ופתח מחדש (איפוס טיימר)
        try:
            if self._admin_menu_dialog is not None and self._admin_menu_dialog.winfo_exists():
                self._admin_menu_dialog.destroy()
        except Exception:
            pass

        dialog = tk.Toplevel(self.root)
        dialog.title("תפריט מנהל - עמדת תצוגה")
        dialog.geometry("420x310")
        dialog.configure(bg='#ecf0f1')
        dialog.transient(self.root)
        dialog.grab_set()

        self._admin_menu_dialog = dialog
        self._admin_menu_open = True
        # חלון זמן של 10 שניות לסריקה שנייה או לבחירת פעולה
        self._admin_menu_exit_deadline = time.time() + 10
        self._schedule_admin_menu_auto_close()

        tk.Label(
            dialog,
            text="בחר פעולה למנהל:",
            font=('Arial', 14, 'bold'),
            bg='#ecf0f1'
        ).pack(pady=(20, 10))

        btn_frame = tk.Frame(dialog, bg='#ecf0f1')
        btn_frame.pack(pady=10, padx=20, fill=tk.X)

        def open_settings():
            try:
                dialog.destroy()
            except Exception:
                pass
            self._admin_menu_open = False
            self._admin_menu_dialog = None
            self._admin_menu_exit_deadline = None
            self.open_public_settings_dialog()

        def open_cloud_settings():
            try:
                dialog.destroy()
            except Exception:
                pass
            self._admin_menu_open = False
            self._admin_menu_dialog = None
            self._admin_menu_exit_deadline = None
            try:
                cfg = self.load_app_config() or {}
                saved = self._open_cloud_credentials_dialog(cfg)
                if saved:
                    self.save_app_config(cfg)
            except Exception:
                pass

        def exit_station():
            try:
                dialog.destroy()
            except Exception:
                pass
            self._admin_menu_open = False
            self._admin_menu_dialog = None
            self._admin_menu_exit_deadline = None
            self.root.destroy()

        tk.Button(
            btn_frame,
            text="\u2699 \u05e9\u05d9\u05e0\u05d5\u05d9 \u05d4\u05d2\u05d3\u05e8\u05d5\u05ea \u05e2\u05de\u05d3\u05d4",
            command=open_settings,
            font=('Arial', 12),
            bg='#3498db',
            fg='white',
            padx=25,
            pady=10
        ).pack(pady=5, fill=tk.X)

        tk.Button(
            btn_frame,
            text="\U0001f310 \u05d7\u05d9\u05d1\u05d5\u05e8 \u05dc\u05e2\u05e0\u05df (\u05e1\u05d9\u05e0\u05db\u05e8\u05d5\u05df)",
            command=open_cloud_settings,
            font=('Arial', 12),
            bg='#27ae60',
            fg='white',
            padx=25,
            pady=10
        ).pack(pady=5, fill=tk.X)

        tk.Button(
            btn_frame,
            text="\U0001f6aa \u05d9\u05e6\u05d9\u05d0\u05d4 \u05de\u05d4\u05e2\u05de\u05d3\u05d4",
            command=exit_station,
            font=('Arial', 12),
            bg='#e74c3c',
            fg='white',
            padx=25,
            pady=10
        ).pack(pady=5, fill=tk.X)

    def _init_cursor_auto_hide(self):
        """הסתרת סמן עכבר אוטומטית לאחר חוסר פעילות."""
        self._cursor_visible = True
        self._last_mouse_activity = time.time()

        def on_activity(event=None):
            self._last_mouse_activity = time.time()
            if not self._cursor_visible:
                try:
                    self.root.config(cursor="")
                except Exception:
                    pass
                self._cursor_visible = True

        self.root.bind('<Motion>', on_activity)
        self.root.bind('<Button>', on_activity)

        def check_hide():
            now = time.time()
            if self._cursor_visible and now - self._last_mouse_activity >= 5:
                try:
                    self.root.config(cursor="none")
                except Exception:
                    pass
                self._cursor_visible = False
            self.root.after(1000, check_hide)

        self.root.after(5000, check_hide)
    
    def _schedule_initial_focus(self):
        try:
            def _focus(attempt=1):
                try:
                    # אם יש כרגע מסך חסימה – לא נשחק עם topmost כדי לא לגרום להבהובים
                    try:
                        if self._closure_overlay is not None and self._closure_overlay.winfo_exists():
                            return
                    except Exception:
                        pass

                    # ניסיון אגרסיבי יותר "לגנוב" את הפוקוס לחלון העמדה
                    self.root.deiconify()
                    self.root.lift()
                    # הפיכת החלון ל-topmost לזמן קצר, כדי שיעלה מעל כל החלונות
                    self.root.attributes('-topmost', True)
                    self.root.focus_force()
                    self.root.update_idletasks()

                    # אם pyautogui זמין בתחנה זו – נבצע גם קליק עכבר אמיתי באמצע המסך
                    # כדי ש-Windows יתייחס לחלון כאל החלון הפעיל גם עבור מקורות קלט חיצוניים.
                    if AUTO_CLICK_AVAILABLE:
                        try:
                            pa = _lazy_import_pyautogui()
                            if pa is None:
                                raise Exception('pyautogui unavailable')
                            screen_w = self.root.winfo_screenwidth()
                            screen_h = self.root.winfo_screenheight()
                            cx = screen_w // 2
                            cy = screen_h // 2
                            pa.moveTo(cx, cy)
                            pa.click()
                        except Exception:
                            pass

                    def _restore_topmost():
                        try:
                            # החזרת המצב הקודם לאחר שהחלון כבר קיבל פוקוס
                            self.root.attributes('-topmost', False)
                        except Exception:
                            pass

                    # אחרי שנייה נחזיר את המצב כך שלא נפריע לשאר האפליקציות
                    self.root.after(1000, _restore_topmost)
                except Exception:
                    pass
                # אם עדיין יש חלון אחר שלקח פוקוס, ננסה שוב עוד כמה פעמים
                if attempt < 5:
                    try:
                        self.root.after(1500, lambda: _focus(attempt + 1))
                    except Exception:
                        pass

            # ננסה לקחת פוקוס כעבור ~2 שניות מהעלייה, כדי לוודא שכל שאר החלונות סיימו להיטען
            self.root.after(2000, lambda: _focus(1))
        except Exception:
            pass

    def _schedule_restart_check(self):
        try:
            cfg = self.load_app_config() or {}
        except Exception:
            cfg = getattr(self, 'app_config', {}) if hasattr(self, 'app_config') else {}
        if isinstance(cfg, dict):
            token = str(cfg.get('restart_public_stations_token', ""))
        else:
            token = ""
        if token and token != self.restart_token_seen:
            _debug_log(f'restart_check: token CHANGED old={self.restart_token_seen!r} new={token!r}')
            self.restart_token_seen = token
            self._restart_requested = True
            try:
                self.root.after(100, self.root.destroy)
            except Exception:
                try:
                    self.root.destroy()
                except Exception:
                    pass
            return
        try:
            self.root.after(5000, self._schedule_restart_check)
        except Exception:
            pass

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

    def _check_for_updates_async(self, show_no_update: bool = False):
        try:
            cfg = self.load_app_config() or {}
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
                cfg2 = self.load_app_config() or {}
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

    def _dismiss_ads_popup(self) -> None:
        try:
            if getattr(self, '_ads_popup_close_job', None) is not None:
                try:
                    self.root.after_cancel(self._ads_popup_close_job)
                except Exception:
                    pass
            self._ads_popup_close_job = None
        except Exception:
            pass

        try:
            if getattr(self, '_ads_popup_win', None) is not None and self._ads_popup_win.winfo_exists():
                self._ads_popup_win.destroy()
        except Exception:
            pass
        self._ads_popup_win = None
        self._ads_popup_img = None

        try:
            self._ads_popup_last_shown_ts = float(time.time())
        except Exception:
            self._ads_popup_last_shown_ts = 0.0

    def _get_ads_image_abs_path(self, image_path: str) -> str:
        p = str(image_path or '').strip()
        if not p:
            return ''
        try:
            if os.path.isabs(p) and os.path.exists(p):
                return p
        except Exception:
            pass

        try:
            cfg = self.load_app_config() or {}
        except Exception:
            cfg = getattr(self, 'app_config', {}) if hasattr(self, 'app_config') else {}

        try:
            shared = str(cfg.get('shared_folder') or cfg.get('network_root') or '').strip()
        except Exception:
            shared = ''
        if shared:
            try:
                cand = os.path.join(shared, p)
                if os.path.exists(cand):
                    return cand
            except Exception:
                pass

        # חפש ליד קובץ ה-DB
        try:
            db_dir = os.path.dirname(os.path.abspath(self.db.db_path))
            cand = os.path.join(db_dir, p)
            if os.path.exists(cand):
                return cand
        except Exception:
            pass

        try:
            cand = os.path.join(self.base_dir, p)
            if os.path.exists(cand):
                return cand
        except Exception:
            pass

        return ''

    def _show_ads_popup(self, item: dict) -> None:
        try:
            self._dismiss_ads_popup()
        except Exception:
            pass

        try:
            sw = int(getattr(self, 'screen_width', 0) or self.root.winfo_width() or 0)
            sh = int(getattr(self, 'screen_height', 0) or self.root.winfo_height() or 0)
        except Exception:
            sw, sh = 0, 0
        if sw <= 0:
            sw = int(self.root.winfo_screenwidth() or 1920)
        if sh <= 0:
            sh = int(self.root.winfo_screenheight() or 1080)

        w = max(520, int(0.75 * sw))
        h = max(280, int(0.65 * sh))
        x = max(10, int((sw - w) / 2))
        y = max(10, int(0.18 * sh))

        win = tk.Toplevel(self.root)
        try:
            win.overrideredirect(True)
        except Exception:
            pass
        try:
            win.attributes('-topmost', True)
        except Exception:
            pass
        try:
            win.geometry(f"{w}x{h}+{x}+{y}")
        except Exception:
            pass

        try:
            cfg = self.load_app_config() or {}
        except Exception:
            cfg = getattr(self, 'app_config', {}) if hasattr(self, 'app_config') else {}

        def _cfg_bool(v, default=True) -> bool:
            try:
                if isinstance(v, bool):
                    return v
                if v is None:
                    return bool(default)
                if isinstance(v, (int, float)):
                    return bool(int(v) != 0)
                s = str(v).strip().lower()
                if s in ('0', 'false', 'no', 'off'):
                    return False
                if s in ('1', 'true', 'yes', 'on'):
                    return True
            except Exception:
                return bool(default)
            return bool(default)

        try:
            border_enabled = _cfg_bool(cfg.get('ads_popup_border', True), True)
        except Exception:
            border_enabled = True

        try:
            border_color = str(cfg.get('ads_popup_border_color', '#2c3e50') or '#2c3e50')
        except Exception:
            border_color = '#2c3e50'

        try:
            border_px = int(cfg.get('ads_popup_border_px', 10) or 10)
        except Exception:
            border_px = 10
        if border_px < 0:
            border_px = 0
        if border_px > 40:
            border_px = 40

        if border_enabled and border_px > 0:
            outer = tk.Frame(win, bg=border_color, bd=0)
            outer.pack(fill=tk.BOTH, expand=True)
            container = tk.Frame(outer, bg='#ffffff', bd=0)
            container.pack(fill=tk.BOTH, expand=True, padx=border_px, pady=border_px)
        else:
            container = tk.Frame(win, bg='#ffffff', bd=0)
            container.pack(fill=tk.BOTH, expand=True)

        img_path = ''
        try:
            img_path = self._get_ads_image_abs_path(item.get('image_path'))
        except Exception:
            img_path = ''

        text = ''
        try:
            text = str(item.get('text') or '').strip()
        except Exception:
            text = ''

        if img_path:
            try:
                img = Image.open(img_path)
                if img.mode not in ('RGB', 'RGBA'):
                    img = img.convert('RGBA')
                # הגדלת התמונה למקסימום האפשרי: אם אין טקסט — 98% מהריבוע, אם יש טקסט — 98%×78%
                _inner_w = w - (2 * border_px if border_enabled else 0)
                _inner_h = h - (2 * border_px if border_enabled else 0)
                max_w = max(200, int(_inner_w * 0.98))
                max_h = max(150, int(_inner_h * (0.92 if not text else 0.78)))
                # שמירה על יחס גובה-רוחב: חישוב scale factor אופטימלי
                orig_w, orig_h = img.size
                if orig_w > 0 and orig_h > 0:
                    scale = min(max_w / orig_w, max_h / orig_h)
                    new_w = max(1, int(orig_w * scale))
                    new_h = max(1, int(orig_h * scale))
                    try:
                        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                    except Exception:
                        try:
                            img = img.resize((new_w, new_h), Image.LANCZOS)
                        except Exception:
                            img = img.resize((new_w, new_h))
                self._ads_popup_img = ImageTk.PhotoImage(img)
                tk.Label(container, image=self._ads_popup_img, bg='#ffffff').pack(
                    pady=(6 if text else 0), expand=(not text), fill=(tk.BOTH if not text else tk.NONE))
            except Exception:
                self._ads_popup_img = None
        if text:
            try:
                font_size = max(18, int(0.028 * sh))
            except Exception:
                font_size = 22
            raw = normalize_ui_icons(text)
            
            # פירוק ידני לשורות כמו באנטי-ספאם (בלי wraplength)
            def _wrap_ads_lines(text_value: str, wrap_px: int):
                try:
                    raw_lines = str(text_value or '').split('\n')
                except Exception:
                    raw_lines = [str(text_value or '')]
                out_lines = []
                for raw in raw_lines:
                    s = str(raw or '').strip()
                    if not s:
                        out_lines.append('')
                        continue
                    words = s.split(' ')
                    cur = ''
                    for word in words:
                        test = (cur + ' ' + word).strip() if cur else word
                        try:
                            font_obj = tkfont.Font(family=self.ui_font_family, size=int(font_size), weight='bold')
                            if int(font_obj.measure(test)) <= int(wrap_px) or not cur:
                                cur = test
                            else:
                                out_lines.append(cur)
                                cur = word
                        except Exception:
                            cur = test
                    if cur:
                        out_lines.append(cur)
                return out_lines
            
            try:
                lines = _wrap_ads_lines(raw, int(w * 0.92))
                try:
                    import re
                    vis_lines = []
                    for ln in (lines or ['']):
                        s = str(ln or '')
                        try:
                            s = re.sub(r'([א-ת])\s*[-–־]\s*(\d)', r'\1 \2', s)
                            s = re.sub(r'(\d)\s*[-–־]\s*([א-ת])', r'\1 \2', s)
                            s = re.sub(r'(\d+)\s+(שעות|דקות|ימים|שעה|דקה|יום|שניות|שניה)', r'\1\u00a0\2', s)
                            s = re.sub(
                                r'(\d+(?:[\.:]\d+)*(?:[־-]\d+(?:[\.:]\d+)*)*)',
                                rf'{LRM}\1{RLM}',
                                s,
                            )
                        except Exception:
                            pass
                        try:
                            v = visual_rtl_simple(s)
                        except Exception:
                            v = s
                        try:
                            for _m in (
                                '\u200e', '\u200f', '\u202a', '\u202b', '\u202c', '\u202d', '\u202e',
                                '\u2066', '\u2067', '\u2068', '\u2069', '\u061c'
                            ):
                                v = v.replace(_m, '')
                        except Exception:
                            pass
                        vis_lines.append(v)

                    img_w = int(max(260, int(w * 0.92)))
                    pad = 10
                    try:
                        font_path = None
                        if hasattr(self, 'agas_ttf_path') and self.agas_ttf_path and os.path.exists(self.agas_ttf_path):
                            font_path = self.agas_ttf_path
                        if not font_path:
                            p1 = os.path.join(self.base_dir, "Gan CLM Bold.otf")
                            p2 = os.path.join(self.base_dir, "fonts", "Gan CLM Bold.otf")
                            if os.path.exists(p1):
                                font_path = p1
                            elif os.path.exists(p2):
                                font_path = p2
                        if font_path:
                            pil_font = ImageFont.truetype(str(font_path), int(font_size))
                        else:
                            pil_font = ImageFont.truetype("arial.ttf", int(font_size))
                    except Exception:
                        pil_font = ImageFont.load_default()

                    line_h = 0
                    try:
                        ascent, descent = pil_font.getmetrics()
                        line_h = int(max(1, int(ascent) + int(descent)))
                    except Exception:
                        try:
                            line_h = int(getattr(pil_font, 'size', 22) or 22)
                        except Exception:
                            line_h = 22
                    try:
                        line_h = int(max(line_h, int((getattr(pil_font, 'size', 22) or 22) * 1.25)))
                    except Exception:
                        line_h = int(max(line_h, 24))

                    img_h = int(max(1, (len(vis_lines) or 1) * line_h + pad * 2))
                    img = Image.new('RGB', (img_w, img_h), '#ffffff')
                    draw = ImageDraw.Draw(img)
                    y0 = pad
                    for vln in (vis_lines or ['']):
                        try:
                            bb = draw.textbbox((0, 0), vln, font=pil_font)
                            tw = int(max(1, bb[2] - bb[0]))
                        except Exception:
                            tw = img_w
                        x0 = int(max(0, (img_w - tw) / 2))
                        try:
                            draw.text((x0, y0), vln, font=pil_font, fill='#2c3e50')
                        except Exception:
                            pass
                        y0 += line_h

                    self._ads_popup_text_img = ImageTk.PhotoImage(img)
                    tk.Label(container, image=self._ads_popup_text_img, bg='#ffffff').pack(padx=16, pady=(0, 14))
                    disp_text = None
                except Exception:
                    disp_text = '\n'.join(lines)
            except Exception:
                disp_text = str(raw or '')

            if disp_text is not None:
                tk.Label(
                    container,
                    text=disp_text,
                    bg='#ffffff',
                    fg='#2c3e50',
                    font=(self.ui_font_family, int(font_size), 'bold'),
                    justify='center',
                ).pack(padx=16, pady=(0, 14), fill=tk.X)

        self._ads_popup_win = win

        try:
            show_sec = float(cfg.get('ads_popup_show_sec', 12) or 12)
        except Exception:
            show_sec = 12.0
        if show_sec < 3:
            show_sec = 3.0
        if show_sec > 120:
            show_sec = 120.0
        try:
            if getattr(self, '_ads_popup_close_job', None) is not None:
                try:
                    self.root.after_cancel(self._ads_popup_close_job)
                except Exception:
                    pass
            self._ads_popup_close_job = self.root.after(int(show_sec * 1000), self._dismiss_ads_popup)
        except Exception:
            self._ads_popup_close_job = None

    def _schedule_ads_popup_loop(self) -> None:
        try:
            if getattr(self, '_ads_popup_loop_job', None) is not None:
                return
        except Exception:
            pass
        try:
            self._ads_popup_loop_job = self.root.after(1200, self._ads_popup_loop)
        except Exception:
            self._ads_popup_loop_job = None

    def _ads_popup_loop(self) -> None:
        try:
            self._ads_popup_loop_job = None
        except Exception:
            pass

        try:
            cfg = self.load_app_config() or {}
        except Exception:
            cfg = getattr(self, 'app_config', {}) if hasattr(self, 'app_config') else {}

        def _cfg_bool(v, default=True) -> bool:
            try:
                if isinstance(v, bool):
                    return v
                if v is None:
                    return bool(default)
                if isinstance(v, (int, float)):
                    return bool(int(v) != 0)
                s = str(v).strip().lower()
                if s in ('0', 'false', 'no', 'off'):
                    return False
                if s in ('1', 'true', 'yes', 'on'):
                    return True
            except Exception:
                return bool(default)
            return bool(default)

        try:
            enabled = _cfg_bool(cfg.get('ads_popup_enabled', True), True)
        except Exception:
            enabled = True
        if not enabled:
            try:
                self._ads_popup_loop_job = self.root.after(5000, self._ads_popup_loop)
            except Exception:
                self._ads_popup_loop_job = None
            return

        try:
            idle_sec = float(cfg.get('ads_popup_idle_sec', 180) or 180)
        except Exception:
            idle_sec = 180.0
        if idle_sec < 10:
            idle_sec = 10.0

        try:
            gap_sec = float(cfg.get('ads_popup_gap_sec', 8) or 8)
        except Exception:
            gap_sec = 8.0
        if gap_sec < 1:
            gap_sec = 1.0
        if gap_sec > 600:
            gap_sec = 600.0

        # לא מציגים פרסומות בזמן חסימה (שבתות/חגים) או Overlay אנטי-ספאם
        try:
            if self._is_public_closed_now():
                self._ads_popup_loop_job = self.root.after(5000, self._ads_popup_loop)
                return
        except Exception:
            pass
        try:
            if self._is_anti_spam_overlay_active():
                self._ads_popup_loop_job = self.root.after(3000, self._ads_popup_loop)
                return
        except Exception:
            pass

        try:
            if getattr(self, '_ads_popup_win', None) is not None and self._ads_popup_win.winfo_exists():
                self._ads_popup_loop_job = self.root.after(1200, self._ads_popup_loop)
                return
        except Exception:
            pass

        try:
            last_shown = float(getattr(self, '_ads_popup_last_shown_ts', 0.0) or 0.0)
        except Exception:
            last_shown = 0.0
        try:
            if last_shown > 0 and (float(time.time()) - last_shown) < float(gap_sec):
                self._ads_popup_loop_job = self.root.after(1200, self._ads_popup_loop)
                return
        except Exception:
            pass

        try:
            since = float(time.time()) - float(getattr(self, 'last_card_time', 0.0) or 0.0)
        except Exception:
            since = 0.0

        if since >= float(idle_sec):
            items = []
            try:
                items = self.messages_db.get_active_ads_items() if getattr(self, 'messages_db', None) else []
            except Exception:
                items = []
            if items:
                try:
                    idx = int(getattr(self, '_ads_popup_index', 0) or 0)
                except Exception:
                    idx = 0
                try:
                    chosen = items[idx % len(items)]
                except Exception:
                    chosen = items[0]
                try:
                    self._ads_popup_index = (idx + 1) % max(1, len(items))
                except Exception:
                    pass
                try:
                    self._show_ads_popup(chosen)
                except Exception:
                    pass

                try:
                    self._ads_popup_last_shown_ts = float(time.time())
                except Exception:
                    self._ads_popup_last_shown_ts = 0.0

        try:
            self._ads_popup_loop_job = self.root.after(1200, self._ads_popup_loop)
        except Exception:
            self._ads_popup_loop_job = None

    def _schedule_admin_menu_auto_close(self):
        """בדיקה מחזורית לסגירת תפריט המנהל אחרי 10 שניות אם לא בוצעה פעולה."""
        if not self._admin_menu_open or self._admin_menu_exit_deadline is None:
            return

        now = time.time()
        if now > self._admin_menu_exit_deadline:
            try:
                if self._admin_menu_dialog is not None and self._admin_menu_dialog.winfo_exists():
                    self._admin_menu_dialog.destroy()
            except Exception:
                pass
            self._admin_menu_open = False
            self._admin_menu_dialog = None
            self._admin_menu_exit_deadline = None
            return

        # אם עדיין לא עבר הזמן – נבדוק שוב בעוד חצי שנייה
        self.root.after(500, self._schedule_admin_menu_auto_close)
    
    def load_bonus_settings(self):
        """טעינת הגדרות בונוס"""
        try:
            # ברירת מחדל: קובץ ליד קוד התוכנה
            local_bonus_file = os.path.join(self.base_dir, 'bonus_settings.json')
            bonus_file = local_bonus_file
            # אם מוגדרת תיקיית רשת משותפת – נעדיף קובץ משותף שם
            try:
                cfg = self.load_app_config()
                if isinstance(cfg, dict):
                    shared_folder = cfg.get('shared_folder') or cfg.get('network_root')
                    if shared_folder and os.path.isdir(shared_folder):
                        bonus_file = os.path.join(shared_folder, 'bonus_settings.json')
                        # אם אין עדיין קובץ משותף אבל יש מקומי – נעתיק
                        if (not os.path.exists(bonus_file)) and os.path.exists(local_bonus_file):
                            try:
                                shutil.copy2(local_bonus_file, bonus_file)
                            except Exception:
                                pass
            except Exception:
                pass

            if os.path.exists(bonus_file):
                with open(bonus_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception:
            pass
        return {"bonus_active": False, "bonus_points": 0, "bonus_running": False, "students_got_bonus": [], "master_card_2": "8888"}
        
    def save_bonus_settings(self, settings):
        """שמירת הגדרות בונוס"""
        try:
            # ברירת מחדל: קובץ ליד קוד התוכנה
            bonus_file = os.path.join(self.base_dir, 'bonus_settings.json')
            # אם מוגדרת תיקיית רשת משותפת – נשמור שם כדי לסנכרן בין כל העמדות
            try:
                cfg = self.load_app_config()
                if isinstance(cfg, dict):
                    shared_folder = cfg.get('shared_folder') or cfg.get('network_root')
                    if shared_folder and os.path.isdir(shared_folder):
                        try:
                            os.makedirs(shared_folder, exist_ok=True)
                        except Exception:
                            pass
                        bonus_file = os.path.join(shared_folder, 'bonus_settings.json')
            except Exception:
                pass

            with open(bonus_file, 'w', encoding='utf-8') as f:
                json.dump(settings, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"שגיאה בשמירת בונוס: {e}")

    # ===== בונוס מורה – שמירת מצב ריצה =====

    def _load_teacher_bonus_state(self):
        """טעינת מצב בונוס מורה מטבלת settings (אם קיים).

        שומר רציפות בונוס המורה גם לאחר פתיחת העמדה הציבורית מחדש,
        כולל רשימת תלמידים שכבר קיבלו את הבונוס בסבב הנוכחי.
        """
        try:
            raw = self.db.get_setting('teacher_bonus_state', None)
        except Exception as e:
            print(f"שגיאה בשליפת מצב בונוס מורה: {e}")
            return

        if not raw:
            return

        try:
            state = json.loads(raw)
        except Exception:
            return

        if not isinstance(state, dict):
            return

        running = bool(state.get('running'))
        teacher_id = state.get('teacher_id')
        points = state.get('points')
        students = state.get('students_got_bonus') or []

        if not running or teacher_id is None:
            return

        try:
            teacher_id = int(teacher_id)
        except Exception:
            return

        # ודא שהמורה עדיין קיים
        try:
            teacher_row = self.db.get_teacher_by_id(teacher_id)
        except Exception:
            teacher_row = None

        if not teacher_row:
            # אם המורה נמחק – ננקה את ההגדרה
            try:
                self.db.set_setting('teacher_bonus_state', json.dumps({"running": False}, ensure_ascii=False))
            except Exception:
                pass
            return

        # בדוק שהגדרת הבונוס בעמדת הניהול עדיין חיובית – אם בוטלה, אין בונוס רץ
        try:
            current_conf_points = self.db.get_teacher_bonus(teacher_id)
        except Exception:
            current_conf_points = 0

        if current_conf_points <= 0:
            try:
                self.db.set_setting('teacher_bonus_state', json.dumps({"running": False}, ensure_ascii=False))
            except Exception:
                pass
            return

        try:
            points_int = int(points if points is not None else current_conf_points)
        except Exception:
            points_int = int(current_conf_points)

        if points_int <= 0:
            return

        # רשימת תלמידים שכבר קיבלו את הבונוס בסבב זה
        students_list = []
        try:
            for sid in students:
                try:
                    students_list.append(int(sid))
                except Exception:
                    continue
        except Exception:
            students_list = []

        self.teacher_bonus_running = True
        self.current_teacher_bonus_teacher_id = teacher_id
        self.current_teacher_bonus_points = points_int
        self.teacher_bonus_students_got_bonus = students_list

        # בנה מחדש את רשימת התלמידים שמותר להם לקבל בונוס
        try:
            teacher_students = self.db.get_students_by_teacher(teacher_id)
            self.teacher_bonus_allowed_student_ids = {s['id'] for s in teacher_students}
        except Exception as e:
            print(f"שגיאה בשליפת תלמידי מורה לבונוס רץ: {e}")
            self.teacher_bonus_allowed_student_ids = set()

        # עדכן פסי בונוס כדי לשקף את המצב הקיים
        try:
            self.update_bonus_display()
            self.update_time_bonus_display()
        except Exception:
            pass

    def _save_teacher_bonus_state(self):
        """שמירת מצב בונוס מורה בטבלת settings.

        נשמר teacher_id, ערך הבונוס, ורשימת התלמידים שכבר קיבלו,
        כדי למנוע קבלת בונוס כפולה לאחר פתיחה מחדש.
        """
        try:
            if not getattr(self, 'db', None):
                return

            if not self.teacher_bonus_running or not self.current_teacher_bonus_teacher_id or self.current_teacher_bonus_points <= 0:
                payload = {"running": False}
            else:
                payload = {
                    "running": True,
                    "teacher_id": int(self.current_teacher_bonus_teacher_id),
                    "points": int(self.current_teacher_bonus_points),
                    "students_got_bonus": list(self.teacher_bonus_students_got_bonus or []),
                }

            self.db.set_setting('teacher_bonus_state', json.dumps(payload, ensure_ascii=False))
        except Exception as e:
            print(f"שגיאה בשמירת מצב בונוס מורה: {e}")
    
    def toggle_bonus_running(self):
        """הפעלה/כיבוי ריצת מצב הבונוס המיוחד (מאסטר 2)"""
        # טען הגדרות מחדש
        self.bonus_settings = self.load_bonus_settings()
        try:
            self._dismiss_ads_popup()
        except Exception:
            pass
        
        if not self.bonus_settings.get('bonus_active', False):
            # אין מצב בונוס מיוחד מוגדר
            self.name_label.config(text="❌ מצב בונוס מיוחד לא מוגדר", fg='#e74c3c')
            self.class_label.config(text="")
            self.id_label.config(text="")
            self.points_label.config(text="")
            self.points_text_label.config(text="הגדר בונוס מיוחד בעמדת הניהול", fg='#e74c3c')
            self.show_info()
            # השתמש בטיימר המאוחד כך שכל סריקת כרטיס חדשה תאפס את הזמן
            self._schedule_hide_info(5000, reset_name_color=False)
            return
        
        if not self.bonus_settings.get('bonus_running', False):
            # התחל ריצת בונוס מיוחד
            self.bonus_settings['bonus_running'] = True
            self.bonus_settings['students_got_bonus'] = []  # אפס רשימה
            self.save_bonus_settings(self.bonus_settings)
            
            # הצג הודעה
            bonus_points = self.bonus_settings.get('bonus_points', 0)
            self.name_label.config(text=f"🎁 מצב בונוס מיוחד החל!", fg='#f39c12')
            self.class_label.config(text="")
            self.id_label.config(text="")
            self.points_label.config(text=str(bonus_points), fg='#f39c12')
            self.points_text_label.config(text="נקודות לכל תלמיד (בונוס מיוחד)", fg='#f39c12')
            self.show_info()
            self._schedule_hide_info(5000, reset_name_color=False)
        else:
            # סיים ריצת בונוס מיוחד
            total_students = len(self.bonus_settings.get('students_got_bonus', []))
            self.bonus_settings['bonus_running'] = False
            self.save_bonus_settings(self.bonus_settings)
            
            # הצג הודעה
            self.name_label.config(text=f"🏁 מצב בונוס מיוחד הסתיים", fg='#27ae60')
            self.class_label.config(text="")
            self.id_label.config(text="")
            self.points_label.config(text=str(total_students), fg='#27ae60')
            self.points_text_label.config(text="תלמידים קיבלו בונוס מיוחד", fg='#27ae60')
            self.show_info()
            self._schedule_hide_info(5000, reset_name_color=False)
        
        # עדכן תצוגה
        self.update_bonus_display()

    def toggle_teacher_bonus(self, teacher):
        """הפעלה/כיבוי מצב בונוס מורה בעמדה הציבורית"""
        teacher_id = teacher.get('id')
        try:
            self._dismiss_ads_popup()
        except Exception:
            pass

        # אם אותו מורה כבר מפעיל בונוס – סיום הבונוס
        if self.teacher_bonus_running and self.current_teacher_bonus_teacher_id == teacher_id:
            total_students = len(self.teacher_bonus_students_got_bonus)
            self.teacher_bonus_running = False
            self.current_teacher_bonus_teacher_id = None
            self.current_teacher_bonus_points = 0
            self.teacher_bonus_students_got_bonus = []
            self.teacher_bonus_allowed_student_ids = set()

            # שמירת מצב: אין יותר בונוס מורה רץ
            try:
                self._save_teacher_bonus_state()
            except Exception:
                pass

            self.name_label.config(text="🏁 מצב בונוס הסתיים", fg='#27ae60')
            self.class_label.config(text="")
            self.id_label.config(text="")
            self.points_label.config(text=str(total_students), fg='#27ae60')
            self.points_text_label.config(text="תלמידים קיבלו בונוס", fg='#27ae60')
            self.show_info()
            self._schedule_hide_info(5000, reset_name_color=False)

            self.update_bonus_display()
            self.update_time_bonus_display()
            return
        # בדיקת הגבלות בונוס לפי טבלת המורים (מספר הפעלות ומקסימום נקודות לבונוס)
        teacher_row = None
        max_runs = None
        used_runs = 0
        max_points_limit = None
        try:
            teacher_row = self.db.get_teacher_by_id(teacher_id)
        except Exception as e:
            print(f"שגיאה בשליפת פרטי מורה {teacher_id}: {e}")
            teacher_row = teacher or {}

        if teacher_row:
            try:
                raw_max_runs = teacher_row.get('bonus_max_total_runs')
                if raw_max_runs is not None:
                    max_runs = int(raw_max_runs)
            except Exception:
                max_runs = None
            try:
                raw_used = teacher_row.get('bonus_runs_used')
                reset_date = teacher_row.get('bonus_runs_reset_date')
                if raw_used is not None:
                    used_runs = int(raw_used)
                # אם אין תאריך איפוס או שהתאריך שונה מהיום – נתייחס כאילו המונה היומי אפס
                today_iso = date.today().isoformat()
                if not reset_date or reset_date != today_iso:
                    used_runs = 0
            except Exception:
                used_runs = 0
            try:
                raw_limit = teacher_row.get('bonus_max_points_per_student')
                if raw_limit is not None:
                    max_points_limit = int(raw_limit)
            except Exception:
                max_points_limit = None

        if max_runs is not None and max_runs > 0 and used_runs >= max_runs:
            # בעמדה הציבורית לא חושפים את מגבלות המורה – רק הודעה כללית
            self.name_label.config(text="❌ מצב בונוס לא הופעל", fg='#e74c3c')
            self.class_label.config(text="")
            self.id_label.config(text="")
            self.points_label.config(text="")
            self.points_text_label.config(text="לא ניתן להפעיל מצב בונוס כעת.", fg='#e74c3c')
            self.show_info()
            self._schedule_hide_info(5000, reset_name_color=False)
            return

        # התחלת בונוס למורה הנתון
        try:
            bonus_points = self.db.get_teacher_bonus(teacher_id)
        except Exception as e:
            print(f"שגיאה בשליפת בונוס מורה {teacher_id}: {e}")
            bonus_points = 0

        if not bonus_points or bonus_points <= 0:
            self.name_label.config(text="❌ לא הוגדר בונוס למורה זה", fg='#e74c3c')
            self.class_label.config(text="")
            self.id_label.config(text="")
            self.points_label.config(text="")
            self.points_text_label.config(text="הגדר בונוס בעמדת הניהול של המורה", fg='#e74c3c')
            self.show_info()
            self._schedule_hide_info(5000, reset_name_color=False)
            return

        if max_points_limit is not None and max_points_limit > 0 and bonus_points > max_points_limit:
            # בעמדה הציבורית לא מציגים את ערך המגבלה – רק הודעה כללית
            self.name_label.config(text="❌ מצב בונוס לא הופעל", fg='#e74c3c')
            self.class_label.config(text="")
            self.id_label.config(text="")
            self.points_label.config(text="")
            self.points_text_label.config(text="לא ניתן להפעיל מצב בונוס עם ערך זה.", fg='#e74c3c')
            self.show_info()
            self._schedule_hide_info(5000, reset_name_color=False)
            return

        # קבלת תלמידי המורה (לפי הכיתות שהוגדרו לו במערכת)
        try:
            teacher_students = self.db.get_students_by_teacher(teacher_id)
            allowed_ids = {s['id'] for s in teacher_students}
        except Exception as e:
            print(f"שגיאה בשליפת תלמידי המורה {teacher_id}: {e}")
            allowed_ids = set()

        if not allowed_ids:
            self.name_label.config(text="❌ אין כיתות משויכות למורה זה", fg='#e74c3c')
            self.class_label.config(text="")
            self.id_label.config(text="")
            self.points_label.config(text="")
            self.points_text_label.config(text="יש לשייך כיתות למורה בעמדת הניהול", fg='#e74c3c')
            self.show_info()
            self._schedule_hide_info(5000, reset_name_color=False)
            return

        try:
            # עדכון מונה הפעלות בונוס למורה (runs)
            self.db.increment_teacher_bonus_runs(teacher_id)
            # עדכון סך נקודות הבונוס שמורה חילק היום – לפי ערך הבונוס לכל סבב,
            # ללא קשר לכמה תלמידים קיבלו בפועל.
            try:
                self.db.increment_teacher_bonus_points_used(teacher_id, bonus_points)
            except Exception as e_points:
                print(f"שגיאה בעדכון סך נקודות בונוס למורה {teacher_id}: {e_points}")

            used_runs += 1
            try:
                if teacher_row is not None:
                    teacher_row['bonus_runs_used'] = used_runs
                if getattr(self, 'current_teacher', None) and self.current_teacher.get('id') == teacher_id:
                    self.current_teacher['bonus_runs_used'] = used_runs
            except Exception:
                pass
        except Exception as e:
            print(f"שגיאה בעדכון מונה הפעלות בונוס למורה {teacher_id}: {e}")

        self.teacher_bonus_running = True
        self.current_teacher_bonus_teacher_id = teacher_id
        self.current_teacher_bonus_points = bonus_points
        self.teacher_bonus_students_got_bonus = []
        self.teacher_bonus_allowed_student_ids = allowed_ids

        # שמירת מצב: בונוס מורה רץ, ללא תלמידים שקיבלו עדיין
        try:
            self._save_teacher_bonus_state()
        except Exception:
            pass

        teacher_name = teacher.get('name') or "מורה"
        self.name_label.config(text=f"🎁 מצב בונוס הופעל", fg='#f39c12')
        self.class_label.config(text=f"מורה: {teacher_name}")
        self.id_label.config(text="")
        self.points_label.config(text=str(bonus_points), fg='#f39c12')
        self.points_text_label.config(text="נקודות לכל תלמיד (בונוס)", fg='#f39c12')
        self.show_info()
        self._schedule_hide_info(5000, reset_name_color=False)

        try:
            self.update_bonus_display()
            self.update_time_bonus_display()
        except Exception:
            pass
        return
    
    def update_bonus_display(self):
        """עדכון תצוגת מצב בונוסים (בונוס מיוחד / בונוס מורה)"""
        parts = []
        total_points = 0

        # בונוס מורה
        try:
            if getattr(self, 'teacher_bonus_running', False) and int(getattr(self, 'current_teacher_bonus_points', 0) or 0) > 0:
                pts = int(getattr(self, 'current_teacher_bonus_points', 0) or 0)
                parts.append(f"🎁 בונוס: +{pts} נק'")
                total_points += pts
        except Exception:
            pass

        # בונוס מיוחד (מאסטר 2)
        bonus_running = False
        try:
            bonus_running = bool(getattr(self, 'bonus_settings', None) and self.bonus_settings.get('bonus_running', False))
        except Exception:
            bonus_running = False
        if bonus_running:
            try:
                bonus_points = int(self.bonus_settings.get('bonus_points', 0) or 0)
            except Exception:
                bonus_points = 0
            if bonus_points > 0:
                parts.append(f"🎁 בונוס מיוחד: +{bonus_points} נק'")
                total_points += int(bonus_points)

        if parts:
            text = "  " + " | ".join(parts) + "  "
            text = fix_rtl_text(text)

            # מצב תצוגה – נזהה אם יש גם בונוס זמנים *מוצג* פעיל להתנגשות בונוסים
            # (בונוס 0 נק' לא נספר כתצוגה)
            has_time_bonus = False
            try:
                tb = self.db.get_active_time_bonus_now(only_shown_public=True)
                has_time_bonus = bool(tb) and int(tb.get('bonus_points', 0) or 0) > 0
            except Exception:
                has_time_bonus = False

            is_template1_portrait = (
                getattr(self, 'background_template', None) == 'template1'
                and getattr(self, 'screen_orientation', 'landscape') == 'portrait'
            )
            collision = is_template1_portrait and has_time_bonus

            # גודל פונט: קטן יותר רק במצב התנגשות בונוסים
            font_size = getattr(self, 'bonus_font_size_base', None) or 20
            if collision:
                font_size = getattr(self, 'bonus_font_size_small', font_size)
            self.bonus_label.config(text=text, font=(self.ui_font_family, font_size, 'bold'))

            # מיקום פס הבונוס העליון
            if is_template1_portrait:
                # במצב התנגשות – פס עליון מעט מעל ברירת המחדל, אך לא יותר מ~0.91
                if collision:
                    y_pos = int(0.91 * self.screen_height)
                else:
                    y_pos = int(0.92 * self.screen_height)
                self.bonus_label.place(relx=0.5, y=y_pos, anchor='n')
            else:
                # ברירת מחדל: מימין ללוגו בחלק העליון
                y_pos = int(0.04 * self.screen_height) if getattr(self, 'background_template', None) != 'template1' else int(0.007 * self.screen_height)
                self.bonus_label.place(relx=0.75, y=y_pos, anchor='n')
        else:
            self.bonus_label.place_forget()  # הסתר

    def update_time_bonus_display(self):
        """עדכון תצוגת מצב בונוס זמנים"""
        # בעמדה ציבורית מציגים בונוס זמנים שמסומן כמוצג.
        # אם זה בונוס לפי כיתה – נציג גם פירוט כיתות כדי למנוע בלבול.
        time_bonus = self.db.get_active_time_bonus_now(only_shown_public=True)
        if time_bonus:
            bonus_name = time_bonus['name']
            bonus_points = time_bonus['bonus_points']
            start_time = time_bonus['start_time']
            end_time = time_bonus['end_time']

            # 0 נק' = שומר נתונים בלבד (לצורך דוחות) – אין תצוגה לציבור
            try:
                if int(bonus_points or 0) <= 0:
                    self.time_bonus_label.place_forget()
                    self.root.after(5000, self.update_time_bonus_display)
                    return
            except Exception:
                pass

            classes_note = ""
            try:
                if int(time_bonus.get('is_general', 1) or 0) == 0:
                    cls = str(time_bonus.get('classes') or '').strip()
                    if cls:
                        classes_note = f" | כיתות: {cls}"
            except Exception:
                classes_note = ""
            
            tb_text = f"  ⏰ {bonus_name}: +{bonus_points} נק' ({start_time}-{end_time}){classes_note}  "
            # עטיפת טקסט ב-RLE/RLM כך שהכל יוצג בכיוון ימין-לשמאל תקין
            self.time_bonus_label.config(text=fix_rtl_text(tb_text))

            # האם יש בונוס מורה/מיוחד פעיל בנוסף לבונוס זמנים
            has_regular_bonus = self.bonus_settings.get('bonus_running', False) or self.teacher_bonus_running
            is_template1_portrait = (
                getattr(self, 'background_template', None) == 'template1'
                and getattr(self, 'screen_orientation', 'landscape') == 'portrait'
            )
            collision = is_template1_portrait and has_regular_bonus

            if is_template1_portrait:
                # במצב אורך עם template1 – נעלה את פס הזמנים במצב התנגשות, ונשמור פונט קטן יותר.
                font_size = getattr(self, 'bonus_font_size_base', None) or 20
                if collision:
                    font_size = getattr(self, 'bonus_font_size_small', font_size)
                self.time_bonus_label.config(font=(self.ui_font_family, font_size, 'bold'))

                if collision:
                    # שני פסי בונוס פעילים – פס עליון ב-0.91, פס זמנים מעט מתחתיו (~0.93)
                    base_y = 0.93
                else:
                    # מצב בונוס יחיד – השאר הגדרות קודמות (קרוב יותר לתחתית)
                    base_y = 0.95 if has_regular_bonus else 0.92

                y_position = int(base_y * self.screen_height)
                self.time_bonus_label.place(relx=0.5, y=y_position, anchor='n')
            else:
                # ברירת מחדל: מימין, מתחת לבונוס/בונוס מיוחד אם פעילים
                self.time_bonus_label.config(font=(self.ui_font_family, self.bonus_font_size_base, 'bold'))
                y_position = int(0.12 * self.screen_height) if has_regular_bonus else int(0.04 * self.screen_height)
                self.time_bonus_label.place(relx=0.75, y=y_position, anchor='n')
        else:
            self.time_bonus_label.place_forget()  # הסתר
        
        # בדוק שוב בתדירות גבוהה יותר (≈ כל 5 שניות) כדי ששינויים ייקלטו מהר
        self.root.after(5000, self.update_time_bonus_display)
    
    def _check_anti_spam(self, student_id, card_number):
        """בדיקת אנטי-ספאם - מחזיר dict עם פרטי חסימה/אזהרה או None"""
        try:
            config = self.load_app_config()

            def _cfg_bool(v, default=True) -> bool:
                try:
                    if isinstance(v, bool):
                        return v
                    if v is None:
                        return bool(default)
                    if isinstance(v, (int, float)):
                        return bool(int(v) != 0)
                    s = str(v).strip().lower()
                    if s in ('0', 'false', 'no', 'off'):
                        return False
                    if s in ('1', 'true', 'yes', 'on'):
                        return True
                except Exception:
                    return bool(default)
                return bool(default)

            # רישום תיקוף תמיד — גם אם אנטי-ספאם מכובה
            try:
                self.db.log_card_validation(student_id, card_number)
            except Exception:
                pass

            if not _cfg_bool((config or {}).get('anti_spam_enabled', True), True):
                return None
            
            rules = config.get('anti_spam_rules', None)
            if not isinstance(rules, list) or not rules:
                rules = [
                    {
                        'type': 'warning',
                        'count': 10,
                        'minutes': 1,
                        'duration': 0,
                        'message': 'שים לב! תיקפת {count} פעמים בדקה האחרונה. אם תמשיך, הכרטיס ייחסם.',
                        'sound_key': '',
                    },
                    {
                        'type': 'warning',
                        'count': 15,
                        'minutes': 1,
                        'duration': 0,
                        'message': 'אזהרה! זו ההתראה השנייה. אם תמשיך, הכרטיס ייחסם ליום.',
                        'sound_key': '',
                    },
                    {
                        'type': 'block',
                        'count': 20,
                        'minutes': 1,
                        'duration': 60,
                        'message': 'הכרטיס נחסם לשעה עקב ניצול יתר. תוכל לחזור בעוד {time_left}.',
                        'sound_key': '',
                    },
                    {
                        'type': 'block',
                        'count': 30,
                        'minutes': 1,
                        'duration': 1440,
                        'message': 'הכרטיס נחסם למשך 24 שעות. תוכל לחזור בעוד {time_left}.',
                        'sound_key': '',
                    },
                ]
            
            is_blocked, block_until, reason = self.db.is_card_blocked(student_id)
            if is_blocked:
                vc = 1
                try:
                    vc = int(self.db.get_violation_count(student_id) or 0)
                except Exception:
                    vc = 1
                if vc < 1:
                    vc = 1
                time_left = self._format_time_left(block_until)
                return {
                    'type': 'block',
                    'message': reason.replace('{time_left}', time_left),
                    'until': block_until,
                    'already_blocked': True,
                    'stage': int(vc),
                }
            
            violation_count = self.db.get_violation_count(student_id)

            suppress_warnings_due_to_hold = False
            try:
                sid_int = int(student_id or 0)
            except Exception:
                sid_int = 0
            try:
                if sid_int > 0:
                    st = (getattr(self, '_anti_spam_last_warning_state', None) or {}).get(sid_int)
                    if isinstance(st, dict) and float(time.time()) < float(st.get('hold_until') or 0.0):
                        suppress_warnings_due_to_hold = True
            except Exception:
                suppress_warnings_due_to_hold = False

            # שליפה וסידור כל הכללים – הסלמה רציפה: אזהרה 1 -> חסימה 1 -> אזהרה 2 -> חסימה 2 וכו'
            # stage = מספר החסימות הקודמות + 1
            try:
                stage = int(violation_count or 0) + 1
            except Exception:
                stage = 1
            if stage < 1:
                stage = 1

            warnings_all = []
            blocks_all = []
            for rule_index, rule in enumerate(rules or []):
                try:
                    count = int(rule.get('count', 10) or 0)
                except Exception:
                    count = 10
                try:
                    minutes = int(rule.get('minutes', 1) or 1)
                except Exception:
                    minutes = 1
                if minutes <= 0:
                    minutes = 1
                rule_type = str(rule.get('type', 'warning') or 'warning').strip().lower()
                item = (int(count), int(minutes), rule, str(rule_type), int(rule_index))
                if rule_type == 'block':
                    blocks_all.append(item)
                else:
                    warnings_all.append(item)

            # חשוב: סטים (1/2/3...) צריכים להיקבע לפי סדר הכללים בהגדרות, לא לפי count.
            warnings_all.sort(key=lambda x: x[4])
            blocks_all.sort(key=lambda x: x[4])

            warn_item = None
            block_item = None
            if warnings_all:
                warn_item = warnings_all[min(stage - 1, len(warnings_all) - 1)]
            if blocks_all:
                block_item = blocks_all[min(stage - 1, len(blocks_all) - 1)]

            # בדיקה אם כבר הוצגה אזהרה בשלב הנוכחי (כדי לאפשר חסימה)
            def _has_stage_warning_within(window_minutes: int) -> bool:
                try:
                    st = (getattr(self, '_anti_spam_last_warning_state', None) or {}).get(int(student_id or 0))
                except Exception:
                    st = None
                if not isinstance(st, dict):
                    return False
                try:
                    if int(st.get('stage') or 0) != int(stage or 0):
                        return False
                except Exception:
                    return False
                try:
                    ts = float(st.get('ts') or 0.0)
                except Exception:
                    ts = 0.0
                try:
                    wm = int(window_minutes or 1)
                except Exception:
                    wm = 1
                if wm <= 0:
                    wm = 1
                return float(time.time()) - float(ts) <= float(wm * 60)

            chosen = None

            # 1) אם הגענו לסף חסימה של השלב: נחסום רק אם כבר הוצגה אזהרה של השלב
            if block_item is not None:
                b_count, b_minutes, b_rule, _b_type, b_index = block_item
                b_recent = self.db.get_recent_validations_count(student_id, int(b_minutes or 1))
                if int(b_recent or 0) >= int(b_count or 0):
                    # אם לא הראינו אזהרה בשלב הזה – ננסה להראות קודם אזהרה (גם אם סף החסימה כבר התקיים)
                    if warn_item is not None and (not _has_stage_warning_within(int(b_minutes or 1))):
                        w_count, w_minutes, w_rule, _w_type, w_index = warn_item
                        w_recent = self.db.get_recent_validations_count(student_id, int(w_minutes or 1))
                        if int(w_recent or 0) >= int(w_count or 0):
                            chosen = (w_count, w_minutes, w_recent, w_rule, 'warning', w_index)
                    if chosen is None and _has_stage_warning_within(int(b_minutes or 1)):
                        chosen = (b_count, b_minutes, b_recent, b_rule, 'block', b_index)

            # 2) אחרת – אזהרה לפי השלב
            if chosen is None and warn_item is not None:
                if suppress_warnings_due_to_hold:
                    return None
                w_count, w_minutes, w_rule, _w_type, w_index = warn_item
                w_recent = self.db.get_recent_validations_count(student_id, int(w_minutes or 1))
                if int(w_recent or 0) >= int(w_count or 0):
                    chosen = (w_count, w_minutes, w_recent, w_rule, 'warning', w_index)

            if chosen is None:
                return None

            rule_count, rule_minutes, recent_count, rule, rule_type, rule_index = chosen
            try:
                rule_sound_key = str(rule.get('sound_key') or '').strip()
            except Exception:
                rule_sound_key = ''

            if rule_type == 'block':
                try:
                    duration = int(rule.get('duration', 60) or 60)
                except Exception:
                    duration = 60
                message = rule.get('message', 'הכרטיס נחסם')
                self.db.block_card(student_id, card_number, duration, message, violation_count + 1)
                try:
                    self.db.log_anti_spam_event(
                        student_id=int(student_id or 0),
                        card_number=str(card_number or '').strip(),
                        event_type='block',
                        rule_count=int(rule_count or 0),
                        rule_minutes=int(rule_minutes or 0),
                        duration_minutes=int(duration or 0),
                        recent_count=int(recent_count or 0),
                        message=str(message or ''),
                    )
                except Exception:
                    pass
                # לחשב זמן שנותר לפי block_until בפועל מה-DB (מדויק גם מיד לאחר חסימה)
                block_until = None
                try:
                    is_blocked2, block_until2, _reason2 = self.db.is_card_blocked(student_id)
                    if is_blocked2:
                        block_until = block_until2
                except Exception:
                    block_until = None
                time_left = self._format_time_left(block_until, duration)
                return {
                    'type': 'block',
                    'message': message.replace('{time_left}', time_left).replace('{count}', str(recent_count)),
                    'duration': duration,
                    'until': block_until,
                    'sound_key': rule_sound_key,
                    'rule_index': int(rule_index or 0),
                    'rule_count': int(rule_count or 0),
                    'rule_minutes': int(rule_minutes or 0),
                    'stage': int(stage or 1),
                }
            else:
                message = rule.get('message', 'אזהרה')
                try:
                    self.db.log_anti_spam_event(
                        student_id=int(student_id or 0),
                        card_number=str(card_number or '').strip(),
                        event_type='warning',
                        rule_count=int(rule_count or 0),
                        rule_minutes=int(rule_minutes or 0),
                        duration_minutes=None,
                        recent_count=int(recent_count or 0),
                        message=str(message or ''),
                    )
                except Exception:
                    pass
                return {
                    'type': 'warning',
                    'message': message.replace('{count}', str(recent_count)),
                    'count': recent_count,
                    'sound_key': rule_sound_key,
                    'rule_index': int(rule_index or 0),
                    'rule_count': int(rule_count or 0),
                    'rule_minutes': int(rule_minutes or 0),
                    'stage': int(stage or 1),
                }
            return None
        except Exception as e:
            print(f"שגיאה בבדיקת אנטי-ספאם: {e}")
            return None
    
    def _format_time_left(self, block_until=None, duration_minutes=None):
        """עיצוב זמן שנותר לחסימה"""
        try:
            diff = None
            if block_until:
                # SQLite datetime('now') מחזיר UTC. לכן נחשב מול utcnow כדי לא לקבל הפרש שלילי.
                try:
                    until = datetime.fromisoformat(str(block_until).replace('Z', '').replace('T', ' '))
                except Exception:
                    until = None
                if until is not None:
                    try:
                        now = datetime.utcnow()
                    except Exception:
                        now = datetime.now()
                    try:
                        diff = float((until - now).total_seconds())
                    except Exception:
                        diff = None

            if diff is None:
                if duration_minutes:
                    diff = float(duration_minutes) * 60.0
                else:
                    return "זמן לא ידוע"

            # אם עדיין קיבלנו הפרש שלילי (בעיית שעון/פורמט) אבל יש duration, נעדיף duration.
            try:
                if diff <= 0 and duration_minutes:
                    diff = float(duration_minutes) * 60.0
            except Exception:
                pass
            if diff <= 0:
                return "פחות מדקה"
            if diff < 60:
                return "פחות מדקה"

            # עיגול למעלה כדי להימנע מ"0 דקות" בתצוגה כאשר נשארו שניות בודדות
            total_minutes = int((diff + 59) // 60)
            hours = int(total_minutes // 60)
            minutes = int(total_minutes % 60)
            if hours > 0:
                return f"{hours} שעות ו {minutes} דקות" if minutes > 0 else f"{hours} שעות"
            return f"{max(1, minutes)} דקות"
        except Exception:
            return "זמן לא ידוע"
    
    def _show_anti_spam_message(self, result, student):
        """הצגת הודעת אנטי-ספאם"""
        try:
            msg_type = result.get('type', 'warning')
            message = result.get('message', '')

            try:
                stage = int((result or {}).get('stage') or 1)
            except Exception:
                stage = 1
            if stage < 1:
                stage = 1

            # משך תצוגה – ברירת מחדל: אזהרה 6 שניות, חסימה 10 שניות
            display_sec = 6.0
            if str(msg_type).lower() == 'block':
                display_sec = 10.0
            try:
                cfg = self.load_app_config()
                if isinstance(cfg, dict):
                    if str(msg_type).lower() == 'block':
                        display_sec = float(cfg.get('anti_spam_block_display_sec', display_sec) or display_sec)
                    else:
                        display_sec = float(cfg.get('anti_spam_warning_display_sec', display_sec) or display_sec)
            except Exception:
                pass
            if display_sec < 2.0:
                display_sec = 2.0

            # שמירת מצב (אזהרה/חסימה) לאחר שחישבנו display_sec
            try:
                try:
                    sid = int((student or {}).get('id') or 0)
                except Exception:
                    sid = 0
                if sid > 0:
                    try:
                        rc = int((result or {}).get('rule_count') or 0)
                    except Exception:
                        rc = 0
                    try:
                        rm = int((result or {}).get('rule_minutes') or 0)
                    except Exception:
                        rm = 0
                    if rm <= 0:
                        rm = 1
                    try:
                        ridx = int((result or {}).get('rule_index') or 0)
                    except Exception:
                        ridx = 0

                    if str(msg_type).strip().lower() == 'warning':
                        if getattr(self, '_anti_spam_last_warning_state', None) is None:
                            self._anti_spam_last_warning_state = {}
                        self._anti_spam_last_warning_state[int(sid)] = {
                            'ts': float(time.time()),
                            'rule_index': int(ridx),
                            'rule_count': int(rc),
                            'minutes': int(rm),
                            'hold_until': float(time.time()) + float(display_sec or 6.0),
                            'stage': int(stage or 1),
                        }
                    elif str(msg_type).strip().lower() == 'block':
                        already_blocked = False
                        try:
                            already_blocked = bool((result or {}).get('already_blocked', False))
                        except Exception:
                            already_blocked = False
                        if not already_blocked:
                            if getattr(self, '_anti_spam_last_block_state', None) is None:
                                self._anti_spam_last_block_state = {}
                            self._anti_spam_last_block_state[int(sid)] = {
                                'ts': float(time.time()),
                                'rule_index': int(ridx),
                                'rule_count': int(rc),
                                'minutes': int(rm),
                                'hold_until': float(time.time()) + float(display_sec or 10.0),
                                'stage': int(stage or 1),
                            }
            except Exception:
                pass

            if msg_type == 'block':
                already_blocked = False
                try:
                    already_blocked = bool((result or {}).get('already_blocked', False))
                except Exception:
                    already_blocked = False

                # צבע חסימה לפי שלב: סט 1 כתום, סט 2+ אדום
                try:
                    stage_color = '#f39c12' if int(stage or 1) <= 1 else '#e74c3c'
                except Exception:
                    stage_color = '#e74c3c'

                try:
                    if hasattr(self, 'name_label'):
                        self.name_label.config(text="")
                    if hasattr(self, 'class_label'):
                        self.class_label.config(text="")
                    if hasattr(self, 'id_label'):
                        self.id_label.config(text="")
                    if hasattr(self, 'points_text_label'):
                        self.points_text_label.config(text="", fg=stage_color)
                    if hasattr(self, 'points_label'):
                        try:
                            self.points_label.config(
                                text="🚫 חסום",
                                fg=stage_color,
                                font=(self.ui_font_family, max(36, int(self.font_points * 1.25)), 'bold'),
                            )
                        except Exception:
                            self.points_label.config(text="🚫 חסום", fg=stage_color)
                    if hasattr(self, 'message_label'):
                        self.message_label.config(text="")
                    if hasattr(self, 'statistics_label'):
                        self.statistics_label.config(text="")
                    if hasattr(self, 'photo_label'):
                        self.photo_label.config(image="", text="")
                    self.current_photo_img = None
                    self.template1_photo_original = None
                except Exception:
                    pass

                overlay_text = str(message or '').strip()
                if already_blocked:
                    # כרטיס כבר חסום – הודעה קטנה ושקטה
                    self._show_anti_spam_overlay(overlay_text, kind=('blocked1' if int(stage or 1) <= 1 else 'blocked'), seconds=max(2.5, min(6.0, display_sec)), keep_name=False)
                else:
                    # חסימה חדשה – Overlay גדול
                    self._show_anti_spam_overlay(overlay_text, kind=('block1' if int(stage or 1) <= 1 else 'block'), seconds=display_sec, keep_name=False)
            else:
                first_name = student.get('first_name', '')
                last_name = student.get('last_name', '')
                full_name = f"{first_name} {last_name}".strip()
                self.name_label.config(text=full_name)
                class_name = student.get('class_name', '')
                if class_name:
                    self.class_label.config(text=f"כיתה: {class_name}")

                # ניקוי פריטי תלמיד קודם כדי שלא ייראו מאחורי ה-Overlay
                try:
                    if hasattr(self, 'id_label'):
                        self.id_label.config(text="")
                    if hasattr(self, 'points_label'):
                        self.points_label.config(text="")
                    if hasattr(self, 'points_text_label'):
                        self.points_text_label.config(text="")
                    if hasattr(self, 'message_label'):
                        self.message_label.config(text="")
                    if hasattr(self, 'statistics_label'):
                        self.statistics_label.config(text="")
                    if hasattr(self, 'photo_label'):
                        self.photo_label.config(image="", text="")
                    self.current_photo_img = None
                    self.template1_photo_original = None
                except Exception:
                    pass

                # Overlay גדול לאזהרה, לא מכסה את שם התלמיד
                overlay_text = str(message or '').strip()
                self._show_anti_spam_overlay(overlay_text, kind=('warning' if int(stage or 1) <= 1 else 'warning2'), seconds=display_sec, keep_name=True)

            # צליל ספאם (אזהרה/חסימה)
            silent = False
            try:
                silent = bool((result or {}).get('already_blocked', False))
            except Exception:
                silent = False

            if not silent:
                try:
                    self._apply_sound_settings_from_config(self.load_app_config())
                except Exception:
                    pass
                try:
                    # אם הכלל שחזר מהבדיקה כולל sound_key – נשתמש בו
                    rule_key = str((result or {}).get('sound_key') or '').strip()
                    if rule_key and self._play_sound_key(rule_key):
                        pass
                    else:
                        p = self._pick_random_from_sound_subfolder('לספאם')
                        self._play_sound_file(p)
                except Exception:
                    pass
            self.show_info()
            if getattr(self, 'background_template', None) == 'template1':
                try:
                    self._render_template1_overlay_from_widgets()
                except Exception:
                    pass
            # לא לקצר את התצוגה ביחס ל-Overlay
            try:
                self._schedule_hide_info(int(max(10000, display_sec * 1000.0)), reset_name_color=False)
            except Exception:
                self._schedule_hide_info(10000, reset_name_color=False)
        except Exception as e:
            print(f"שגיאה בהצגת הודעת אנטי-ספאם: {e}")


def _is_in_job_object():
    """בדיקה אם התהליך הנוכחי נמצא בתוך Windows Job Object."""
    try:
        if sys.platform != 'win32':
            return False
        import ctypes
        kernel32 = ctypes.windll.kernel32
        result = ctypes.c_int(0)
        kernel32.IsProcessInJob(kernel32.GetCurrentProcess(), None, ctypes.byref(result))
        return bool(result.value)
    except Exception:
        return False


def _relaunch_outside_job():
    """הפעלה מחדש של התהליך מחוץ ל-Job Object באמצעות CREATE_BREAKAWAY_FROM_JOB."""
    try:
        import subprocess
        CREATE_BREAKAWAY_FROM_JOB = 0x01000000
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        script = os.path.abspath(__file__)
        proc = subprocess.Popen(
            [sys.executable, script],
            cwd=os.path.dirname(script),
            creationflags=CREATE_BREAKAWAY_FROM_JOB | CREATE_NEW_PROCESS_GROUP,
        )
        return True
    except OSError:
        # CREATE_BREAKAWAY_FROM_JOB may fail if the job doesn't allow breakaway
        return False
    except Exception:
        return False


def main():
    """הפעלה רגילה של העמדה הציבורית, כולל בדיקת רישיון בתוך המחלקה."""
    try:
        import sp_logger
        sp_logger.install()
    except Exception:
        pass

    # אם התהליך נמצא בתוך Job Object (למשל כשהופעל דרך py.exe launcher),
    # נפעיל מחדש מחוץ ל-Job כדי למנוע הריגה כשתהליך אחר באותו Job יוצא.
    if os.environ.get('_SP_NO_JOB_RELAUNCH') != '1' and _is_in_job_object():
        os.environ['_SP_NO_JOB_RELAUNCH'] = '1'
        if _relaunch_outside_job():
            return  # התהליך החדש הופעל, נצא מהנוכחי
        # אם ה-relaunch נכשל, נמשיך לרוץ רגיל

    try:
        _debug_log('entered main()')
    except Exception:
        pass

    while True:
        _set_windows_dpi_awareness()
        try:
            _debug_log('before tk.Tk()')
        except Exception:
            pass
        root = tk.Tk()
        try:
            import sys
            base_dir = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
            candidates = [
                os.path.join(base_dir, 'icons', 'public.ico'),
                os.path.join(os.path.dirname(base_dir), 'icons', 'public.ico'),
            ]
            for p in candidates:
                if p and os.path.exists(p):
                    root.iconbitmap(p)
                    break
        except Exception:
            pass
        _force_tk_scaling_96dpi(root)
        try:
            tk_scale = None
            fpix = None
            try:
                tk_scale = root.tk.call('tk', 'scaling')
            except Exception:
                tk_scale = None
            try:
                fpix = root.winfo_fpixels('1i')
            except Exception:
                fpix = None
            _debug_log(
                f'main_metrics tk_scaling={tk_scale} fpixels_1i={fpix} screen={root.winfo_screenwidth()}x{root.winfo_screenheight()} win={root.winfo_width()}x{root.winfo_height()}'
            )
        except Exception:
            pass
        # DEBUG: wrap root.destroy to log caller
        import traceback as _tb_mod
        _orig_root_destroy = root.destroy
        def _logged_destroy(*a, **kw):
            try:
                stack = ''.join(_tb_mod.format_stack())
                _debug_log(f'root.destroy() CALLED\n{stack}')
            except Exception:
                pass
            return _orig_root_destroy(*a, **kw)
        root.destroy = _logged_destroy

        # --- מסך טעינה מיידי (אותו חלון – ללא רגע ריק) ---
        try:
            root.attributes('-fullscreen', True)
            root.configure(bg='#16213e')
            root.update_idletasks()

            _lf = tk.Frame(root, bg='#16213e')
            _lf.place(relx=0, rely=0, relwidth=1, relheight=1)

            _lc = tk.Frame(_lf, bg='#16213e')
            _lc.place(relx=0.5, rely=0.40, anchor='center')

            # עיגול התקדמות
            _sz, _pd = 150, 14
            _cv = tk.Canvas(_lc, width=_sz, height=_sz, bg='#16213e', highlightthickness=0)
            _cv.pack(pady=(0, 18))
            _cv.create_oval(_pd, _pd, _sz - _pd, _sz - _pd, outline='#2d3a5e', width=8)
            _arc = _cv.create_arc(_pd, _pd, _sz - _pd, _sz - _pd, start=90, extent=0, outline='#3498db', width=8, style='arc')
            _pct = _cv.create_text(_sz // 2, _sz // 2, text='0%', font=('Arial', 24, 'bold'), fill='white')

            tk.Label(_lc, text='\U0001F393', font=('Arial', 52), bg='#16213e', fg='white').pack(pady=(0, 2))
            tk.Label(_lc, text='נקודה טובה', font=('Arial', 26, 'bold'), bg='#16213e', fg='white').pack(pady=(0, 14))
            _st = tk.Label(_lc, text='מאתחל מערכת...', font=('Arial', 13), bg='#16213e', fg='#8899aa')
            _st.pack(pady=5)

            root._sp_loading = {
                'frame': _lf, 'canvas': _cv, 'arc': _arc,
                'pct': _pct, 'status': _st, 'sz': _sz, 'pd': _pd,
            }
            root.update()
        except Exception:
            pass

        try:
            app = PublicStation(root)
        except Exception as e:
            try:
                _debug_log("❌ PublicStation init failed: " + repr(e))
                _debug_log(traceback.format_exc())
            except Exception:
                pass
            try:
                messagebox.showerror("שגיאה", "העמדה הציבורית לא הצליחה להיפתח.\nבדוק את הקובץ public_station_startup.log לפרטים.")
            except Exception:
                pass
            try:
                root.destroy()
            except Exception:
                pass
            return

        # אם האתחול נכשל (למשל בגלל רישיון או ביטול הגדרת תיקיית רשת) – אל תריץ mainloop
        if getattr(app, "_init_failed", False):
            try:
                root.destroy()
            except Exception:
                pass
            return

        root.mainloop()
        _debug_log(f'mainloop returned, _restart_requested={getattr(app, "_restart_requested", "N/A")}, _init_failed={getattr(app, "_init_failed", "N/A")}')
        if not getattr(app, "_restart_requested", False):
            _debug_log('breaking out of main loop (no restart requested)')
            break
    # Force-kill background threads to prevent zombie processes holding WAL locks
    try:
        os._exit(0)
    except Exception:
        pass


def main_no_splash():
    """הפעלה ללא splash screen (לבדיקות)"""
    _set_windows_dpi_awareness()
    root = tk.Tk()
    app = PublicStation(root)
    root.mainloop()
    try:
        os._exit(0)
    except Exception:
        pass


if __name__ == "__main__":
    main()
