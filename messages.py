"""
מערכת הודעות למערכת ניקוד בית ספרית
"""
import sqlite3
import os
import json
import urllib.request
import urllib.error
from typing import Optional, List, Dict, Any
from datetime import datetime


class MessagesDB:
    _journal_mode_applied = set()
    def __init__(self, db_path: str = None):
        self._remote_write_url = None
        self._remote_write_api_key = 'local'
        # ברירת מחדל: קובץ ה-DB בתיקייה של הפרויקט (תומך ב-UNC)
        if db_path is None:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            
            # בדיקה אם יש נתיב DB משותף מוגדר (כמו ב-database.py)
            custom_db_path = None
            db_config_file = os.path.join(base_dir, 'db_path.txt')
            if os.path.exists(db_config_file):
                try:
                    with open(db_config_file, 'r', encoding='utf-8') as f:
                        for line in f:
                            line = line.strip()
                            if line and not line.startswith('#'):
                                custom_db_path = line
                                break
                except:
                    pass
            
            # השתמש ב-DB משותף אם הוגדר, אחרת מקומי
            if custom_db_path:
                self.db_path = custom_db_path
            else:
                self.db_path = os.path.join(base_dir, 'school_points.db')
        else:
            self.db_path = db_path
        # זיהוי עמדה משנית - הפניית כתיבות דרך HTTP
        try:
            self._detect_remote_write()
        except Exception:
            pass
        self.init_tables()
    
    def _detect_remote_write(self):
        """זיהוי אם זו עמדה משנית שצריכה לכתוב דרך HTTP"""
        try:
            from database import Database
            # אם Database כבר זיהה remote write, נשתמש באותו URL
            dummy = Database.__new__(Database)
            dummy._remote_write_url = None
            dummy._remote_write_api_key = 'local'
            # קרא config
            import socket as _sock
            base_dir = os.path.dirname(os.path.abspath(__file__))
            cfg = {}
            for env_name in ("PROGRAMDATA", "LOCALAPPDATA", "APPDATA"):
                root = os.environ.get(env_name)
                if not root:
                    continue
                cfg_path = os.path.join(root, "SchoolPoints", "config.json")
                if os.path.exists(cfg_path):
                    with open(cfg_path, 'r', encoding='utf-8') as f:
                        cfg = json.loads(f.read())
                    break
            if not cfg:
                cfg_path = os.path.join(base_dir, 'config.json')
                if os.path.exists(cfg_path):
                    with open(cfg_path, 'r', encoding='utf-8') as f:
                        cfg = json.loads(f.read())
            local_sync_enabled = str(cfg.get('local_sync_enabled') or '').strip().lower() in ('1', 'true', 'on', 'yes')
            if not local_sync_enabled:
                return
            shared_folder = str(cfg.get('shared_folder') or cfg.get('network_root') or '').strip()
            if not shared_folder:
                return
            # חלץ host מ-UNC
            p = shared_folder.replace('/', '\\')
            if not p.startswith('\\\\'):
                return
            host = p[2:].split('\\', 1)[0].strip()
            if not host:
                return
            # בדוק אם זה מקומי
            local_names = {
                str(_sock.gethostname() or '').strip().lower(),
                str(os.environ.get('COMPUTERNAME') or '').strip().lower(),
                'localhost', '127.0.0.1', '::1'
            }
            if host.lower() in local_names:
                return  # עמדה ראשית - לא צריך proxy
            try:
                port = int(cfg.get('local_sync_port') or 8765)
            except Exception:
                port = 8765
            self._remote_write_url = f"http://{host}:{port}"
            self._remote_write_api_key = str(cfg.get('local_sync_key') or 'local').strip()
        except Exception:
            pass

    def get_connection(self):
        """יצירת חיבור למסד הנתונים"""
        db_dir = os.path.dirname(self.db_path) or '.'
        try:
            os.makedirs(db_dir, exist_ok=True)
        except Exception:
            # אם לא הצלחנו ליצור תיקייה – ניתן ל-sqlite לטפל בשגיאה
            pass

        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        self._apply_pragmas(conn)
        # עמדה משנית: עטוף ב-proxy שמפנה כתיבות דרך HTTP
        if self._remote_write_url:
            try:
                from database import _RemoteWriteConnection
                return _RemoteWriteConnection(conn, self._remote_write_url, self._remote_write_api_key)
            except Exception:
                pass
        return conn

    def _is_unc_path(self) -> bool:
        try:
            p = str(self.db_path or '')
        except Exception:
            return False
        return p.startswith('\\') or p.startswith('//')

    def _apply_pragmas(self, conn: sqlite3.Connection) -> None:
        try:
            conn.execute('PRAGMA foreign_keys = ON')
        except Exception:
            pass
        try:
            conn.execute('PRAGMA busy_timeout = 30000')
        except Exception:
            pass
        try:
            try:
                is_unc = self._is_unc_path()
            except Exception:
                is_unc = False
            try:
                db_key = os.path.abspath(str(self.db_path or '')).lower()
            except Exception:
                db_key = str(self.db_path or '')
            try:
                should_set_mode = bool(db_key) and db_key not in MessagesDB._journal_mode_applied
            except Exception:
                should_set_mode = True

            if should_set_mode:
                if is_unc:
                    conn.execute('PRAGMA journal_mode = DELETE')
                    conn.execute('PRAGMA synchronous = FULL')
                else:
                    conn.execute('PRAGMA journal_mode = WAL')
                    conn.execute('PRAGMA synchronous = NORMAL')
                try:
                    if db_key:
                        MessagesDB._journal_mode_applied.add(db_key)
                except Exception:
                    pass
            else:
                if is_unc:
                    conn.execute('PRAGMA synchronous = FULL')
                else:
                    conn.execute('PRAGMA synchronous = NORMAL')
        except Exception:
            pass
    
    def _log_change(self, cursor, *, entity_type: str, entity_id: str, action_type: str, payload=None):
        """רישום שינוי ב-change_log לסנכרון"""
        try:
            payload_json = json.dumps(payload or {}, ensure_ascii=False)
        except Exception:
            payload_json = '{}'
        try:
            cursor.execute(
                '''INSERT INTO change_log (entity_type, entity_id, action_type, payload_json)
                   VALUES (?, ?, ?, ?)''',
                (entity_type, entity_id, action_type, payload_json)
            )
        except Exception:
            pass

    def _get_raw_connection(self):
        """חיבור ישיר ל-DB ללא proxy (לשימוש פנימי כמו init_tables)"""
        db_dir = os.path.dirname(self.db_path) or '.'
        try:
            os.makedirs(db_dir, exist_ok=True)
        except Exception:
            pass
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        self._apply_pragmas(conn)
        return conn

    def init_tables(self):
        """יצירת טבלאות הודעות"""
        conn = self._get_raw_connection()
        cursor = conn.cursor()
        
        # טבלת הודעות סטטיות (public static messages)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS static_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message TEXT NOT NULL,
                show_always INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # הוספת עמודת show_always אם לא קיימת (למסדי נתונים קיימים)
        try:
            cursor.execute('ALTER TABLE static_messages ADD COLUMN show_always INTEGER DEFAULT 0')
        except:
            pass  # העמודה כבר קיימת
        
        # טבלת הודעות לפי סף נקודות (general messages by point threshold)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS threshold_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                min_points INTEGER NOT NULL,
                max_points INTEGER NOT NULL,
                message TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # טבלת חדשות (news items for ticker)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS news_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                sort_order INTEGER,
                start_date TEXT,
                end_date TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # טבלת פרסומות קופצות (POP-UP ads)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ads_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                image_path TEXT,
                is_active INTEGER DEFAULT 1,
                sort_order INTEGER,
                start_date TEXT,
                end_date TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        try:
            cursor.execute('ALTER TABLE news_items ADD COLUMN sort_order INTEGER')
        except Exception:
            pass

        try:
            cursor.execute('SELECT id FROM ads_items WHERE sort_order IS NULL ORDER BY created_at DESC')
            rows = cursor.fetchall()
            order = 1
            for row in rows:
                cursor.execute('UPDATE ads_items SET sort_order = ? WHERE id = ?', (order, row['id']))
                order += 1
        except Exception:
            pass
        
        try:
            cursor.execute('ALTER TABLE news_items ADD COLUMN start_date TEXT')
        except Exception:
            pass
        
        try:
            cursor.execute('ALTER TABLE news_items ADD COLUMN end_date TEXT')
        except Exception:
            pass

        try:
            cursor.execute('ALTER TABLE ads_items ADD COLUMN sort_order INTEGER')
        except Exception:
            pass

        try:
            cursor.execute('ALTER TABLE ads_items ADD COLUMN start_date TEXT')
        except Exception:
            pass

        try:
            cursor.execute('ALTER TABLE ads_items ADD COLUMN end_date TEXT')
        except Exception:
            pass

        try:
            cursor.execute('ALTER TABLE ads_items ADD COLUMN image_path TEXT')
        except Exception:
            pass

        try:
            cursor.execute('SELECT id FROM news_items WHERE sort_order IS NULL ORDER BY created_at DESC')
            rows = cursor.fetchall()
            order = 1
            for row in rows:
                cursor.execute('UPDATE news_items SET sort_order = ? WHERE id = ?', (order, row['id']))
                order += 1
        except Exception:
            pass
        
        # טבלת הודעות פרטיות לתלמידים (private messages for specific students)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS student_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                message TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (student_id) REFERENCES students (id)
            )
        ''')
        
        conn.commit()
        conn.close()
    
    # ===================== הודעות סטטיות =====================
    
    def add_static_message(self, message: str, show_always: bool = False) -> int:
        """הוספת הודעה סטטית"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO static_messages (message, show_always) VALUES (?, ?)
        ''', (message, 1 if show_always else 0))
        message_id = cursor.lastrowid
        try:
            self._log_change(cursor, entity_type='static_message', entity_id=str(message_id), action_type='create',
                             payload={'id': message_id, 'message': message, 'show_always': 1 if show_always else 0, 'is_active': 1})
        except Exception:
            pass
        conn.commit()
        conn.close()
        return message_id
    
    def get_active_static_messages(self, show_always: bool = None) -> List[Dict[str, Any]]:
        """קבלת כל ההודעות הסטטיות הפעילות"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        if show_always is None:
            cursor.execute('''
                SELECT * FROM static_messages WHERE is_active = 1
                ORDER BY created_at DESC
            ''')
        else:
            cursor.execute('''
                SELECT * FROM static_messages WHERE is_active = 1 AND show_always = ?
                ORDER BY created_at DESC
            ''', (1 if show_always else 0,))
        
        messages = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return messages
    
    def update_static_message(self, message_id: int, message: str) -> bool:
        """עדכון הודעה סטטית"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE static_messages SET message = ? WHERE id = ?
        ''', (message, message_id))
        success = cursor.rowcount > 0
        try:
            self._log_change(cursor, entity_type='static_message', entity_id=str(message_id), action_type='update',
                             payload={'id': message_id, 'message': message})
        except Exception:
            pass
        conn.commit()
        conn.close()
        return success
    
    def delete_static_message(self, message_id: int) -> bool:
        """מחיקת הודעה סטטית"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM static_messages WHERE id = ?', (message_id,))
        success = cursor.rowcount > 0
        try:
            self._log_change(cursor, entity_type='static_message', entity_id=str(message_id), action_type='delete', payload={})
        except Exception:
            pass
        conn.commit()
        conn.close()
        return success
    
    def toggle_static_message(self, message_id: int) -> bool:
        """הפעלה/כיבוי הודעה סטטית"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE static_messages 
            SET is_active = 1 - is_active 
            WHERE id = ?
        ''', (message_id,))
        success = cursor.rowcount > 0
        try:
            cursor.execute('SELECT * FROM static_messages WHERE id = ?', (message_id,))
            row = cursor.fetchone()
            if row:
                self._log_change(cursor, entity_type='static_message', entity_id=str(message_id), action_type='update',
                                 payload=dict(row))
        except Exception:
            pass
        conn.commit()
        conn.close()
        return success
    
    # ===================== הודעות לפי סף נקודות =====================
    
    def add_threshold_message(self, min_points: int, max_points: int, message: str) -> int:
        """הוספת הודעה לפי סף נקודות"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO threshold_messages (min_points, max_points, message)
            VALUES (?, ?, ?)
        ''', (min_points, max_points, message))
        message_id = cursor.lastrowid
        try:
            self._log_change(cursor, entity_type='threshold_message', entity_id=str(message_id), action_type='create',
                             payload={'id': message_id, 'min_points': min_points, 'max_points': max_points, 'message': message, 'is_active': 1})
        except Exception:
            pass
        conn.commit()
        conn.close()
        return message_id
    
    def get_message_for_points(self, points: int) -> Optional[str]:
        """קבלת הודעה לפי מספר נקודות"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT message FROM threshold_messages 
            WHERE is_active = 1 
            AND ? >= min_points 
            AND ? <= max_points
            ORDER BY created_at DESC
            LIMIT 1
        ''', (points, points))
        row = cursor.fetchone()
        conn.close()
        return dict(row)['message'] if row else None
    
    def get_all_threshold_messages(self) -> List[Dict[str, Any]]:
        """קבלת כל הודעות הסף"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM threshold_messages 
            ORDER BY min_points ASC
        ''')
        messages = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return messages
    
    def update_threshold_message(self, message_id: int, min_points: int, 
                                 max_points: int, message: str) -> bool:
        """עדכון הודעת סף"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE threshold_messages 
            SET min_points = ?, max_points = ?, message = ?
            WHERE id = ?
        ''', (min_points, max_points, message, message_id))
        success = cursor.rowcount > 0
        try:
            self._log_change(cursor, entity_type='threshold_message', entity_id=str(message_id), action_type='update',
                             payload={'id': message_id, 'min_points': min_points, 'max_points': max_points, 'message': message})
        except Exception:
            pass
        conn.commit()
        conn.close()
        return success
    
    def delete_threshold_message(self, message_id: int) -> bool:
        """מחיקת הודעת סף"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM threshold_messages WHERE id = ?', (message_id,))
        success = cursor.rowcount > 0
        try:
            self._log_change(cursor, entity_type='threshold_message', entity_id=str(message_id), action_type='delete', payload={})
        except Exception:
            pass
        conn.commit()
        conn.close()
        return success
    
    def toggle_threshold_message(self, message_id: int) -> bool:
        """הפעלה/כיבוי הודעת סף"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE threshold_messages 
            SET is_active = 1 - is_active 
            WHERE id = ?
        ''', (message_id,))
        success = cursor.rowcount > 0
        try:
            cursor.execute('SELECT * FROM threshold_messages WHERE id = ?', (message_id,))
            row = cursor.fetchone()
            if row:
                self._log_change(cursor, entity_type='threshold_message', entity_id=str(message_id), action_type='update',
                                 payload=dict(row))
        except Exception:
            pass
        conn.commit()
        conn.close()
        return success
    
    # ===================== חדשות (News) =====================
    
    def add_news_item(self, text: str, start_date: str = None, end_date: str = None) -> int:
        """הוספת פריט חדשות לרצועת החדשות
        
        Args:
            text: טקסט החדשה
            start_date: תאריך התחלה (YYYY-MM-DD) - אופציונלי
            end_date: תאריך סיום (YYYY-MM-DD) - אופציונלי
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT COALESCE(MAX(sort_order), 0) + 1 FROM news_items')
            row = cursor.fetchone()
            next_order = row[0] if row is not None else 1
            cursor.execute('''
                INSERT INTO news_items (text, sort_order, start_date, end_date) 
                VALUES (?, ?, ?, ?)
            ''', (text, next_order, start_date, end_date))
        except Exception:
            cursor.execute('''
                INSERT INTO news_items (text, start_date, end_date) VALUES (?, ?, ?)
            ''', (text, start_date, end_date))
        news_id = cursor.lastrowid
        try:
            self._log_change(cursor, entity_type='news_item', entity_id=str(news_id), action_type='create',
                             payload={'id': news_id, 'text': text, 'start_date': start_date, 'end_date': end_date, 'is_active': 1})
        except Exception:
            pass
        conn.commit()
        conn.close()
        return news_id
    
    def get_active_news_items(self) -> List[Dict[str, Any]]:
        """קבלת כל פריטי החדשות הפעילים לרצועת החדשות
        
        מחזיר רק חדשות שהן:
        1. פעילות (is_active = 1)
        2. בתוך טווח התאריכים (אם הוגדרו)
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM news_items
            WHERE is_active = 1
            AND (start_date IS NULL OR DATE(start_date) <= DATE('now'))
            AND (end_date IS NULL OR DATE(end_date) >= DATE('now'))
            ORDER BY 
                CASE WHEN sort_order IS NULL THEN 1 ELSE 0 END,
                sort_order ASC,
                created_at DESC
        ''')
        items = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return items
    
    def get_all_news_items(self) -> List[Dict[str, Any]]:
        """קבלת כל פריטי החדשות (לממשק הניהול)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM news_items
            ORDER BY 
                CASE WHEN sort_order IS NULL THEN 1 ELSE 0 END,
                sort_order ASC,
                created_at DESC
        ''')
        items = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return items
    
    def update_news_item(self, news_id: int, text: str, start_date: str = None, end_date: str = None) -> bool:
        """עדכון פריט חדשות
        
        Args:
            news_id: מזהה החדשה
            text: טקסט החדשה
            start_date: תאריך התחלה (YYYY-MM-DD) - אופציונלי
            end_date: תאריך סיום (YYYY-MM-DD) - אופציונלי
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE news_items 
            SET text = ?, start_date = ?, end_date = ? 
            WHERE id = ?
        ''', (text, start_date, end_date, news_id))
        success = cursor.rowcount > 0
        try:
            self._log_change(cursor, entity_type='news_item', entity_id=str(news_id), action_type='update',
                             payload={'id': news_id, 'text': text, 'start_date': start_date, 'end_date': end_date})
        except Exception:
            pass
        conn.commit()
        conn.close()
        return success
    
    def delete_news_item(self, news_id: int) -> bool:
        """מחיקת פריט חדשות"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM news_items WHERE id = ?', (news_id,))
        success = cursor.rowcount > 0
        try:
            self._log_change(cursor, entity_type='news_item', entity_id=str(news_id), action_type='delete', payload={})
        except Exception:
            pass
        conn.commit()
        conn.close()
        return success
    
    def toggle_news_item(self, news_id: int) -> bool:
        """הפעלה/כיבוי של פריט חדשות"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE news_items
            SET is_active = 1 - is_active
            WHERE id = ?
        ''', (news_id,))
        success = cursor.rowcount > 0
        try:
            cursor.execute('SELECT * FROM news_items WHERE id = ?', (news_id,))
            row = cursor.fetchone()
            if row:
                self._log_change(cursor, entity_type='news_item', entity_id=str(news_id), action_type='update',
                                 payload=dict(row))
        except Exception:
            pass
        conn.commit()
        conn.close()
        return success
    
    def clear_news_items(self) -> None:
        """מחיקת כל פריטי החדשות (לעריכה מרוכזת)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM news_items')
        conn.commit()
        conn.close()
    
    def swap_news_order(self, news_id1: int, news_id2: int) -> None:
        if news_id1 == news_id2:
            return

        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                'SELECT id, sort_order FROM news_items WHERE id IN (?, ?)',
                (news_id1, news_id2),
            )
            rows = cursor.fetchall()
            if len(rows) != 2:
                conn.close()
                return

            orders = {row['id']: row['sort_order'] for row in rows}
            order1 = orders.get(news_id1)
            order2 = orders.get(news_id2)

            # אם אחד הערכים ריק, נאתחל מחדש את כל הסדר לפי created_at וננסה שוב
            if order1 is None or order2 is None:
                cursor.execute('SELECT id FROM news_items ORDER BY created_at DESC')
                all_rows = cursor.fetchall()
                order = 1
                for row in all_rows:
                    cursor.execute('UPDATE news_items SET sort_order = ? WHERE id = ?', (order, row['id']))
                    order += 1

                cursor.execute(
                    'SELECT id, sort_order FROM news_items WHERE id IN (?, ?)',
                    (news_id1, news_id2),
                )
                rows = cursor.fetchall()
                if len(rows) != 2:
                    conn.commit()
                    conn.close()
                    return
                orders = {row['id']: row['sort_order'] for row in rows}
                order1 = orders.get(news_id1)
                order2 = orders.get(news_id2)

            if order1 is None or order2 is None:
                conn.commit()
                conn.close()
                return

            cursor.execute('UPDATE news_items SET sort_order = ? WHERE id = ?', (order2, news_id1))
            cursor.execute('UPDATE news_items SET sort_order = ? WHERE id = ?', (order1, news_id2))
            conn.commit()
        except Exception:
            conn.rollback()
        finally:
            conn.close()

    # ===================== פרסומות POP-UP =====================

    def add_ads_item(self, text: str, start_date: str = None, end_date: str = None, image_path: str = None) -> int:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT COALESCE(MAX(sort_order), 0) + 1 FROM ads_items')
            row = cursor.fetchone()
            next_order = row[0] if row is not None else 1
            cursor.execute(
                '''
                INSERT INTO ads_items (text, image_path, sort_order, start_date, end_date)
                VALUES (?, ?, ?, ?, ?)
                ''',
                (text, image_path, next_order, start_date, end_date)
            )
        except Exception:
            cursor.execute(
                '''
                INSERT INTO ads_items (text, image_path, start_date, end_date)
                VALUES (?, ?, ?, ?)
                ''',
                (text, image_path, start_date, end_date)
            )
        ads_id = cursor.lastrowid
        try:
            self._log_change(cursor, entity_type='ads_item', entity_id=str(ads_id), action_type='create',
                             payload={'id': ads_id, 'text': text, 'start_date': start_date, 'end_date': end_date, 'image_path': image_path, 'is_active': 1})
        except Exception:
            pass
        conn.commit()
        conn.close()
        return ads_id

    def get_active_ads_items(self) -> List[Dict[str, Any]]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''
            SELECT * FROM ads_items
            WHERE is_active = 1
            AND (start_date IS NULL OR DATE(start_date) <= DATE('now'))
            AND (end_date IS NULL OR DATE(end_date) >= DATE('now'))
            ORDER BY
                CASE WHEN sort_order IS NULL THEN 1 ELSE 0 END,
                sort_order ASC,
                created_at DESC
            '''
        )
        items = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return items

    def get_all_ads_items(self) -> List[Dict[str, Any]]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''
            SELECT * FROM ads_items
            ORDER BY
                CASE WHEN sort_order IS NULL THEN 1 ELSE 0 END,
                sort_order ASC,
                created_at DESC
            '''
        )
        items = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return items

    def update_ads_item(self, ads_id: int, text: str, start_date: str = None, end_date: str = None, image_path: str = None) -> bool:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''
            UPDATE ads_items
            SET text = ?, image_path = ?, start_date = ?, end_date = ?
            WHERE id = ?
            ''',
            (text, image_path, start_date, end_date, ads_id)
        )
        success = cursor.rowcount > 0
        try:
            self._log_change(cursor, entity_type='ads_item', entity_id=str(ads_id), action_type='update',
                             payload={'id': ads_id, 'text': text, 'start_date': start_date, 'end_date': end_date, 'image_path': image_path})
        except Exception:
            pass
        conn.commit()
        conn.close()
        return success

    def delete_ads_item(self, ads_id: int) -> bool:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM ads_items WHERE id = ?', (ads_id,))
        success = cursor.rowcount > 0
        try:
            self._log_change(cursor, entity_type='ads_item', entity_id=str(ads_id), action_type='delete', payload={})
        except Exception:
            pass
        conn.commit()
        conn.close()
        return success

    def toggle_ads_item(self, ads_id: int) -> bool:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            '''
            UPDATE ads_items
            SET is_active = 1 - is_active
            WHERE id = ?
            ''',
            (ads_id,)
        )
        success = cursor.rowcount > 0
        try:
            cursor.execute('SELECT * FROM ads_items WHERE id = ?', (ads_id,))
            row = cursor.fetchone()
            if row:
                self._log_change(cursor, entity_type='ads_item', entity_id=str(ads_id), action_type='update',
                                 payload=dict(row))
        except Exception:
            pass
        conn.commit()
        conn.close()
        return success

    def swap_ads_order(self, ads_id1: int, ads_id2: int) -> None:
        if ads_id1 == ads_id2:
            return

        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                'SELECT id, sort_order FROM ads_items WHERE id IN (?, ?)',
                (ads_id1, ads_id2),
            )
            rows = cursor.fetchall()
            if len(rows) != 2:
                conn.close()
                return

            orders = {row['id']: row['sort_order'] for row in rows}
            order1 = orders.get(ads_id1)
            order2 = orders.get(ads_id2)

            if order1 is None or order2 is None:
                cursor.execute('SELECT id FROM ads_items ORDER BY created_at DESC')
                all_rows = cursor.fetchall()
                order = 1
                for row in all_rows:
                    cursor.execute('UPDATE ads_items SET sort_order = ? WHERE id = ?', (order, row['id']))
                    order += 1

                cursor.execute(
                    'SELECT id, sort_order FROM ads_items WHERE id IN (?, ?)',
                    (ads_id1, ads_id2),
                )
                rows = cursor.fetchall()
                if len(rows) != 2:
                    conn.commit()
                    conn.close()
                    return
                orders = {row['id']: row['sort_order'] for row in rows}
                order1 = orders.get(ads_id1)
                order2 = orders.get(ads_id2)

            if order1 is None or order2 is None:
                conn.commit()
                conn.close()
                return

            cursor.execute('UPDATE ads_items SET sort_order = ? WHERE id = ?', (order2, ads_id1))
            cursor.execute('UPDATE ads_items SET sort_order = ? WHERE id = ?', (order1, ads_id2))
            conn.commit()
        except Exception:
            conn.rollback()
        finally:
            conn.close()
    
    # ===================== הודעות פרטיות לתלמידים =====================
    
    def add_student_message(self, student_id: int, message: str) -> int:
        """הוספת הודעה פרטית לתלמיד"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO student_messages (student_id, message)
            VALUES (?, ?)
        ''', (student_id, message))
        message_id = cursor.lastrowid
        try:
            self._log_change(cursor, entity_type='student_message', entity_id=str(message_id), action_type='create',
                             payload={'id': message_id, 'student_id': student_id, 'message': message, 'is_active': 1})
        except Exception:
            pass
        conn.commit()
        conn.close()
        return message_id
    
    def get_student_message(self, student_id: int) -> Optional[str]:
        """קבלת הודעה פרטית לתלמיד"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT message FROM student_messages 
            WHERE student_id = ? AND is_active = 1
            ORDER BY created_at DESC
            LIMIT 1
        ''', (student_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row)['message'] if row else None
    
    def get_all_student_messages(self) -> List[Dict[str, Any]]:
        """קבלת כל ההודעות הפרטיות"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT sm.*, s.first_name, s.last_name
            FROM student_messages sm
            JOIN students s ON sm.student_id = s.id
            ORDER BY sm.created_at DESC
        ''')
        messages = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return messages
    
    def update_student_message(self, message_id: int, message: str) -> bool:
        """עדכון הודעה פרטית"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE student_messages SET message = ? WHERE id = ?
        ''', (message, message_id))
        success = cursor.rowcount > 0
        try:
            self._log_change(cursor, entity_type='student_message', entity_id=str(message_id), action_type='update',
                             payload={'id': message_id, 'message': message})
        except Exception:
            pass
        conn.commit()
        conn.close()
        return success
    
    def delete_student_message(self, message_id: int) -> bool:
        """מחיקת הודעה פרטית"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM student_messages WHERE id = ?', (message_id,))
        success = cursor.rowcount > 0
        try:
            self._log_change(cursor, entity_type='student_message', entity_id=str(message_id), action_type='delete', payload={})
        except Exception:
            pass
        conn.commit()
        conn.close()
        return success
    
    def toggle_student_message(self, message_id: int) -> bool:
        """הפעלה/כיבוי הודעה פרטית"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE student_messages 
            SET is_active = 1 - is_active 
            WHERE id = ?
        ''', (message_id,))
        success = cursor.rowcount > 0
        try:
            cursor.execute('SELECT * FROM student_messages WHERE id = ?', (message_id,))
            row = cursor.fetchone()
            if row:
                self._log_change(cursor, entity_type='student_message', entity_id=str(message_id), action_type='update',
                                 payload=dict(row))
        except Exception:
            pass
        conn.commit()
        conn.close()
        return success
