"""
מנהל הודעות - ממשק גרפי
"""
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, filedialog
from messages import MessagesDB
from database import Database

import os
import shutil
import uuid

try:
    import jewish_calendar
except Exception:
    jewish_calendar = None

# סימני BIDI לתיקון כיוון טקסט עברי
RLE = '\u202b'  # Right-to-Left Embedding
PDF = '\u202c'  # Pop Directional Formatting
RLM = '\u200f'

def fix_rtl_text(text):
    """תיקון כיוון טקסט עברי עם סימני קריאה בצד הנכון (לתצוגה בלבד)."""
    if text and text.strip():
        return RLE + text + RLM + PDF
    return text

def strip_rtl_marks(text: str) -> str:
    """הסרת סימוני RLE/PDF מטקסט לפני עריכה כדי למנוע בעיות סימון בעברית."""
    if not text:
        return text
    return text.replace(RLE, '').replace(PDF, '')


def _strip_image_icon_prefix(text: str) -> str:
    """מנקה סמל 🖼 שמוצמד לטקסט (בדרך כלל לתצוגה בלבד) כדי שלא יצטבר בשמירה/עריכה."""
    try:
        t = str(text or '')
    except Exception:
        return str(text or '')

    while True:
        s = t.lstrip()
        if s.startswith('🖼️'):
            t = s[len('🖼️'):].lstrip()
            continue
        if s.startswith('🖼'):
            t = s[len('🖼'):].lstrip()
            continue
        break

    return t


class ToggleSwitch(tk.Frame):
    def __init__(self, master, variable=None, on_color="#1e90ff",
                 off_color="#bdc3c7", width=40, height=20, command=None, **kwargs):
        super().__init__(master, width=width, height=height, bg=master.cget('background'), **kwargs)
        self.variable = variable or tk.BooleanVar(value=False)
        self.on_color = on_color
        self.off_color = off_color
        self.command = command

        self.canvas = tk.Canvas(
            self,
            width=width,
            height=height,
            highlightthickness=0,
            bd=0,
            bg=master.cget('background')
        )
        self.canvas.pack()
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.configure(cursor="hand2")

        self._width = width
        self._height = height
        self._draw()

    def _draw(self):
        self.canvas.delete("all")
        is_on = bool(self.variable.get())
        bg_color = self.on_color if is_on else self.off_color
        w = self._width
        h = self._height
        r = h // 2

        self.canvas.create_oval(0, 0, h, h, outline="", fill=bg_color)
        self.canvas.create_oval(w - h, 0, w, h, outline="", fill=bg_color)
        self.canvas.create_rectangle(r, 0, w - r, h, outline="", fill=bg_color)

        x0 = (w - h) if is_on else 0
        self.canvas.create_oval(x0 + 2, 2, x0 + h - 2, h - 2, outline="", fill="#ffffff")

    def _on_click(self, event):
        self.variable.set(not self.variable.get())
        self._draw()
        if self.command:
            try:
                self.command()
            except Exception:
                pass


def _open_date_picker_ddmmyyyy(parent, target_var: tk.StringVar):
    picker = tk.Toplevel(parent)
    picker.title("בחר תאריך")
    picker.transient(parent)
    picker.grab_set()
    picker.resizable(False, False)

    pf = tk.Frame(picker, padx=10, pady=10)
    pf.pack(fill=tk.BOTH, expand=True)
    tk.Label(pf, text=fix_rtl_text("בחר תאריך"), font=('Arial', 10, 'bold')).pack(pady=(0, 6))

    from datetime import date as _date
    today = _date.today()
    d0, m0, y0 = today.day, today.month, today.year

    try:
        cur = str(target_var.get() or '').strip()
    except Exception:
        cur = ''
    try:
        if cur and '.' in cur:
            parts = cur.split('.')
            if len(parts) == 3:
                d0 = int(parts[0])
                m0 = int(parts[1])
                y0 = int(parts[2])
    except Exception:
        d0, m0, y0 = today.day, today.month, today.year

    rowp = tk.Frame(pf)
    rowp.pack(pady=(0, 6))
    yv = tk.StringVar(value=str(y0))
    mv = tk.StringVar(value=str(m0))
    dv = tk.StringVar(value=str(d0))
    tk.Entry(rowp, textvariable=dv, width=4, justify='center').pack(side=tk.LEFT)
    tk.Label(rowp, text='.').pack(side=tk.LEFT)
    tk.Entry(rowp, textvariable=mv, width=4, justify='center').pack(side=tk.LEFT)
    tk.Label(rowp, text='.').pack(side=tk.LEFT)
    tk.Entry(rowp, textvariable=yv, width=6, justify='center').pack(side=tk.LEFT)

    def _ok_date():
        try:
            dd = int(dv.get())
            mm = int(mv.get())
            yy = int(yv.get())
            dsel = _date(yy, mm, dd)
        except Exception:
            messagebox.showwarning('שגיאה', 'תאריך לא תקין')
            return
        target_var.set(f"{dsel.day:02d}.{dsel.month:02d}.{dsel.year:04d}")
        picker.destroy()

    btns = tk.Frame(pf)
    btns.pack(pady=(2, 0))
    tk.Button(btns, text='אישור', command=_ok_date, width=10).pack(side=tk.LEFT, padx=5)
    tk.Button(btns, text='ביטול', command=picker.destroy, width=10).pack(side=tk.LEFT, padx=5)

    picker.wait_window()


class MessagesManager:
    def __init__(self, root):
        self.root = root
        self.root.title("ניהול הודעות - מערכת ניקוד")
        self.root.geometry("800x600")
        self.root.configure(bg='#ecf0f1')
        
        # השתמש באותו מסד נתונים כמו המערכת הראשית
        self.db = Database()
        self.messages_db = MessagesDB(self.db.db_path)

        # דגל פנימי כדי לא לבצע bind_all לקיצורי טקסט יותר מפעם אחת
        self._global_text_shortcuts_bound = False
        
        # מסגרת כרטיסיות
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # 2 כרטיסיות (הודעות פרטיות עברו לטבלה הראשית)
        self.setup_static_tab()
        self.setup_threshold_tab()
        self.setup_news_tab()
        self.setup_time_bonus_messages_tab()
        self.setup_ads_tab()

    def setup_time_bonus_messages_tab(self):
        tab = tk.Frame(self.notebook, bg='#ecf0f1')
        self.notebook.add(tab, text="⏰ בונוס זמנים")

        tk.Label(tab, text=fix_rtl_text("הודעת 'הגעת ראשון להיום'"),
                 font=('Arial', 14, 'bold'), bg='#ecf0f1').pack(pady=10)

        try:
            from admin_station import AdminStation
            cfg = AdminStation.load_app_config_static() or {}
        except Exception:
            cfg = {}

        cur = cfg.get('time_bonus_first_today', {}) if isinstance(cfg, dict) else {}
        if not isinstance(cur, dict):
            cur = {}

        enabled_var = tk.IntVar(value=1 if bool(cur.get('enabled', True)) else 0)
        mode_var = tk.StringVar(value=str(cur.get('mode', 'first_overall') or 'first_overall'))
        n_var = tk.StringVar(value=str(cur.get('n', 1) or 1))
        text_var = tk.StringVar(value=str(cur.get('text', '*הגעת ראשון להיום!*') or '*הגעת ראשון להיום!*'))

        frm = tk.Frame(tab, bg='#ecf0f1')
        frm.pack(fill=tk.X, padx=20, pady=10)

        tk.Checkbutton(frm, text=fix_rtl_text("הפעל הודעה"), variable=enabled_var, bg='#ecf0f1',
                       font=('Arial', 11)).pack(anchor='e', pady=(0, 10))

        tk.Label(frm, text=fix_rtl_text('מצב:'), font=('Arial', 11), bg='#ecf0f1').pack(anchor='e')
        mode_cb = ttk.Combobox(frm, textvariable=mode_var, state='readonly', width=30)
        mode_map = {
            'ראשון בכלל המערכת': 'first_overall',
            'X ראשונים בכלל המערכת': 'first_n_overall',
            'ראשון לכל כיתה': 'first_per_class',
            'X ראשונים לכל כיתה': 'first_n_per_class',
        }
        inv_mode_map = {v: k for (k, v) in mode_map.items()}
        mode_cb['values'] = tuple(mode_map.keys())
        try:
            mode_var.set(inv_mode_map.get(str(mode_var.get() or '').strip(), 'ראשון בכלל המערכת'))
        except Exception:
            mode_var.set('ראשון בכלל המערכת')
        mode_cb.pack(anchor='e', pady=(4, 10))

        tk.Label(frm, text=fix_rtl_text("כמה ראשונים (למצבי 'X ראשונים')"), font=('Arial', 11), bg='#ecf0f1').pack(anchor='e')
        tk.Entry(frm, textvariable=n_var, font=('Arial', 11), justify='right', width=8).pack(anchor='e', pady=(4, 10))

        tk.Label(frm, text=fix_rtl_text("טקסט ההודעה (אפשר לשנות):"), font=('Arial', 11), bg='#ecf0f1').pack(anchor='e')
        txt = tk.Text(frm, height=3, width=50, font=('Arial', 12), wrap=tk.WORD)
        txt.pack(fill=tk.X, pady=(6, 10))
        try:
            txt.insert('1.0', text_var.get())
        except Exception:
            pass
        try:
            self.setup_text_edit_menu(txt)
        except Exception:
            pass

        help_text = (
            "בחר מצב להצגת התוספת 'הגעת ראשון להיום'\n"
            "אפשר לבחור: ראשון בכלל המערכת / X ראשונים בכלל המערכת / ראשון לכל כיתה / X ראשונים לכל כיתה"
        )
        tk.Label(frm, text=fix_rtl_text(help_text), font=('Arial', 9), bg='#ecf0f1', fg='#7f8c8d', justify='right').pack(anchor='e', pady=(0, 8))

        max_len = 60
        counter_lbl = tk.Label(frm, text='', font=('Arial', 9), bg='#ecf0f1', fg='#7f8c8d', justify='right')
        counter_lbl.pack(anchor='e', pady=(0, 6))

        def _enforce_text_limit(_event=None):
            try:
                cur_txt = str(txt.get('1.0', 'end-1c') or '')
            except Exception:
                cur_txt = ''
            if len(cur_txt) > int(max_len):
                try:
                    txt.delete('1.0', 'end')
                    txt.insert('1.0', cur_txt[:int(max_len)])
                except Exception:
                    pass
                cur_txt = cur_txt[:int(max_len)]
            try:
                left = int(max_len) - int(len(cur_txt))
            except Exception:
                left = 0
            try:
                if left <= 0:
                    counter_lbl.config(text=fix_rtl_text(f"מקסימום {max_len} תווים (הגעת למקסימום)"), fg='#e74c3c')
                else:
                    counter_lbl.config(text=fix_rtl_text(f"מקסימום {max_len} תווים (נשארו {left})"), fg='#7f8c8d')
            except Exception:
                pass

        try:
            txt.bind('<KeyRelease>', _enforce_text_limit)
        except Exception:
            pass
        _enforce_text_limit()

        def _save():
            try:
                try:
                    n_val = int(float(str(n_var.get() or '1').strip() or '1'))
                except Exception:
                    n_val = 1
                if n_val < 1:
                    n_val = 1

                try:
                    new_text = str(txt.get('1.0', 'end-1c') or '').strip()
                except Exception:
                    new_text = '*הגעת ראשון להיום!*'
                if not new_text:
                    new_text = '*הגעת ראשון להיום!*'

                new_cfg = dict(cfg) if isinstance(cfg, dict) else {}
                try:
                    mode_code = mode_map.get(str(mode_var.get() or '').strip(), 'first_overall')
                except Exception:
                    mode_code = 'first_overall'
                new_cfg['time_bonus_first_today'] = {
                    'enabled': True if int(enabled_var.get() or 0) == 1 else False,
                    'mode': str(mode_code or 'first_overall').strip(),
                    'n': int(n_val),
                    'text': str(new_text),
                }
                from admin_station import AdminStation
                AdminStation.save_app_config_static(new_cfg)
                messagebox.showinfo('נשמר', 'ההגדרות נשמרו')
            except Exception as e:
                messagebox.showerror('שגיאה', str(e))

        btns = tk.Frame(tab, bg='#ecf0f1')
        btns.pack(pady=10)
        tk.Button(btns, text='💾 שמור', command=_save, bg='#27ae60', fg='white', font=('Arial', 12, 'bold'), padx=22, pady=8).pack(side=tk.LEFT, padx=6)
    
    def setup_static_tab(self):
        """כרטיסייה: הודעות סטטיות"""
        tab = tk.Frame(self.notebook, bg='#ecf0f1')
        self.notebook.add(tab, text="📢 הודעות כלליות")
        
        # כותרת
        tk.Label(tab, text="הודעות כלליות (מופיעות לכולם)", 
                font=('Arial', 14, 'bold'), bg='#ecf0f1').pack(pady=10)
        
        # רשימת הודעות
        frame_list = tk.Frame(tab, bg='white')
        frame_list.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        self.static_tree = ttk.Treeview(frame_list, columns=('message', 'when', 'status'), show='headings', height=7)
        self.static_tree.heading('message', text='הודעה')
        self.static_tree.heading('when', text='מתי')
        self.static_tree.heading('status', text='סטטוס')
        self.static_tree.column('message', width=400)
        self.static_tree.column('when', width=120)
        self.static_tree.column('status', width=80)
        self.static_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(frame_list, orient=tk.VERTICAL, command=self.static_tree.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.static_tree.config(yscrollcommand=scrollbar.set)
        
        # כפתורים
        btn_frame = tk.Frame(tab, bg='#ecf0f1')
        btn_frame.pack(pady=10)
        
        tk.Button(btn_frame, text="➕ הוסף הודעה", command=self.add_static, 
                 bg='#27ae60', fg='white', font=('Arial', 11), padx=20, pady=8).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="✏️ ערוך", command=self.edit_static,
                 bg='#3498db', fg='white', font=('Arial', 11), padx=20, pady=8).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="🔄 הפעל/בטל", command=self.toggle_static,
                 bg='#f39c12', fg='white', font=('Arial', 11), padx=20, pady=8).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="🗑️ מחק", command=self.delete_static,
                 bg='#e74c3c', fg='white', font=('Arial', 11), padx=20, pady=8).pack(side=tk.LEFT, padx=5)
        
        self.load_static_messages()
    
    def setup_threshold_tab(self):
        """כרטיסייה: הודעות לפי נקודות"""
        tab = tk.Frame(self.notebook, bg='#ecf0f1')
        self.notebook.add(tab, text="🎯 הודעות לפי נקודות")
        
        tk.Label(tab, text="הודעות לפי טווח נקודות", 
                font=('Arial', 14, 'bold'), bg='#ecf0f1').pack(pady=10)
        
        frame_list = tk.Frame(tab, bg='white')
        frame_list.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        self.threshold_tree = ttk.Treeview(frame_list, columns=('range', 'message', 'status'), show='headings', height=8)
        self.threshold_tree.heading('range', text='טווח נקודות')
        self.threshold_tree.heading('message', text='הודעה')
        self.threshold_tree.heading('status', text='סטטוס')
        self.threshold_tree.column('range', width=150)
        self.threshold_tree.column('message', width=450)
        self.threshold_tree.column('status', width=100)
        self.threshold_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(frame_list, orient=tk.VERTICAL, command=self.threshold_tree.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.threshold_tree.config(yscrollcommand=scrollbar.set)
        
        btn_frame = tk.Frame(tab, bg='#ecf0f1')
        btn_frame.pack(pady=10)
        
        tk.Button(btn_frame, text="➕ הוסף טווח", command=self.add_threshold,
                 bg='#27ae60', fg='white', font=('Arial', 11), padx=20, pady=8).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="✏️ ערוך", command=self.edit_threshold,
                 bg='#3498db', fg='white', font=('Arial', 11), padx=20, pady=8).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="🔄 הפעל/בטל", command=self.toggle_threshold,
                 bg='#f39c12', fg='white', font=('Arial', 11), padx=20, pady=8).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="🗑️ מחק", command=self.delete_threshold,
                 bg='#e74c3c', fg='white', font=('Arial', 11), padx=20, pady=8).pack(side=tk.LEFT, padx=5)
        
        self.load_threshold_messages()
    
    def setup_news_tab(self):
        """כרטיסייה: חדשות (לטיקר בעמדה הציבורית)"""
        tab = tk.Frame(self.notebook, bg='#ecf0f1')
        self.notebook.add(tab, text="📰 חדשות")

        tk.Label(
            tab,
            text="פריטי חדשות שיוצגו בטיקר בעמדה הציבורית (ברצף עם מפריד •)",
            font=('Arial', 12),
            bg='#ecf0f1'
        ).pack(pady=10)

        controls_frame = tk.Frame(tab, bg='#ecf0f1')
        controls_frame.pack(fill=tk.X, padx=20, pady=(0, 8))

        def get_bool_setting(key: str, default: str = '0') -> bool:
            try:
                return str(self.db.get_setting(key, default)) == '1'
            except Exception:
                return default == '1'

        def set_bool_setting(key: str, value: bool) -> None:
            try:
                self.db.set_setting(key, '1' if value else '0')
            except Exception:
                pass

        weekday_var = tk.BooleanVar(value=get_bool_setting('news_show_weekday', '0'))
        heb_date_var = tk.BooleanVar(value=get_bool_setting('news_show_hebrew_date', '0'))
        parsha_var = tk.BooleanVar(value=get_bool_setting('news_show_parsha', '0'))
        holidays_var = tk.BooleanVar(value=get_bool_setting('news_show_holidays', '0'))

        def persist_calendar_settings():
            set_bool_setting('news_show_weekday', bool(weekday_var.get()))
            set_bool_setting('news_show_hebrew_date', bool(heb_date_var.get()))
            set_bool_setting('news_show_parsha', bool(parsha_var.get()))
            set_bool_setting('news_show_holidays', bool(holidays_var.get()))

        row_a = tk.Frame(controls_frame, bg='#ecf0f1')
        row_a.pack(fill=tk.X, pady=(0, 4))
        tk.Label(row_a, text=fix_rtl_text("לוח יהודי (לטיקר):"), font=('Arial', 10, 'bold'), bg='#ecf0f1', anchor='e').pack(side=tk.RIGHT, padx=5)

        def _mk_toggle_row(parent, label_text: str, var: tk.BooleanVar):
            row = tk.Frame(parent, bg='#ecf0f1')
            row.pack(side=tk.RIGHT, padx=10)
            tk.Label(row, text=fix_rtl_text(label_text), font=('Arial', 10), bg='#ecf0f1', anchor='e').pack(side=tk.RIGHT)
            ToggleSwitch(row, variable=var, command=persist_calendar_settings).pack(side=tk.RIGHT, padx=4)

        _mk_toggle_row(row_a, "יום בשבוע", weekday_var)
        _mk_toggle_row(row_a, "תאריך יהודי", heb_date_var)
        _mk_toggle_row(row_a, "פרשת השבוע", parsha_var)
        _mk_toggle_row(row_a, "חגים", holidays_var)

        # Ticker speed control
        row_speed = tk.Frame(controls_frame, bg='#ecf0f1')
        row_speed.pack(fill=tk.X, pady=(8, 4))
        tk.Label(row_speed, text=fix_rtl_text("מהירות טיקר:"), font=('Arial', 10, 'bold'), bg='#ecf0f1', anchor='e').pack(side=tk.RIGHT, padx=5)
        
        def get_ticker_speed() -> str:
            try:
                from admin_station import AdminStation
                cfg = AdminStation.load_app_config_static() or {}
                return str(cfg.get('news_ticker_speed', 'normal') or 'normal')
            except Exception:
                return 'normal'
        
        def set_ticker_speed(speed: str):
            try:
                from admin_station import AdminStation
                cfg = AdminStation.load_app_config_static() or {}
                cfg['news_ticker_speed'] = str(speed or 'normal')
                AdminStation.save_app_config_static(cfg)
            except Exception:
                pass
        
        # שינוי סקאלה: מה שהיה עד היום "רגיל" תיחשב כ"איטי" (normal).
        # "רגיל" יהיה fast, ו"מהיר" יהיה very_fast.
        ticker_speed_map = {"מהיר": "very_fast", "רגיל": "fast", "איטי": "normal"}
        rev_ticker_speed = {v: k for k, v in ticker_speed_map.items()}
        ticker_speed_var = tk.StringVar(value=rev_ticker_speed.get(get_ticker_speed(), "איטי"))
        
        def on_speed_change(selection=None):
            # Get the current value from the variable (not from the parameter)
            speed = ticker_speed_map.get(ticker_speed_var.get(), 'normal')
            set_ticker_speed(speed)
        
        speed_menu = tk.OptionMenu(row_speed, ticker_speed_var, *list(ticker_speed_map.keys()))
        speed_menu.config(font=('Arial', 10), bg='white')
        speed_menu.pack(side=tk.RIGHT, padx=5)
        
        # Bind to variable changes to save automatically
        ticker_speed_var.trace_add('write', lambda *args: on_speed_change())

        # טבלה להצגת פריטי החדשות
        columns = ('טקסט', 'תאריכים', 'סטטוס')
        self.news_tree = ttk.Treeview(tab, columns=columns, show='headings', height=12)
        self.news_tree.heading('טקסט', text='טקסט חדשות')
        self.news_tree.heading('תאריכים', text='תאריכי תזמון')
        self.news_tree.heading('סטטוס', text='סטטוס')
        self.news_tree.column('טקסט', width=450)
        self.news_tree.column('תאריכים', width=200)
        self.news_tree.column('סטטוס', width=100)
        self.news_tree.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 10))

        btn_frame = tk.Frame(tab, bg='#ecf0f1')
        btn_frame.pack(pady=5)
        btn_row1 = tk.Frame(btn_frame, bg='#ecf0f1')
        btn_row1.pack()
        btn_row2 = tk.Frame(btn_frame, bg='#ecf0f1')
        btn_row2.pack(pady=(6, 0))

        tk.Button(
            btn_row1,
            text="➕ הוסף חדשות",
            command=self.add_news,
            bg='#27ae60',
            fg='white',
            font=('Arial', 11),
            padx=20,
            pady=8
        ).pack(side=tk.LEFT, padx=5)

        tk.Button(
            btn_row1,
            text="✏️ ערוך",
            command=self.edit_news,
            bg='#3498db',
            fg='white',
            font=('Arial', 11),
            padx=20,
            pady=8
        ).pack(side=tk.LEFT, padx=5)

        tk.Button(
            btn_row1,
            text="🗑️ מחק",
            command=self.delete_news,
            bg='#e74c3c',
            fg='white',
            font=('Arial', 11),
            padx=20,
            pady=8
        ).pack(side=tk.LEFT, padx=5)

        tk.Button(
            btn_row1,
            text="🔄 כבה/הפעל",
            command=self.toggle_news,
            bg='#f39c12',
            fg='white',
            font=('Arial', 11),
            padx=20,
            pady=8
        ).pack(side=tk.LEFT, padx=5)

        tk.Button(
            btn_row2,
            text="⬆ למעלה",
            command=self.move_news_up,
            bg='#95a5a6',
            fg='white',
            font=('Arial', 11),
            padx=16,
            pady=8
        ).pack(side=tk.LEFT, padx=5)

        tk.Button(
            btn_row2,
            text="⬇ למטה",
            command=self.move_news_down,
            bg='#95a5a6',
            fg='white',
            font=('Arial', 11),
            padx=16,
            pady=8
        ).pack(side=tk.LEFT, padx=5)

        self.load_news_items()

    def setup_ads_tab(self):
        """כרטיסייה: פרסומות (POP-UP בעמדה הציבורית)"""
        tab = tk.Frame(self.notebook, bg='#ecf0f1')
        self.notebook.add(tab, text="🪧 פרסומות")

        tk.Label(
            tab,
            text="פרסומות קופצות בעמדה הציבורית (מופיעות אחרי זמן ללא תיקופים)",
            font=('Arial', 12),
            bg='#ecf0f1'
        ).pack(pady=10)

        columns = ('טקסט', 'תאריכים', 'סטטוס')
        self.ads_tree = ttk.Treeview(tab, columns=columns, show='headings', height=12)
        self.ads_tree.heading('טקסט', text='טקסט פרסומת')
        self.ads_tree.heading('תאריכים', text='תאריכי תזמון')
        self.ads_tree.heading('סטטוס', text='סטטוס')
        self.ads_tree.column('טקסט', width=450)
        self.ads_tree.column('תאריכים', width=200)
        self.ads_tree.column('סטטוס', width=100)
        self.ads_tree.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 10))

        btn_frame = tk.Frame(tab, bg='#ecf0f1')
        btn_frame.pack(pady=5)

        btn_row1 = tk.Frame(btn_frame, bg='#ecf0f1')
        btn_row1.pack()
        btn_row2 = tk.Frame(btn_frame, bg='#ecf0f1')
        btn_row2.pack(pady=(6, 0))

        tk.Button(btn_row1, text="➕ הוסף פרסומת", command=self.add_ads,
                 bg='#27ae60', fg='white', font=('Arial', 11), padx=20, pady=8).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_row1, text="✏️ ערוך", command=self.edit_ads,
                 bg='#3498db', fg='white', font=('Arial', 11), padx=20, pady=8).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_row1, text="🗑️ מחק", command=self.delete_ads,
                 bg='#e74c3c', fg='white', font=('Arial', 11), padx=20, pady=8).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_row1, text="🔄 כבה/הפעל", command=self.toggle_ads,
                 bg='#f39c12', fg='white', font=('Arial', 11), padx=20, pady=8).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_row2, text="⬆ למעלה", command=self.move_ads_up,
                 bg='#95a5a6', fg='white', font=('Arial', 11), padx=16, pady=8).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_row2, text="⬇ למטה", command=self.move_ads_down,
                 bg='#95a5a6', fg='white', font=('Arial', 11), padx=16, pady=8).pack(side=tk.LEFT, padx=5)

        tk.Button(btn_row2, text="⚙ הגדרות הצגה אוטומטית", command=self.open_ads_auto_settings,
                 bg='#2c3e50', fg='white', font=('Arial', 11), padx=16, pady=8).pack(side=tk.LEFT, padx=5)

        self.load_ads_items()
    
    def setup_student_tab(self):
        """כרטיסייה: הודעות פרטיות"""
        tab = tk.Frame(self.notebook, bg='#ecf0f1')
        self.notebook.add(tab, text="👤 הודעות פרטיות")
        
        tk.Label(tab, text="הודעות פרטיות לתלמידים", 
                font=('Arial', 14, 'bold'), bg='#ecf0f1').pack(pady=10)
        
        frame_list = tk.Frame(tab, bg='white')
        frame_list.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        self.student_tree = ttk.Treeview(frame_list, columns=('student', 'message', 'status'), show='headings', height=8)
        self.student_tree.heading('student', text='תלמיד')
        self.student_tree.heading('message', text='הודעה')
        self.student_tree.heading('status', text='סטטוס')
        self.student_tree.column('student', width=200)
        self.student_tree.column('message', width=400)
        self.student_tree.column('status', width=100)
        self.student_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(frame_list, orient=tk.VERTICAL, command=self.student_tree.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.student_tree.config(yscrollcommand=scrollbar.set)
        
        btn_frame = tk.Frame(tab, bg='#ecf0f1')
        btn_frame.pack(pady=10)
        
        tk.Button(btn_frame, text="➕ הוסף הודעה", command=self.add_student_msg,
                 bg='#27ae60', fg='white', font=('Arial', 11), padx=20, pady=8).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="✏️ ערוך", command=self.edit_student_msg,
                 bg='#3498db', fg='white', font=('Arial', 11), padx=20, pady=8).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="🔄 הפעל/בטל", command=self.toggle_student_msg,
                 bg='#f39c12', fg='white', font=('Arial', 11), padx=20, pady=8).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="🗑️ מחק", command=self.delete_student_msg,
                 bg='#e74c3c', fg='white', font=('Arial', 11), padx=20, pady=8).pack(side=tk.LEFT, padx=5)
        
        self.load_student_messages()
    
    # פונקציות טעינה
    def load_static_messages(self):
        for item in self.static_tree.get_children():
            self.static_tree.delete(item)
        messages = self.messages_db.get_active_static_messages()
        for msg in messages:
            when_text = "תמיד" if msg['show_always'] else "עם כרטיס"
            status = "🟢 פעיל" if msg['is_active'] else "🔴 כבוי"
            self.static_tree.insert('', 'end', iid=msg['id'], values=(fix_rtl_text(msg['message']), when_text, status))
    
    def load_threshold_messages(self):
        for item in self.threshold_tree.get_children():
            self.threshold_tree.delete(item)
        messages = self.messages_db.get_all_threshold_messages()
        for msg in messages:
            range_text = f"{msg['min_points']} - {msg['max_points']}"
            status = "🟢 פעיל" if msg['is_active'] else "🔴 כבוי"
            self.threshold_tree.insert('', 'end', iid=msg['id'], values=(range_text, fix_rtl_text(msg['message']), status))
    
    def load_student_messages(self):
        for item in self.student_tree.get_children():
            self.student_tree.delete(item)
        messages = self.messages_db.get_all_student_messages()
        for msg in messages:
            student_name = f"{msg['first_name']} {msg['last_name']}"
            status = "🟢 פעיל" if msg['is_active'] else "🔴 כבוי"
            self.student_tree.insert('', 'end', iid=msg['id'], values=(student_name, msg['message'], status))
    
    def load_news_items(self):
        """טעינת פריטי החדשות לטבלה."""
        if not hasattr(self, 'news_tree'):
            return
        for item in self.news_tree.get_children():
            self.news_tree.delete(item)
        items = self.messages_db.get_all_news_items()
        for item in items:
            text = item.get('text', '')
            status = "🟢 פעיל" if item['is_active'] else "🔴 כבוי"
            
            # Format dates for display
            dates_text = ''
            start_date = item.get('start_date')
            end_date = item.get('end_date')
            
            if start_date or end_date:
                parts = []
                if start_date:
                    try:
                        d_parts = start_date.split('-')
                        if len(d_parts) == 3:
                            parts.append(f"מ-{d_parts[2]}.{d_parts[1]}.{d_parts[0]}")
                    except Exception:
                        pass
                if end_date:
                    try:
                        d_parts = end_date.split('-')
                        if len(d_parts) == 3:
                            parts.append(f"עד-{d_parts[2]}.{d_parts[1]}.{d_parts[0]}")
                    except Exception:
                        pass
                dates_text = ' '.join(parts)
            else:
                dates_text = 'קבוע'
            self.news_tree.insert('', 'end', iid=item['id'], values=(fix_rtl_text(text), dates_text, status))

    def load_ads_items(self):
        """טעינת פריטי פרסומות לטבלה."""
        if not hasattr(self, 'ads_tree'):
            return
        for item in self.ads_tree.get_children():
            self.ads_tree.delete(item)
        items = self.messages_db.get_all_ads_items()
        for item in items:
            text = _strip_image_icon_prefix(item.get('text', ''))
            try:
                if item.get('image_path'):
                    text = f"🖼 {text}" if text else "🖼"
            except Exception:
                pass
            status = "🟢 פעיל" if item['is_active'] else "🔴 כבוי"

            dates_text = ''
            start_date = item.get('start_date')
            end_date = item.get('end_date')

            if start_date or end_date:
                parts = []
                if start_date:
                    try:
                        d_parts = start_date.split('-')
                        if len(d_parts) == 3:
                            parts.append(f"מ-{d_parts[2]}.{d_parts[1]}.{d_parts[0]}")
                    except Exception:
                        pass
                if end_date:
                    try:
                        d_parts = end_date.split('-')
                        if len(d_parts) == 3:
                            parts.append(f"עד-{d_parts[2]}.{d_parts[1]}.{d_parts[0]}")
                    except Exception:
                        pass
                dates_text = ' '.join(parts)
            else:
                dates_text = 'קבוע'

            self.ads_tree.insert('', 'end', iid=item['id'], values=(fix_rtl_text(text), dates_text, status))

    def open_ads_auto_settings(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("הגדרות הצגה אוטומטית לפרסומות")
        dialog.geometry("520x520")
        try:
            dialog.minsize(480, 420)
        except Exception:
            pass
        dialog.configure(bg='#ecf0f1')
        dialog.transient(self.root)
        try:
            dialog.grab_set()
        except Exception:
            pass

        enabled_var = tk.IntVar(value=1)
        idle_var = tk.StringVar(value='180')
        show_sec_var = tk.StringVar(value='12')
        gap_var = tk.StringVar(value='8')
        border_var = tk.IntVar(value=1)

        try:
            from admin_station import AdminStation
            cfg = AdminStation.load_app_config_static() or {}
            try:
                enabled_var.set(1 if bool(cfg.get('ads_popup_enabled', True)) else 0)
            except Exception:
                enabled_var.set(1)
            idle_var.set(str(cfg.get('ads_popup_idle_sec', 180) or 180))
            show_sec_var.set(str(cfg.get('ads_popup_show_sec', 12) or 12))
            gap_var.set(str(cfg.get('ads_popup_gap_sec', 8) or 8))
            try:
                border_var.set(1 if bool(cfg.get('ads_popup_border', True)) else 0)
            except Exception:
                border_var.set(1)
        except Exception:
            pass

        tk.Label(dialog, text=fix_rtl_text('הצגה אוטומטית לפרסומות'), font=('Arial', 14, 'bold'), bg='#ecf0f1', fg='#2c3e50').pack(pady=(14, 8))

        tk.Checkbutton(dialog, text=fix_rtl_text('אפשר הצגת פרסומות בעמדה הציבורית'), variable=enabled_var, bg='#ecf0f1').pack(anchor='e', padx=16, pady=(0, 12))

        frm = tk.Frame(dialog, bg='#ecf0f1')
        frm.pack(fill=tk.X, padx=16)

        tk.Label(frm, text=fix_rtl_text('הצג אחרי X שניות ללא פעילות:'), font=('Arial', 10), bg='#ecf0f1').pack(anchor='e', pady=(6, 2))
        tk.Entry(frm, textvariable=idle_var, font=('Arial', 11), justify='right', width=10).pack(anchor='e')

        tk.Label(frm, text=fix_rtl_text('הצג פרסומת למשך X שניות:'), font=('Arial', 10), bg='#ecf0f1').pack(anchor='e', pady=(10, 2))
        tk.Entry(frm, textvariable=show_sec_var, font=('Arial', 11), justify='right', width=10).pack(anchor='e')

        tk.Label(frm, text=fix_rtl_text('זמן קפיצה בין פרסומות (שניות):'), font=('Arial', 10), bg='#ecf0f1').pack(anchor='e', pady=(10, 2))
        tk.Entry(frm, textvariable=gap_var, font=('Arial', 11), justify='right', width=10).pack(anchor='e')

        tk.Checkbutton(frm, text=fix_rtl_text('מסגרת סביב חלון הפרסומת'), variable=border_var, bg='#ecf0f1').pack(anchor='e', pady=(12, 8))

        def _save_settings():
            try:
                idle_sec = int(float(str(idle_var.get() or '0').strip() or '0'))
                if idle_sec < 10:
                    idle_sec = 10

                try:
                    show_sec = float(str(show_sec_var.get() or '0').strip() or '0')
                except Exception:
                    show_sec = 12.0
                if show_sec < 3:
                    show_sec = 3.0

                try:
                    gap_sec = float(str(gap_var.get() or '0').strip() or '0')
                except Exception:
                    gap_sec = 8.0
                if gap_sec < 1:
                    gap_sec = 1.0

                from admin_station import AdminStation
                cfg2 = AdminStation.load_app_config_static() or {}
                cfg2['ads_popup_enabled'] = True if int(enabled_var.get() or 0) == 1 else False
                cfg2['ads_popup_idle_sec'] = int(idle_sec)
                cfg2['ads_popup_show_sec'] = float(show_sec)
                cfg2['ads_popup_gap_sec'] = float(gap_sec)
                try:
                    cfg2['ads_popup_border'] = True if int(border_var.get() or 0) == 1 else False
                except Exception:
                    cfg2['ads_popup_border'] = True
                AdminStation.save_app_config_static(cfg2)
                dialog.destroy()
            except Exception as e:
                messagebox.showerror('שגיאה', str(e))

        btns = tk.Frame(dialog, bg='#ecf0f1')
        btns.pack(pady=14)
        tk.Button(btns, text='💾 שמור', command=_save_settings, bg='#27ae60', fg='white', font=('Arial', 12, 'bold'), padx=22, pady=8).pack(side=tk.LEFT, padx=6)
        tk.Button(btns, text='ביטול', command=dialog.destroy, bg='#95a5a6', fg='white', font=('Arial', 12), padx=22, pady=8).pack(side=tk.LEFT, padx=6)

    def _get_shared_folder_for_media(self) -> str:
        try:
            from admin_station import AdminStation
            cfg = AdminStation.load_app_config_static() or {}
            shared = str(cfg.get('shared_folder') or cfg.get('network_root') or '').strip()
            if shared and os.path.isdir(shared):
                return shared
        except Exception:
            pass
        return ''

    def _persist_ads_image(self, src_path: str) -> str:
        p = str(src_path or '').strip()
        if not p or not os.path.exists(p):
            return ''

        shared = self._get_shared_folder_for_media()
        if not shared:
            return ''

        try:
            ext = os.path.splitext(p)[1].lower()
        except Exception:
            ext = ''
        if ext not in ('.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp'):
            ext = '.png'

        rel_dir = os.path.join('ads_media')
        dst_dir = os.path.join(shared, rel_dir)
        try:
            os.makedirs(dst_dir, exist_ok=True)
        except Exception:
            return ''

        fname = f"{uuid.uuid4().hex}{ext}"
        dst_abs = os.path.join(dst_dir, fname)
        try:
            shutil.copy2(p, dst_abs)
        except Exception:
            return ''

        return os.path.join(rel_dir, fname)
    
    # פונקציות הודעות סטטיות
    def add_static(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("הוספת הודעה כללית")
        dialog.geometry("640x420")
        try:
            dialog.minsize(620, 400)
        except Exception:
            pass
        try:
            dialog.resizable(True, True)
        except Exception:
            pass
        dialog.configure(bg='#ecf0f1')
        
        tk.Label(dialog, text="הודעה:", font=('Arial', 12), bg='#ecf0f1').pack(pady=10)
        text_frame = tk.Frame(dialog, bg='#ecf0f1')
        text_frame.pack(padx=20, pady=10)
        text = tk.Text(text_frame, height=5, width=50, font=('Arial', 12), wrap=tk.WORD)
        text.config(insertwidth=2)
        text.tag_configure('rtl', justify='right')
        text.insert('1.0', '', 'rtl')
        scrollbar = tk.Scrollbar(text_frame, command=text.yview)
        text.config(yscrollcommand=scrollbar.set)
        text.pack(side=tk.LEFT)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # הוספת תפריט העתקה/הדבקה וקיצורי מקלדת
        self.setup_text_edit_menu(text)
        
        show_always_var = tk.BooleanVar()
        tk.Checkbutton(dialog, text="הצג תמיד (גם ללא כרטיס)", variable=show_always_var,
                      font=('Arial', 11), bg='#ecf0f1').pack(pady=5)
        
        def save():
            msg = text.get('1.0', 'end-1c').strip()
            if msg:
                self.messages_db.add_static_message(msg, show_always_var.get())
                self.load_static_messages()
                dialog.destroy()
        
        tk.Button(dialog, text="💾 שמור", command=save, bg='#27ae60', fg='white', 
                 font=('Arial', 12), padx=30, pady=10).pack(pady=10)
    
    def edit_static(self):
        selection = self.static_tree.selection()
        if not selection:
            messagebox.showwarning("אזהרה", "יש לבחור הודעה")
            return
        
        msg_id = int(selection[0])
        # הערך בעמודה הראשונה מכיל סימוני RLE/PDF לצורך תצוגה בעץ –
        # לפני עריכה נוריד אותם כדי שהסימון בעברית יעבוד כראוי.
        current_display = self.static_tree.item(msg_id)['values'][0]
        current = strip_rtl_marks(current_display)
        
        dialog = tk.Toplevel(self.root)
        dialog.title("עריכת הודעה")
        dialog.geometry("640x420")
        try:
            dialog.minsize(620, 400)
        except Exception:
            pass
        try:
            dialog.resizable(True, True)
        except Exception:
            pass
        dialog.configure(bg='#ecf0f1')
        
        tk.Label(dialog, text="הודעה:", font=('Arial', 12), bg='#ecf0f1').pack(pady=10)
        text_frame = tk.Frame(dialog, bg='#ecf0f1')
        text_frame.pack(padx=20, pady=10)
        text = tk.Text(text_frame, height=6, width=50, font=('Arial', 12), wrap=tk.WORD)
        text.config(insertwidth=2)
        text.tag_configure('rtl', justify='right')
        text.insert('1.0', current, 'rtl')
        scrollbar = tk.Scrollbar(text_frame, command=text.yview)
        text.config(yscrollcommand=scrollbar.set)
        text.pack(side=tk.LEFT)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # הוספת תפריט העתקה/הדבקה וקיצורי מקלדת
        self.setup_text_edit_menu(text)
        
        def save():
            msg = text.get('1.0', 'end-1c').strip()
            if msg:
                self.messages_db.update_static_message(msg_id, msg)
                self.load_static_messages()
                dialog.destroy()
        
        tk.Button(dialog, text="💾 שמור", command=save, bg='#27ae60', fg='white',
                 font=('Arial', 12), padx=30, pady=10).pack(pady=10)
    
    def toggle_static(self):
        selection = self.static_tree.selection()
        if not selection:
            messagebox.showwarning("אזהרה", "יש לבחור הודעה")
            return
        msg_id = int(selection[0])
        self.messages_db.toggle_static_message(msg_id)
        self.load_static_messages()
    
    # פונקציות חדשות
    
    def setup_text_edit_menu(self, text_widget):
        """הוספת תפריט העתקה/הדבקה וקיצורי מקלדת לשדה טקסט."""
        # תפריט קליק-ימני
        menu = tk.Menu(text_widget, tearoff=0)
        menu.add_command(label="גזור (Ctrl+X)", command=lambda: text_widget.event_generate('<<Cut>>'))
        menu.add_command(label="העתק (Ctrl+C)", command=lambda: text_widget.event_generate('<<Copy>>'))
        menu.add_command(label="הדבק (Ctrl+V)", command=lambda: text_widget.event_generate('<<Paste>>'))
        menu.add_separator()
        menu.add_command(label="בחר הכל (Ctrl+A)", command=lambda: text_widget.tag_add('sel', '1.0', 'end'))
        
        def show_menu(event):
            try:
                text_widget.focus_set()
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()
        
        text_widget.bind('<Button-3>', show_menu)
        
        # קיצורי מקלדת
        text_widget.bind('<Control-c>', lambda e: text_widget.event_generate('<<Copy>>'))
        text_widget.bind('<Control-C>', lambda e: text_widget.event_generate('<<Copy>>'))
        text_widget.bind('<Control-x>', lambda e: text_widget.event_generate('<<Cut>>'))
        text_widget.bind('<Control-X>', lambda e: text_widget.event_generate('<<Cut>>'))
        text_widget.bind('<Control-v>', lambda e: text_widget.event_generate('<<Paste>>'))
        text_widget.bind('<Control-V>', lambda e: text_widget.event_generate('<<Paste>>'))
        text_widget.bind('<Control-a>', lambda e: (text_widget.tag_add('sel', '1.0', 'end'), 'break'))
        text_widget.bind('<Control-A>', lambda e: (text_widget.tag_add('sel', '1.0', 'end'), 'break'))

        # גיבוי: קיצורי מקלדת גם ברמת החלון – למקרים שבהם הביינד המקומי על הטקסט לא נתפס
        def _global_copy(event):
            try:
                event.widget.event_generate('<<Copy>>')
            except Exception:
                pass
            return 'break'

        def _global_cut(event):
            try:
                event.widget.event_generate('<<Cut>>')
            except Exception:
                pass
            return 'break'

        def _global_paste(event):
            try:
                event.widget.event_generate('<<Paste>>')
            except Exception:
                pass
            return 'break'

        def _global_select_all(event):
            w = event.widget
            try:
                if isinstance(w, tk.Text):
                    w.tag_add('sel', '1.0', 'end')
                elif isinstance(w, (tk.Entry, ttk.Entry)):
                    w.select_range(0, 'end')
                    w.icursor('end')
            except Exception:
                pass
            return 'break'

        # מאזין גלובלי לכל Ctrl+Key: מזהה Ctrl+C/X/V/A גם במקלדת עברית לפי keysym/char
        def _handle_global_ctrl_shortcuts(event):
            try:
                w = event.widget
            except Exception:
                return

            # נטפל רק בשדות טקסט / אנטרי
            if not isinstance(w, (tk.Text, tk.Entry, ttk.Entry)):
                return

            keysym = (getattr(event, 'keysym', '') or '').lower()
            ch = getattr(event, 'char', '') or ''

            # קודי ה-control הסטנדרטיים: Ctrl+C=\x03, Ctrl+X=\x18, Ctrl+V=\x16, Ctrl+A=\x01
            if keysym == 'c' or ch == '\x03':
                _global_copy(event)
                return 'break'
            if keysym == 'x' or ch == '\x18':
                _global_cut(event)
                return 'break'
            if keysym == 'v' or ch == '\x16':
                _global_paste(event)
                return 'break'
            if keysym == 'a' or ch == '\x01':
                _global_select_all(event)
                return 'break'

        # bind_all כדי לוודא שקיצורי המקלדת עובדים גם כאשר פריסת המקלדת/פוקוס גורמים להתעלמות מהביינד המקומי
        # נבצע זאת פעם אחת בלבד לכל מופע של המנהל
        if not getattr(self, '_global_text_shortcuts_bound', False):
            self.root.bind_all('<Control-Key>', _handle_global_ctrl_shortcuts, add="+")
            self._global_text_shortcuts_bound = True

    def add_news(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("הוספת פריט חדשות")
        dialog.geometry("720x560")
        try:
            dialog.minsize(680, 520)
        except Exception:
            pass
        dialog.configure(bg='#ecf0f1')
        dialog.resizable(True, True)
        
        tk.Label(dialog, text="טקסט חדשות:", font=('Arial', 12), bg='#ecf0f1').pack(pady=10)
        text_frame = tk.Frame(dialog, bg='#ecf0f1')
        text_frame.pack(padx=20, pady=10)
        text = tk.Text(text_frame, height=5, width=50, font=('Arial', 12), wrap=tk.WORD)
        text.config(insertwidth=2)
        scrollbar = tk.Scrollbar(text_frame, command=text.yview)
        text.config(yscrollcommand=scrollbar.set)
        text.pack(side=tk.LEFT)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.setup_text_edit_menu(text)
        
        # תאריכי תזמון
        dates_frame = tk.LabelFrame(dialog, text='תזמון חדשה (אופציונלי)', font=('Arial', 11, 'bold'), bg='#ecf0f1')
        dates_frame.pack(padx=20, pady=10, fill=tk.X)
        
        tk.Label(dates_frame, text=fix_rtl_text('תאריך התחלה (DD.MM.YYYY):'), font=('Arial', 10), bg='#ecf0f1').pack(anchor='e', padx=10, pady=(10, 5))
        start_date_var = tk.StringVar()
        start_ent = tk.Entry(dates_frame, textvariable=start_date_var, font=('Arial', 11), justify='right', width=20)
        start_ent.pack(anchor='e', padx=10)
        try:
            start_ent.bind('<Button-1>', lambda _e: _open_date_picker_ddmmyyyy(dialog, start_date_var))
        except Exception:
            pass

        tk.Label(dates_frame, text=fix_rtl_text('תאריך סיום (DD.MM.YYYY):'), font=('Arial', 10), bg='#ecf0f1').pack(anchor='e', padx=10, pady=(10, 5))
        end_date_var = tk.StringVar()
        end_ent = tk.Entry(dates_frame, textvariable=end_date_var, font=('Arial', 11), justify='right', width=20)
        end_ent.pack(anchor='e', padx=10, pady=(0, 10))
        try:
            end_ent.bind('<Button-1>', lambda _e: _open_date_picker_ddmmyyyy(dialog, end_date_var))
        except Exception:
            pass
        
        tk.Label(dates_frame, text=fix_rtl_text('השאר ריק לחדשה קבועה ללא תאריך תפוגה'), font=('Arial', 9), bg='#ecf0f1', fg='#7f8c8d').pack(anchor='e', padx=10, pady=(0, 10))
        
        def save():
            msg = text.get('1.0', 'end-1c').strip()
            if not msg:
                messagebox.showwarning('אזהרה', 'יש להזין טקסט חדשה')
                return
            
            # המרת תאריכים מ-DD.MM.YYYY ל-YYYY-MM-DD
            start_date = None
            end_date = None
            
            start_str = start_date_var.get().strip()
            if start_str:
                try:
                    parts = start_str.split('.')
                    if len(parts) == 3:
                        start_date = f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"
                except Exception:
                    messagebox.showerror('שגיאה', 'תאריך התחלה לא תקין. השתמש בפורמט DD.MM.YYYY')
                    return
            
            end_str = end_date_var.get().strip()
            if end_str:
                try:
                    parts = end_str.split('.')
                    if len(parts) == 3:
                        end_date = f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"
                except Exception:
                    messagebox.showerror('שגיאה', 'תאריך סיום לא תקין. השתמש בפורמט DD.MM.YYYY')
                    return
            
            self.messages_db.add_news_item(msg, start_date, end_date)
            self.load_news_items()
            dialog.destroy()
        
        tk.Button(dialog, text="💾 שמור", command=save, bg='#27ae60', fg='white', 
                 font=('Arial', 12), padx=30, pady=10).pack(pady=10)

    def add_ads(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("הוספת פרסומת")
        try:
            sw = int(dialog.winfo_screenwidth() or 1200)
            sh = int(dialog.winfo_screenheight() or 800)
        except Exception:
            sw = 1200
            sh = 800
        w0 = min(760, max(620, sw - 120))
        h0 = min(740, max(560, sh - 140))
        dialog.geometry(f"{w0}x{h0}")
        try:
            dialog.minsize(560, 520)
        except Exception:
            pass
        dialog.configure(bg='#ecf0f1')
        dialog.resizable(True, True)
        
        tk.Label(dialog, text="טקסט פרסומת:", font=('Arial', 12), bg='#ecf0f1').pack(pady=10)
        text_frame = tk.Frame(dialog, bg='#ecf0f1')
        text_frame.pack(padx=20, pady=10)
        text = tk.Text(text_frame, height=5, width=50, font=('Arial', 12), wrap=tk.WORD)
        text.config(insertwidth=2)
        scrollbar = tk.Scrollbar(text_frame, command=text.yview)
        text.config(yscrollcommand=scrollbar.set)
        text.pack(side=tk.LEFT)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.setup_text_edit_menu(text)

        image_var = tk.StringVar(value='')

        img_frame = tk.Frame(dialog, bg='#ecf0f1')
        img_frame.pack(fill=tk.X, padx=20, pady=(0, 5))

        tk.Label(img_frame, text=fix_rtl_text('תמונה (אופציונלי):'), font=('Arial', 10), bg='#ecf0f1').pack(side=tk.RIGHT, padx=5)

        img_label = tk.Label(img_frame, text="", font=('Arial', 9), bg='#ecf0f1', fg='#34495e', anchor='e', justify='right')
        img_label.pack(side=tk.RIGHT, padx=5, fill=tk.X, expand=True)

        def _choose_img():
            try:
                p = filedialog.askopenfilename(
                    title='בחר תמונה לפרסומת',
                    filetypes=[('Images', '*.png;*.jpg;*.jpeg;*.webp;*.gif;*.bmp'), ('All files', '*.*')]
                )
            except Exception:
                p = ''
            if p:
                image_var.set(p)
                try:
                    img_label.config(text=os.path.basename(p))
                except Exception:
                    img_label.config(text=p)

        def _clear_img():
            image_var.set('')
            img_label.config(text='')

        tk.Button(img_frame, text="בחר", command=_choose_img, font=('Arial', 9), bg='#bdc3c7', fg='#2c3e50', padx=8, pady=2).pack(side=tk.LEFT, padx=4)
        tk.Button(img_frame, text="נקה", command=_clear_img, font=('Arial', 9), bg='#95a5a6', fg='white', padx=8, pady=2).pack(side=tk.LEFT, padx=4)

        dates_frame = tk.LabelFrame(dialog, text='תזמון פרסומת (אופציונלי)', font=('Arial', 11, 'bold'), bg='#ecf0f1')
        dates_frame.pack(padx=20, pady=10, fill=tk.X)

        tk.Label(dates_frame, text=fix_rtl_text('תאריך התחלה (DD.MM.YYYY):'), font=('Arial', 10), bg='#ecf0f1').pack(anchor='e', padx=10, pady=(10, 5))
        start_date_var = tk.StringVar()
        start_ent = tk.Entry(dates_frame, textvariable=start_date_var, font=('Arial', 11), justify='right', width=20)
        start_ent.pack(anchor='e', padx=10)
        try:
            start_ent.bind('<Button-1>', lambda _e: _open_date_picker_ddmmyyyy(dialog, start_date_var))
        except Exception:
            pass

        tk.Label(dates_frame, text=fix_rtl_text('תאריך סיום (DD.MM.YYYY):'), font=('Arial', 10), bg='#ecf0f1').pack(anchor='e', padx=10, pady=(10, 5))
        end_date_var = tk.StringVar()
        end_ent = tk.Entry(dates_frame, textvariable=end_date_var, font=('Arial', 11), justify='right', width=20)
        end_ent.pack(anchor='e', padx=10, pady=(0, 10))
        try:
            end_ent.bind('<Button-1>', lambda _e: _open_date_picker_ddmmyyyy(dialog, end_date_var))
        except Exception:
            pass

        tk.Label(dates_frame, text=fix_rtl_text('השאר ריק לפרסומת קבועה ללא תאריך תפוגה'), font=('Arial', 9), bg='#ecf0f1', fg='#7f8c8d').pack(anchor='e', padx=10, pady=(0, 10))

        def save():
            msg = _strip_image_icon_prefix(text.get('1.0', 'end-1c').strip())
            if not msg:
                messagebox.showwarning('אזהרה', 'יש להזין טקסט פרסומת')
                return

            start_date = None
            end_date = None

            start_str = start_date_var.get().strip()
            if start_str:
                try:
                    parts = start_str.split('.')
                    if len(parts) == 3:
                        start_date = f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"
                except Exception:
                    messagebox.showerror('שגיאה', 'תאריך התחלה לא תקין. השתמש בפורמט DD.MM.YYYY')
                    return

            end_str = end_date_var.get().strip()
            if end_str:
                try:
                    parts = end_str.split('.')
                    if len(parts) == 3:
                        end_date = f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"
                except Exception:
                    messagebox.showerror('שגיאה', 'תאריך סיום לא תקין. השתמש בפורמט DD.MM.YYYY')
                    return

            img_rel = ''
            try:
                src_img = str(image_var.get() or '').strip()
            except Exception:
                src_img = ''
            if src_img:
                img_rel = self._persist_ads_image(src_img)
                if not img_rel:
                    messagebox.showwarning('אזהרה', 'לא ניתן לשמור את התמונה בתיקייה המשותפת. הפרסומת תישמר ללא תמונה.')

            try:
                self.messages_db.add_ads_item(msg, start_date, end_date, img_rel or None)
            except TypeError:
                self.messages_db.add_ads_item(msg, start_date, end_date)
            self.load_ads_items()
            dialog.destroy()

        btn_bar = tk.Frame(dialog, bg='#ecf0f1')
        btn_bar.pack(side=tk.BOTTOM, fill=tk.X, pady=10)
        tk.Button(btn_bar, text="💾 שמור", command=save, bg='#27ae60', fg='white',
                 font=('Arial', 12), padx=30, pady=10).pack(pady=0)

        try:
            dialog.update_idletasks()
            sw2 = int(dialog.winfo_screenwidth() or 1200)
            sh2 = int(dialog.winfo_screenheight() or 800)
            max_w = max(620, sw2 - 120)
            max_h = max(560, sh2 - 140)
            req_w = int(dialog.winfo_reqwidth() or 620)
            req_h = int(dialog.winfo_reqheight() or 560)
            w = min(max_w, max(620, req_w))
            h = min(max_h, max(560, req_h))
            dialog.geometry(f"{w}x{h}")
        except Exception:
            pass

    def edit_ads(self):
        selection = self.ads_tree.selection() if hasattr(self, 'ads_tree') else ()
        if not selection:
            messagebox.showwarning("אזהרה", "יש לבחור פרסומת")
            return

        ads_id = int(selection[0])
        current_display = self.ads_tree.item(ads_id)['values'][0]
        current = _strip_image_icon_prefix(strip_rtl_marks(current_display))

        all_ads = self.messages_db.get_all_ads_items()
        current_ads = next((a for a in all_ads if int(a.get('id', 0) or 0) == ads_id), None)

        dialog = tk.Toplevel(self.root)
        dialog.title("עריכת פרסומת")
        try:
            sw = int(dialog.winfo_screenwidth() or 1200)
            sh = int(dialog.winfo_screenheight() or 800)
        except Exception:
            sw = 1200
            sh = 800
        w0 = min(760, max(620, sw - 120))
        h0 = min(740, max(560, sh - 140))
        dialog.geometry(f"{w0}x{h0}")
        try:
            dialog.minsize(560, 520)
        except Exception:
            pass
        dialog.configure(bg='#ecf0f1')
        dialog.resizable(True, True)

        tk.Label(dialog, text="טקסט פרסומת:", font=('Arial', 12), bg='#ecf0f1').pack(pady=10)
        text_frame = tk.Frame(dialog, bg='#ecf0f1')
        text_frame.pack(padx=20, pady=10)
        text = tk.Text(text_frame, height=5, width=50, font=('Arial', 12), wrap=tk.WORD)
        text.config(insertwidth=2)
        text.insert('1.0', current)
        scrollbar = tk.Scrollbar(text_frame, command=text.yview)
        text.config(yscrollcommand=scrollbar.set)
        text.pack(side=tk.LEFT)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.setup_text_edit_menu(text)

        image_var = tk.StringVar(value='')
        current_img_rel = ''
        try:
            current_img_rel = str((current_ads or {}).get('image_path') or '').strip()
        except Exception:
            current_img_rel = ''

        img_frame = tk.Frame(dialog, bg='#ecf0f1')
        img_frame.pack(fill=tk.X, padx=20, pady=(0, 5))

        tk.Label(img_frame, text=fix_rtl_text('תמונה (אופציונלי):'), font=('Arial', 10), bg='#ecf0f1').pack(side=tk.RIGHT, padx=5)

        img_label = tk.Label(img_frame, text="", font=('Arial', 9), bg='#ecf0f1', fg='#34495e', anchor='e', justify='right')
        img_label.pack(side=tk.RIGHT, padx=5, fill=tk.X, expand=True)
        if current_img_rel:
            img_label.config(text=str(current_img_rel))

        def _choose_img():
            try:
                p = filedialog.askopenfilename(
                    title='בחר תמונה לפרסומת',
                    filetypes=[('Images', '*.png;*.jpg;*.jpeg;*.webp;*.gif;*.bmp'), ('All files', '*.*')]
                )
            except Exception:
                p = ''
            if p:
                image_var.set(p)
                try:
                    img_label.config(text=os.path.basename(p))
                except Exception:
                    img_label.config(text=p)

        def _clear_img():
            nonlocal current_img_rel
            image_var.set('')
            current_img_rel = ''
            img_label.config(text='')

        tk.Button(img_frame, text="בחר", command=_choose_img, font=('Arial', 9), bg='#bdc3c7', fg='#2c3e50', padx=8, pady=2).pack(side=tk.LEFT, padx=4)
        tk.Button(img_frame, text="נקה", command=_clear_img, font=('Arial', 9), bg='#95a5a6', fg='white', padx=8, pady=2).pack(side=tk.LEFT, padx=4)

        dates_frame = tk.LabelFrame(dialog, text='תזמון פרסומת (אופציונלי)', font=('Arial', 11, 'bold'), bg='#ecf0f1')
        dates_frame.pack(padx=20, pady=10, fill=tk.X)

        tk.Label(dates_frame, text=fix_rtl_text('תאריך התחלה (DD.MM.YYYY):'), font=('Arial', 10), bg='#ecf0f1').pack(anchor='e', padx=10, pady=(10, 5))
        start_date_var = tk.StringVar()
        if current_ads and current_ads.get('start_date'):
            try:
                parts = str(current_ads.get('start_date') or '').split('-')
                if len(parts) == 3:
                    start_date_var.set(f"{parts[2]}.{parts[1]}.{parts[0]}")
            except Exception:
                pass
        start_ent = tk.Entry(dates_frame, textvariable=start_date_var, font=('Arial', 11), justify='right', width=20)
        start_ent.pack(anchor='e', padx=10)
        try:
            start_ent.bind('<Button-1>', lambda _e: _open_date_picker_ddmmyyyy(dialog, start_date_var))
        except Exception:
            pass

        tk.Label(dates_frame, text=fix_rtl_text('תאריך סיום (DD.MM.YYYY):'), font=('Arial', 10), bg='#ecf0f1').pack(anchor='e', padx=10, pady=(10, 5))
        end_date_var = tk.StringVar()
        if current_ads and current_ads.get('end_date'):
            try:
                parts = str(current_ads.get('end_date') or '').split('-')
                if len(parts) == 3:
                    end_date_var.set(f"{parts[2]}.{parts[1]}.{parts[0]}")
            except Exception:
                pass
        end_ent = tk.Entry(dates_frame, textvariable=end_date_var, font=('Arial', 11), justify='right', width=20)
        end_ent.pack(anchor='e', padx=10, pady=(0, 10))
        try:
            end_ent.bind('<Button-1>', lambda _e: _open_date_picker_ddmmyyyy(dialog, end_date_var))
        except Exception:
            pass

        tk.Label(dates_frame, text=fix_rtl_text('השאר ריק לפרסומת קבועה ללא תאריך תפוגה'), font=('Arial', 9), bg='#ecf0f1', fg='#7f8c8d').pack(anchor='e', padx=10, pady=(0, 10))

        def save():
            msg = _strip_image_icon_prefix(text.get('1.0', 'end-1c').strip())
            if not msg:
                messagebox.showwarning('אזהרה', 'יש להזין טקסט פרסומת')
                return

            start_date = None
            end_date = None

            start_str = start_date_var.get().strip()
            if start_str:
                try:
                    parts = start_str.split('.')
                    if len(parts) == 3:
                        start_date = f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"
                except Exception:
                    messagebox.showerror('שגיאה', 'תאריך התחלה לא תקין. השתמש בפורמט DD.MM.YYYY')
                    return

            end_str = end_date_var.get().strip()
            if end_str:
                try:
                    parts = end_str.split('.')
                    if len(parts) == 3:
                        end_date = f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"
                except Exception:
                    messagebox.showerror('שגיאה', 'תאריך סיום לא תקין. השתמש בפורמט DD.MM.YYYY')
                    return

            img_rel = current_img_rel
            try:
                src_img = str(image_var.get() or '').strip()
            except Exception:
                src_img = ''
            if src_img:
                new_rel = self._persist_ads_image(src_img)
                if new_rel:
                    img_rel = new_rel
                else:
                    messagebox.showwarning('אזהרה', 'לא ניתן לשמור את התמונה בתיקייה המשותפת. נשמרה התמונה הקודמת (אם הייתה).')

            try:
                self.messages_db.update_ads_item(ads_id, msg, start_date, end_date, img_rel or None)
            except TypeError:
                self.messages_db.update_ads_item(ads_id, msg, start_date, end_date)
            self.load_ads_items()
            dialog.destroy()

        btn_bar = tk.Frame(dialog, bg='#ecf0f1')
        btn_bar.pack(side=tk.BOTTOM, fill=tk.X, pady=10)
        tk.Button(btn_bar, text="💾 שמור", command=save, bg='#27ae60', fg='white',
                 font=('Arial', 12), padx=30, pady=10).pack(pady=0)

        try:
            dialog.update_idletasks()
            sw2 = int(dialog.winfo_screenwidth() or 1200)
            sh2 = int(dialog.winfo_screenheight() or 800)
            max_w = max(620, sw2 - 120)
            max_h = max(560, sh2 - 140)
            req_w = int(dialog.winfo_reqwidth() or 620)
            req_h = int(dialog.winfo_reqheight() or 560)
            w = min(max_w, max(620, req_w))
            h = min(max_h, max(560, req_h))
            dialog.geometry(f"{w}x{h}")
        except Exception:
            pass

    def delete_ads(self):
        selection = self.ads_tree.selection() if hasattr(self, 'ads_tree') else ()
        if not selection:
            messagebox.showwarning("אזהרה", "יש לבחור פרסומת")
            return
        if messagebox.askyesno("אישור", "למחוק פרסומת?"):
            ads_id = int(selection[0])
            self.messages_db.delete_ads_item(ads_id)
            self.load_ads_items()

    def toggle_ads(self):
        selection = self.ads_tree.selection() if hasattr(self, 'ads_tree') else ()
        if not selection:
            messagebox.showwarning("אזהרה", "יש לבחור פרסומת")
            return
        ads_id = int(selection[0])
        self.messages_db.toggle_ads_item(ads_id)
        self.load_ads_items()

    def move_ads_up(self):
        selection = self.ads_tree.selection() if hasattr(self, 'ads_tree') else ()
        if not selection:
            messagebox.showwarning("אזהרה", "יש לבחור פרסומת")
            return

        selected_iid = selection[0]
        children = list(self.ads_tree.get_children())
        try:
            index = children.index(selected_iid)
        except ValueError:
            return

        if index == 0:
            return

        above_iid = children[index - 1]

        try:
            ads_id = int(selected_iid)
            other_id = int(above_iid)
        except ValueError:
            return

        self.messages_db.swap_ads_order(ads_id, other_id)
        self.load_ads_items()

        try:
            self.ads_tree.selection_set(str(ads_id))
            self.ads_tree.see(str(ads_id))
        except Exception:
            pass

    def move_ads_down(self):
        selection = self.ads_tree.selection() if hasattr(self, 'ads_tree') else ()
        if not selection:
            messagebox.showwarning("אזהרה", "יש לבחור פרסומת")
            return

        selected_iid = selection[0]
        children = list(self.ads_tree.get_children())
        try:
            index = children.index(selected_iid)
        except ValueError:
            return

        if index >= len(children) - 1:
            return

        below_iid = children[index + 1]

        try:
            ads_id = int(selected_iid)
            other_id = int(below_iid)
        except ValueError:
            return

        self.messages_db.swap_ads_order(ads_id, other_id)
        self.load_ads_items()

        try:
            self.ads_tree.selection_set(str(ads_id))
            self.ads_tree.see(str(ads_id))
        except Exception:
            pass
    
    def edit_news(self):
        selection = self.news_tree.selection()
        if not selection:
            messagebox.showwarning("אזהרה", "יש לבחור פריט חדשות")
            return
        
        news_id = int(selection[0])
        current_display = self.news_tree.item(news_id)['values'][0]
        current = strip_rtl_marks(current_display)
        
        # קבלת נתוני החדשה המלאים
        all_news = self.messages_db.get_all_news_items()
        current_news = next((n for n in all_news if n['id'] == news_id), None)
        
        dialog = tk.Toplevel(self.root)
        dialog.title("עריכת פריט חדשות")
        dialog.geometry("720x560")
        try:
            dialog.minsize(680, 520)
        except Exception:
            pass
        dialog.configure(bg='#ecf0f1')
        dialog.resizable(True, True)
        
        tk.Label(dialog, text="טקסט חדשות:", font=('Arial', 12), bg='#ecf0f1').pack(pady=10)
        text_frame = tk.Frame(dialog, bg='#ecf0f1')
        text_frame.pack(padx=20, pady=10)
        text = tk.Text(text_frame, height=5, width=50, font=('Arial', 12), wrap=tk.WORD)
        text.config(insertwidth=2)
        text.insert('1.0', current)
        scrollbar = tk.Scrollbar(text_frame, command=text.yview)
        text.config(yscrollcommand=scrollbar.set)
        text.pack(side=tk.LEFT)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.setup_text_edit_menu(text)
        
        # תאריכי תזמון
        dates_frame = tk.LabelFrame(dialog, text='תזמון חדשה (אופציונלי)', font=('Arial', 11, 'bold'), bg='#ecf0f1')
        dates_frame.pack(padx=20, pady=10, fill=tk.X)
        
        tk.Label(dates_frame, text=fix_rtl_text('תאריך התחלה (DD.MM.YYYY):'), font=('Arial', 10), bg='#ecf0f1').pack(anchor='e', padx=10, pady=(10, 5))
        start_date_var = tk.StringVar()
        # המרה מ-YYYY-MM-DD ל-DD.MM.YYYY
        if current_news and current_news.get('start_date'):
            try:
                parts = current_news['start_date'].split('-')
                if len(parts) == 3:
                    start_date_var.set(f"{parts[2]}.{parts[1]}.{parts[0]}")
            except Exception:
                pass
        start_ent = tk.Entry(dates_frame, textvariable=start_date_var, font=('Arial', 11), justify='right', width=20)
        start_ent.pack(anchor='e', padx=10)
        try:
            start_ent.bind('<Button-1>', lambda _e: _open_date_picker_ddmmyyyy(dialog, start_date_var))
        except Exception:
            pass
        
        tk.Label(dates_frame, text=fix_rtl_text('תאריך סיום (DD.MM.YYYY):'), font=('Arial', 10), bg='#ecf0f1').pack(anchor='e', padx=10, pady=(10, 5))
        end_date_var = tk.StringVar()
        if current_news and current_news.get('end_date'):
            try:
                parts = current_news['end_date'].split('-')
                if len(parts) == 3:
                    end_date_var.set(f"{parts[2]}.{parts[1]}.{parts[0]}")
            except Exception:
                pass
        end_ent = tk.Entry(dates_frame, textvariable=end_date_var, font=('Arial', 11), justify='right', width=20)
        end_ent.pack(anchor='e', padx=10, pady=(0, 10))
        try:
            end_ent.bind('<Button-1>', lambda _e: _open_date_picker_ddmmyyyy(dialog, end_date_var))
        except Exception:
            pass
        
        tk.Label(dates_frame, text=fix_rtl_text('השאר ריק לחדשה קבועה ללא תאריך תפוגה'), font=('Arial', 9), bg='#ecf0f1', fg='#7f8c8d').pack(anchor='e', padx=10, pady=(0, 10))
        
        def save():
            msg = text.get('1.0', 'end-1c').strip()
            if not msg:
                messagebox.showwarning('אזהרה', 'יש להזין טקסט חדשה')
                return
            
            # המרת תאריכים מ-DD.MM.YYYY ל-YYYY-MM-DD
            start_date = None
            end_date = None
            
            start_str = start_date_var.get().strip()
            if start_str:
                try:
                    parts = start_str.split('.')
                    if len(parts) == 3:
                        start_date = f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"
                except Exception:
                    messagebox.showerror('שגיאה', 'תאריך התחלה לא תקין. השתמש בפורמט DD.MM.YYYY')
                    return
            
            end_str = end_date_var.get().strip()
            if end_str:
                try:
                    parts = end_str.split('.')
                    if len(parts) == 3:
                        end_date = f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"
                except Exception:
                    messagebox.showerror('שגיאה', 'תאריך סיום לא תקין. השתמש בפורמט DD.MM.YYYY')
                    return
            
            self.messages_db.update_news_item(news_id, msg, start_date, end_date)
            self.load_news_items()
            dialog.destroy()
        
        tk.Button(dialog, text="💾 שמור", command=save, bg='#27ae60', fg='white', 
                 font=('Arial', 12), padx=30, pady=10).pack(pady=10)
    
    def delete_news(self):
        selection = self.news_tree.selection()
        if not selection:
            messagebox.showwarning("אזהרה", "יש לבחור פריט חדשות")
            return
        if messagebox.askyesno("אישור", "למחוק פריט חדשות?"):
            news_id = int(selection[0])
            self.messages_db.delete_news_item(news_id)
            self.load_news_items()
    
    def toggle_news(self):
        selection = self.news_tree.selection()
        if not selection:
            messagebox.showwarning("אזהרה", "יש לבחור פריט חדשות")
            return
        news_id = int(selection[0])
        self.messages_db.toggle_news_item(news_id)
        self.load_news_items()
    
    def move_news_up(self):
        selection = self.news_tree.selection()
        if not selection:
            messagebox.showwarning("אזהרה", "יש לבחור פריט חדשות")
            return

        selected_iid = selection[0]
        children = list(self.news_tree.get_children())
        try:
            index = children.index(selected_iid)
        except ValueError:
            return

        if index == 0:
            return

        above_iid = children[index - 1]

        try:
            news_id = int(selected_iid)
            other_id = int(above_iid)
        except ValueError:
            return

        self.messages_db.swap_news_order(news_id, other_id)
        self.load_news_items()

        try:
            self.news_tree.selection_set(str(news_id))
            self.news_tree.see(str(news_id))
        except Exception:
            pass

    def move_news_down(self):
        selection = self.news_tree.selection()
        if not selection:
            messagebox.showwarning("אזהרה", "יש לבחור פריט חדשות")
            return

        selected_iid = selection[0]
        children = list(self.news_tree.get_children())
        try:
            index = children.index(selected_iid)
        except ValueError:
            return

        if index >= len(children) - 1:
            return

        below_iid = children[index + 1]

        try:
            news_id = int(selected_iid)
            other_id = int(below_iid)
        except ValueError:
            return

        self.messages_db.swap_news_order(news_id, other_id)
        self.load_news_items()

        try:
            self.news_tree.selection_set(str(news_id))
            self.news_tree.see(str(news_id))
        except Exception:
            pass
    
    def delete_static(self):
        selection = self.static_tree.selection()
        if not selection:
            messagebox.showwarning("אזהרה", "יש לבחור הודעה")
            return
        if messagebox.askyesno("אישור", "למחוק הודעה?"):
            msg_id = int(selection[0])
            self.messages_db.delete_static_message(msg_id)
            self.load_static_messages()
    
    # פונקציות הודעות סף
    def add_threshold(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("הוספת הודעה לפי טווח")
        dialog.geometry("640x520")
        try:
            dialog.minsize(620, 480)
        except Exception:
            pass
        try:
            dialog.resizable(True, True)
        except Exception:
            pass
        dialog.configure(bg='#ecf0f1')
        
        tk.Label(dialog, text="מינימום נקודות:", font=('Arial', 12), bg='#ecf0f1').pack(pady=5)
        min_entry = tk.Entry(dialog, font=('Arial', 12), width=20)
        min_entry.pack()
        
        tk.Label(dialog, text="מקסימום נקודות:", font=('Arial', 12), bg='#ecf0f1').pack(pady=5)
        max_entry = tk.Entry(dialog, font=('Arial', 12), width=20)
        max_entry.pack()
        
        tk.Label(dialog, text="הודעה:", font=('Arial', 12), bg='#ecf0f1').pack(pady=5)
        text_frame = tk.Frame(dialog, bg='#ecf0f1')
        text_frame.pack(padx=20, pady=10)
        text = tk.Text(text_frame, height=6, width=50, font=('Arial', 12), wrap=tk.WORD)
        text.config(insertwidth=2)
        text.tag_configure('rtl', justify='right')
        text.insert('1.0', '', 'rtl')
        scrollbar = tk.Scrollbar(text_frame, command=text.yview)
        text.config(yscrollcommand=scrollbar.set)
        text.pack(side=tk.LEFT)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # הוספת תפריט העתקה/הדבקה וקיצורי מקלדת
        self.setup_text_edit_menu(text)
        
        def save():
            try:
                min_p = int(min_entry.get())
                max_p = int(max_entry.get())
                msg = text.get('1.0', 'end-1c').strip()
                if msg:
                    self.messages_db.add_threshold_message(min_p, max_p, msg)
                    self.load_threshold_messages()
                    dialog.destroy()
            except ValueError:
                messagebox.showerror("שגיאה", "יש להזין מספרים")
        
        tk.Button(dialog, text="💾 שמור", command=save, bg='#27ae60', fg='white',
                 font=('Arial', 12), padx=30, pady=10).pack(pady=10)
    
    def edit_threshold(self):
        selection = self.threshold_tree.selection()
        if not selection:
            messagebox.showwarning("אזהרה", "יש לבחור הודעה")
            return
        
        msg_id = int(selection[0])
        messages = self.messages_db.get_all_threshold_messages()
        current = next(m for m in messages if m['id'] == msg_id)
        
        dialog = tk.Toplevel(self.root)
        dialog.title("עריכת הודעה")
        dialog.geometry("640x520")
        try:
            dialog.minsize(620, 480)
        except Exception:
            pass
        try:
            dialog.resizable(True, True)
        except Exception:
            pass
        dialog.configure(bg='#ecf0f1')
        
        tk.Label(dialog, text="מינימום נקודות:", font=('Arial', 12), bg='#ecf0f1').pack(pady=5)
        min_entry = tk.Entry(dialog, font=('Arial', 12), width=20)
        min_entry.insert(0, str(current['min_points']))
        min_entry.pack()
        
        tk.Label(dialog, text="מקסימום נקודות:", font=('Arial', 12), bg='#ecf0f1').pack(pady=5)
        max_entry = tk.Entry(dialog, font=('Arial', 12), width=20)
        max_entry.insert(0, str(current['max_points']))
        max_entry.pack()
        
        tk.Label(dialog, text="הודעה:", font=('Arial', 12), bg='#ecf0f1').pack(pady=5)
        text_frame = tk.Frame(dialog, bg='#ecf0f1')
        text_frame.pack(padx=20, pady=10)
        text = tk.Text(text_frame, height=6, width=50, font=('Arial', 12), wrap=tk.WORD)
        text.config(insertwidth=2)
        text.tag_configure('rtl', justify='right')
        text.insert('1.0', current['message'], 'rtl')
        scrollbar = tk.Scrollbar(text_frame, command=text.yview)
        text.config(yscrollcommand=scrollbar.set)
        text.pack(side=tk.LEFT)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # הוספת תפריט העתקה/הדבקה וקיצורי מקלדת
        self.setup_text_edit_menu(text)
        
        def save():
            try:
                min_p = int(min_entry.get())
                max_p = int(max_entry.get())
                msg = text.get('1.0', 'end-1c').strip()
                if msg:
                    self.messages_db.update_threshold_message(msg_id, min_p, max_p, msg)
                    self.load_threshold_messages()
                    dialog.destroy()
            except ValueError:
                messagebox.showerror("שגיאה", "יש להזין מספרים")
        
        tk.Button(dialog, text="💾 שמור", command=save, bg='#27ae60', fg='white',
                 font=('Arial', 12), padx=30, pady=10).pack(pady=10)
    
    def toggle_threshold(self):
        selection = self.threshold_tree.selection()
        if not selection:
            messagebox.showwarning("אזהרה", "יש לבחור הודעה")
            return
        msg_id = int(selection[0])
        self.messages_db.toggle_threshold_message(msg_id)
        self.load_threshold_messages()
    
    def delete_threshold(self):
        selection = self.threshold_tree.selection()
        if not selection:
            messagebox.showwarning("אזהרה", "יש לבחור הודעה")
            return
        if messagebox.askyesno("אישור", "למחוק הודעה?"):
            msg_id = int(selection[0])
            self.messages_db.delete_threshold_message(msg_id)
            self.load_threshold_messages()
    
    # פונקציות הודעות פרטיות
    def add_student_msg(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("הוספת הודעה פרטית")
        dialog.geometry("640x520")
        try:
            dialog.minsize(620, 480)
        except Exception:
            pass
        try:
            dialog.resizable(True, True)
        except Exception:
            pass
        dialog.configure(bg='#ecf0f1')
        
        tk.Label(dialog, text="בחר תלמיד:", font=('Arial', 12), bg='#ecf0f1').pack(pady=10)
        
        students = self.db.get_all_students()
        student_combo = ttk.Combobox(dialog, font=('Arial', 12), width=30, state='readonly')
        student_combo['values'] = [f"{s['first_name']} {s['last_name']}" for s in students]
        student_combo.pack()
        
        tk.Label(dialog, text="הודעה:", font=('Arial', 12), bg='#ecf0f1').pack(pady=10)
        text = scrolledtext.ScrolledText(dialog, height=6, width=50, font=('Arial', 12))
        text.pack(padx=20, pady=10)
        
        def save():
            if student_combo.current() >= 0:
                student_id = students[student_combo.current()]['id']
                msg = text.get('1.0', 'end-1c').strip()
                if msg:
                    self.messages_db.add_student_message(student_id, msg)
                    self.load_student_messages()
                    dialog.destroy()
        
        tk.Button(dialog, text="💾 שמור", command=save, bg='#27ae60', fg='white',
                 font=('Arial', 12), padx=30, pady=10).pack(pady=10)
    
    def edit_student_msg(self):
        selection = self.student_tree.selection()
        if not selection:
            messagebox.showwarning("אזהרה", "יש לבחור הודעה")
            return
        
        msg_id = int(selection[0])
        current = self.student_tree.item(msg_id)['values'][1]
        
        dialog = tk.Toplevel(self.root)
        dialog.title("עריכת הודעה")
        dialog.geometry("640x420")
        try:
            dialog.minsize(620, 400)
        except Exception:
            pass
        try:
            dialog.resizable(True, True)
        except Exception:
            pass
        dialog.configure(bg='#ecf0f1')
        
        tk.Label(dialog, text="הודעה:", font=('Arial', 12), bg='#ecf0f1').pack(pady=10)
        text = scrolledtext.ScrolledText(dialog, height=6, width=50, font=('Arial', 12))
        text.insert('1.0', current)
        text.pack(padx=20, pady=10)
        
        def save():
            msg = text.get('1.0', 'end-1c').strip()
            if msg:
                self.messages_db.update_student_message(msg_id, msg)
                self.load_student_messages()
                dialog.destroy()
        
        tk.Button(dialog, text="💾 שמור", command=save, bg='#27ae60', fg='white',
                 font=('Arial', 12), padx=30, pady=10).pack(pady=10)
    
    def toggle_student_msg(self):
        selection = self.student_tree.selection()
        if not selection:
            messagebox.showwarning("אזהרה", "יש לבחור הודעה")
            return
        msg_id = int(selection[0])
        self.messages_db.toggle_student_message(msg_id)
        self.load_student_messages()
    
    def delete_student_msg(self):
        selection = self.student_tree.selection()
        if not selection:
            messagebox.showwarning("אזהרה", "יש לבחור הודעה")
            return
        if messagebox.askyesno("אישור", "למחוק הודעה?"):
            msg_id = int(selection[0])
            self.messages_db.delete_student_message(msg_id)
            self.load_student_messages()


def main():
    root = tk.Tk()
    app = MessagesManager(root)
    root.mainloop()


if __name__ == "__main__":
    main()
