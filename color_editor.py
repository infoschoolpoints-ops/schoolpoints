"""
עורך הגדרות צבעים לטווחי נקודות
"""
import tkinter as tk
from tkinter import ttk, messagebox, colorchooser, filedialog
import json
import os
import shutil
import wave
import re

try:
    from sound_manager import SoundManager
except Exception:
    SoundManager = None

NO_SOUND_LABEL = "ללא צליל"


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

    # ניסיון שני: קובץ הגדרות במיקום נתוני משתמש (PROGRAMDATA/LOCALAPPDATA/APPDATA)
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


def _get_shared_folder_from_live_config(base_dir: str) -> str:
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
                return str(shared_folder)
    except Exception:
        pass
    return ""


class ColorEditor:
    def __init__(self, root):
        self.root = root
        self.root.title("🎵 הגדרות צלילים, צבעים ומטבעות - מערכת ניקוד")
        # חלון מעט יותר ריבועי וקומפקטי, כמו בדוגמה הרצויה
        self.root.geometry("900x620")
        self.root.configure(bg='#ecf0f1')
        try:
            self.root.minsize(860, 580)
        except Exception:
            pass
        self.root.resizable(True, True)

        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.settings_file = _get_color_settings_file(base_dir)
        self.ranges = []
        self.coins = []
        self.goal = {}
        self.event_sounds = {}
        self._sounds_index = {}
        self._sound_keys_sorted = []
        self._range_sound_keys = []
        self._preview_sound_manager = None
        self._preview_sound_manager_dir = ''
        
        self.load_settings()
        self.setup_ui()

    def _get_preview_sound_manager(self):
        if not SoundManager:
            return None
        try:
            sounds_dir = self._get_sounds_dir()
        except Exception:
            sounds_dir = ''
        try:
            if self._preview_sound_manager is None or str(self._preview_sound_manager_dir or '') != str(sounds_dir or ''):
                base_dir = os.path.dirname(os.path.abspath(__file__))
                self._preview_sound_manager = SoundManager(base_dir, sounds_dir=sounds_dir)
                self._preview_sound_manager_dir = str(sounds_dir or '')
        except Exception:
            self._preview_sound_manager = None
            self._preview_sound_manager_dir = ''
        return self._preview_sound_manager

    def _preview_sound_key(self, key_or_display: str) -> None:
        try:
            raw = str(key_or_display or '').strip()
        except Exception:
            raw = ''
        if not raw or raw == NO_SOUND_LABEL:
            return
        try:
            k = str((getattr(self, '_display_to_key', {}) or {}).get(raw, raw)).strip()
        except Exception:
            k = raw
        if not k:
            return

        try:
            p = str((getattr(self, '_sounds_index', {}) or {}).get(k, '') or '')
        except Exception:
            p = ''

        if not p:
            mgr = self._get_preview_sound_manager()
            if mgr is not None:
                try:
                    p = mgr.resolve_sound([k]) or ''
                except Exception:
                    p = ''

        if not p:
            return

        mgr = self._get_preview_sound_manager()
        if mgr is None:
            return
        try:
            mgr.play_sound(p, async_play=True)
        except Exception:
            pass

    def _sound_display(self, key: str) -> str:
        try:
            k = str(key or '').strip()
        except Exception:
            k = ''
        if not k:
            return NO_SOUND_LABEL
        try:
            return str((getattr(self, '_key_to_display', {}) or {}).get(k, k))
        except Exception:
            return str(k)

    def _sound_key_from_display(self, display: str) -> str:
        try:
            raw = str(display or '').strip()
        except Exception:
            raw = ''
        if not raw or raw == NO_SOUND_LABEL:
            return ''
        try:
            return str((getattr(self, '_display_to_key', {}) or {}).get(raw, raw)).strip()
        except Exception:
            return str(raw).strip()

    def _sound_folder_parts_for_event(self, event_key: str):
        try:
            k = str(event_key or '').strip()
        except Exception:
            k = ''
        mapping = {
            'swipe_ok': ['תיקופים רגילים'],
            'first_swipe': ['הראשונים לבונוס'],
            'time_bonus': ['לבונוס זמנים'],
            'tier_up_first_time': ['התפעלות'],
            'unknown_card': ['כרטיס לא מזוהה'],
            'teacher_bonus': ['כפיים'],
            'special_bonus': ['לבונוס מיוחד'],
        }
        return mapping.get(k) or []

    def _refresh_event_sound_combo(self, event_key: str) -> None:
        try:
            ev_key = str(event_key or '').strip()
        except Exception:
            ev_key = ''
        if not ev_key:
            return

        cb = None
        try:
            for c in (getattr(self, '_event_sound_combos', None) or []):
                try:
                    if str(getattr(c, '_event_key', '') or '').strip() == ev_key:
                        cb = c
                        break
                except Exception:
                    continue
        except Exception:
            cb = None

        if cb is None:
            return

        try:
            folder_parts = list(self._sound_folder_parts_for_event(ev_key) or [])
        except Exception:
            folder_parts = []

        try:
            if folder_parts:
                keys = list(self._list_sound_keys_in_folder(folder_parts) or [])
                displays = [str((getattr(self, '_key_to_display', {}) or {}).get(k, k)) for k in keys]
                cb.configure(values=[NO_SOUND_LABEL] + displays)
            else:
                cb.configure(values=[NO_SOUND_LABEL] + list(getattr(self, '_sound_displays_sorted', None) or []))
        except Exception:
            pass

        try:
            v = (getattr(self, '_event_sound_vars', {}) or {}).get(ev_key)
        except Exception:
            v = None
        if v is not None:
            try:
                k = str((self.event_sounds or {}).get(ev_key) or '').strip()
            except Exception:
                k = ''
            try:
                v.set(self._sound_display(k))
            except Exception:
                pass

    def _list_sound_keys_in_folder(self, folder_parts):
        sounds_dir = self._get_sounds_dir()
        base = os.path.join(sounds_dir, *(folder_parts or []))
        if not os.path.isdir(base):
            return []

        sounds = {}
        try:
            for root, _, files in os.walk(base):
                for filename in files:
                    if not str(filename).lower().endswith(('.wav', '.mp3', '.ogg')):
                        continue
                    key = os.path.splitext(filename)[0]
                    if not key:
                        continue
                    path = os.path.join(root, filename)
                    prev = sounds.get(key)
                    if not prev:
                        sounds[key] = path
                        continue
                    try:
                        ext = str(os.path.splitext(path)[1] or '').lower()
                    except Exception:
                        ext = ''
                    try:
                        prev_ext = str(os.path.splitext(prev)[1] or '').lower()
                    except Exception:
                        prev_ext = ''
                    priorities = {'.wav': 30, '.mp3': 20, '.ogg': 10}
                    if int(priorities.get(ext, 0)) > int(priorities.get(prev_ext, 0)):
                        sounds[key] = path
        except Exception:
            sounds = {}

        try:
            return sorted(list(sounds.keys()), key=lambda x: str(x))
        except Exception:
            return list(sounds.keys())

    def _get_sounds_dir(self) -> str:
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__))
        except Exception:
            base_dir = '.'
        try:
            shared = _get_shared_folder_from_live_config(base_dir)
        except Exception:
            shared = ""
        if shared:
            return os.path.join(shared, 'sounds')
        return os.path.join(base_dir, 'sounds')

    def _scan_sounds(self) -> None:
        sounds_dir = self._get_sounds_dir()
        sounds = {}
        try:
            if os.path.exists(sounds_dir):
                for root, _, files in os.walk(sounds_dir):
                    for filename in files:
                        if not filename.lower().endswith(('.wav', '.mp3', '.ogg')):
                            continue
                        key = os.path.splitext(filename)[0]
                        if not key:
                            continue
                        path = os.path.join(root, filename)
                        prev = sounds.get(key)
                        if not prev:
                            sounds[key] = path
                            continue
                        try:
                            ext = str(os.path.splitext(path)[1] or '').lower()
                        except Exception:
                            ext = ''
                        try:
                            prev_ext = str(os.path.splitext(prev)[1] or '').lower()
                        except Exception:
                            prev_ext = ''
                        priorities = {'.wav': 30, '.mp3': 20, '.ogg': 10}
                        if int(priorities.get(ext, 0)) > int(priorities.get(prev_ext, 0)):
                            sounds[key] = path
        except Exception:
            sounds = {}

        self._sounds_index = sounds
        try:
            self._sound_keys_sorted = sorted(list(sounds.keys()), key=lambda x: str(x))
        except Exception:
            self._sound_keys_sorted = list(sounds.keys())

        try:
            def _format_duration(p: str) -> str:
                try:
                    ext = str(os.path.splitext(p)[1] or '').lower()
                except Exception:
                    ext = ''
                if ext != '.wav':
                    return ""
                try:
                    with wave.open(p, 'rb') as wf:
                        frames = wf.getnframes()
                        fr = wf.getframerate() or 0
                    if not fr:
                        return ""
                    total_ms = int((float(frames) / float(fr)) * 1000.0)
                    s = int(total_ms // 1000)
                    ms = int(total_ms % 1000)
                    return f"{s}.{ms:03d}"
                except Exception:
                    return ""

            self._display_to_key = {}
            self._key_to_display = {}
            for k, p in (sounds or {}).items():
                try:
                    d = _format_duration(p)
                    if d:
                        disp = f"{k} ({d})"
                    else:
                        disp = str(k)
                except Exception:
                    disp = str(k)
                self._key_to_display[str(k)] = disp
                self._display_to_key[str(disp)] = str(k)

            self._sound_displays_sorted = [self._key_to_display.get(k, k) for k in (self._sound_keys_sorted or [])]
        except Exception:
            self._display_to_key = {}
            self._key_to_display = {}
            self._sound_displays_sorted = list(self._sound_keys_sorted or [])

        try:
            self._range_sound_keys = []
            self._range_sound_keys = list(self._list_sound_keys_in_folder(['תיקופים רגילים']) or [])
        except Exception:
            self._range_sound_keys = []

        try:
            self._range_sound_displays = [self._key_to_display.get(k, k) for k in (self._range_sound_keys or [])]
        except Exception:
            self._range_sound_displays = list(self._range_sound_keys or [])

        try:
            for cb in (getattr(self, '_event_sound_combos', None) or []):
                try:
                    event_key = getattr(cb, '_event_key', None)
                except Exception:
                    event_key = None

                try:
                    folder_parts = list(self._sound_folder_parts_for_event(event_key) or [])
                except Exception:
                    folder_parts = []

                try:
                    if folder_parts:
                        keys = list(self._list_sound_keys_in_folder(folder_parts) or [])
                        displays = [str((getattr(self, '_key_to_display', {}) or {}).get(k, k)) for k in keys]
                        cb.configure(values=[NO_SOUND_LABEL] + displays)
                    else:
                        cb.configure(values=[NO_SOUND_LABEL] + list(getattr(self, '_sound_displays_sorted', None) or []))
                except Exception:
                    pass
        except Exception:
            pass
    
    def load_settings(self):
        """טעינת הגדרות מקובץ"""
        try:
            if os.path.exists(self.settings_file):
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.ranges = data.get('color_ranges', [])
                    self.coins = data.get('coins') or []
                    self.goal = data.get('goal') or {}
                    self.event_sounds = data.get('event_sounds') or {}
                    # תאימות לאחור – אם אין שדה kind, נניח שמדובר במטבע רגיל
                    for coin in self.coins:
                        if 'kind' not in coin:
                            coin['kind'] = 'coin'
            else:
                # ברירת מחדל
                self.ranges = [
                    {"min": 0, "max": 49, "color": "#95a5a6", "name": "אפור"},
                    {"min": 50, "max": 99, "color": "#3498db", "name": "כחול"},
                    {"min": 100, "max": 199, "color": "#2ecc71", "name": "ירוק"},
                    {"min": 200, "max": 999999, "color": "#f39c12", "name": "זהב"}
                ]
                self.coins = []
                self.goal = {}
                self.event_sounds = {}
        except Exception as e:
            messagebox.showerror("שגיאה", f"לא ניתן לטעון הגדרות: {e}")

        try:
            self._scan_sounds()
        except Exception:
            pass

        try:
            mgr = None
            try:
                mgr = self._get_preview_sound_manager()
            except Exception:
                mgr = None

            changed_any = False

            def _fix_key(old_key: str) -> str:
                try:
                    k = str(old_key or '').strip()
                except Exception:
                    k = ''
                if not k:
                    return ''
                try:
                    if k in (getattr(self, '_sounds_index', {}) or {}):
                        return k
                except Exception:
                    pass
                if mgr is None:
                    return k
                try:
                    p = mgr.resolve_sound([k])
                except Exception:
                    p = None
                if not p:
                    return k
                try:
                    nk = os.path.splitext(os.path.basename(str(p)))[0]
                except Exception:
                    nk = ''
                if nk:
                    return str(nk).strip()
                return k

            try:
                if isinstance(self.ranges, list):
                    for r in self.ranges:
                        if not isinstance(r, dict):
                            continue
                        old = str(r.get('sound_key') or '').strip()
                        if not old:
                            continue
                        new = _fix_key(old)
                        if new and new != old:
                            r['sound_key'] = new
                            changed_any = True
            except Exception:
                pass

            try:
                if isinstance(self.event_sounds, dict):
                    for ek in list(self.event_sounds.keys()):
                        old = str(self.event_sounds.get(ek) or '').strip()
                        if not old:
                            continue
                        new = _fix_key(old)
                        if new and new != old:
                            self.event_sounds[ek] = new
                            changed_any = True
            except Exception:
                pass

            if changed_any:
                try:
                    self.save_settings()
                except Exception:
                    pass
        except Exception:
            pass

        # ברירת מחדל: 6 הטווחים הראשונים יקבלו 001..006 אם קיימים
        try:
            if isinstance(self.ranges, list) and self.ranges:
                folder_keys = list(self._list_sound_keys_in_folder(['תיקופים רגילים']) or [])
                for i in range(min(6, len(self.ranges))):
                    r = self.ranges[i]
                    if not isinstance(r, dict):
                        continue
                    existing = str(r.get('sound_key') or '').strip()
                    if existing:
                        continue
                    if i < len(folder_keys):
                        r['sound_key'] = str(folder_keys[i]).strip()
        except Exception:
            pass

        try:
            if not isinstance(self.event_sounds, dict):
                self.event_sounds = {}

            sounds_dir = self._get_sounds_dir()

            def _ensure_event_from_root_file(event_key: str, filename: str) -> None:
                try:
                    cur = str((self.event_sounds or {}).get(event_key) or '').strip()
                except Exception:
                    cur = ''
                if cur:
                    return
                try:
                    p = os.path.join(sounds_dir, filename)
                    if os.path.exists(p):
                        self.event_sounds[event_key] = os.path.splitext(os.path.basename(p))[0]
                except Exception:
                    return

            def _first_key_in_folder(parts):
                try:
                    base = os.path.join(sounds_dir, *parts)
                    if not os.path.isdir(base):
                        return ""
                    for _root, _, files in os.walk(base):
                        for fn in (files or []):
                            if str(fn).lower().endswith(('.wav', '.mp3', '.ogg')):
                                return os.path.splitext(str(fn))[0]
                except Exception:
                    return ""
                return ""

            def _ensure_event_from_folder(event_key: str, folder_parts, preferred_filename: str = ""):
                try:
                    cur = str((self.event_sounds or {}).get(event_key) or '').strip()
                except Exception:
                    cur = ''
                if cur:
                    return

                if preferred_filename:
                    try:
                        p = os.path.join(sounds_dir, *folder_parts, preferred_filename)
                        if os.path.exists(p):
                            self.event_sounds[event_key] = os.path.splitext(os.path.basename(p))[0]
                            return
                    except Exception:
                        pass

                k = _first_key_in_folder(folder_parts)
                if k:
                    self.event_sounds[event_key] = str(k).strip()

            _ensure_event_from_folder('unknown_card', ['כרטיס לא מזוהה'])
            _ensure_event_from_folder('swipe_ok', ['תיקופים רגילים'])
            _ensure_event_from_folder('first_swipe', ['הראשונים לבונוס'])
            _ensure_event_from_folder('time_bonus', ['לבונוס זמנים'])
            _ensure_event_from_folder('tier_up_first_time', ['התפעלות'])

            try:
                for k in ('chimes', 'tada', 'טדה', 'ding'):
                    if k in (self._sounds_index or {}):
                        if not str((self.event_sounds or {}).get('teacher_bonus') or '').strip():
                            self.event_sounds['teacher_bonus'] = k
                        break
            except Exception:
                pass

            try:
                for k in ('טדה', 'tada', 'chimes', 'ding'):
                    if k in (self._sounds_index or {}):
                        if not str((self.event_sounds or {}).get('special_bonus') or '').strip():
                            self.event_sounds['special_bonus'] = k
                        break
            except Exception:
                pass
        except Exception:
            pass
    
    def save_settings(self):
        """שמירת הגדרות לקובץ"""
        try:
            data = {"color_ranges": self.ranges, "coins": self.coins, "goal": self.goal, "event_sounds": self.event_sounds}
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            messagebox.showerror("שגיאה", f"לא ניתן לשמור הגדרות: {e}")
            return False
    
    def setup_ui(self):
        """בניית ממשק המשתמש"""
        # כותרת
        header = tk.Frame(self.root, bg='#2c3e50', height=50)
        header.pack(fill=tk.X)
        
        tk.Label(
            header,
            text="🎵 עורך צלילים, צבעים ומטבעות",
            font=('Arial', 16, 'bold'),
            bg='#2c3e50',
            fg='white'
        ).pack(pady=10)
        
        # הסבר
        info_frame = tk.Frame(self.root, bg='#ecf0f1')
        info_frame.pack(fill=tk.X, padx=15, pady=5)
        
        tk.Label(
            info_frame,
            text="קבע צלילים וצבעים לטווחי נקודות, ומטבעות/יהלומים בעמדה הציבורית",
            font=('Arial', 10),
            bg='#ecf0f1',
            fg='#7f8c8d'
        ).pack()
        
        # לשוניות עבור טווחי צבעים ומטבעות/יהלומים
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        ranges_tab = tk.Frame(notebook, bg='#ecf0f1')
        coins_tab = tk.Frame(notebook, bg='#ecf0f1')
        goals_tab = tk.Frame(notebook, bg='#ecf0f1')
        events_tab = tk.Frame(notebook, bg='#ecf0f1')

        notebook.add(ranges_tab, text="צלילים וצבעים")
        notebook.add(coins_tab, text="מטבעות ויהלומים")
        notebook.add(goals_tab, text="יעדים")
        notebook.add(events_tab, text="צלילי אירועים")

        # מסגרת טווחים בטאב הראשון
        ranges_frame = tk.Frame(ranges_tab, bg='#ecf0f1')
        ranges_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=5)
        
        # כותרות
        headers = tk.Frame(ranges_frame, bg='#ecf0f1')
        headers.pack(fill=tk.X, pady=5)
        
        # חשוב: pack(side=RIGHT) מצייר את הפריטים בסדר הפוך. לכן סדר יצירה מותאם לתצוגה.
        tk.Label(headers, text="מינימום", font=('Arial', 10, 'bold'), bg='#ecf0f1', width=10).pack(side=tk.RIGHT, padx=5)
        tk.Label(headers, text="מקסימום", font=('Arial', 10, 'bold'), bg='#ecf0f1', width=10).pack(side=tk.RIGHT, padx=5)
        tk.Label(headers, text="שם", font=('Arial', 10, 'bold'), bg='#ecf0f1', width=10).pack(side=tk.RIGHT, padx=5)
        tk.Label(headers, text="צבע", font=('Arial', 10, 'bold'), bg='#ecf0f1', width=10).pack(side=tk.RIGHT, padx=5)
        tk.Label(headers, text="צליל", font=('Arial', 10, 'bold'), bg='#ecf0f1', width=12).pack(side=tk.RIGHT, padx=5)
        
        # אזור גלילה לטווחים
        canvas = tk.Canvas(ranges_frame, bg='#ecf0f1', highlightthickness=0)
        scrollbar = ttk.Scrollbar(ranges_frame, orient="vertical", command=canvas.yview)
        self.scrollable_frame = tk.Frame(canvas, bg='#ecf0f1')
        
        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.LEFT, fill=tk.Y)
        
        # הצגת טווחים
        self.refresh_ranges()
        
        # טאב שני – מטבעות ויהלומים
        coins_header = tk.Frame(coins_tab, bg='#ecf0f1')
        coins_header.pack(fill=tk.X, padx=15, pady=5)
        
        tk.Label(
            coins_header,
            text="מטבעות ויהלומים (מבוססי נקודות)",
            font=('Arial', 11, 'bold'),
            bg='#ecf0f1',
            fg='#2c3e50'
        ).pack(side=tk.RIGHT)

        headers = tk.Frame(coins_tab, bg='#ecf0f1')
        headers.pack(fill=tk.X, padx=15, pady=(0, 5))
        # חשוב: pack(side=RIGHT) מצייר את הפריטים בסדר הפוך. לכן סדר יצירה מותאם לתצוגה.
        tk.Label(headers, text="צבע", font=('Arial', 10, 'bold'), bg='#ecf0f1', width=10).pack(side=tk.RIGHT, padx=5)
        tk.Label(headers, text="שם (רשות)", font=('Arial', 10, 'bold'), bg='#ecf0f1', width=12).pack(side=tk.RIGHT, padx=5)
        tk.Label(headers, text="סכום", font=('Arial', 10, 'bold'), bg='#ecf0f1', width=10).pack(side=tk.RIGHT, padx=5)
        tk.Label(headers, text="סוג", font=('Arial', 10, 'bold'), bg='#ecf0f1', width=10).pack(side=tk.RIGHT, padx=5)
        
        self.coins_frame = tk.Frame(coins_tab, bg='#ecf0f1')
        self.coins_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=(0, 5))
        
        self.refresh_coins()

        # טאב רביעי – צלילי אירועים
        events_header = tk.Frame(events_tab, bg='#ecf0f1')
        events_header.pack(fill=tk.X, padx=15, pady=8)
        tk.Label(
            events_header,
            text="צלילים לאירועים בעמדה הציבורית",
            font=('Arial', 11, 'bold'),
            bg='#ecf0f1',
            fg='#2c3e50'
        ).pack(side=tk.RIGHT)

        events_body_container = tk.Frame(events_tab, bg='#ecf0f1')
        events_body_container.pack(fill=tk.BOTH, expand=True, padx=15, pady=(0, 10))

        events_canvas = tk.Canvas(events_body_container, bg='#ecf0f1', highlightthickness=0)
        events_scrollbar = ttk.Scrollbar(events_body_container, orient="vertical", command=events_canvas.yview)
        events_scrollable_frame = tk.Frame(events_canvas, bg='#ecf0f1')

        events_scrollable_frame.bind(
            "<Configure>",
            lambda e: events_canvas.configure(scrollregion=events_canvas.bbox("all"))
        )

        events_canvas.create_window((0, 0), window=events_scrollable_frame, anchor="nw")
        events_canvas.configure(yscrollcommand=events_scrollbar.set)

        events_canvas.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        events_scrollbar.pack(side=tk.LEFT, fill=tk.Y)

        events_body = events_scrollable_frame

        tk.Label(
            events_body,
            text="בחר צליל לכל אירוע (מתוך תיקיית sounds). אם לא מוגדר – תישאר ברירת מחדל.",
            font=('Arial', 10),
            bg='#ecf0f1',
            fg='#7f8c8d'
        ).pack(anchor='e', pady=(0, 10))

        sound_values = [NO_SOUND_LABEL]
        try:
            sound_values += list(getattr(self, '_sound_displays_sorted', None) or [])
        except Exception:
            pass

        self._event_sound_combos = []
        self._event_sound_vars = {}

        def add_event_row(key: str, label: str):
            row = tk.Frame(events_body, bg='#ecf0f1')
            row.pack(fill=tk.X, pady=6)

            folder_parts = []
            try:
                folder_parts = list(self._sound_folder_parts_for_event(key) or [])
            except Exception:
                folder_parts = []

            local_values = [NO_SOUND_LABEL]
            try:
                if folder_parts:
                    keys = list(self._list_sound_keys_in_folder(folder_parts) or [])
                    local_values += [str((getattr(self, '_key_to_display', {}) or {}).get(k, k)) for k in keys]
                else:
                    local_values += list(getattr(self, '_sound_displays_sorted', None) or [])
            except Exception:
                local_values = [NO_SOUND_LABEL]

            try:
                _k = str((self.event_sounds or {}).get(key) or '').strip()
            except Exception:
                _k = ''
            var = tk.StringVar(value=self._sound_display(_k))
            try:
                self._event_sound_vars[str(key)] = var
            except Exception:
                pass

            combo = ttk.Combobox(
                row,
                textvariable=var,
                values=local_values,
                state='readonly',
                width=30
            )
            combo.pack(side=tk.LEFT, padx=5)
            try:
                combo._event_key = str(key)
            except Exception:
                pass
            try:
                self._event_sound_combos.append(combo)
            except Exception:
                pass

            tk.Button(
                row,
                text="📁",
                command=lambda k=key: self._set_event_sound_from_file(k),
                font=('Arial', 10),
                bg='#bdc3c7',
                fg='black',
                width=3,
                cursor='hand2'
            ).pack(side=tk.LEFT, padx=5)

            tk.Button(
                row,
                text="PLAY ▶",
                command=lambda v=var: self._preview_sound_key(v.get()),
                font=('Arial', 10, 'bold'),
                bg='#27ae60',
                fg='black',
                width=7,
                cursor='hand2'
            ).pack(side=tk.LEFT, padx=5)

            def on_change(event=None, k=key, v=var):
                try:
                    if not isinstance(self.event_sounds, dict):
                        self.event_sounds = {}
                    raw = (v.get() or '').strip()
                    mapped = self._sound_key_from_display(raw)
                    self.event_sounds[k] = mapped
                except Exception:
                    pass

            combo.bind('<<ComboboxSelected>>', on_change)

            def _refresh_combo_values(_event=None, cb=combo, ev_key=key):
                try:
                    self._scan_sounds()
                except Exception:
                    pass
                try:
                    folder_parts = list(self._sound_folder_parts_for_event(ev_key) or [])
                except Exception:
                    folder_parts = []
                try:
                    if folder_parts:
                        keys = list(self._list_sound_keys_in_folder(folder_parts) or [])
                        displays = [str((getattr(self, '_key_to_display', {}) or {}).get(k, k)) for k in keys]
                        cb.configure(values=[NO_SOUND_LABEL] + displays)
                    else:
                        cb.configure(values=[NO_SOUND_LABEL] + list(getattr(self, '_sound_displays_sorted', None) or []))
                except Exception:
                    pass

            combo.bind('<Button-1>', _refresh_combo_values)

            tk.Label(row, text=label, font=('Arial', 10, 'bold'), bg='#ecf0f1').pack(side=tk.RIGHT)

        add_event_row('unknown_card', 'כרטיס לא מזוהה')
        add_event_row('swipe_ok', 'תיקוף רגיל')
        add_event_row('teacher_bonus', 'בונוס מורה')
        add_event_row('special_bonus', 'בונוס מיוחד (מאסטר)')
        add_event_row('first_swipe', 'מתקף ראשון')
        add_event_row('time_bonus', 'בונוס זמנים')
        add_event_row('tier_up_first_time', 'דרגה חדשה (פעם ראשונה)')

        # שורת כפתורים בטאב "צלילי אירועים" – שמור / סגור ללא שמירה
        events_buttons = tk.Frame(events_tab, bg='#ecf0f1')
        events_buttons.pack(fill=tk.X, padx=15, pady=5)
        tk.Button(
            events_buttons,
            text="❌ סגור ללא שמירה",
            command=self.root.destroy,
            font=('Arial', 10),
            bg='#95a5a6',
            fg='white',
            padx=15,
            pady=8,
            cursor='hand2'
        ).pack(side=tk.LEFT, padx=5)
        tk.Button(
            events_buttons,
            text="💾 שמור",
            command=self.save_and_close,
            font=('Arial', 11, 'bold'),
            bg='#3498db',
            fg='white',
            padx=30,
            pady=8,
            cursor='hand2'
        ).pack(side=tk.RIGHT, padx=5)

        # טאב שלישי – יעדים
        goals_header = tk.Frame(goals_tab, bg='#ecf0f1')
        goals_header.pack(fill=tk.X, padx=15, pady=8)
        tk.Label(
            goals_header,
            text="יעד נקודות (פס התקדמות לתלמיד)",
            font=('Arial', 11, 'bold'),
            bg='#ecf0f1',
            fg='#2c3e50'
        ).pack(side=tk.RIGHT)

        goals_body = tk.Frame(goals_tab, bg='#ecf0f1')
        goals_body.pack(fill=tk.BOTH, expand=True, padx=15, pady=(0, 10))

        def _safe_int(v, default=0):
            try:
                return int(v)
            except Exception:
                return default

        def _safe_float(v, default=0.0):
            try:
                return float(v)
            except Exception:
                return default

        enabled_var = tk.IntVar(value=1 if int(self.goal.get('enabled', 0) or 0) == 1 else 0)
        mode_var = tk.StringVar(value=str(self.goal.get('mode') or 'absolute'))
        abs_points_var = tk.StringVar(value=str(_safe_int(self.goal.get('absolute_points', 100), 100)))
        rel_percent_var = tk.StringVar(value=str(_safe_float(self.goal.get('relative_percent', 80), 80)))
        show_percent_var = tk.IntVar(value=1 if int(self.goal.get('show_percent', 1) or 0) == 1 else 0)
        filled_color_var = tk.StringVar(value=str(self.goal.get('filled_color') or '#2ecc71'))
        empty_color_var = tk.StringVar(value=str(self.goal.get('empty_color') or '#ecf0f1'))
        border_color_var = tk.StringVar(value=str(self.goal.get('border_color') or '#2c3e50'))

        enabled_row = tk.Frame(goals_body, bg='#ecf0f1')
        enabled_row.pack(fill=tk.X, pady=6)
        tk.Checkbutton(enabled_row, text="הפעל פס יעד", variable=enabled_var, bg='#ecf0f1').pack(side=tk.RIGHT)

        mode_row = tk.Frame(goals_body, bg='#ecf0f1')
        mode_row.pack(fill=tk.X, pady=8)
        tk.Label(mode_row, text="סוג יעד:", font=('Arial', 10, 'bold'), bg='#ecf0f1').pack(side=tk.RIGHT, padx=6)
        tk.Radiobutton(mode_row, text="יעד מוחלט", variable=mode_var, value='absolute', bg='#ecf0f1').pack(side=tk.RIGHT, padx=8)
        tk.Radiobutton(mode_row, text="יעד יחסי", variable=mode_var, value='relative', bg='#ecf0f1').pack(side=tk.RIGHT, padx=8)
        tk.Radiobutton(mode_row, text="יעד יחסי לכיתה", variable=mode_var, value='relative_class', bg='#ecf0f1').pack(side=tk.RIGHT, padx=8)
        tk.Radiobutton(mode_row, text="מקסימום נקודות אפשרי", variable=mode_var, value='max_points_possible', bg='#ecf0f1').pack(side=tk.RIGHT, padx=8)

        abs_row = tk.Frame(goals_body, bg='#ecf0f1')
        abs_row.pack(fill=tk.X, pady=6)
        tk.Label(abs_row, text="יעד מוחלט (נקודות):", bg='#ecf0f1', font=('Arial', 10)).pack(side=tk.RIGHT, padx=6)
        abs_entry = tk.Entry(abs_row, textvariable=abs_points_var, width=10, font=('Arial', 10), justify='right')
        abs_entry.pack(side=tk.RIGHT, padx=6)

        rel_row = tk.Frame(goals_body, bg='#ecf0f1')
        rel_row.pack(fill=tk.X, pady=6)
        tk.Label(rel_row, text="יעד יחסי (% ממקסימום נקודות):", bg='#ecf0f1', font=('Arial', 10)).pack(side=tk.RIGHT, padx=6)
        rel_entry = tk.Entry(rel_row, textvariable=rel_percent_var, width=10, font=('Arial', 10), justify='right')
        rel_entry.pack(side=tk.RIGHT, padx=6)

        def _refresh_goal_mode_fields(*_):
            try:
                mode = (mode_var.get() or '').strip().lower()
                if mode in ('relative', 'relative_class'):
                    try:
                        abs_entry.configure(state='disabled')
                    except Exception:
                        pass
                    try:
                        rel_entry.configure(state='normal')
                    except Exception:
                        pass
                elif mode == 'max_points_possible':
                    try:
                        abs_entry.configure(state='disabled')
                    except Exception:
                        pass
                    try:
                        rel_entry.configure(state='disabled')
                    except Exception:
                        pass
                else:
                    try:
                        abs_entry.configure(state='normal')
                    except Exception:
                        pass
                    try:
                        rel_entry.configure(state='disabled')
                    except Exception:
                        pass
            except Exception:
                pass

        show_row = tk.Frame(goals_body, bg='#ecf0f1')
        show_row.pack(fill=tk.X, pady=8)
        tk.Checkbutton(show_row, text="הצג טקסט אחוזים על הפס", variable=show_percent_var, bg='#ecf0f1').pack(side=tk.RIGHT)

        colors_frame = tk.Frame(goals_body, bg='#ecf0f1')
        colors_frame.pack(fill=tk.X, pady=10)

        def choose_goal_color(var: tk.StringVar, title: str):
            color = colorchooser.askcolor(initialcolor=var.get(), title=title, parent=self.root)
            if color and color[1]:
                var.set(color[1])
                try:
                    self.root.lift()
                    self.root.focus_force()
                except Exception:
                    pass

        tk.Label(colors_frame, text="צבע מלא:", bg='#ecf0f1', font=('Arial', 10)).pack(side=tk.RIGHT, padx=6)
        tk.Button(colors_frame, text="", bg=filled_color_var.get(), width=10,
                  command=lambda: (choose_goal_color(filled_color_var, "בחר צבע מלא"), None)).pack(side=tk.RIGHT, padx=6)

        tk.Label(colors_frame, text="צבע ריק:", bg='#ecf0f1', font=('Arial', 10)).pack(side=tk.RIGHT, padx=6)
        tk.Button(colors_frame, text="", bg=empty_color_var.get(), width=10,
                  command=lambda: (choose_goal_color(empty_color_var, "בחר צבע ריק"), None)).pack(side=tk.RIGHT, padx=6)

        tk.Label(colors_frame, text="צבע מסגרת:", bg='#ecf0f1', font=('Arial', 10)).pack(side=tk.RIGHT, padx=6)
        tk.Button(colors_frame, text="", bg=border_color_var.get(), width=10,
                  command=lambda: (choose_goal_color(border_color_var, "בחר צבע מסגרת"), None)).pack(side=tk.RIGHT, padx=6)

        def _apply_color_btn_bg(frame: tk.Frame):
            try:
                for w in frame.winfo_children():
                    if isinstance(w, tk.Button) and str(w.cget('text') or '') == '':
                        # עדכון צבעים על הכפתורים הריקים
                        pass
            except Exception:
                pass

        def _refresh_goal_color_buttons(*_):
            try:
                # עדכון צבע הרקע של הכפתורים (3 כפתורים ברצף)
                btns = [w for w in colors_frame.winfo_children() if isinstance(w, tk.Button)]
                if len(btns) >= 3:
                    btns[0].configure(bg=filled_color_var.get())
                    btns[1].configure(bg=empty_color_var.get())
                    btns[2].configure(bg=border_color_var.get())
            except Exception:
                pass

        try:
            filled_color_var.trace_add('write', _refresh_goal_color_buttons)
            empty_color_var.trace_add('write', _refresh_goal_color_buttons)
            border_color_var.trace_add('write', _refresh_goal_color_buttons)
        except Exception:
            pass
        _refresh_goal_color_buttons()

        def persist_goal_settings():
            mode = mode_var.get().strip() or 'absolute'
            abs_points = _safe_int(abs_points_var.get(), 0)
            rel_pct = _safe_float(rel_percent_var.get(), 0.0)
            # גבולות בסיסיים
            if rel_pct < 0:
                rel_pct = 0.0
            if rel_pct > 100:
                rel_pct = 100.0
            if abs_points < 0:
                abs_points = 0
            self.goal = {
                'enabled': 1 if int(enabled_var.get() or 0) == 1 else 0,
                'mode': mode,
                'absolute_points': abs_points,
                'relative_percent': rel_pct,
                'show_percent': 1 if int(show_percent_var.get() or 0) == 1 else 0,
                'filled_color': filled_color_var.get(),
                'empty_color': empty_color_var.get(),
                'border_color': border_color_var.get(),
            }

        # שמירה אוטומטית של goal לתוך self.goal כשמשנים שדות (לפני לחיצה על "שמור")
        for var in (enabled_var, mode_var, abs_points_var, rel_percent_var, show_percent_var, filled_color_var, empty_color_var, border_color_var):
            try:
                var.trace_add('write', lambda *_: persist_goal_settings())
            except Exception:
                pass
        persist_goal_settings()

        # נטרול/הדלקת שדות לפי סוג יעד
        try:
            mode_var.trace_add('write', _refresh_goal_mode_fields)
        except Exception:
            pass
        _refresh_goal_mode_fields()

        # שורת כפתורים בטאב "יעדים" – שמור / סגור ללא שמירה
        goals_buttons = tk.Frame(goals_tab, bg='#ecf0f1')
        goals_buttons.pack(fill=tk.X, padx=15, pady=5)
        tk.Button(
            goals_buttons,
            text="❌ סגור ללא שמירה",
            command=self.root.destroy,
            font=('Arial', 10),
            bg='#95a5a6',
            fg='white',
            padx=15,
            pady=8,
            cursor='hand2'
        ).pack(side=tk.LEFT, padx=5)
        tk.Button(
            goals_buttons,
            text="💾 שמור",
            command=self.save_and_close,
            font=('Arial', 11, 'bold'),
            bg='#3498db',
            fg='white',
            padx=30,
            pady=8,
            cursor='hand2'
        ).pack(side=tk.RIGHT, padx=5)

        # שורת כפתורים בטאב "צבעים" – הוסף טווח / שמור / סגור ללא שמירה
        ranges_buttons = tk.Frame(ranges_tab, bg='#ecf0f1')
        ranges_buttons.pack(fill=tk.X, padx=15, pady=5)
        tk.Button(
            ranges_buttons,
            text="❌ סגור ללא שמירה",
            command=self.root.destroy,
            font=('Arial', 10),
            bg='#95a5a6',
            fg='white',
            padx=15,
            pady=8,
            cursor='hand2'
        ).pack(side=tk.LEFT, padx=5)
        tk.Button(
            ranges_buttons,
            text="💾 שמור",
            command=self.save_and_close,
            font=('Arial', 11, 'bold'),
            bg='#3498db',
            fg='white',
            padx=30,
            pady=8,
            cursor='hand2'
        ).pack(side=tk.RIGHT, padx=5)
        tk.Button(
            ranges_buttons,
            text="➕ הוסף טווח",
            command=self.add_range,
            font=('Arial', 11),
            bg='#27ae60',
            fg='white',
            padx=20,
            pady=8,
            cursor='hand2'
        ).pack(side=tk.RIGHT, padx=5)

        # שורת כפתורים בטאב "מטבעות ויהלומים" – הוסף מטבע / שמור / סגור ללא שמירה
        coins_buttons = tk.Frame(coins_tab, bg='#ecf0f1')
        coins_buttons.pack(fill=tk.X, padx=15, pady=5)
        tk.Button(
            coins_buttons,
            text="❌ סגור ללא שמירה",
            command=self.root.destroy,
            font=('Arial', 10),
            bg='#95a5a6',
            fg='white',
            padx=15,
            pady=8,
            cursor='hand2'
        ).pack(side=tk.LEFT, padx=5)
        tk.Button(
            coins_buttons,
            text="💾 שמור",
            command=self.save_and_close,
            font=('Arial', 11, 'bold'),
            bg='#3498db',
            fg='white',
            padx=30,
            pady=8,
            cursor='hand2'
        ).pack(side=tk.RIGHT, padx=5)
        tk.Button(
            coins_buttons,
            text="➕ הוסף מטבע",
            command=self.add_coin,
            font=('Arial', 11),
            bg='#27ae60',
            fg='white',
            padx=20,
            pady=8,
            cursor='hand2'
        ).pack(side=tk.RIGHT, padx=5)
    
    def refresh_ranges(self):
        """רענון תצוגת הטווחים"""
        # ניקוי
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()
        
        # הצגת כל טווח
        for i, range_data in enumerate(self.ranges):
            self.create_range_row(i, range_data)

    def _import_sound_file(self) -> str:
        return self._import_sound_file_to_folder([])

    def _import_sound_file_to_folder(self, folder_parts) -> str:
        try:
            initial_dir = os.path.join(self._get_sounds_dir(), *(folder_parts or []))
        except Exception:
            initial_dir = None

        path = filedialog.askopenfilename(
            title="בחר קובץ צליל",
            initialdir=initial_dir,
            filetypes=[
                ("Sound files", "*.wav;*.mp3;*.ogg"),
                ("All files", "*.*"),
            ],
            parent=self.root
        )
        if not path:
            return ""

        try:
            sounds_dir = os.path.join(self._get_sounds_dir(), *(folder_parts or []))
            os.makedirs(sounds_dir, exist_ok=True)
            filename = os.path.basename(path)
            dest = os.path.join(sounds_dir, filename)
            if os.path.abspath(path) != os.path.abspath(dest):
                shutil.copy2(path, dest)
            key = os.path.splitext(filename)[0]
            return key
        except Exception as e:
            messagebox.showerror("שגיאה", f"לא ניתן להעתיק קובץ צליל: {e}")
            return ""

    def _set_range_sound_from_file(self, index: int) -> None:
        key = self._import_sound_file_to_folder(['תיקופים רגילים'])
        if not key:
            return

        try:
            self.ranges[index]['sound_key'] = str(key).strip()
        except Exception:
            return

        try:
            self._scan_sounds()
        except Exception:
            pass

        try:
            self.refresh_ranges()
        except Exception:
            pass

    def _set_event_sound_from_file(self, event_key: str) -> None:
        try:
            folder_parts = list(self._sound_folder_parts_for_event(event_key) or [])
        except Exception:
            folder_parts = []
        key = self._import_sound_file_to_folder(folder_parts)
        if not key:
            return
        try:
            if not isinstance(self.event_sounds, dict):
                self.event_sounds = {}
            self.event_sounds[str(event_key)] = str(key).strip()
        except Exception:
            return
        try:
            self._scan_sounds()
        except Exception:
            pass
        try:
            self.save_settings()
        except Exception:
            pass

        try:
            self._refresh_event_sound_combo(event_key)
        except Exception:
            pass
    
    def refresh_coins(self):
        for widget in self.coins_frame.winfo_children():
            widget.destroy()
        for i, coin_data in enumerate(self.coins):
            self.create_coin_row(i, coin_data)
    
    def create_range_row(self, index, range_data):
        """יצירת שורה עבור טווח"""
        row = tk.Frame(self.scrollable_frame, bg='white', relief=tk.RAISED, bd=1)
        row.pack(fill=tk.X, pady=5, padx=5)
        
        # כפתור מחיקה
        tk.Button(
            row,
            text="🗑️",
            command=lambda: self.delete_range(index),
            font=('Arial', 10),
            bg='#e74c3c',
            fg='white',
            width=3,
            cursor='hand2'
        ).pack(side=tk.LEFT, padx=5, pady=5)
        
        # כפתור בחירת צבע
        color_btn = tk.Button(
            row,
            text="",
            bg=range_data['color'],
            width=10,
            command=lambda: self.choose_color(index),
            cursor='hand2',
            relief=tk.RAISED,
            bd=2
        )

        # בחירת צליל
        sound_key = str(range_data.get('sound_key') or '').strip()
        sound_var = tk.StringVar(value=self._sound_display(sound_key))

        # למדרג נקודות: מאפשרים לבחור רק 001-006
        sound_values = [NO_SOUND_LABEL]
        try:
            sound_values += list(getattr(self, '_range_sound_displays', None) or [])
        except Exception:
            pass

        sound_combo = ttk.Combobox(
            row,
            textvariable=sound_var,
            values=sound_values,
            state='readonly',
            width=12
        )

        tk.Button(
            row,
            text="📁",
            command=lambda idx=index: self._set_range_sound_from_file(idx),
            font=('Arial', 10),
            bg='#bdc3c7',
            fg='black',
            width=3,
            cursor='hand2'
        ).pack(side=tk.RIGHT, padx=5, pady=5)

        tk.Button(
            row,
            text="PLAY ▶",
            command=lambda v=sound_var: self._preview_sound_key(v.get()),
            font=('Arial', 10, 'bold'),
            bg='#27ae60',
            fg='black',
            width=7,
            cursor='hand2'
        ).pack(side=tk.RIGHT, padx=0, pady=5)

        def on_sound_changed(event=None, idx=index, var=sound_var):
            try:
                raw = (var.get() or '').strip()
                mapped = self._sound_key_from_display(raw)
                self.ranges[idx]['sound_key'] = mapped
            except Exception:
                pass

        sound_combo.bind('<<ComboboxSelected>>', on_sound_changed)

        def _refresh_range_combo_values(_event=None, cb=sound_combo):
            try:
                self._scan_sounds()
            except Exception:
                pass
            try:
                cb.configure(values=[NO_SOUND_LABEL] + list(getattr(self, '_range_sound_displays', None) or []))
            except Exception:
                pass

        sound_combo.bind('<Button-1>', _refresh_range_combo_values)
        
        # שם
        name_entry = tk.Entry(row, font=('Arial', 10), width=12)
        name_entry.insert(0, range_data['name'])
        name_entry.bind('<FocusOut>', lambda e, idx=index: self.update_name(idx, name_entry.get()))
        name_entry.bind('<KeyRelease>', lambda e, idx=index: self.update_name(idx, name_entry.get()))
        name_entry.bind('<Return>', lambda e, idx=index: self.update_name(idx, name_entry.get()))
        name_entry.pack(side=tk.RIGHT, padx=5, pady=5)
        
        # מקסימום
        max_entry = tk.Entry(row, font=('Arial', 10), width=10)
        max_entry.insert(0, str(range_data['max']) if range_data['max'] < 999999 else "∞")
        max_entry.bind('<FocusOut>', lambda e, idx=index: self.update_max(idx, max_entry.get()))
        max_entry.bind('<KeyRelease>', lambda e, idx=index: self.update_max(idx, max_entry.get()))
        max_entry.bind('<Return>', lambda e, idx=index: self.update_max(idx, max_entry.get()))
        max_entry.pack(side=tk.RIGHT, padx=5, pady=5)
        
        # מינימום
        min_entry = tk.Entry(row, font=('Arial', 10), width=10)
        min_entry.insert(0, str(range_data['min']))
        min_entry.bind('<FocusOut>', lambda e, idx=index: self.update_min(idx, min_entry.get()))
        min_entry.bind('<KeyRelease>', lambda e, idx=index: self.update_min(idx, min_entry.get()))
        min_entry.bind('<Return>', lambda e, idx=index: self.update_min(idx, min_entry.get()))
        min_entry.pack(side=tk.RIGHT, padx=5, pady=5)

        color_btn.pack(side=tk.RIGHT, padx=5, pady=5)
        sound_combo.pack(side=tk.RIGHT, padx=5, pady=5)
    
    def create_coin_row(self, index, coin_data):
        row = tk.Frame(self.coins_frame, bg='white', relief=tk.RAISED, bd=1)
        row.pack(fill=tk.X, pady=3, padx=5)
        
        tk.Button(
            row,
            text="🗑️",
            command=lambda: self.delete_coin(index),
            font=('Arial', 10),
            bg='#e74c3c',
            fg='white',
            width=3,
            cursor='hand2'
        ).pack(side=tk.LEFT, padx=5, pady=5)
        
        # כפתור בחירת צבע
        color_btn = tk.Button(
            row,
            text="",
            bg=coin_data.get('color', '#f1c40f'),
            width=10,
            command=lambda: self.choose_coin_color(index),
            cursor='hand2',
            relief=tk.RAISED,
            bd=2
        )
        color_btn.pack(side=tk.RIGHT, padx=5, pady=5)
        
        name_entry = tk.Entry(row, font=('Arial', 10), width=12)
        name_entry.insert(0, coin_data.get('name', ''))
        name_entry.bind('<FocusOut>', lambda e, idx=index: self.update_coin_name(idx, name_entry.get()))
        name_entry.pack(side=tk.RIGHT, padx=5, pady=5)
        
        # ערך בנקודות – שדה ריק כאשר הערך אינו חיובי
        value_entry = tk.Entry(row, font=('Arial', 10), width=10)
        raw_value = coin_data.get('value', 0)
        try:
            raw_int = int(raw_value)
        except Exception:
            raw_int = 0
        if raw_int > 0:
            value_entry.insert(0, str(raw_int))
        else:
            value_entry.insert(0, "")
        value_entry.bind('<FocusOut>', lambda e, idx=index: self.update_coin_value(idx, value_entry.get()))
        value_entry.bind('<KeyRelease>', lambda e, idx=index: self.update_coin_value(idx, value_entry.get()))
        value_entry.bind('<Return>', lambda e, idx=index: self.update_coin_value(idx, value_entry.get()))
        value_entry.pack(side=tk.RIGHT, padx=5, pady=5)

        # סוג – מטבע / יהלום
        kind_map = {'coin': 'מטבע', 'diamond': 'יהלום'}
        inv_kind_map = {v: k for k, v in kind_map.items()}
        current_kind = coin_data.get('kind', 'coin')
        kind_text = kind_map.get(current_kind, 'מטבע')
        kind_var = tk.StringVar(value=kind_text)

        type_combo = ttk.Combobox(
            row,
            textvariable=kind_var,
            values=list(kind_map.values()),
            state='readonly',
            width=10
        )
        type_combo.pack(side=tk.RIGHT, padx=5, pady=5)

        def on_kind_changed(event=None, idx=index, var=kind_var, inv_map=inv_kind_map):
            selected = var.get()
            kind = inv_map.get(selected, 'coin')
            self.update_coin_kind(idx, kind)

        type_combo.bind('<<ComboboxSelected>>', on_kind_changed)
    
    def choose_color(self, index):
        """בחירת צבע"""
        color = colorchooser.askcolor(
            initialcolor=self.ranges[index]['color'],
            title="בחר צבע",
            parent=self.root
        )
        if color[1]:  # אם נבחר צבע
            self.ranges[index]['color'] = color[1]
            self.refresh_ranges()
            try:
                self.root.lift()
                self.root.focus_force()
            except Exception:
                pass
    
    def choose_coin_color(self, index):
        color = colorchooser.askcolor(
            initialcolor=self.coins[index].get('color', '#f1c40f'),
            title="בחר צבע",
            parent=self.root
        )
        if color[1]:
            self.coins[index]['color'] = color[1]
            self.refresh_coins()
            try:
                self.root.lift()
                self.root.focus_force()
            except Exception:
                pass
    
    def update_min(self, index, value):
        """עדכון מינימום"""
        try:
            mn, mx = self._parse_range_text(value)
            if mn is None and mx is None:
                return
            if mn is not None and mx is not None and int(mx) < int(mn):
                mn, mx = mx, mn
            if mn is not None:
                self.ranges[index]['min'] = int(mn)
            if mx is not None and ('-' in str(value) or '–' in str(value) or '—' in str(value)):
                self.ranges[index]['max'] = int(mx)
        except:
            pass
    
    def update_max(self, index, value):
        """עדכון מקסימום"""
        try:
            mn, mx = self._parse_range_text(value)
            if mn is None and mx is None:
                return
            if mn is not None and mx is not None and int(mx) < int(mn):
                mn, mx = mx, mn
            if mx is not None:
                self.ranges[index]['max'] = int(mx)
            if mn is not None and ('-' in str(value) or '–' in str(value) or '—' in str(value)):
                self.ranges[index]['min'] = int(mn)
        except:
            pass

    def _parse_range_text(self, text):
        try:
            s = str(text or '').strip()
        except Exception:
            s = ''
        if not s:
            return None, None
        if s == '∞':
            return None, 999999
        try:
            s_norm = s.replace('״', '').replace('"', '').strip().lower()
        except Exception:
            s_norm = str(s).strip().lower()
        if s_norm in ('*', 'inf', 'infinite', 'unlimited', 'אין הגבלה', 'ללא הגבלה', 'בלי הגבלה'):
            return None, 999999
        try:
            s2 = s.replace(',', '').replace('–', '-').replace('—', '-')
        except Exception:
            s2 = s
        try:
            nums = re.findall(r"\d+", s2)
        except Exception:
            nums = []
        if not nums:
            return None, None
        try:
            vals = [int(n) for n in nums]
        except Exception:
            return None, None
        if len(vals) == 1:
            return vals[0], vals[0]
        return vals[0], vals[-1]
    
    def update_name(self, index, value):
        """עדכון שם"""
        self.ranges[index]['name'] = value
    
    def update_coin_value(self, index, value):
        try:
            text = (value or "").strip()
            if not text:
                self.coins[index]['value'] = 0
                return
            self.coins[index]['value'] = int(text)
        except Exception:
            pass
    
    def update_coin_name(self, index, value):
        self.coins[index]['name'] = value

    def update_coin_kind(self, index, kind):
        if 0 <= index < len(self.coins):
            self.coins[index]['kind'] = kind
    
    def delete_range(self, index):
        """מחיקת טווח"""
        if len(self.ranges) <= 1:
            messagebox.showwarning("אזהרה", "חייב להיות לפחות טווח אחד")
            return
        
        if messagebox.askyesno("אישור מחיקה", "האם למחוק טווח זה?"):
            del self.ranges[index]
            self.refresh_ranges()
    
    def add_range(self):
        """הוספת טווח חדש"""
        new_range = {
            "min": 0,
            "max": 50,
            "color": "#95a5a6",
            "name": "חדש"
        }
        self.ranges.append(new_range)
        self.refresh_ranges()
    
    def delete_coin(self, index):
        if 0 <= index < len(self.coins):
            del self.coins[index]
            self.refresh_coins()
    
    def add_coin(self):
        new_coin = {
            "value": 0,
            "color": "#f1c40f",
            "name": "חדש",
            "kind": "coin"
        }
        self.coins.append(new_coin)
        self.refresh_coins()
    
    def save_and_close(self):
        """שמירה וסגירה"""
        # מיון לפי מינימום
        self.ranges.sort(key=lambda x: x['min'])
        self.coins.sort(key=lambda x: x.get('value', 0))
        try:
            if not isinstance(self.goal, dict):
                self.goal = {}
        except Exception:
            self.goal = {}
        
        if self.save_settings():
            messagebox.showinfo(
                "הצלחה",
                "ההגדרות נשמרו בהצלחה!\n\n"
                "הפעל מחדש את העמדה הציבורית כדי לראות את השינויים."
            )
            self.root.destroy()


def main():
    root = tk.Tk()
    app = ColorEditor(root)
    root.mainloop()


if __name__ == "__main__":
    main()
