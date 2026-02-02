"""
מודול מסד נתונים למערכת ניקוד בית ספרית
"""
import sqlite3
import os
import json
import shutil
import re
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple


class Database:
    _db_path_printed = False

    def __init__(self, db_path: str = None):
        """אתחול מסד נתונים"""
        # ברירת מחדל: איתור קובץ ה-DB לפי הגדרות רשת/קובץ, ואם אין – תיקיית נתונים למשתמש
        if db_path is None:
            base_dir = os.path.dirname(os.path.abspath(__file__))

            # קריאת הגדרות מ-config.json "חי" (אם קיים) במיקום כתיב, עם נפילה חזרה לקובץ המובנה
            config_db_path = None
            shared_folder = None

            config_file = None
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
                        candidate = os.path.join(cfg_dir, "config.json")
                        # אם אין קובץ חי אבל יש קובץ ברירת-מחדל בתיקיית הקוד – ננסה להעתיקו
                        if not os.path.exists(candidate):
                            base_cfg = os.path.join(base_dir, "config.json")
                            if os.path.exists(base_cfg):
                                try:
                                    shutil.copy2(base_cfg, candidate)
                                except Exception:
                                    pass
                        config_file = candidate
                        break
                except Exception:
                    continue

            # אם לא נמצא קובץ חי – נשתמש בקובץ שבתיקיית הקוד אם קיים
            if config_file is None:
                fallback = os.path.join(base_dir, "config.json")
                if os.path.exists(fallback):
                    config_file = fallback

            if config_file and os.path.exists(config_file):
                try:
                    with open(config_file, 'r', encoding='utf-8') as f:
                        cfg = json.load(f)
                    # נתיב DB ישיר
                    config_db_path = cfg.get('db_path')
                    # או תיקיית רשת משותפת (db ו-Excel יחד)
                    if not config_db_path:
                        shared_folder = cfg.get('shared_folder') or cfg.get('network_root')
                except Exception as e:
                    print(f"שגיאה בקריאת config.json: {e}")

            # בדיקה אם יש נתיב DB משותף מוגדר
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
                except Exception:
                    pass

            # נתיב ברירת מחדל ל-DB עבור משתמש הנוכחי (LOCALAPPDATA / APPDATA / PROGRAMDATA)
            user_root = (
                os.environ.get('LOCALAPPDATA')
                or os.environ.get('APPDATA')
                or os.environ.get('PROGRAMDATA')
                or base_dir
            )
            default_user_db = os.path.join(user_root, 'SchoolPoints', 'school_points.db')

            # השתמש ב-DB משותף אם הוגדר, אחרת מקומי למשתמש
            if config_db_path:
                self.db_path = config_db_path
                if not Database._db_path_printed:
                    print(f"[DB] Config DB: {config_db_path}")
                    Database._db_path_printed = True
            elif shared_folder:
                self.db_path = os.path.join(shared_folder, 'school_points.db')
                if not Database._db_path_printed:
                    print(f"[DB] Shared folder DB: {self.db_path}")
                    Database._db_path_printed = True
            elif custom_db_path:
                self.db_path = custom_db_path
                if not Database._db_path_printed:
                    print(f"[DB] Shared DB: {custom_db_path}")
                    Database._db_path_printed = True
            else:
                # אם תיקיית הקוד ניתנת לכתיבה ולא מדובר ב-Program Files – אפשר להשתמש בה בסביבת פיתוח
                use_base_dir = False
                try:
                    if os.access(base_dir, os.W_OK) and 'program files' not in base_dir.lower():
                        use_base_dir = True
                except Exception:
                    use_base_dir = False

                if use_base_dir:
                    self.db_path = os.path.join(base_dir, 'school_points.db')
                else:
                    self.db_path = default_user_db
                    if not Database._db_path_printed:
                        print(f"[DB] Local user DB: {self.db_path}")
                        Database._db_path_printed = True
        else:
            self.db_path = db_path
        self.create_tables()
    
    def get_connection(self):
        """יצירת חיבור למסד הנתונים"""
        # ודא שהתיקייה של ה-DB קיימת (למשל בתיקיית נתוני משתמש)
        db_dir = os.path.dirname(self.db_path) or '.'
        try:
            os.makedirs(db_dir, exist_ok=True)
        except Exception:
            # אם לא הצלחנו ליצור תיקייה – ניתן ל-sqlite לטפל בשגיאה
            pass

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # מאפשר גישה לעמודות לפי שם
        return conn

    def _cleanup_expired_holds(self, cursor) -> None:
        try:
            cursor.execute('DELETE FROM purchase_holds WHERE expires_at <= CURRENT_TIMESTAMP')
        except Exception:
            pass

    def clear_holds(self, *, station_id: str, student_id: Optional[int] = None) -> None:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            self._cleanup_expired_holds(cursor)
            if student_id is None:
                cursor.execute('DELETE FROM purchase_holds WHERE station_id = ?', (str(station_id or '').strip(),))
            else:
                cursor.execute(
                    'DELETE FROM purchase_holds WHERE station_id = ? AND student_id = ?',
                    (str(station_id or '').strip(), int(student_id or 0))
                )
            conn.commit()
        finally:
            conn.close()

    def refresh_holds(self, *, station_id: str, student_id: Optional[int] = None, ttl_minutes: int = 10) -> None:
        """Extends expires_at for active holds (used as a heartbeat while cashier is active)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            conn.execute('BEGIN IMMEDIATE')
            self._cleanup_expired_holds(cursor)
            station_key = str(station_id or '').strip()
            if not station_key:
                conn.rollback()
                return
            if student_id is None:
                cursor.execute(
                    "UPDATE purchase_holds SET expires_at = datetime('now', ?) WHERE station_id = ?",
                    (self._ttl_expr_minutes(int(ttl_minutes)), station_key)
                )
            else:
                cursor.execute(
                    "UPDATE purchase_holds SET expires_at = datetime('now', ?) WHERE station_id = ? AND student_id = ?",
                    (self._ttl_expr_minutes(int(ttl_minutes)), station_key, int(student_id or 0))
                )
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
        finally:
            conn.close()

    def _ttl_expr_minutes(self, ttl_minutes: int) -> str:
        try:
            ttl = int(ttl_minutes or 0)
        except Exception:
            ttl = 10
        if ttl <= 0:
            ttl = 10
        return f"+{ttl} minutes"

    def apply_product_hold_delta(self, *, station_id: str, student_id: int, product_id: int,
                                 variant_id: int, delta_qty: int, ttl_minutes: int = 10) -> Dict[str, Any]:
        """Creates/removes product holds immediately. Enforces stock against other stations' holds."""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            conn.execute('BEGIN IMMEDIATE')
            self._cleanup_expired_holds(cursor)

            pid = int(product_id or 0)
            vid = int(variant_id or 0)
            dq = int(delta_qty or 0)
            if not pid or dq == 0:
                conn.rollback()
                return {'ok': False, 'error': 'כמות לא תקינה'}

            stock_qty = None
            if vid > 0:
                cursor.execute('SELECT stock_qty, product_id, is_active FROM product_variants WHERE id = ?', (int(vid),))
                vrow = cursor.fetchone()
                if not vrow or int(vrow['is_active'] or 1) != 1:
                    conn.rollback()
                    return {'ok': False, 'error': 'וריאציה לא פעילה'}
                try:
                    pid = int(vrow['product_id'] or 0)
                except Exception:
                    pid = int(pid)
                stock_qty = vrow['stock_qty']

            cursor.execute('SELECT stock_qty, is_active FROM products WHERE id = ?', (int(pid),))
            prow = cursor.fetchone()
            if not prow or int(prow['is_active'] or 1) != 1:
                conn.rollback()
                return {'ok': False, 'error': 'מוצר לא פעיל'}
            if vid <= 0:
                stock_qty = prow['stock_qty']

            if stock_qty is not None:
                try:
                    stock_qty = int(stock_qty)
                except Exception:
                    stock_qty = None

            station_key = str(station_id or '').strip()

            if stock_qty is not None:
                cursor.execute(
                    '''
                    SELECT COALESCE(SUM(qty),0) AS q
                      FROM purchase_holds
                     WHERE hold_type = 'product'
                       AND expires_at > CURRENT_TIMESTAMP
                       AND product_id = ?
                       AND COALESCE(variant_id, 0) = ?
                       AND station_id <> ?
                    ''',
                    (int(pid), int(vid), station_key)
                )
                row = cursor.fetchone()
                other_qty = int((row['q'] if row else 0) or 0)

                cursor.execute(
                    '''
                    SELECT COALESCE(SUM(qty),0) AS q
                      FROM purchase_holds
                     WHERE hold_type = 'product'
                       AND expires_at > CURRENT_TIMESTAMP
                       AND product_id = ?
                       AND COALESCE(variant_id, 0) = ?
                       AND station_id = ? AND student_id = ?
                    ''',
                    (int(pid), int(vid), station_key, int(student_id or 0))
                )
                row = cursor.fetchone()
                mine_qty = int((row['q'] if row else 0) or 0)

                new_mine = int(mine_qty + dq)
                if new_mine < 0:
                    new_mine = 0
                available_for_me = int(stock_qty - other_qty)
                if new_mine > available_for_me:
                    conn.rollback()
                    return {'ok': False, 'error': 'אין מספיק מלאי'}

            if dq > 0:
                cursor.execute(
                    '''
                    INSERT INTO purchase_holds (station_id, student_id, hold_type, product_id, variant_id, qty, expires_at)
                    VALUES (?, ?, 'product', ?, ?, ?, datetime('now', ?))
                    ''',
                    (
                        station_key,
                        int(student_id or 0),
                        int(pid),
                        (int(vid) if int(vid or 0) > 0 else None),
                        int(dq),
                        self._ttl_expr_minutes(int(ttl_minutes)),
                    )
                )
            else:
                dq = abs(int(dq))
                cursor.execute(
                    '''
                    SELECT id, qty
                      FROM purchase_holds
                     WHERE hold_type = 'product'
                       AND expires_at > CURRENT_TIMESTAMP
                       AND station_id = ? AND student_id = ?
                       AND product_id = ? AND COALESCE(variant_id,0) = ?
                     ORDER BY id DESC
                    ''',
                    (station_key, int(student_id or 0), int(pid), int(vid))
                )
                rows = cursor.fetchall() or []
                for r in rows:
                    if dq <= 0:
                        break
                    rid = int(r['id'] or 0)
                    try:
                        q = int(r['qty'] or 0)
                    except Exception:
                        q = 0
                    if q <= dq:
                        cursor.execute('DELETE FROM purchase_holds WHERE id = ?', (int(rid),))
                        dq -= q
                    else:
                        cursor.execute('UPDATE purchase_holds SET qty = ? WHERE id = ?', (int(q - dq), int(rid)))
                        dq = 0

            conn.commit()
            return {'ok': True}
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            return {'ok': False, 'error': str(e)}
        finally:
            conn.close()

    def create_scheduled_hold(self, *, station_id: str, student_id: int, service_id: int,
                              service_date: str, slot_start_time: str, duration_minutes: int,
                              ttl_minutes: int = 10) -> Dict[str, Any]:
        """Creates a scheduled-slot hold immediately (capacity across stations)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            conn.execute('BEGIN IMMEDIATE')
            self._cleanup_expired_holds(cursor)

            sid = int(service_id or 0)
            stid = int(student_id or 0)
            sd = str(service_date or '').strip()
            stt = str(slot_start_time or '').strip()
            dur = int(duration_minutes or 0)
            if not sid or not stid or not sd or not stt or dur <= 0:
                conn.rollback()
                return {'ok': False, 'error': 'נתונים לא תקינים'}

            cursor.execute('SELECT capacity_per_slot FROM scheduled_services WHERE id = ? AND is_active = 1', (int(sid),))
            row = cursor.fetchone()
            if not row:
                conn.rollback()
                return {'ok': False, 'error': 'האתגר לא פעיל'}
            cap = int((row['capacity_per_slot'] if row else 1) or 1)

            cursor.execute(
                'SELECT COUNT(1) AS c FROM scheduled_service_dates WHERE service_id = ? AND is_active = 1 AND service_date = ?',
                (int(sid), sd)
            )
            ok = cursor.fetchone()
            if int((ok['c'] if ok else 0) or 0) <= 0:
                conn.rollback()
                return {'ok': False, 'error': 'התאריך לא זמין'}

            station_key = str(station_id or '').strip()

            # If already held by this station/student for same slot, treat as ok (idempotent)
            cursor.execute(
                '''
                SELECT COUNT(1) AS c
                  FROM purchase_holds
                 WHERE hold_type = 'scheduled'
                   AND expires_at > CURRENT_TIMESTAMP
                   AND station_id = ? AND student_id = ?
                   AND service_id = ? AND service_date = ? AND slot_start_time = ?
                ''',
                (station_key, int(stid), int(sid), sd, stt)
            )
            row = cursor.fetchone()
            if int((row['c'] if row else 0) or 0) > 0:
                conn.commit()
                return {'ok': True}

            # Prevent overlaps for the same student on the same date (reservations + holds)
            try:
                def _to_min(hhmm: str) -> int:
                    hhmm = str(hhmm or '').strip()
                    if ':' not in hhmm:
                        return -1
                    hh, mm = hhmm.split(':', 1)
                    return int(hh) * 60 + int(mm)

                start_min = _to_min(stt)
                end_min = start_min + int(dur)
                if start_min >= 0 and int(dur) > 0:
                    cursor.execute(
                        '''
                        SELECT slot_start_time, duration_minutes
                          FROM scheduled_service_reservations
                         WHERE student_id = ? AND service_date = ?
                        ''',
                        (int(stid), sd)
                    )
                    for r in (cursor.fetchall() or []):
                        os_ = _to_min(r['slot_start_time'])
                        try:
                            od = int(r['duration_minutes'] or 0)
                        except Exception:
                            od = 0
                        if os_ < 0 or od <= 0:
                            continue
                        oe = os_ + od
                        if start_min < oe and os_ < end_min:
                            conn.rollback()
                            return {'ok': False, 'error': 'לתלמיד כבר יש אתגר בזמן הזה'}

                    cursor.execute(
                        '''
                        SELECT slot_start_time, duration_minutes
                          FROM purchase_holds
                         WHERE hold_type = 'scheduled'
                           AND expires_at > CURRENT_TIMESTAMP
                           AND student_id = ? AND service_date = ?
                        ''',
                        (int(stid), sd)
                    )
                    for r in (cursor.fetchall() or []):
                        os_ = _to_min(r['slot_start_time'])
                        try:
                            od = int(r['duration_minutes'] or 0)
                        except Exception:
                            od = 0
                        if os_ < 0 or od <= 0:
                            continue
                        oe = os_ + od
                        if start_min < oe and os_ < end_min:
                            conn.rollback()
                            return {'ok': False, 'error': 'לתלמיד כבר יש שריון לאתגר בזמן הזה'}
            except Exception:
                pass

            cursor.execute(
                'SELECT COUNT(1) AS c FROM scheduled_service_reservations WHERE service_id = ? AND service_date = ? AND slot_start_time = ?',
                (int(sid), sd, stt)
            )
            row = cursor.fetchone()
            used_res = int((row['c'] if row else 0) or 0)
            cursor.execute(
                '''
                SELECT COALESCE(SUM(qty),0) AS q
                  FROM purchase_holds
                 WHERE hold_type = 'scheduled'
                   AND expires_at > CURRENT_TIMESTAMP
                   AND service_id = ? AND service_date = ? AND slot_start_time = ?
                   AND station_id <> ?
                ''',
                (int(sid), sd, stt, station_key)
            )
            other_h = cursor.fetchone()
            used_hold = int((other_h['q'] if other_h else 0) or 0)
            if int(used_res + used_hold) >= int(cap):
                conn.rollback()
                return {'ok': False, 'error': 'הסלוט מלא'}

            cursor.execute(
                '''
                INSERT INTO purchase_holds (station_id, student_id, hold_type, service_id, service_date, slot_start_time, duration_minutes, qty, expires_at)
                VALUES (?, ?, 'scheduled', ?, ?, ?, ?, 1, datetime('now', ?))
                ''',
                (station_key, int(stid), int(sid), sd, stt, int(dur), self._ttl_expr_minutes(int(ttl_minutes)))
            )
            conn.commit()
            return {'ok': True}
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            return {'ok': False, 'error': str(e)}
        finally:
            conn.close()

    def release_scheduled_hold(self, *, station_id: str, student_id: int, service_id: int,
                               service_date: str, slot_start_time: str) -> Dict[str, Any]:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            conn.execute('BEGIN IMMEDIATE')
            self._cleanup_expired_holds(cursor)

            station_key = str(station_id or '').strip()
            stid = int(student_id or 0)
            sid = int(service_id or 0)
            sd = str(service_date or '').strip()
            stt = str(slot_start_time or '').strip()
            if not station_key or not stid or not sid or not sd or not stt:
                conn.rollback()
                return {'ok': False, 'error': 'נתונים לא תקינים'}

            cursor.execute(
                '''
                SELECT id
                  FROM purchase_holds
                 WHERE hold_type = 'scheduled'
                   AND expires_at > CURRENT_TIMESTAMP
                   AND station_id = ? AND student_id = ?
                   AND service_id = ? AND service_date = ? AND slot_start_time = ?
                 ORDER BY id DESC
                 LIMIT 1
                ''',
                (station_key, int(stid), int(sid), sd, stt)
            )
            row = cursor.fetchone()
            if row:
                cursor.execute('DELETE FROM purchase_holds WHERE id = ?', (int(row['id'] or 0),))
            conn.commit()
            return {'ok': True}
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            return {'ok': False, 'error': str(e)}
        finally:
            conn.close()
    
    def create_tables(self):
        """יצירת טבלאות במסד הנתונים"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # טבלת תלמידים
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                serial_number INTEGER,
                last_name TEXT NOT NULL,
                first_name TEXT NOT NULL,
                id_number TEXT,
                class_name TEXT,
                photo_number TEXT,
                card_number TEXT,
                points INTEGER DEFAULT 0,
                private_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(card_number) ON CONFLICT IGNORE
            )
        ''')
        
        # הוספת עמודת private_message אם לא קיימת (למסדי נתונים קיימים)
        try:
            cursor.execute('ALTER TABLE students ADD COLUMN private_message TEXT')
        except:
            pass  # העמודה כבר קיימת
        
        # הוספת עמודת is_free_fix_blocked אם לא קיימת (חסימת תיקופים חינם)
        try:
            cursor.execute('ALTER TABLE students ADD COLUMN is_free_fix_blocked INTEGER DEFAULT 0')
        except:
            pass  # העמודה כבר קיימת
        
        # טבלת חסימות כרטיסים (אנטי-ספאם)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS card_blocks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                card_number TEXT NOT NULL,
                block_start TIMESTAMP NOT NULL,
                block_end TIMESTAMP NOT NULL,
                block_reason TEXT,
                violation_count INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (student_id) REFERENCES students(id)
            )
        ''')
        
        # טבלת תיקופי כרטיס (למעקב אחר ספאם)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS card_validations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                card_number TEXT NOT NULL,
                validated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (student_id) REFERENCES students(id)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS anti_spam_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                card_number TEXT NOT NULL,
                event_type TEXT NOT NULL,
                rule_count INTEGER,
                rule_minutes INTEGER,
                duration_minutes INTEGER,
                recent_count INTEGER,
                message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (student_id) REFERENCES students(id)
            )
        ''')

        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_anti_spam_events_time ON anti_spam_events(created_at)')
        except Exception:
            pass
        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_anti_spam_events_student_time ON anti_spam_events(student_id, created_at)')
        except Exception:
            pass

        # טבלת היסטוריית נקודות (אופציונלי - למעקב)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS points_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER,
                points_added INTEGER,
                reason TEXT,
                added_by TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (student_id) REFERENCES students(id)
            )
        ''')

        # טבלת לוג נקודות מפורט (מומלץ) – מאפשר ייצוא מלא לפי תלמיד (תאריך/שעה, לפני/אחרי, מי ביצע וסוג פעולה)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS points_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                old_points INTEGER NOT NULL,
                new_points INTEGER NOT NULL,
                delta INTEGER NOT NULL,
                reason TEXT,
                actor_name TEXT,
                action_type TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (student_id) REFERENCES students(id)
            )
        ''')

        # אינדקסים לייצוא מהיר לפי תלמיד/תאריך
        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_points_log_student_time ON points_log(student_id, created_at)')
        except Exception:
            pass
        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_points_log_time ON points_log(created_at)')
        except Exception:
            pass
        
        # טבלת הודעות
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_type TEXT NOT NULL,
                message_text TEXT NOT NULL,
                points_threshold INTEGER,
                student_id INTEGER,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (student_id) REFERENCES students(id)
            )
        ''')
        
        # טבלת הגדרות
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # לוג שינויים לסנכרון עתידי (שלב A)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS change_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_type TEXT NOT NULL,
                entity_id TEXT,
                action_type TEXT NOT NULL,
                payload_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                synced_at TIMESTAMP
            )
        ''')

        try:
            cursor.execute("""
                INSERT OR IGNORE INTO settings (key, value) VALUES ('cashier_mode', 'teacher')
            """)
        except Exception:
            pass
        try:
            cursor.execute("""
                INSERT OR IGNORE INTO settings (key, value) VALUES ('cashier_idle_timeout_sec', '300')
            """)
        except Exception:
            pass
        try:
            cursor.execute("""
                INSERT OR IGNORE INTO settings (key, value) VALUES ('cashier_bw_logo_path', '')
            """)
        except Exception:
            pass

        try:
            cursor.execute("""
                INSERT OR IGNORE INTO settings (key, value) VALUES ('cashier_require_rescan_confirm', '1')
            """)
        except Exception:
            pass

        # קטגוריות מוצרים לקופה
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS product_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                sort_order INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(name) ON CONFLICT IGNORE
            )
        ''')

        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_product_categories_active_sort ON product_categories(is_active, sort_order, name)')
        except Exception:
            pass

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                display_name TEXT,
                image_path TEXT,
                category_id INTEGER,
                price_points INTEGER DEFAULT 0,
                stock_qty INTEGER,
                deduct_points INTEGER DEFAULT 1,
                sort_order INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # וריאציות למוצרים (קטן/בינוני/גדול וכו')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS product_variants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                variant_name TEXT NOT NULL,
                display_name TEXT,
                price_points INTEGER DEFAULT 0,
                stock_qty INTEGER,
                deduct_points INTEGER DEFAULT 1,
                is_active INTEGER DEFAULT 1,
                sort_order INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
            )
        ''')

        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_product_variants_product ON product_variants(product_id, is_active, sort_order)')
        except Exception:
            pass

        try:
            cursor.execute('ALTER TABLE products ADD COLUMN display_name TEXT')
        except Exception:
            pass
        try:
            cursor.execute('ALTER TABLE products ADD COLUMN image_path TEXT')
        except Exception:
            pass

        try:
            cursor.execute('ALTER TABLE products ADD COLUMN category_id INTEGER')
        except Exception:
            pass

        # Product availability / limits / conditional pricing (migrations)
        try:
            cursor.execute('ALTER TABLE products ADD COLUMN allowed_classes TEXT')
        except Exception:
            pass
        try:
            cursor.execute('ALTER TABLE products ADD COLUMN min_points_required INTEGER DEFAULT 0')
        except Exception:
            pass
        try:
            cursor.execute('ALTER TABLE products ADD COLUMN max_per_student INTEGER')
        except Exception:
            pass
        try:
            cursor.execute('ALTER TABLE products ADD COLUMN max_per_class INTEGER')
        except Exception:
            pass
        try:
            cursor.execute('ALTER TABLE products ADD COLUMN price_override_min_points INTEGER')
        except Exception:
            pass
        try:
            cursor.execute('ALTER TABLE products ADD COLUMN price_override_points INTEGER')
        except Exception:
            pass

        try:
            cursor.execute('ALTER TABLE products ADD COLUMN price_override_discount_pct INTEGER')
        except Exception:
            pass

        try:
            cursor.execute('ALTER TABLE purchases_log ADD COLUMN refunded_at TIMESTAMP')
        except Exception:
            pass

        # UI no longer supports non-deducting products; enforce consistent data
        try:
            cursor.execute('UPDATE products SET deduct_points = 1')
        except Exception:
            pass
        try:
            cursor.execute('UPDATE product_variants SET deduct_points = 1')
        except Exception:
            pass

        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_products_active ON products(is_active, name)')
        except Exception:
            pass
        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_products_category ON products(category_id, is_active, sort_order)')
        except Exception:
            pass

        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_products_active_sort ON products(is_active, sort_order, name)')
        except Exception:
            pass

        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_products_category ON products(category_id, is_active, sort_order)')
        except Exception:
            pass

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS cashier_responsibles (
                student_id INTEGER PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS purchases_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER,
                product_id INTEGER,
                variant_id INTEGER,
                qty INTEGER DEFAULT 1,
                points_each INTEGER DEFAULT 0,
                total_points INTEGER DEFAULT 0,
                deduct_points INTEGER DEFAULT 1,
                station_type TEXT,
                is_refunded INTEGER DEFAULT 0,
                refunded_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (student_id) REFERENCES students(id),
                FOREIGN KEY (product_id) REFERENCES products(id),
                FOREIGN KEY (variant_id) REFERENCES product_variants(id)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS receipt_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                station_type TEXT,
                student_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                data_json TEXT
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS receipt_snapshot_purchases (
                purchase_id INTEGER PRIMARY KEY,
                snapshot_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (purchase_id) REFERENCES purchases_log(id) ON DELETE CASCADE,
                FOREIGN KEY (snapshot_id) REFERENCES receipt_snapshots(id) ON DELETE CASCADE
            )
        ''')
        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_receipt_snapshot_purchases_snapshot ON receipt_snapshot_purchases(snapshot_id, created_at)')
        except Exception:
            pass

        # Holds (temporary reservations) for products and scheduled slots
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS purchase_holds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                station_id TEXT NOT NULL,
                student_id INTEGER,
                hold_type TEXT NOT NULL,
                product_id INTEGER,
                variant_id INTEGER,
                qty INTEGER DEFAULT 1,
                service_id INTEGER,
                service_date TEXT,
                slot_start_time TEXT,
                duration_minutes INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL
            )
        ''')
        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_holds_exp ON purchase_holds(expires_at)')
        except Exception:
            pass
        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_holds_prod ON purchase_holds(hold_type, product_id, variant_id, expires_at)')
        except Exception:
            pass
        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_holds_sched ON purchase_holds(hold_type, service_id, service_date, slot_start_time, expires_at)')
        except Exception:
            pass
        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_holds_station ON purchase_holds(station_id, student_id, expires_at)')
        except Exception:
            pass

        # מיגרציות לטבלה קיימת
        try:
            cursor.execute('ALTER TABLE purchases_log ADD COLUMN variant_id INTEGER')
        except Exception:
            pass
        try:
            cursor.execute('ALTER TABLE purchases_log ADD COLUMN is_refunded INTEGER DEFAULT 0')
        except Exception:
            pass
        try:
            cursor.execute('ALTER TABLE purchases_log ADD COLUMN refunded_at TIMESTAMP')
        except Exception:
            pass

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS refunds_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                purchase_id INTEGER NOT NULL UNIQUE,
                student_id INTEGER NOT NULL,
                refunded_points INTEGER DEFAULT 0,
                qty INTEGER DEFAULT 1,
                product_id INTEGER,
                variant_id INTEGER,
                reason TEXT,
                approved_by_teacher_id INTEGER,
                approved_by_teacher_name TEXT,
                station_type TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (purchase_id) REFERENCES purchases_log(id),
                FOREIGN KEY (student_id) REFERENCES students(id),
                FOREIGN KEY (product_id) REFERENCES products(id),
                FOREIGN KEY (variant_id) REFERENCES product_variants(id)
            )
        ''')

        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_products_active ON products(is_active, name)')
        except Exception:
            pass
        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_purchases_student_time ON purchases_log(student_id, created_at)')
        except Exception:
            pass

        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_purchases_refunded ON purchases_log(is_refunded, created_at)')
        except Exception:
            pass

        # יצירת וריאציה ברירת מחדל לכל מוצר (רק אם אין וריאציות)
        try:
            cursor.execute('SELECT id, display_name, price_points, stock_qty, deduct_points, is_active FROM products')
            prows = cursor.fetchall() or []
        except Exception:
            prows = []
        for pr in prows:
            try:
                pid = int(pr['id'] or 0)
            except Exception:
                pid = 0
            if not pid:
                continue
            try:
                cursor.execute('SELECT COUNT(1) AS c FROM product_variants WHERE product_id = ?', (pid,))
                c = cursor.fetchone()
                has_any = int((c['c'] if c else 0) or 0) > 0
            except Exception:
                has_any = False
            if has_any:
                continue
            try:
                cursor.execute(
                    '''
                    INSERT INTO product_variants (product_id, variant_name, display_name, price_points, stock_qty, deduct_points, is_active, sort_order, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ''',
                    (
                        pid,
                        'ברירת מחדל',
                        str(pr['display_name'] or '').strip(),
                        int(pr['price_points'] or 0),
                        pr['stock_qty'],
                        int(pr['deduct_points'] or 1),
                        int(pr['is_active'] or 1),
                        0
                    )
                )
            except Exception:
                pass
        
        # הגדרת ברירת מחדל - סטטיסטיקות כבויות (ניתן להפעיל בהגדרות מערכת)
        cursor.execute('''
            INSERT OR IGNORE INTO settings (key, value) VALUES ('show_statistics', '0')
        ''')

        # הגדרת ברירת מחדל - הצגת תמונת תלמיד בעמדה הציבורית כבויה (ניתן להפעיל בהגדרות מערכת)
        cursor.execute('''
            INSERT OR IGNORE INTO settings (key, value) VALUES ('show_student_photo', '0')
        ''')

        cursor.execute("""
            INSERT OR IGNORE INTO settings (key, value) VALUES ('news_show_weekday', '0')
        """)
        cursor.execute("""
            INSERT OR IGNORE INTO settings (key, value) VALUES ('news_show_hebrew_date', '0')
        """)
        cursor.execute("""
            INSERT OR IGNORE INTO settings (key, value) VALUES ('news_show_parsha', '0')
        """)
        cursor.execute("""
            INSERT OR IGNORE INTO settings (key, value) VALUES ('news_show_holidays', '0')
        """)
        cursor.execute("""
            INSERT OR IGNORE INTO settings (key, value) VALUES ('news_israel_schedule', '1')
        """)
        
        # טבלת בונוס זמנים
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS time_bonus_schedules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                group_name TEXT,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                bonus_points INTEGER NOT NULL,
                sound_key TEXT,
                is_general INTEGER DEFAULT 1,
                classes TEXT,
                days_of_week TEXT,
                is_shown_public INTEGER DEFAULT 1,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        try:
            cursor.execute('ALTER TABLE time_bonus_schedules ADD COLUMN group_name TEXT')
        except:
            pass

        try:
            cursor.execute('ALTER TABLE time_bonus_schedules ADD COLUMN is_general INTEGER DEFAULT 1')
        except:
            pass

        try:
            cursor.execute('ALTER TABLE time_bonus_schedules ADD COLUMN classes TEXT')
        except:
            pass

        try:
            cursor.execute('ALTER TABLE time_bonus_schedules ADD COLUMN is_shown_public INTEGER DEFAULT 1')
        except:
            pass

        try:
            cursor.execute('ALTER TABLE time_bonus_schedules ADD COLUMN days_of_week TEXT')
        except:
            pass

        try:
            cursor.execute('ALTER TABLE time_bonus_schedules ADD COLUMN sound_key TEXT')
        except:
            pass

        # טבלת חסימות/חופשות לעמדה הציבורית בלבד
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS public_closures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                subtitle TEXT,
                start_at TEXT NOT NULL,
                end_at TEXT NOT NULL,
                repeat_weekly INTEGER DEFAULT 0,
                weekly_start_day TEXT,
                weekly_start_time TEXT,
                weekly_end_day TEXT,
                weekly_end_time TEXT,
                image_path_portrait TEXT,
                image_path_landscape TEXT,
                enabled INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_public_closures_enabled ON public_closures(enabled)')
        except Exception:
            pass

        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_public_closures_window ON public_closures(start_at, end_at)')
        except Exception:
            pass

        # טבלאות אתגרים (משימות) עם לוח זמנים + מעקב מימוש יומי
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS activities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                points INTEGER DEFAULT 0,
                print_code TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS activity_schedules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                activity_id INTEGER NOT NULL,
                start_time TEXT,
                end_time TEXT,
                days_of_week TEXT,
                start_date TEXT,
                end_date TEXT,
                is_general INTEGER DEFAULT 1,
                classes TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (activity_id) REFERENCES activities(id)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS activity_claims (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                activity_id INTEGER NOT NULL,
                student_id INTEGER NOT NULL,
                claim_date TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (activity_id) REFERENCES activities(id),
                FOREIGN KEY (student_id) REFERENCES students(id)
            )
        ''')

        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_activity_schedules_activity ON activity_schedules(activity_id, is_active)')
        except Exception:
            pass
        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_activity_claims_student_day ON activity_claims(student_id, claim_date)')
        except Exception:
            pass
        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_activity_claims_activity_day ON activity_claims(activity_id, claim_date)')
        except Exception:
            pass

        # ================================
        # אתגרים מתוזמנים לקופה (שירותים עם הזמנה לסלוט)
        # ================================
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS scheduled_services (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL UNIQUE,
                duration_minutes INTEGER NOT NULL DEFAULT 10,
                capacity_per_slot INTEGER NOT NULL DEFAULT 1,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                allow_auto_time INTEGER DEFAULT 1,
                max_per_student INTEGER,
                max_per_class INTEGER,
                queue_priority_mode TEXT DEFAULT 'class_asc',
                queue_priority_custom TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
            )
        ''')

        try:
            cursor.execute("ALTER TABLE scheduled_services ADD COLUMN queue_priority_mode TEXT DEFAULT 'class_asc'")
        except Exception:
            pass
        try:
            cursor.execute('ALTER TABLE scheduled_services ADD COLUMN queue_priority_custom TEXT')
        except Exception:
            pass
        try:
            cursor.execute('ALTER TABLE scheduled_services ADD COLUMN allowed_classes TEXT')
        except Exception:
            pass
        try:
            cursor.execute('ALTER TABLE scheduled_services ADD COLUMN min_points_required INTEGER DEFAULT 0')
        except Exception:
            pass

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS scheduled_service_dates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service_id INTEGER NOT NULL,
                service_date TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (service_id) REFERENCES scheduled_services(id) ON DELETE CASCADE,
                UNIQUE(service_id, service_date)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS scheduled_service_reservations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service_id INTEGER NOT NULL,
                student_id INTEGER NOT NULL,
                purchase_id INTEGER,
                service_date TEXT NOT NULL,
                slot_start_time TEXT NOT NULL,
                duration_minutes INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (service_id) REFERENCES scheduled_services(id) ON DELETE CASCADE,
                FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
                FOREIGN KEY (purchase_id) REFERENCES purchases_log(id) ON DELETE SET NULL,
                UNIQUE(service_id, student_id, service_date, slot_start_time)
            )
        ''')

        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_sched_dates_service ON scheduled_service_dates(service_id, is_active, service_date)')
        except Exception:
            pass
        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_sched_res_service_slot ON scheduled_service_reservations(service_id, service_date, slot_start_time)')
        except Exception:
            pass
        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_sched_res_student ON scheduled_service_reservations(student_id, created_at)')
        except Exception:
            pass
        
        # טבלת מעקב בונוס זמנים שניתנו (למניעת כפילויות)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS time_bonus_given (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                bonus_schedule_id INTEGER NOT NULL,
                given_date DATE NOT NULL,
                given_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (student_id) REFERENCES students(id),
                FOREIGN KEY (bonus_schedule_id) REFERENCES time_bonus_schedules(id),
                UNIQUE(student_id, bonus_schedule_id, given_date)
            )
        ''')
        
        # טבלת מורים (הרשאות גישה)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS teachers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                card_number TEXT UNIQUE,
                card_number2 TEXT,
                card_number3 TEXT,
                is_admin INTEGER DEFAULT 0,
                can_edit_student_card INTEGER DEFAULT 1,
                can_edit_student_photo INTEGER DEFAULT 1,
                bonus_max_points_per_student INTEGER,
                bonus_max_total_runs INTEGER,
                bonus_runs_used INTEGER DEFAULT 0,
                bonus_runs_reset_date DATE,
                bonus_points_used INTEGER DEFAULT 0,
                bonus_points_reset_date DATE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        try:
            cursor.execute('ALTER TABLE teachers ADD COLUMN bonus_max_points_per_student INTEGER')
        except:
            pass

        try:
            cursor.execute('ALTER TABLE teachers ADD COLUMN card_number2 TEXT')
        except:
            pass

        try:
            cursor.execute('ALTER TABLE teachers ADD COLUMN card_number3 TEXT')
        except:
            pass

        try:
            cursor.execute('ALTER TABLE teachers ADD COLUMN can_edit_student_card INTEGER DEFAULT 1')
        except:
            pass

        try:
            cursor.execute('ALTER TABLE teachers ADD COLUMN can_edit_student_photo INTEGER DEFAULT 1')
        except:
            pass

        try:
            cursor.execute('ALTER TABLE teachers ADD COLUMN bonus_max_total_runs INTEGER')
        except:
            pass

        try:
            cursor.execute('ALTER TABLE teachers ADD COLUMN bonus_runs_used INTEGER DEFAULT 0')
        except:
            pass

        try:
            cursor.execute('ALTER TABLE teachers ADD COLUMN bonus_runs_reset_date DATE')
        except:
            pass

        try:
            cursor.execute('ALTER TABLE teachers ADD COLUMN bonus_points_used INTEGER DEFAULT 0')
        except:
            pass

        try:
            cursor.execute('ALTER TABLE teachers ADD COLUMN bonus_points_reset_date DATE')
        except:
            pass
        
        # טבלת שיוך מורים לכיתות (many-to-many)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS teacher_classes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                teacher_id INTEGER NOT NULL,
                class_name TEXT NOT NULL,
                FOREIGN KEY (teacher_id) REFERENCES teachers(id) ON DELETE CASCADE,
                UNIQUE(teacher_id, class_name)
            )
        ''')

        # טבלת הגדרות בונוס למורים (כמה נקודות בונוס לכל תלמיד בסבב)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS teacher_bonus (
                teacher_id INTEGER PRIMARY KEY,
                bonus_points INTEGER NOT NULL DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (teacher_id) REFERENCES teachers(id) ON DELETE CASCADE
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS swipe_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER,
                card_number TEXT,
                station_type TEXT,
                swiped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (student_id) REFERENCES students(id)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS student_tier_state (
                student_id INTEGER PRIMARY KEY,
                last_tier_index INTEGER,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE
            )
        ''')
        
        conn.commit()
        conn.close()

    def get_max_points_config(self) -> Dict[str, Any]:
        import json
        from datetime import date

        default_cfg: Dict[str, Any] = {
            'start_date': date.today().isoformat(),
            'daily_points': 0,
            'daily_points_by_weekday': None,
            'daily_special_rules': [],
            'weekly_points': 0,
            'free_additions': [],
            'policy': 'none',
            'warn_within_points': 0,
        }
        try:
            raw = self.get_setting('max_points_config', None)
        except Exception:
            raw = None
        if not raw:
            return default_cfg
        try:
            cfg = json.loads(str(raw))
            if not isinstance(cfg, dict):
                return default_cfg
        except Exception:
            return default_cfg
        out = dict(default_cfg)
        out.update(cfg)
        # normalize
        try:
            out['daily_points'] = int(out.get('daily_points', 0) or 0)
        except Exception:
            out['daily_points'] = 0
        dpw = out.get('daily_points_by_weekday', None)
        if isinstance(dpw, dict):
            norm_dpw = {}
            for k, v in dpw.items():
                try:
                    kk = int(k)
                except Exception:
                    continue
                if kk < 0 or kk > 6:
                    continue
                try:
                    vv = int(v or 0)
                except Exception:
                    vv = 0
                norm_dpw[str(kk)] = int(vv)
            out['daily_points_by_weekday'] = norm_dpw
        else:
            out['daily_points_by_weekday'] = None

        ds = out.get('daily_special_rules')
        if not isinstance(ds, list):
            ds = []
        norm_ds = []
        for it in ds:
            if not isinstance(it, dict):
                continue
            start_s = str(it.get('start') or '').strip()
            end_s = str(it.get('end') or '').strip()
            if not start_s or not end_s:
                continue
            try:
                pts = int(it.get('daily_points', 0) or 0)
            except Exception:
                pts = 0
            try:
                note = str(it.get('note') or '').strip()
            except Exception:
                note = ''
            norm_ds.append({'start': start_s, 'end': end_s, 'daily_points': int(pts), 'note': note})
        out['daily_special_rules'] = norm_ds
        try:
            out['weekly_points'] = int(out.get('weekly_points', 0) or 0)
        except Exception:
            out['weekly_points'] = 0
        try:
            out['warn_within_points'] = int(out.get('warn_within_points', 0) or 0)
        except Exception:
            out['warn_within_points'] = 0
        try:
            pol = str(out.get('policy') or 'none').strip().lower()
            if pol not in ('none', 'warn', 'block'):
                pol = 'none'
            out['policy'] = pol
        except Exception:
            out['policy'] = 'none'
        fa = out.get('free_additions')
        if not isinstance(fa, list):
            fa = []
        norm = []
        for it in fa:
            if not isinstance(it, dict):
                continue
            d = str(it.get('date') or '').strip()
            if not d:
                continue
            try:
                pts = int(it.get('points', 0) or 0)
            except Exception:
                pts = 0
            try:
                note = str(it.get('note') or '').strip()
            except Exception:
                note = ''
            norm.append({'date': d, 'points': pts, 'note': note})
        out['free_additions'] = norm
        return out

    def set_max_points_config(self, cfg: Dict[str, Any]) -> bool:
        import json
        try:
            self.set_setting('max_points_config', json.dumps(cfg, ensure_ascii=False))
            return True
        except Exception:
            return False

    def compute_max_points_allowed_from_cfg(self, cfg: Dict[str, Any], *, for_date: str = None) -> int:
        from datetime import date, datetime, timedelta

        if not for_date:
            for_date = date.today().isoformat()
        try:
            cur = datetime.strptime(str(for_date), '%Y-%m-%d').date()
        except Exception:
            cur = date.today()
        try:
            start = datetime.strptime(str(cfg.get('start_date') or ''), '%Y-%m-%d').date()
        except Exception:
            start = cur
        if cur < start:
            return 0

        try:
            daily_default = int(cfg.get('daily_points', 0) or 0)
        except Exception:
            daily_default = 0
        try:
            weekly = int(cfg.get('weekly_points', 0) or 0)
        except Exception:
            weekly = 0

        dpw = cfg.get('daily_points_by_weekday')
        if not isinstance(dpw, dict):
            dpw = None
        ds_rules = cfg.get('daily_special_rules')
        if not isinstance(ds_rules, list):
            ds_rules = []

        def _daily_for(d: date) -> int:
            # precedence: date rules -> weekday rules -> default
            try:
                for r in list(ds_rules or []):
                    if not isinstance(r, dict):
                        continue
                    ss = str(r.get('start') or '').strip()
                    ee = str(r.get('end') or '').strip()
                    if not ss or not ee:
                        continue
                    try:
                        sd = datetime.strptime(ss, '%Y-%m-%d').date()
                        ed = datetime.strptime(ee, '%Y-%m-%d').date()
                    except Exception:
                        continue
                    if sd <= d <= ed:
                        try:
                            return int(r.get('daily_points', daily_default) or 0)
                        except Exception:
                            return int(daily_default)
            except Exception:
                pass
            if dpw:
                try:
                    wd = int(d.weekday())
                except Exception:
                    wd = 0
                try:
                    return int(dpw.get(str(wd), daily_default) or 0)
                except Exception:
                    return int(daily_default)
            return int(daily_default)

        days_elapsed = (cur - start).days
        days_count = int(days_elapsed) + 1

        # שבוע קלנדרי שמתחיל ביום ראשון
        def _week_start_sunday(d: date) -> date:
            # Python weekday(): Monday=0 .. Sunday=6
            delta = int((int(d.weekday()) + 1) % 7)
            return d - timedelta(days=delta)

        try:
            ws_start = _week_start_sunday(start)
            ws_cur = _week_start_sunday(cur)
            weeks_count = int(((ws_cur - ws_start).days // 7) + 1)
        except Exception:
            weeks_count = 1

        total_daily = 0
        try:
            for i in range(max(0, int(days_count))):
                total_daily += int(_daily_for(start + timedelta(days=int(i))))
        except Exception:
            total_daily = 0

        total = int(total_daily) + (int(weekly) * max(0, int(weeks_count)))

        extra_sum = 0
        for it in (cfg.get('free_additions') or []):
            if not isinstance(it, dict):
                continue
            d = str(it.get('date') or '').strip()
            if not d:
                continue
            try:
                ddt = datetime.strptime(d, '%Y-%m-%d').date()
            except Exception:
                continue
            if ddt <= cur:
                try:
                    extra_sum += int(it.get('points', 0) or 0)
                except Exception:
                    pass
        total += int(extra_sum)
        if total < 0:
            total = 0
        return int(total)

    def compute_max_points_allowed(self, *, for_date: str = None) -> int:
        cfg = self.get_max_points_config()
        return int(self.compute_max_points_allowed_from_cfg(cfg, for_date=for_date))

    def evaluate_points_against_max(self, *, proposed_points: int, for_date: str = None) -> Dict[str, Any]:
        cfg = self.get_max_points_config()
        max_allowed = self.compute_max_points_allowed(for_date=for_date)
        try:
            proposed = int(proposed_points)
        except Exception:
            proposed = 0
        try:
            warn_within = int(cfg.get('warn_within_points', 0) or 0)
        except Exception:
            warn_within = 0
        status = 'ok'
        if proposed > max_allowed:
            status = 'exceed'
        elif warn_within > 0 and proposed >= max(0, max_allowed - warn_within):
            status = 'near'
        return {
            'status': status,
            'max_allowed': int(max_allowed),
            'proposed_points': int(proposed),
            'policy': str(cfg.get('policy') or 'none'),
            'warn_within_points': int(warn_within),
        }
    
    def add_student(self, last_name: str, first_name: str, id_number: str = "",
                   class_name: str = "", photo_number: str = "", 
                   card_number: str = "", points: int = 0,
                   serial_number: Optional[int] = None) -> int:
        """הוספת תלמיד חדש"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO students (serial_number, last_name, first_name, id_number, class_name, 
                                 photo_number, card_number, points)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (serial_number, last_name, first_name, id_number, class_name, photo_number, 
              card_number, points))
        
        student_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return student_id
    
    def update_student_basic(self, student_id: int, last_name: str, first_name: str,
                             id_number: str = "", class_name: str = "",
                             card_number: str = "", photo_number: str = "",
                             serial_number: Optional[int] = None) -> bool:
        """עדכון פרטי תלמיד בסיסיים (שם, ת"ז, כיתה, כרטיס, תמונה, מס' סידורי)."""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute('''
                UPDATE students
                SET last_name = ?,
                    first_name = ?,
                    id_number = ?,
                    class_name = ?,
                    card_number = ?,
                    photo_number = ?,
                    serial_number = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (last_name, first_name, id_number or None, class_name or None,
                  card_number or None, photo_number or None, serial_number, student_id))

            conn.commit()
            conn.close()
            return True
        except Exception as e:
            conn.close()
            print(f"שגיאה בעדכון פרטי תלמיד: {e}")
            return False
    def get_student_by_card(self, card_number: str) -> Optional[Dict[str, Any]]:
        """שליפת פרטי תלמיד לפי מספר כרטיס"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM students WHERE card_number = ?
        ''', (card_number,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return dict(row)
        return None

    # ========================================
    # קניות / קופה
    # ========================================

    def get_scheduled_service_by_product(self, product_id: int) -> Optional[Dict[str, Any]]:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT * FROM scheduled_services WHERE product_id = ?', (int(product_id or 0),))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_all_scheduled_services(self, *, active_only: bool = False) -> List[Dict[str, Any]]:
        """מחזיר את כל האתגרים (scheduled_services) כולל פרטי מוצר קשור."""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            where = ""
            if bool(active_only):
                where = "WHERE ss.is_active = 1"
            cursor.execute(
                f'''
                SELECT ss.*, 
                       p.name AS product_name,
                       p.display_name AS product_display_name,
                       p.price_points AS product_price_points,
                       p.is_active AS product_is_active
                  FROM scheduled_services ss
                  LEFT JOIN products p ON p.id = ss.product_id
                  {where}
                 ORDER BY ss.is_active DESC, ss.id DESC
                '''
            )
            rows = cursor.fetchall() or []
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_purchases_log_export(self, *, limit: int = 5000) -> List[Dict[str, Any]]:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            try:
                limit = int(limit or 0)
            except Exception:
                limit = 5000
            if limit <= 0:
                limit = 5000

            cursor.execute(
                '''
                SELECT pl.id AS purchase_id,
                       pl.created_at,
                       pl.station_type,
                       pl.student_id,
                       s.serial_number,
                       s.class_name,
                       s.first_name,
                       s.last_name,
                       pl.product_id,
                       p.name AS product_name,
                       p.display_name AS product_display_name,
                       pl.variant_id,
                       v.variant_name AS variant_name,
                       v.display_name AS variant_display_name,
                       pl.qty,
                       pl.points_each,
                       pl.total_points,
                       pl.deduct_points,
                       COALESCE(pl.is_refunded, 0) AS is_refunded,
                       pl.refunded_at
                  FROM purchases_log pl
                  LEFT JOIN students s ON s.id = pl.student_id
                  LEFT JOIN products p ON p.id = pl.product_id
                  LEFT JOIN product_variants v ON v.id = pl.variant_id
                 ORDER BY pl.created_at DESC
                 LIMIT ?
                ''',
                (int(limit),)
            )
            rows = cursor.fetchall() or []
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_purchases_summary_by_category(self, *, from_date: str = '', to_date: str = '', include_refunded: bool = False) -> List[Dict[str, Any]]:
        """Summary of purchases grouped by product category.

        Dates are optional and expected as 'YYYY-MM-DD'. When provided, range is inclusive.
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            where = []
            params = []
            if not include_refunded:
                where.append('COALESCE(pl.is_refunded, 0) = 0')
            if str(from_date or '').strip():
                where.append('DATE(pl.created_at) >= DATE(?)')
                params.append(str(from_date).strip())
            if str(to_date or '').strip():
                where.append('DATE(pl.created_at) <= DATE(?)')
                params.append(str(to_date).strip())
            wh = ''
            if where:
                wh = 'WHERE ' + ' AND '.join(where)

            cursor.execute(
                f'''
                SELECT COALESCE(c.name, 'ללא קטגוריה') AS category_name,
                       COUNT(*) AS rows_count,
                       COALESCE(SUM(pl.qty), 0) AS total_qty,
                       COALESCE(SUM(pl.total_points), 0) AS total_points
                  FROM purchases_log pl
                  LEFT JOIN products p ON p.id = pl.product_id
                  LEFT JOIN product_categories c ON c.id = p.category_id
                  {wh}
                 GROUP BY COALESCE(c.name, 'ללא קטגוריה')
                 ORDER BY total_points DESC, category_name
                ''',
                tuple(params)
            )
            rows = cursor.fetchall() or []
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_purchases_by_product(self, product_id: int) -> List[Dict[str, Any]]:
        """Get all purchases for a specific product with student details."""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                '''
                SELECT pl.id AS purchase_id,
                       pl.created_at,
                       pl.student_id,
                       s.serial_number,
                       s.class_name,
                       s.first_name,
                       s.last_name,
                       pl.product_id,
                       pl.variant_id,
                       pl.qty,
                       pl.points_each,
                       pl.total_points,
                       COALESCE(pl.is_refunded, 0) AS is_refunded
                  FROM purchases_log pl
                  LEFT JOIN students s ON s.id = pl.student_id
                 WHERE pl.product_id = ?
                 ORDER BY pl.created_at DESC
                ''',
                (int(product_id),)
            )
            rows = cursor.fetchall() or []
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def save_receipt_snapshot(self, *, station_type: str, student_id: int, purchase_ids: List[int], items: List[Dict[str, Any]], scheduled_reservations: List[Dict[str, Any]]) -> int:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            conn.execute('BEGIN IMMEDIATE')

            pid_list = []
            for x in (purchase_ids or []):
                try:
                    v = int(x or 0)
                except Exception:
                    v = 0
                if v > 0:
                    pid_list.append(v)
            pid_list = list(dict.fromkeys(pid_list))
            if not pid_list:
                conn.rollback()
                return 0

            payload = {
                'station_type': str(station_type or '').strip(),
                'student_id': int(student_id or 0),
                'items': items or [],
                'scheduled_reservations': scheduled_reservations or [],
                'purchase_ids': pid_list,
            }
            try:
                js = json.dumps(payload, ensure_ascii=False)
            except Exception:
                js = ''

            cursor.execute(
                'INSERT INTO receipt_snapshots (station_type, student_id, data_json) VALUES (?, ?, ?)',
                (str(station_type or '').strip(), int(student_id or 0), str(js or ''))
            )
            snap_id = int(cursor.lastrowid or 0)
            if not snap_id:
                conn.rollback()
                return 0

            for pid in pid_list:
                cursor.execute(
                    'INSERT OR REPLACE INTO receipt_snapshot_purchases (purchase_id, snapshot_id) VALUES (?, ?)',
                    (int(pid), int(snap_id))
                )

            conn.commit()
            return int(snap_id)
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            return 0
        finally:
            conn.close()

    def get_receipt_snapshot_by_purchase(self, purchase_id: int) -> Optional[Dict[str, Any]]:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                '''
                SELECT rs.*
                  FROM receipt_snapshot_purchases rsp
                  JOIN receipt_snapshots rs ON rs.id = rsp.snapshot_id
                 WHERE rsp.purchase_id = ?
                ''',
                (int(purchase_id or 0),)
            )
            row = cursor.fetchone()
            if not row:
                return None
            out = dict(row)
            try:
                data = json.loads(str(out.get('data_json') or '') or '{}')
            except Exception:
                data = {}
            out['data'] = data
            return out
        finally:
            conn.close()

    def get_scheduled_queue_export(self, *, service_id: int, service_date: str) -> List[Dict[str, Any]]:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            try:
                service_id = int(service_id or 0)
            except Exception:
                service_id = 0
            sd = str(service_date or '').strip()
            if not service_id or not sd:
                return []

            cursor.execute(
                '''
                SELECT r.id AS reservation_id,
                       r.service_id,
                       r.service_date,
                       r.slot_start_time,
                       r.duration_minutes,
                       r.created_at,
                       s.id AS student_id,
                       s.serial_number,
                       s.class_name,
                       s.first_name,
                       s.last_name,
                       ss.product_id,
                       COALESCE(ss.queue_priority_mode, 'class_asc') AS queue_priority_mode,
                       COALESCE(ss.queue_priority_custom, '') AS queue_priority_custom,
                       p.name AS product_name,
                       p.display_name AS product_display_name
                  FROM scheduled_service_reservations r
                  JOIN students s ON s.id = r.student_id
                  JOIN scheduled_services ss ON ss.id = r.service_id
                  LEFT JOIN products p ON p.id = ss.product_id
                 WHERE r.service_id = ? AND r.service_date = ?
                 ORDER BY r.slot_start_time, r.created_at
                ''',
                (int(service_id), sd)
            )
            rows = [dict(r) for r in (cursor.fetchall() or [])]
            if not rows:
                return []

            mode = str((rows[0].get('queue_priority_mode') or 'class_asc')).strip().lower()
            custom_raw = str(rows[0].get('queue_priority_custom') or '').strip()
            custom_list = [c.strip() for c in custom_raw.split(',') if c.strip()] if custom_raw else []
            custom_rank = {c: i for i, c in enumerate(custom_list)}

            def _class_num(cn: str) -> int:
                cn = str(cn or '').strip()
                if not cn:
                    return 0
                m = re.search(r'(\d+)', cn)
                if not m:
                    return 0
                try:
                    return int(m.group(1))
                except Exception:
                    return 0

            def _class_key(row: Dict[str, Any]):
                cn = str(row.get('class_name') or '').strip()
                if mode in ('none', 'no', 'off', 'disabled'):
                    return (0, '', '')
                if mode in ('custom', 'custom_list', 'custom_order'):
                    return (int(custom_rank.get(cn, 10 ** 9)), _class_num(cn), cn)
                # default: use numeric if possible then string
                return (_class_num(cn), cn)

            reverse_class = mode in ('class_desc', 'desc', 'high_to_low', 'big_to_small')
            if mode in ('none', 'no', 'off', 'disabled'):
                # No class priority: stable by slot then created_at then name
                rows.sort(
                    key=lambda r: (
                        str(r.get('slot_start_time') or '').strip(),
                        str(r.get('created_at') or '').strip(),
                        str(r.get('last_name') or '').strip(),
                        str(r.get('first_name') or '').strip(),
                    ),
                    reverse=False,
                )
            else:
                # stable within slot: by class priority then name
                rows.sort(
                    key=lambda r: (
                        str(r.get('slot_start_time') or '').strip(),
                        _class_key(r),
                        str(r.get('last_name') or '').strip(),
                        str(r.get('first_name') or '').strip(),
                    ),
                    reverse=False,
                )
            if reverse_class:
                # re-sort per slot with reversed class ordering
                by_slot: Dict[str, List[Dict[str, Any]]] = {}
                for r in rows:
                    by_slot.setdefault(str(r.get('slot_start_time') or '').strip(), []).append(r)
                out: List[Dict[str, Any]] = []
                for slot in sorted(by_slot.keys()):
                    chunk = by_slot[slot]
                    chunk.sort(
                        key=lambda r: (
                            _class_key(r),
                            str(r.get('last_name') or '').strip(),
                            str(r.get('first_name') or '').strip(),
                        ),
                        reverse=True,
                    )
                    out.extend(chunk)
                rows = out

            return rows
        finally:
            conn.close()

    def _reserve_scheduled_service_slot_in_tx(self, cursor, *, service_id: int, student_id: int,
                                             service_date: str, slot_start_time: str,
                                             purchase_id: Optional[int] = None) -> Dict[str, Any]:
        cursor.execute('SELECT * FROM scheduled_services WHERE id = ? AND is_active = 1', (int(service_id or 0),))
        srow = cursor.fetchone()
        if not srow:
            return {'ok': False, 'error': 'האתגר לא פעיל'}
        s = dict(srow)

        sd = str(service_date or '').strip()
        cursor.execute(
            'SELECT COUNT(1) AS c FROM scheduled_service_dates WHERE service_id = ? AND is_active = 1 AND service_date = ?',
            (int(service_id or 0), sd)
        )
        ok = cursor.fetchone()
        if int((ok['c'] if ok else 0) or 0) <= 0:
            return {'ok': False, 'error': 'התאריך לא זמין'}

        lim = self._scheduled_service_limits_ok(cursor, service_id=int(service_id or 0), student_id=int(student_id or 0))
        if not lim.get('ok'):
            return lim

        dur = int(s.get('duration_minutes', 10) or 10)
        cap = int(s.get('capacity_per_slot', 1) or 1)
        t = str(slot_start_time or '').strip()
        if not re.match(r'^\d{2}:\d{2}$', t):
            return {'ok': False, 'error': 'שעה לא תקינה'}

        # Prevent student from reserving overlapping challenges on the same date
        try:
            def _to_min(hhmm: str) -> int:
                hhmm = str(hhmm or '').strip()
                if ':' not in hhmm:
                    return -1
                hh, mm = hhmm.split(':', 1)
                return int(hh) * 60 + int(mm)

            start_min = _to_min(t)
            end_min = start_min + int(dur)

            cursor.execute(
                '''
                SELECT r.service_id, r.slot_start_time, r.duration_minutes
                  FROM scheduled_service_reservations r
                 WHERE r.student_id = ? AND r.service_date = ?
                ''',
                (int(student_id or 0), sd)
            )
            existing = cursor.fetchall() or []
            for r in existing:
                try:
                    other_start = _to_min(r['slot_start_time'])
                except Exception:
                    other_start = -1
                try:
                    other_dur = int(r['duration_minutes'] or 0)
                except Exception:
                    other_dur = 0
                if other_start < 0 or other_dur <= 0:
                    continue
                other_end = other_start + other_dur
                if start_min < other_end and other_start < end_min:
                    return {'ok': False, 'error': 'לתלמיד כבר יש אתגר בזמן הזה'}
        except Exception:
            # If overlap check fails unexpectedly, do not block reservation
            pass

        cursor.execute(
            'SELECT COUNT(1) AS used FROM scheduled_service_reservations WHERE service_id = ? AND service_date = ? AND slot_start_time = ?',
            (int(service_id or 0), sd, t)
        )
        used_row = cursor.fetchone()
        used = int((used_row['used'] if used_row else 0) or 0)
        if used >= cap:
            return {'ok': False, 'error': 'הסלוט מלא'}

        try:
            cursor.execute(
                '''
                INSERT INTO scheduled_service_reservations
                    (service_id, student_id, purchase_id, service_date, slot_start_time, duration_minutes)
                VALUES (?, ?, ?, ?, ?, ?)
                ''',
                (
                    int(service_id or 0),
                    int(student_id or 0),
                    (int(purchase_id) if purchase_id is not None else None),
                    sd,
                    t,
                    int(dur),
                )
            )
            rid = int(cursor.lastrowid or 0)
            return {'ok': True, 'reservation_id': int(rid)}
        except Exception:
            return {'ok': False, 'error': 'הסלוט כבר נתפס'}

    def cashier_purchase_batch_with_scheduled(self, *, student_id: int, items: List[Dict[str, Any]],
                                             scheduled_reservations: List[Dict[str, Any]],
                                             station_type: str = 'cashier',
                                             actor_name: str = 'cashier') -> Dict[str, Any]:
        """רכישה אטומית של עגלה + שריון אתגרים מתוזמנים.

        items: [{'product_id','variant_id','qty'}]
        scheduled_reservations: [{'service_id','service_date','slot_start_time','purchase_item_index'}]
        """
        # First run the same purchase logic, but we need it inline to keep the same transaction.
        cleaned = []
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
                q = int(it.get('qty') or 0)
            except Exception:
                q = 0
            if (pid or vid) and q > 0:
                cleaned.append({'product_id': pid, 'variant_id': vid, 'qty': q})

        if not cleaned:
            return {'ok': False, 'error': 'אין פריטים לתשלום'}

        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            conn.execute('BEGIN IMMEDIATE')

            cursor.execute('SELECT * FROM students WHERE id = ?', (int(student_id or 0),))
            stu_row = cursor.fetchone()
            if not stu_row:
                conn.rollback()
                return {'ok': False, 'error': 'תלמיד לא נמצא'}
            stu = dict(stu_row)
            old_points = int(stu.get('points', 0) or 0)
            stu_class = str(stu.get('class_name') or '').strip()

            stock_updates = []
            purchases = []
            total_deduct_points = 0
            total_display_points = 0

            for it in cleaned:
                pid = int(it.get('product_id') or 0)
                vid = int(it.get('variant_id') or 0)
                qty = int(it['qty'])

                v = {}
                if vid:
                    cursor.execute('SELECT * FROM product_variants WHERE id = ?', (vid,))
                    vrow = cursor.fetchone()
                    if not vrow:
                        conn.rollback()
                        return {'ok': False, 'error': 'וריאציה לא נמצאה'}
                    v = dict(vrow)
                    if int(v.get('is_active', 1) or 0) != 1:
                        conn.rollback()
                        return {'ok': False, 'error': 'הווריאציה לא פעילה'}
                    try:
                        pid = int(v.get('product_id') or 0)
                    except Exception:
                        pid = 0

                if not pid:
                    conn.rollback()
                    return {'ok': False, 'error': 'מוצר לא נמצא'}

                cursor.execute('SELECT * FROM products WHERE id = ?', (pid,))
                prow = cursor.fetchone()
                if not prow:
                    conn.rollback()
                    return {'ok': False, 'error': 'מוצר לא נמצא'}
                p = dict(prow)
                if int(p.get('is_active', 1) or 0) != 1:
                    conn.rollback()
                    return {'ok': False, 'error': 'המוצר לא פעיל'}

                # Availability rules
                allowed = str(p.get('allowed_classes') or '').strip()
                if allowed and stu_class:
                    allowed_list = [x.strip() for x in allowed.split(',') if x.strip()]
                    if allowed_list and (stu_class not in allowed_list):
                        conn.rollback()
                        return {'ok': False, 'error': 'המוצר לא זמין לכיתה זו'}
                try:
                    minp = int(p.get('min_points_required', 0) or 0)
                except Exception:
                    minp = 0
                if minp > 0 and int(old_points) < int(minp):
                    conn.rollback()
                    return {'ok': False, 'error': 'אין מספיק נקודות למוצר זה'}

                # Per-student / per-class limits (excluding refunded)
                try:
                    mps = p.get('max_per_student', None)
                    mps = (int(mps) if mps is not None and str(mps).strip() != '' else None)
                except Exception:
                    mps = None
                try:
                    mpc = p.get('max_per_class', None)
                    mpc = (int(mpc) if mpc is not None and str(mpc).strip() != '' else None)
                except Exception:
                    mpc = None

                if mps is not None and int(mps) >= 0:
                    try:
                        cursor.execute(
                            'SELECT COALESCE(SUM(qty),0) AS q FROM purchases_log WHERE student_id = ? AND product_id = ? AND is_refunded = 0',
                            (int(student_id or 0), int(pid))
                        )
                        row = cursor.fetchone()
                        already = int((row['q'] if row else 0) or 0)
                    except Exception:
                        already = 0
                    if int(already) + int(qty) > int(mps):
                        conn.rollback()
                        return {'ok': False, 'error': 'חריגה ממקסימום לתלמיד למוצר זה'}

                if mpc is not None and int(mpc) >= 0 and stu_class:
                    try:
                        cursor.execute(
                            '''
                            SELECT COALESCE(SUM(pl.qty),0) AS q
                              FROM purchases_log pl
                              JOIN students s ON s.id = pl.student_id
                             WHERE pl.product_id = ?
                               AND pl.is_refunded = 0
                               AND s.class_name = ?
                            ''',
                            (int(pid), str(stu_class))
                        )
                        row = cursor.fetchone()
                        already = int((row['q'] if row else 0) or 0)
                    except Exception:
                        already = 0
                    if int(already) + int(qty) > int(mpc):
                        conn.rollback()
                        return {'ok': False, 'error': 'חריגה ממקסימום לכיתה למוצר זה'}

                if vid:
                    price_each = int(v.get('price_points', 0) or 0)
                    deduct = 1 if int(v.get('deduct_points', 1) or 0) == 1 else 0
                    stock_qty = v.get('stock_qty', None)
                else:
                    price_each = int(p.get('price_points', 0) or 0)
                    deduct = 1 if int(p.get('deduct_points', 1) or 0) == 1 else 0
                    stock_qty = p.get('stock_qty', None)

                # Conditional price override by points balance
                try:
                    po_min = p.get('price_override_min_points', None)
                    po_price = p.get('price_override_points', None)
                    po_pct = p.get('price_override_discount_pct', None)
                    if po_min is not None and int(old_points) >= int(po_min):
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
                                price_each = int(round(int(price_each) * (100 - pct) / 100))
                            except Exception:
                                pass
                        elif po_price is not None:
                            price_each = int(po_price)
                        if int(price_each) < 0:
                            price_each = 0
                except Exception:
                    pass

                total_item = price_each * qty

                if stock_qty is not None:
                    try:
                        stock_qty = int(stock_qty)
                    except Exception:
                        stock_qty = None
                if stock_qty is not None and stock_qty < qty:
                    conn.rollback()
                    return {'ok': False, 'error': 'אין מספיק מלאי'}

                if stock_qty is not None:
                    stock_updates.append((pid, vid, int(stock_qty - qty)))

                if deduct == 1:
                    total_deduct_points += int(total_item)
                total_display_points += int(total_item)

                purchases.append({
                    'product_id': pid,
                    'variant_id': int(vid or 0),
                    'qty': int(qty),
                    'points_each': int(price_each),
                    'total_points': int(total_item),
                    'deduct_points': int(deduct),
                    'purchase_id': 0,
                })

            if old_points < total_deduct_points:
                conn.rollback()
                return {'ok': False, 'error': 'אין מספיק נקודות'}

            new_points = int(old_points - total_deduct_points)

            for pid, vid, new_stock in stock_updates:
                if int(vid or 0) > 0:
                    cursor.execute('UPDATE product_variants SET stock_qty = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?', (int(new_stock), int(vid)))
                else:
                    cursor.execute('UPDATE products SET stock_qty = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?', (int(new_stock), int(pid)))

            if new_points != old_points:
                cursor.execute('UPDATE students SET points = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?', (int(new_points), int(student_id or 0)))
                try:
                    cursor.execute(
                        '''
                        INSERT INTO points_log (student_id, old_points, new_points, delta, reason, actor_name, action_type)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        ''',
                        (
                            int(student_id or 0),
                            int(old_points),
                            int(new_points),
                            int(new_points - old_points),
                            'קניה בקופה',
                            str(actor_name or 'cashier'),
                            'purchase'
                        )
                    )
                except Exception:
                    pass
                try:
                    self._log_change(
                        cursor,
                        entity_type='student_points',
                        entity_id=str(student_id or ''),
                        action_type='update',
                        payload={'old_points': int(old_points), 'new_points': int(new_points), 'reason': 'קניה בקופה'}
                    )
                except Exception:
                    pass

            # purchases_log with ids
            for it in purchases:
                cursor.execute(
                    '''
                    INSERT INTO purchases_log (student_id, product_id, variant_id, qty, points_each, total_points, deduct_points, station_type)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    (
                        int(student_id or 0),
                        int(it['product_id']),
                        (int(it.get('variant_id') or 0) if int(it.get('variant_id') or 0) > 0 else None),
                        int(it['qty']),
                        int(it['points_each']),
                        int(it['total_points']),
                        int(it['deduct_points']),
                        str(station_type or 'cashier')
                    )
                )
                it['purchase_id'] = int(cursor.lastrowid or 0)
                try:
                    self._log_change(
                        cursor,
                        entity_type='purchase',
                        entity_id=str(it['purchase_id'] or ''),
                        action_type='insert',
                        payload={
                            'student_id': int(student_id or 0),
                            'product_id': int(it['product_id']),
                            'variant_id': int(it.get('variant_id') or 0),
                            'qty': int(it['qty']),
                            'total_points': int(it['total_points']),
                            'deduct_points': int(it['deduct_points']),
                            'station_type': str(station_type or 'cashier')
                        }
                    )
                except Exception:
                    pass

            # Reserve scheduled slots (must succeed or rollback)
            for sr in (scheduled_reservations or []):
                try:
                    idx = int(sr.get('purchase_item_index') or 0)
                except Exception:
                    idx = 0
                if idx < 0 or idx >= len(purchases):
                    conn.rollback()
                    return {'ok': False, 'error': 'שגיאת התאמת פריט אתגר לרכישה'}
                purchase_id = int(purchases[idx].get('purchase_id') or 0)
                rr = self._reserve_scheduled_service_slot_in_tx(
                    cursor,
                    service_id=int(sr.get('service_id') or 0),
                    student_id=int(student_id or 0),
                    service_date=str(sr.get('service_date') or '').strip(),
                    slot_start_time=str(sr.get('slot_start_time') or '').strip(),
                    purchase_id=int(purchase_id or 0) if purchase_id else None,
                )
                if not rr.get('ok'):
                    conn.rollback()
                    return {'ok': False, 'error': str(rr.get('error') or 'שגיאה בשריון אתגר')}

            conn.commit()
            return {
                'ok': True,
                'student_id': int(student_id or 0),
                'old_points': int(old_points),
                'new_points': int(new_points),
                'total_points': int(total_display_points),
                'total_deduct_points': int(total_deduct_points),
                'items': purchases,
            }
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            return {'ok': False, 'error': str(e)}
        finally:
            conn.close()

    def upsert_scheduled_service(self, *, product_id: int, duration_minutes: int, capacity_per_slot: int,
                                 start_time: str, end_time: str, allow_auto_time: int = 1,
                                 max_per_student: Optional[int] = None, max_per_class: Optional[int] = None,
                                 queue_priority_mode: str = 'class_asc',
                                 queue_priority_custom: str = '',
                                 allowed_classes: str = '',
                                 min_points_required: int = 0,
                                 is_active: int = 1) -> int:
        """יוצר/מעדכן שירות מתוזמן עבור מוצר. מחזיר service_id."""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            conn.execute('BEGIN IMMEDIATE')
            cursor.execute('SELECT id FROM scheduled_services WHERE product_id = ?', (int(product_id or 0),))
            row = cursor.fetchone()
            if row:
                sid = int(row['id'] or 0)
                cursor.execute(
                    '''
                    UPDATE scheduled_services
                       SET duration_minutes = ?,
                           capacity_per_slot = ?,
                           start_time = ?,
                           end_time = ?,
                           allow_auto_time = ?,
                           max_per_student = ?,
                           max_per_class = ?,
                           queue_priority_mode = ?,
                           queue_priority_custom = ?,
                           allowed_classes = ?,
                           min_points_required = ?,
                           is_active = ?,
                           updated_at = CURRENT_TIMESTAMP
                     WHERE id = ?
                    ''',
                    (
                        int(duration_minutes or 0),
                        int(capacity_per_slot or 0),
                        str(start_time or '').strip(),
                        str(end_time or '').strip(),
                        1 if int(allow_auto_time or 0) == 1 else 0,
                        (int(max_per_student) if max_per_student is not None else None),
                        (int(max_per_class) if max_per_class is not None else None),
                        str(queue_priority_mode or 'class_asc').strip(),
                        str(queue_priority_custom or '').strip(),
                        str(allowed_classes or '').strip(),
                        int(min_points_required or 0),
                        1 if int(is_active or 0) == 1 else 0,
                        int(sid),
                    )
                )
                conn.commit()
                return int(sid)

            cursor.execute(
                '''
                INSERT INTO scheduled_services
                    (product_id, duration_minutes, capacity_per_slot, start_time, end_time, allow_auto_time,
                     max_per_student, max_per_class, queue_priority_mode, queue_priority_custom,
                     allowed_classes, min_points_required, is_active, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ''',
                (
                    int(product_id or 0),
                    int(duration_minutes or 0),
                    int(capacity_per_slot or 0),
                    str(start_time or '').strip(),
                    str(end_time or '').strip(),
                    1 if int(allow_auto_time or 0) == 1 else 0,
                    (int(max_per_student) if max_per_student is not None else None),
                    (int(max_per_class) if max_per_class is not None else None),
                    str(queue_priority_mode or 'class_asc').strip(),
                    str(queue_priority_custom or '').strip(),
                    str(allowed_classes or '').strip(),
                    int(min_points_required or 0),
                    1 if int(is_active or 0) == 1 else 0,
                )
            )
            sid = int(cursor.lastrowid or 0)
            conn.commit()
            return int(sid)
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            conn.close()

    def delete_scheduled_service_by_product(self, product_id: int) -> bool:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('DELETE FROM scheduled_services WHERE product_id = ?', (int(product_id or 0),))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def set_scheduled_service_dates(self, *, service_id: int, dates_greg: List[str]):
        """מחליף את רשימת התאריכים הפעילים לשירות. תאריכים בפורמט YYYY-MM-DD."""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            conn.execute('BEGIN IMMEDIATE')
            cursor.execute('DELETE FROM scheduled_service_dates WHERE service_id = ?', (int(service_id or 0),))
            for d in (dates_greg or []):
                ds = str(d or '').strip()
                if not ds:
                    continue
                cursor.execute(
                    '''
                    INSERT OR IGNORE INTO scheduled_service_dates
                        (service_id, service_date, is_active, updated_at)
                    VALUES (?, ?, 1, CURRENT_TIMESTAMP)
                    ''',
                    (int(service_id or 0), ds)
                )
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            conn.close()

    def get_scheduled_service_dates(self, service_id: int, *, active_only: bool = True) -> List[str]:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            if active_only:
                cursor.execute(
                    'SELECT service_date FROM scheduled_service_dates WHERE service_id = ? AND is_active = 1 ORDER BY service_date',
                    (int(service_id or 0),)
                )
            else:
                cursor.execute(
                    'SELECT service_date FROM scheduled_service_dates WHERE service_id = ? ORDER BY is_active DESC, service_date',
                    (int(service_id or 0),)
                )
            rows = cursor.fetchall() or []
            return [str(r['service_date'] or '').strip() for r in rows if str(r['service_date'] or '').strip()]
        finally:
            conn.close()

    def _time_to_minutes(self, t: str) -> int:
        t = str(t or '').strip()
        if not t:
            return 0
        try:
            hh, mm = t.split(':', 1)
            return int(hh) * 60 + int(mm)
        except Exception:
            return 0

    def _minutes_to_time(self, m: int) -> str:
        try:
            m = int(m)
        except Exception:
            m = 0
        if m < 0:
            m = 0
        hh = m // 60
        mm = m % 60
        return f"{hh:02d}:{mm:02d}"

    def get_scheduled_service_slots(self, *, service_id: int, service_date: str) -> List[Dict[str, Any]]:
        """מחזיר סלוטים עם תפוסה/פנויים לתאריך ספציפי."""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT * FROM scheduled_services WHERE id = ? AND is_active = 1', (int(service_id or 0),))
            srow = cursor.fetchone()
            if not srow:
                return []
            s = dict(srow)
            dur = int(s.get('duration_minutes', 10) or 10)
            cap = int(s.get('capacity_per_slot', 1) or 1)
            start_m = self._time_to_minutes(s.get('start_time', ''))
            end_m = self._time_to_minutes(s.get('end_time', ''))
            if dur <= 0 or cap <= 0 or end_m <= start_m:
                return []

            # validate date is allowed
            cursor.execute(
                'SELECT COUNT(1) AS c FROM scheduled_service_dates WHERE service_id = ? AND is_active = 1 AND service_date = ?',
                (int(service_id or 0), str(service_date or '').strip())
            )
            ok = cursor.fetchone()
            if int((ok['c'] if ok else 0) or 0) <= 0:
                return []

            cursor.execute(
                '''
                SELECT slot_start_time, COUNT(1) AS used
                  FROM scheduled_service_reservations
                 WHERE service_id = ? AND service_date = ?
                 GROUP BY slot_start_time
                ''',
                (int(service_id or 0), str(service_date or '').strip())
            )
            used_map = {str(r['slot_start_time'] or '').strip(): int(r['used'] or 0) for r in (cursor.fetchall() or [])}

            cursor.execute(
                '''
                SELECT slot_start_time, COALESCE(SUM(qty),0) AS used
                  FROM purchase_holds
                 WHERE hold_type = 'scheduled'
                   AND expires_at > CURRENT_TIMESTAMP
                   AND service_id = ? AND service_date = ?
                 GROUP BY slot_start_time
                ''',
                (int(service_id or 0), str(service_date or '').strip())
            )
            hold_map = {str(r['slot_start_time'] or '').strip(): int(r['used'] or 0) for r in (cursor.fetchall() or [])}

            out: List[Dict[str, Any]] = []
            cur = int(start_m)
            while cur + dur <= end_m:
                t = self._minutes_to_time(cur)
                used = int(used_map.get(t, 0) or 0)
                held = int(hold_map.get(t, 0) or 0)
                remaining = int(cap - used - held)
                if remaining < 0:
                    remaining = 0
                out.append({
                    'slot_start_time': t,
                    'used': int(used + held),
                    'capacity': int(cap),
                    'remaining': int(remaining),
                    'is_full': 1 if remaining <= 0 else 0,
                })
                cur += dur
            return out
        finally:
            conn.close()

    def get_student_scheduled_reservations_on_date(self, *, student_id: int, service_date: str) -> List[Dict[str, Any]]:
        """מחזיר את כל התורים המתוזמנים של תלמיד לתאריך נתון (לבדיקת חפיפות בצד לקוח)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            sd = str(service_date or '').strip()
            cursor.execute(
                '''
                SELECT service_id, service_date, slot_start_time, duration_minutes
                  FROM scheduled_service_reservations
                 WHERE student_id = ? AND service_date = ?
                 ORDER BY slot_start_time
                ''',
                (int(student_id or 0), sd)
            )
            rows = cursor.fetchall() or []
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def _scheduled_service_limits_ok(self, cursor, *, service_id: int, student_id: int) -> Dict[str, Any]:
        cursor.execute('SELECT max_per_student, max_per_class FROM scheduled_services WHERE id = ?', (int(service_id or 0),))
        srow = cursor.fetchone()
        if not srow:
            return {'ok': False, 'error': 'שירות לא נמצא'}
        max_per_student = srow['max_per_student']
        max_per_class = srow['max_per_class']

        if max_per_student is not None:
            try:
                mps = int(max_per_student)
            except Exception:
                mps = None
            if mps is not None and mps >= 0:
                cursor.execute(
                    'SELECT COUNT(1) AS c FROM scheduled_service_reservations WHERE service_id = ? AND student_id = ?',
                    (int(service_id or 0), int(student_id or 0))
                )
                c = cursor.fetchone()
                if int((c['c'] if c else 0) or 0) >= int(mps):
                    return {'ok': False, 'error': 'חרגת מהמקסימום לתלמיד'}

        if max_per_class is not None:
            try:
                mpc = int(max_per_class)
            except Exception:
                mpc = None
            if mpc is not None and mpc >= 0:
                cursor.execute('SELECT class_name FROM students WHERE id = ?', (int(student_id or 0),))
                st = cursor.fetchone()
                cls = str((st['class_name'] if st else '') or '').strip()
                if cls:
                    cursor.execute(
                        '''
                        SELECT COUNT(1) AS c
                          FROM scheduled_service_reservations r
                          JOIN students s ON s.id = r.student_id
                         WHERE r.service_id = ? AND s.class_name = ?
                        ''',
                        (int(service_id or 0), cls)
                    )
                    c = cursor.fetchone()
                    if int((c['c'] if c else 0) or 0) >= int(mpc):
                        return {'ok': False, 'error': 'חרגת מהמקסימום לכיתה'}

        return {'ok': True}

    def reserve_scheduled_service_slot(self, *, service_id: int, student_id: int, service_date: str,
                                       slot_start_time: str, purchase_id: Optional[int] = None) -> Dict[str, Any]:
        """שריון סלוט אטומי (כולל בדיקת קיבולת + מגבלות)."""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT * FROM scheduled_services WHERE id = ? AND is_active = 1', (int(service_id or 0),))
            svc = cursor.fetchone()
            if not svc:
                return {'ok': False, 'error': 'האתגר לא פעיל'}
            s = dict(svc)

            # date allowed
            sd = str(service_date or '').strip()
            cursor.execute(
                'SELECT COUNT(1) AS c FROM scheduled_service_dates WHERE service_id = ? AND is_active = 1 AND service_date = ?',
                (int(service_id or 0), sd)
            )
            ok = cursor.fetchone()
            if int((ok['c'] if ok else 0) or 0) <= 0:
                return {'ok': False, 'error': 'התאריך לא זמין'}

            # limits
            lim = self._scheduled_service_limits_ok(cursor, service_id=int(service_id or 0), student_id=int(student_id or 0))
            if not lim.get('ok'):
                return lim

            dur = int(s.get('duration_minutes', 10) or 10)
            cap = int(s.get('capacity_per_slot', 1) or 1)
            t = str(slot_start_time or '').strip()
            if not t:
                return {'ok': False, 'error': 'שעה לא תקינה'}

            # Prevent student from reserving overlapping challenges on the same date
            try:
                def _to_min(hhmm: str) -> int:
                    hhmm = str(hhmm or '').strip()
                    if ':' not in hhmm:
                        return -1
                    hh, mm = hhmm.split(':', 1)
                    return int(hh) * 60 + int(mm)

                start_min = _to_min(t)
                end_min = start_min + int(dur)

                cursor.execute(
                    '''
                    SELECT slot_start_time, duration_minutes
                      FROM scheduled_service_reservations
                     WHERE student_id = ? AND service_date = ?
                    ''',
                    (int(student_id or 0), sd)
                )
                existing = cursor.fetchall() or []
                for r in existing:
                    try:
                        other_start = _to_min(r['slot_start_time'])
                    except Exception:
                        other_start = -1
                    try:
                        other_dur = int(r['duration_minutes'] or 0)
                    except Exception:
                        other_dur = 0
                    if other_start < 0 or other_dur <= 0:
                        continue
                    other_end = other_start + other_dur
                    if start_min < other_end and other_start < end_min:
                        return {'ok': False, 'error': 'לתלמיד כבר יש אתגר בזמן הזה'}
            except Exception:
                pass

            cursor.execute(
                'SELECT COUNT(1) AS used FROM scheduled_service_reservations WHERE service_id = ? AND service_date = ? AND slot_start_time = ?',
                (int(service_id or 0), sd, t)
            )
            used_row = cursor.fetchone()
            used = int((used_row['used'] if used_row else 0) or 0)
            if used >= cap:
                conn.rollback()
                return {'ok': False, 'error': 'הסלוט מלא'}

            try:
                cursor.execute(
                    '''
                    INSERT INTO scheduled_service_reservations
                        (service_id, student_id, purchase_id, service_date, slot_start_time, duration_minutes)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ''',
                    (
                        int(service_id or 0),
                        int(student_id or 0),
                        (int(purchase_id) if purchase_id is not None else None),
                        sd,
                        t,
                        int(dur),
                    )
                )
            except Exception:
                conn.rollback()
                return {'ok': False, 'error': 'הסלוט כבר נתפס'}

            rid = int(cursor.lastrowid or 0)
            conn.commit()
            return {
                'ok': True,
                'reservation_id': int(rid),
                'service_id': int(service_id or 0),
                'student_id': int(student_id or 0),
                'service_date': sd,
                'slot_start_time': t,
                'duration_minutes': int(dur),
            }
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            return {'ok': False, 'error': str(e)}
        finally:
            conn.close()

    def get_all_products(self, *, active_only: bool = False) -> List[Dict[str, Any]]:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            if active_only:
                cursor.execute(
                    '''
                    SELECT p.*, c.name AS category_name
                      FROM products p
                      LEFT JOIN product_categories c ON c.id = p.category_id
                     WHERE p.is_active = 1
                     ORDER BY COALESCE(p.sort_order, 0), p.name
                    '''
                )
            else:
                cursor.execute(
                    '''
                    SELECT p.*, c.name AS category_name
                      FROM products p
                      LEFT JOIN product_categories c ON c.id = p.category_id
                     ORDER BY p.is_active DESC, COALESCE(p.sort_order, 0), p.name
                    '''
                )
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_product_by_id(self, product_id: int) -> Optional[Dict[str, Any]]:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                '''
                SELECT p.*, c.name AS category_name
                  FROM products p
                  LEFT JOIN product_categories c ON c.id = p.category_id
                 WHERE p.id = ?
                 LIMIT 1
                ''',
                (int(product_id or 0),)
            )
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_cashier_catalog_export(self) -> List[Dict[str, Any]]:
        """Export catalog for cashier/admin: products with category and optional scheduled_service (challenge) info."""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                '''
                SELECT p.id AS product_id,
                       p.is_active AS product_is_active,
                       p.name AS product_name,
                       p.display_name AS product_display_name,
                       p.price_points AS product_price_points,
                       p.stock_qty AS product_stock_qty,
                       p.image_path AS product_image_path,
                       c.name AS category_name,
                       p.allowed_classes AS product_allowed_classes,
                       p.min_points_required AS product_min_points_required,
                       p.max_per_student AS product_max_per_student,
                       p.max_per_class AS product_max_per_class,
                       p.price_override_min_points AS product_price_override_min_points,
                       p.price_override_discount_pct AS product_price_override_discount_pct,
                       ss.id AS challenge_id,
                       ss.is_active AS challenge_is_active,
                       ss.duration_minutes AS challenge_duration_minutes,
                       ss.capacity_per_slot AS challenge_capacity_per_slot,
                       ss.start_time AS challenge_start_time,
                       ss.end_time AS challenge_end_time,
                       ss.allow_auto_time AS challenge_allow_auto_time,
                       ss.max_per_student AS challenge_max_per_student,
                       ss.max_per_class AS challenge_max_per_class,
                       ss.queue_priority_mode AS challenge_queue_priority_mode,
                       ss.queue_priority_custom AS challenge_queue_priority_custom,
                       ss.allowed_classes AS challenge_allowed_classes,
                       ss.min_points_required AS challenge_min_points_required
                  FROM products p
                  LEFT JOIN product_categories c ON c.id = p.category_id
                  LEFT JOIN scheduled_services ss ON ss.product_id = p.id
                 ORDER BY p.is_active DESC, COALESCE(p.sort_order, 0), p.name
                '''
            )
            rows = cursor.fetchall() or []
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_product_categories(self, *, active_only: bool = True) -> List[Dict[str, Any]]:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            if active_only:
                cursor.execute('SELECT * FROM product_categories WHERE is_active = 1 ORDER BY COALESCE(sort_order, 0), name')
            else:
                cursor.execute('SELECT * FROM product_categories ORDER BY is_active DESC, COALESCE(sort_order, 0), name')
            rows = cursor.fetchall() or []
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def add_product_category(self, *, name: str, sort_order: int = 0, is_active: int = 1) -> int:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                'INSERT INTO product_categories (name, sort_order, is_active, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)',
                (str(name or '').strip(), int(sort_order or 0), int(is_active or 0))
            )
            cid = cursor.lastrowid
            conn.commit()
            return int(cid or 0)
        finally:
            conn.close()

    def update_product_category(self, category_id: int, *, name: str, sort_order: int = 0, is_active: int = 1) -> bool:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                'UPDATE product_categories SET name = ?, sort_order = ?, is_active = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                (str(name or '').strip(), int(sort_order or 0), int(is_active or 0), int(category_id or 0))
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def delete_product_category(self, category_id: int) -> bool:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('UPDATE products SET category_id = NULL, updated_at = CURRENT_TIMESTAMP WHERE category_id = ?', (int(category_id or 0),))
            cursor.execute('DELETE FROM product_categories WHERE id = ?', (int(category_id or 0),))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def _ensure_products_have_sort_order(self) -> None:
        """מבטיח שלכל המוצרים יש sort_order סדרתי כך שניתן להזיז מעלה/מטה."""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT COUNT(*) AS c FROM products')
            row = cursor.fetchone()
            total = int(dict(row).get('c', 0) or 0) if row else 0
            if total <= 1:
                return

            cursor.execute('SELECT COUNT(DISTINCT COALESCE(sort_order, 0)) AS c FROM products')
            row2 = cursor.fetchone()
            distinct = int(dict(row2).get('c', 0) or 0) if row2 else 0
            if distinct > 1:
                return

            cursor.execute('SELECT id FROM products ORDER BY is_active DESC, name')
            ids = [int(r['id']) for r in (cursor.fetchall() or [])]
            for idx, pid in enumerate(ids):
                cursor.execute('UPDATE products SET sort_order = ? WHERE id = ?', (int(idx), int(pid)))
            conn.commit()
        finally:
            conn.close()

    def move_product_sort_order(self, *, product_id: int, direction: int) -> bool:
        """הזזת מוצר מעלה/מטה לפי sort_order. direction=-1 למעלה, +1 למטה."""
        try:
            product_id = int(product_id or 0)
            direction = int(direction or 0)
        except Exception:
            return False
        if not product_id or direction not in (-1, 1):
            return False

        self._ensure_products_have_sort_order()

        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT id, COALESCE(sort_order, 0) AS sort_order, COALESCE(is_active, 1) AS is_active FROM products WHERE id = ?', (int(product_id),))
            cur = cursor.fetchone()
            if not cur:
                return False
            cur = dict(cur)
            cur_active = int(cur.get('is_active', 1) or 0)
            cur_sort = int(cur.get('sort_order', 0) or 0)

            cursor.execute(
                'SELECT id, COALESCE(sort_order, 0) AS sort_order FROM products WHERE COALESCE(is_active, 1) = ? ORDER BY COALESCE(sort_order, 0), name',
                (int(cur_active),)
            )
            rows = [dict(r) for r in (cursor.fetchall() or [])]
            ids = [int(r['id']) for r in rows]
            if product_id not in ids:
                return False
            i = ids.index(product_id)
            j = i + direction
            if j < 0 or j >= len(ids):
                return False
            other_id = int(ids[j])

            cursor.execute('SELECT COALESCE(sort_order, 0) AS sort_order FROM products WHERE id = ?', (int(other_id),))
            other = cursor.fetchone()
            other_sort = int(dict(other).get('sort_order', 0) or 0) if other else 0

            cursor.execute('UPDATE products SET sort_order = ? WHERE id = ?', (int(other_sort), int(product_id)))
            cursor.execute('UPDATE products SET sort_order = ? WHERE id = ?', (int(cur_sort), int(other_id)))
            conn.commit()
            return True
        finally:
            conn.close()

    def get_student_purchases(self, student_id: int, *, limit: int = 200, include_refunded: bool = False) -> List[Dict[str, Any]]:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            if include_refunded:
                cursor.execute(
                    '''
                    SELECT pl.*, p.name AS product_name, p.display_name AS product_display_name,
                           v.variant_name AS variant_name, v.display_name AS variant_display_name
                      FROM purchases_log pl
                      LEFT JOIN products p ON p.id = pl.product_id
                      LEFT JOIN product_variants v ON v.id = pl.variant_id
                     WHERE pl.student_id = ?
                     ORDER BY pl.created_at DESC
                     LIMIT ?
                    ''',
                    (int(student_id or 0), int(limit or 200))
                )
            else:
                cursor.execute(
                    '''
                    SELECT pl.*, p.name AS product_name, p.display_name AS product_display_name,
                           v.variant_name AS variant_name, v.display_name AS variant_display_name
                      FROM purchases_log pl
                      LEFT JOIN products p ON p.id = pl.product_id
                      LEFT JOIN product_variants v ON v.id = pl.variant_id
                     WHERE pl.student_id = ? AND COALESCE(pl.is_refunded, 0) = 0
                     ORDER BY pl.created_at DESC
                     LIMIT ?
                    ''',
                    (int(student_id or 0), int(limit or 200))
                )
            rows = cursor.fetchall() or []
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def refund_purchase(self, *, purchase_id: int, approved_by_teacher: Dict[str, Any], reason: str = '',
                        station_type: str = 'cashier') -> Dict[str, Any]:
        """ביטול קנייה (שורה אחת) + זיכוי נקודות + החזרת מלאי, אטומי."""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            conn.execute('BEGIN IMMEDIATE')

            cursor.execute('SELECT * FROM purchases_log WHERE id = ?', (int(purchase_id or 0),))
            prow = cursor.fetchone()
            if not prow:
                conn.rollback()
                return {'ok': False, 'error': 'רכישה לא נמצאה'}
            p = dict(prow)

            if int(p.get('is_refunded', 0) or 0) == 1:
                conn.rollback()
                return {'ok': False, 'error': 'הרכישה כבר בוטלה'}

            sid = int(p.get('student_id') or 0)
            pid = int(p.get('product_id') or 0)
            vid = int(p.get('variant_id') or 0) if p.get('variant_id', None) is not None else 0
            qty = int(p.get('qty') or 0)
            if qty < 1:
                qty = 1

            cursor.execute('SELECT * FROM students WHERE id = ?', (int(sid),))
            srow = cursor.fetchone()
            if not srow:
                conn.rollback()
                return {'ok': False, 'error': 'תלמיד לא נמצא'}
            s = dict(srow)
            old_points = int(s.get('points', 0) or 0)

            refunded_points = 0
            if int(p.get('deduct_points', 1) or 0) == 1:
                refunded_points = int(p.get('total_points', 0) or 0)

            new_points = int(old_points + refunded_points)
            if refunded_points:
                cursor.execute('UPDATE students SET points = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?', (int(new_points), int(sid)))

            # restore stock
            if vid:
                cursor.execute('SELECT stock_qty FROM product_variants WHERE id = ?', (int(vid),))
                vrow = cursor.fetchone()
                if vrow is not None:
                    cur = vrow['stock_qty']
                    if cur is not None:
                        try:
                            cur = int(cur)
                            cursor.execute('UPDATE product_variants SET stock_qty = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?', (int(cur + qty), int(vid)))
                        except Exception:
                            pass
            else:
                cursor.execute('SELECT stock_qty FROM products WHERE id = ?', (int(pid),))
                pr = cursor.fetchone()
                if pr is not None:
                    cur = pr['stock_qty']
                    if cur is not None:
                        try:
                            cur = int(cur)
                            cursor.execute('UPDATE products SET stock_qty = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?', (int(cur + qty), int(pid)))
                        except Exception:
                            pass

            cursor.execute(
                'UPDATE purchases_log SET is_refunded = 1, refunded_at = CURRENT_TIMESTAMP WHERE id = ?',
                (int(purchase_id or 0),)
            )

            # If this purchase created a scheduled reservation, free the slot for other students
            try:
                cursor.execute(
                    'DELETE FROM scheduled_service_reservations WHERE purchase_id = ?',
                    (int(purchase_id or 0),)
                )
            except Exception:
                pass

            try:
                cursor.execute(
                    '''
                    INSERT INTO refunds_log (purchase_id, student_id, refunded_points, qty, product_id, variant_id, reason,
                                             approved_by_teacher_id, approved_by_teacher_name, station_type)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    (
                        int(purchase_id or 0),
                        int(sid),
                        int(refunded_points),
                        int(qty),
                        int(pid) if pid else None,
                        int(vid) if vid else None,
                        str(reason or '').strip(),
                        int(approved_by_teacher.get('id', 0) or 0) if approved_by_teacher else None,
                        str(approved_by_teacher.get('name') or '').strip() if approved_by_teacher else None,
                        str(station_type or 'cashier')
                    )
                )
            except Exception:
                pass

            try:
                cursor.execute(
                    '''
                    INSERT INTO points_log (student_id, old_points, new_points, delta, reason, actor_name, action_type)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''',
                    (
                        int(sid),
                        int(old_points),
                        int(new_points),
                        int(new_points - old_points),
                        (str(reason).strip() if str(reason or '').strip() else 'ביטול קנייה'),
                        (str(approved_by_teacher.get('name') or 'מנהל').strip() if approved_by_teacher else 'מנהל'),
                        'refund'
                    )
                )
            except Exception:
                pass

            conn.commit()
            return {
                'ok': True,
                'purchase_id': int(purchase_id or 0),
                'student_id': int(sid),
                'refunded_points': int(refunded_points),
                'old_points': int(old_points),
                'new_points': int(new_points),
            }
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            return {'ok': False, 'error': str(e)}
        finally:
            conn.close()

    def cashier_purchase_batch(self, *, student_id: int, items: List[Dict[str, Any]],
                               station_type: str = 'cashier',
                               actor_name: str = 'cashier') -> Dict[str, Any]:
        """רכישה אטומית של עגלה: items=[{'product_id':int,'variant_id':int,'qty':int}, ...]."""
        cleaned = []
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
                q = int(it.get('qty') or 0)
            except Exception:
                q = 0
            if (pid or vid) and q > 0:
                cleaned.append({'product_id': pid, 'variant_id': vid, 'qty': q})

        if not cleaned:
            return {'ok': False, 'error': 'אין פריטים לתשלום'}

        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            conn.execute('BEGIN IMMEDIATE')

            cursor.execute('SELECT * FROM students WHERE id = ?', (int(student_id or 0),))
            stu_row = cursor.fetchone()
            if not stu_row:
                conn.rollback()
                return {'ok': False, 'error': 'תלמיד לא נמצא'}
            stu = dict(stu_row)
            old_points = int(stu.get('points', 0) or 0)

            products_by_id: Dict[int, Dict[str, Any]] = {}
            stock_updates = []
            purchases = []
            total_deduct_points = 0
            total_display_points = 0

            for it in cleaned:
                pid = int(it.get('product_id') or 0)
                vid = int(it.get('variant_id') or 0)
                qty = int(it['qty'])

                v = {}
                if vid:
                    cursor.execute('SELECT * FROM product_variants WHERE id = ?', (vid,))
                    vrow = cursor.fetchone()
                    if not vrow:
                        conn.rollback()
                        return {'ok': False, 'error': 'וריאציה לא נמצאה'}
                    v = dict(vrow)
                    if int(v.get('is_active', 1) or 0) != 1:
                        conn.rollback()
                        return {'ok': False, 'error': 'הווריאציה לא פעילה'}
                    try:
                        pid = int(v.get('product_id') or 0)
                    except Exception:
                        pid = 0

                if not pid:
                    conn.rollback()
                    return {'ok': False, 'error': 'מוצר לא נמצא'}

                cursor.execute('SELECT * FROM products WHERE id = ?', (pid,))
                prow = cursor.fetchone()
                if not prow:
                    conn.rollback()
                    return {'ok': False, 'error': 'מוצר לא נמצא'}
                p = dict(prow)
                if int(p.get('is_active', 1) or 0) != 1:
                    conn.rollback()
                    return {'ok': False, 'error': 'המוצר לא פעיל'}

                if vid:
                    price_each = int(v.get('price_points', 0) or 0)
                    deduct = 1 if int(v.get('deduct_points', 1) or 0) == 1 else 0
                    stock_qty = v.get('stock_qty', None)
                else:
                    price_each = int(p.get('price_points', 0) or 0)
                    deduct = 1 if int(p.get('deduct_points', 1) or 0) == 1 else 0
                    stock_qty = p.get('stock_qty', None)

                total_item = price_each * qty

                if stock_qty is not None:
                    try:
                        stock_qty = int(stock_qty)
                    except Exception:
                        stock_qty = None
                if stock_qty is not None and stock_qty < qty:
                    conn.rollback()
                    return {'ok': False, 'error': 'אין מספיק מלאי'}

                if stock_qty is not None:
                    stock_updates.append((pid, vid, int(stock_qty - qty)))

                if deduct == 1:
                    total_deduct_points += int(total_item)
                total_display_points += int(total_item)

                products_by_id[pid] = p
                purchases.append({
                    'product_id': pid,
                    'variant_id': int(vid or 0),
                    'qty': int(qty),
                    'points_each': int(price_each),
                    'total_points': int(total_item),
                    'deduct_points': int(deduct),
                })

            if old_points < total_deduct_points:
                conn.rollback()
                return {'ok': False, 'error': 'אין מספיק נקודות'}

            new_points = int(old_points - total_deduct_points)

            for pid, vid, new_stock in stock_updates:
                if int(vid or 0) > 0:
                    cursor.execute('UPDATE product_variants SET stock_qty = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?', (int(new_stock), int(vid)))
                else:
                    cursor.execute('UPDATE products SET stock_qty = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?', (int(new_stock), int(pid)))

            if new_points != old_points:
                cursor.execute('UPDATE students SET points = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?', (int(new_points), int(student_id or 0)))
                try:
                    cursor.execute(
                        '''
                        INSERT INTO points_log (student_id, old_points, new_points, delta, reason, actor_name, action_type)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        ''',
                        (
                            int(student_id or 0),
                            int(old_points),
                            int(new_points),
                            int(new_points - old_points),
                            'קניה בקופה',
                            str(actor_name or 'cashier'),
                            'purchase'
                        )
                    )
                except Exception:
                    pass

            for it in purchases:
                try:
                    cursor.execute(
                        '''
                        INSERT INTO purchases_log (student_id, product_id, variant_id, qty, points_each, total_points, deduct_points, station_type)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ''',
                        (
                            int(student_id or 0),
                            int(it['product_id']),
                            (int(it.get('variant_id') or 0) if int(it.get('variant_id') or 0) > 0 else None),
                            int(it['qty']),
                            int(it['points_each']),
                            int(it['total_points']),
                            int(it['deduct_points']),
                            str(station_type or 'cashier')
                        )
                    )
                    try:
                        it['purchase_id'] = int(cursor.lastrowid or 0)
                    except Exception:
                        it['purchase_id'] = 0
                except Exception:
                    pass

            conn.commit()
            return {
                'ok': True,
                'student_id': int(student_id or 0),
                'old_points': int(old_points),
                'new_points': int(new_points),
                'total_points': int(total_display_points),
                'total_deduct_points': int(total_deduct_points),
                'items': purchases,
            }
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            return {'ok': False, 'error': str(e)}
        finally:
            conn.close()

    def add_product(self, *, name: str, price_points: int = 0, stock_qty: Optional[int] = None,
                    deduct_points: int = 1, is_active: int = 1,
                    display_name: str = "", image_path: str = "", category_id: Optional[int] = None,
                    allowed_classes: str = '', min_points_required: int = 0,
                    max_per_student: Optional[int] = None, max_per_class: Optional[int] = None,
                    price_override_min_points: Optional[int] = None, price_override_points: Optional[int] = None,
                    price_override_discount_pct: Optional[int] = None) -> int:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                '''
                INSERT INTO products (
                    name, display_name, image_path, category_id,
                    price_points, stock_qty, deduct_points, is_active,
                    allowed_classes, min_points_required, max_per_student, max_per_class,
                    price_override_min_points, price_override_points, price_override_discount_pct,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ''',
                (
                    str(name).strip(),
                    (str(display_name).strip() if str(display_name or '').strip() else None),
                    (str(image_path).strip() if str(image_path or '').strip() else None),
                    (int(category_id) if category_id is not None and str(category_id).strip() != '' else None),
                    int(price_points or 0),
                    stock_qty,
                    int(deduct_points or 0),
                    int(is_active or 0),
                    (str(allowed_classes or '').strip() if str(allowed_classes or '').strip() else None),
                    int(min_points_required or 0),
                    max_per_student,
                    max_per_class,
                    price_override_min_points,
                    price_override_points,
                    price_override_discount_pct,
                )
            )
            pid = cursor.lastrowid
            conn.commit()
            return int(pid or 0)
        finally:
            conn.close()

    def update_product(self, product_id: int, *, name: str, price_points: int = 0, stock_qty: Optional[int] = None,
                       deduct_points: int = 1, is_active: int = 1,
                       display_name: str = "", image_path: str = "", category_id: Optional[int] = None,
                       allowed_classes: str = '', min_points_required: int = 0,
                       max_per_student: Optional[int] = None, max_per_class: Optional[int] = None,
                       price_override_min_points: Optional[int] = None, price_override_points: Optional[int] = None,
                       price_override_discount_pct: Optional[int] = None) -> bool:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                '''
                UPDATE products
                   SET name = ?,
                       display_name = ?,
                       image_path = ?,
                       category_id = ?,
                       price_points = ?,
                       stock_qty = ?,
                       deduct_points = ?,
                       allowed_classes = ?,
                       min_points_required = ?,
                       max_per_student = ?,
                       max_per_class = ?,
                       price_override_min_points = ?,
                       price_override_points = ?,
                       price_override_discount_pct = ?,
                       is_active = ?,
                       updated_at = CURRENT_TIMESTAMP
                 WHERE id = ?
                ''',
                (
                    str(name).strip(),
                    (str(display_name).strip() if str(display_name or '').strip() else None),
                    (str(image_path).strip() if str(image_path or '').strip() else None),
                    (int(category_id) if category_id is not None and str(category_id).strip() != '' else None),
                    int(price_points or 0),
                    stock_qty,
                    int(deduct_points or 0),
                    (str(allowed_classes or '').strip() if str(allowed_classes or '').strip() else None),
                    int(min_points_required or 0),
                    max_per_student,
                    max_per_class,
                    price_override_min_points,
                    price_override_points,
                    price_override_discount_pct,
                    int(is_active or 0),
                    int(product_id or 0)
                )
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def get_cashier_mode(self) -> str:
        v = (self.get_setting('cashier_mode', 'teacher') or 'teacher').strip()
        if v not in ('teacher', 'responsible_student', 'self_service'):
            v = 'teacher'
        return v

    def set_cashier_mode(self, mode: str):
        self.set_setting('cashier_mode', str(mode or '').strip())

    def get_cashier_idle_timeout_sec(self) -> int:
        try:
            return int(self.get_setting('cashier_idle_timeout_sec', '300') or 300)
        except Exception:
            return 300

    def set_cashier_idle_timeout_sec(self, seconds: int):
        try:
            seconds = int(seconds)
        except Exception:
            seconds = 300
        if seconds < 30:
            seconds = 30
        self.set_setting('cashier_idle_timeout_sec', str(seconds))

    def get_cashier_bw_logo_path(self) -> str:
        return (self.get_setting('cashier_bw_logo_path', '') or '').strip()

    def set_cashier_bw_logo_path(self, path: str):
        self.set_setting('cashier_bw_logo_path', (path or '').strip())

    def get_cashier_payment_confirm_mode(self) -> str:
        v = str(self.get_setting('cashier_payment_confirm_mode', '') or '').strip().lower()
        if v in ('always', 'never', 'threshold'):
            return v
        # backward compatibility with old checkbox
        try:
            old = self.get_cashier_require_rescan_confirm()
            return 'always' if bool(old) else 'never'
        except Exception:
            return 'always'

    def set_cashier_payment_confirm_mode(self, mode: str):
        mode = str(mode or '').strip().lower()
        if mode not in ('always', 'never', 'threshold'):
            mode = 'always'
        self.set_setting('cashier_payment_confirm_mode', mode)

    def get_cashier_payment_confirm_threshold(self) -> int:
        try:
            return int(self.get_setting('cashier_payment_confirm_threshold', '0') or 0)
        except Exception:
            return 0

    def set_cashier_payment_confirm_threshold(self, threshold_points: int):
        try:
            threshold_points = int(threshold_points)
        except Exception:
            threshold_points = 0
        if threshold_points < 0:
            threshold_points = 0
        self.set_setting('cashier_payment_confirm_threshold', str(threshold_points))

    def get_cashier_print_item_receipts(self) -> bool:
        v = str(self.get_setting('cashier_print_item_receipts', '0') or '0').strip()
        return v not in ('0', 'false', 'False', 'no', 'No')

    def set_cashier_print_item_receipts(self, enabled: bool):
        self.set_setting('cashier_print_item_receipts', '1' if bool(enabled) else '0')

    def get_cashier_receipt_footer_text(self) -> str:
        return (self.get_setting('cashier_receipt_footer_text', 'תודה ולהתראות') or '').strip()

    def set_cashier_receipt_footer_text(self, text: str):
        self.set_setting('cashier_receipt_footer_text', (text or '').strip())

    def get_cashier_require_rescan_confirm(self) -> bool:
        v = str(self.get_setting('cashier_require_rescan_confirm', '1') or '1').strip()
        return v not in ('0', 'false', 'False', 'no', 'No')

    def set_cashier_require_rescan_confirm(self, enabled: bool):
        self.set_setting('cashier_require_rescan_confirm', '1' if bool(enabled) else '0')

    def should_cashier_require_rescan_confirm(self, total_points: int) -> bool:
        try:
            total_points = int(total_points)
        except Exception:
            total_points = 0
        mode = self.get_cashier_payment_confirm_mode()
        if mode == 'never':
            return False
        if mode == 'threshold':
            thr = self.get_cashier_payment_confirm_threshold()
            return total_points > int(thr or 0)
        return True

    def get_product_variants(self, product_id: int, *, active_only: bool = False) -> List[Dict[str, Any]]:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            if active_only:
                cursor.execute(
                    'SELECT * FROM product_variants WHERE product_id = ? AND is_active = 1 ORDER BY sort_order, id',
                    (int(product_id or 0),)
                )
            else:
                cursor.execute(
                    'SELECT * FROM product_variants WHERE product_id = ? ORDER BY is_active DESC, sort_order, id',
                    (int(product_id or 0),)
                )
            rows = cursor.fetchall() or []
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def add_product_variant(self, *, product_id: int, variant_name: str,
                            display_name: str = '', price_points: int = 0,
                            stock_qty: Optional[int] = None, deduct_points: int = 1,
                            is_active: int = 1, sort_order: int = 0) -> int:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                '''
                INSERT INTO product_variants (product_id, variant_name, display_name, price_points, stock_qty, deduct_points, is_active, sort_order, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ''',
                (
                    int(product_id or 0),
                    str(variant_name or '').strip(),
                    (str(display_name or '').strip() if str(display_name or '').strip() else None),
                    int(price_points or 0),
                    stock_qty,
                    int(deduct_points or 0),
                    int(is_active or 0),
                    int(sort_order or 0),
                )
            )
            vid = cursor.lastrowid
            conn.commit()
            return int(vid or 0)
        finally:
            conn.close()

    def update_product_variant(self, variant_id: int, *, variant_name: str,
                               display_name: str = '', price_points: int = 0,
                               stock_qty: Optional[int] = None, deduct_points: int = 1,
                               is_active: int = 1, sort_order: int = 0) -> bool:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                '''
                UPDATE product_variants
                   SET variant_name = ?,
                       display_name = ?,
                       price_points = ?,
                       stock_qty = ?,
                       deduct_points = ?,
                       is_active = ?,
                       sort_order = ?,
                       updated_at = CURRENT_TIMESTAMP
                 WHERE id = ?
                ''',
                (
                    str(variant_name or '').strip(),
                    (str(display_name or '').strip() if str(display_name or '').strip() else None),
                    int(price_points or 0),
                    stock_qty,
                    int(deduct_points or 0),
                    int(is_active or 0),
                    int(sort_order or 0),
                    int(variant_id or 0)
                )
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def delete_product_variant(self, variant_id: int) -> bool:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('DELETE FROM product_variants WHERE id = ?', (int(variant_id or 0),))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def get_cashier_catalog(self) -> List[Dict[str, Any]]:
        """מחזיר קטלוג לקופה: מוצרים פעילים עם וריאציות פעילות."""
        prods = self.get_all_products(active_only=True) or []
        out: List[Dict[str, Any]] = []
        for p in prods:
            try:
                pid = int(p.get('id') or 0)
            except Exception:
                pid = 0
            if not pid:
                continue
            vars_ = self.get_product_variants(pid, active_only=True) or []
            if not vars_:
                # fallback
                vars_ = [{
                    'id': 0,
                    'product_id': pid,
                    'variant_name': 'ברירת מחדל',
                    'display_name': str(p.get('display_name') or '').strip(),
                    'price_points': int(p.get('price_points', 0) or 0),
                    'stock_qty': p.get('stock_qty', None),
                    'deduct_points': int(p.get('deduct_points', 1) or 0),
                    'is_active': 1,
                    'sort_order': 0,
                }]
            p2 = dict(p)
            p2['variants'] = vars_
            out.append(p2)
        return out

    # ========================================
    # Activities (Challenges)
    # ========================================

    def get_all_activities(self) -> List[Dict[str, Any]]:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT * FROM activities ORDER BY is_active DESC, id DESC')
            rows = cursor.fetchall() or []
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def add_activity(self, *, name: str, description: str = '', points: int = 0, print_code: str = '', is_active: int = 1) -> int:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                'INSERT INTO activities (name, description, points, print_code, is_active, updated_at) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)',
                (
                    str(name or '').strip(),
                    (str(description or '').strip() if str(description or '').strip() else None),
                    int(points or 0),
                    (str(print_code or '').strip() if str(print_code or '').strip() else None),
                    int(is_active or 0),
                )
            )
            aid = cursor.lastrowid
            conn.commit()
            return int(aid or 0)
        finally:
            conn.close()

    def update_activity(self, activity_id: int, *, name: str, description: str = '', points: int = 0, print_code: str = '', is_active: int = 1) -> bool:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                'UPDATE activities SET name = ?, description = ?, points = ?, print_code = ?, is_active = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                (
                    str(name or '').strip(),
                    (str(description or '').strip() if str(description or '').strip() else None),
                    int(points or 0),
                    (str(print_code or '').strip() if str(print_code or '').strip() else None),
                    int(is_active or 0),
                    int(activity_id or 0),
                )
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def delete_activity(self, activity_id: int) -> bool:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('DELETE FROM activity_schedules WHERE activity_id = ?', (int(activity_id or 0),))
            cursor.execute('DELETE FROM activity_claims WHERE activity_id = ?', (int(activity_id or 0),))
            cursor.execute('DELETE FROM activities WHERE id = ?', (int(activity_id or 0),))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def get_activity_schedules(self, activity_id: int, *, active_only: bool = False) -> List[Dict[str, Any]]:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            if active_only:
                cursor.execute(
                    'SELECT * FROM activity_schedules WHERE activity_id = ? AND is_active = 1 ORDER BY id',
                    (int(activity_id or 0),)
                )
            else:
                cursor.execute(
                    'SELECT * FROM activity_schedules WHERE activity_id = ? ORDER BY is_active DESC, id',
                    (int(activity_id or 0),)
                )
            rows = cursor.fetchall() or []
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def add_activity_schedule(self, *, activity_id: int, start_time: str = '', end_time: str = '', days_of_week: str = '',
                              start_date: str = '', end_date: str = '', is_general: int = 1, classes: str = '', is_active: int = 1) -> int:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                '''
                INSERT INTO activity_schedules (activity_id, start_time, end_time, days_of_week, start_date, end_date, is_general, classes, is_active, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ''',
                (
                    int(activity_id or 0),
                    (str(start_time or '').strip() if str(start_time or '').strip() else None),
                    (str(end_time or '').strip() if str(end_time or '').strip() else None),
                    (str(days_of_week or '').strip() if str(days_of_week or '').strip() else None),
                    (str(start_date or '').strip() if str(start_date or '').strip() else None),
                    (str(end_date or '').strip() if str(end_date or '').strip() else None),
                    int(is_general or 0),
                    (str(classes or '').strip() if str(classes or '').strip() else None),
                    int(is_active or 0),
                )
            )
            sid = cursor.lastrowid
            conn.commit()
            return int(sid or 0)
        finally:
            conn.close()

    def update_activity_schedule(self, schedule_id: int, *, start_time: str = '', end_time: str = '', days_of_week: str = '',
                                 start_date: str = '', end_date: str = '', is_general: int = 1, classes: str = '', is_active: int = 1) -> bool:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                '''
                UPDATE activity_schedules
                   SET start_time = ?,
                       end_time = ?,
                       days_of_week = ?,
                       start_date = ?,
                       end_date = ?,
                       is_general = ?,
                       classes = ?,
                       is_active = ?,
                       updated_at = CURRENT_TIMESTAMP
                 WHERE id = ?
                ''',
                (
                    (str(start_time or '').strip() if str(start_time or '').strip() else None),
                    (str(end_time or '').strip() if str(end_time or '').strip() else None),
                    (str(days_of_week or '').strip() if str(days_of_week or '').strip() else None),
                    (str(start_date or '').strip() if str(start_date or '').strip() else None),
                    (str(end_date or '').strip() if str(end_date or '').strip() else None),
                    int(is_general or 0),
                    (str(classes or '').strip() if str(classes or '').strip() else None),
                    int(is_active or 0),
                    int(schedule_id or 0),
                )
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def delete_activity_schedule(self, schedule_id: int) -> bool:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('DELETE FROM activity_schedules WHERE id = ?', (int(schedule_id or 0),))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def has_student_claimed_activity_today(self, student_id: int, activity_id: int) -> bool:
        from datetime import date
        d = date.today().isoformat()
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                'SELECT 1 FROM activity_claims WHERE student_id = ? AND activity_id = ? AND claim_date = ? LIMIT 1',
                (int(student_id or 0), int(activity_id or 0), d)
            )
            return bool(cursor.fetchone())
        finally:
            conn.close()

    def record_activity_claim(self, student_id: int, activity_id: int) -> bool:
        from datetime import date
        d = date.today().isoformat()
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                'INSERT INTO activity_claims (activity_id, student_id, claim_date) VALUES (?, ?, ?)',
                (int(activity_id or 0), int(student_id or 0), d)
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def _activity_schedule_applies_to_class(self, sched_row: Dict[str, Any], class_name: Optional[str]) -> bool:
        try:
            is_general_val = sched_row.get('is_general', None)
            is_general = 1
            if is_general_val is not None:
                try:
                    is_general = int(is_general_val)
                except Exception:
                    is_general = 1
            if is_general == 1:
                return True
            if not class_name:
                return False
            classes = self._parse_bonus_classes(sched_row.get('classes'))
            return class_name.strip() in set(classes)
        except Exception:
            return False

    def get_active_activities_now(self, class_name: Optional[str] = None) -> List[Dict[str, Any]]:
        from datetime import datetime, date

        def _weekday_he(dt: datetime) -> str:
            m = {0: 'ב', 1: 'ג', 2: 'ד', 3: 'ה', 4: 'ו', 5: 'ש', 6: 'א'}
            return m.get(int(dt.weekday()), '')

        def _parse_days_of_week(s: Optional[str]) -> set:
            try:
                raw = str(s or '').strip()
            except Exception:
                raw = ''
            if not raw:
                return set()
            raw = raw.replace(';', ',').replace('\u05f3', ',').replace('\u05f4', ',')
            parts = [p.strip() for p in raw.split(',')]
            out = set()
            for p in parts:
                if not p:
                    continue
                p1 = p[0]
                if p1 in set(['א', 'ב', 'ג', 'ד', 'ה', 'ו', 'ש']):
                    out.add(p1)
            return out

        def _time_to_minutes(t: Optional[str]) -> Optional[int]:
            try:
                s = str(t or '').strip()
                if not s:
                    return None
                parts = s.split(':')
                if len(parts) != 2:
                    return None
                hh = int(parts[0])
                mm = int(parts[1])
                if hh < 0 or hh > 23 or mm < 0 or mm > 59:
                    return None
                return hh * 60 + mm
            except Exception:
                return None

        now_dt = datetime.now()
        today_iso = date.today().isoformat()
        cur_min = _time_to_minutes(now_dt.strftime('%H:%M'))
        today_w = _weekday_he(now_dt)

        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT a.*, s.id AS schedule_id, s.start_time, s.end_time, s.days_of_week, s.start_date, s.end_date,
                       s.is_general AS schedule_is_general, s.classes AS schedule_classes
                  FROM activities a
                  JOIN activity_schedules s ON s.activity_id = a.id
                 WHERE a.is_active = 1 AND s.is_active = 1
            ''')
            rows = cursor.fetchall() or []
        finally:
            conn.close()

        out: List[Dict[str, Any]] = []
        for r0 in rows:
            r = dict(r0)
            # date window
            sd = str(r.get('start_date') or '').strip()
            ed = str(r.get('end_date') or '').strip()
            if sd and today_iso < sd:
                continue
            if ed and today_iso > ed:
                continue
            # day-of-week filter
            allowed_days = _parse_days_of_week(r.get('days_of_week'))
            if allowed_days and (today_w not in allowed_days):
                continue
            # time window
            s_min = _time_to_minutes(r.get('start_time'))
            e_min = _time_to_minutes(r.get('end_time'))
            if cur_min is not None and s_min is not None and e_min is not None:
                if cur_min < s_min or cur_min > e_min:
                    continue
            # class filter
            sched_row = {
                'is_general': r.get('schedule_is_general', 1),
                'classes': r.get('schedule_classes', None),
            }
            if class_name is not None and (not self._activity_schedule_applies_to_class(sched_row, class_name)):
                continue
            out.append(r)
        return out

    def add_cashier_responsible(self, student_id: int) -> bool:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('INSERT OR IGNORE INTO cashier_responsibles (student_id) VALUES (?)', (int(student_id or 0),))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def remove_cashier_responsible(self, student_id: int) -> bool:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('DELETE FROM cashier_responsibles WHERE student_id = ?', (int(student_id or 0),))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def is_cashier_responsible(self, student_id: int) -> bool:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT 1 FROM cashier_responsibles WHERE student_id = ? LIMIT 1', (int(student_id or 0),))
            row = cursor.fetchone()
            return bool(row)
        finally:
            conn.close()

    def get_cashier_responsibles(self) -> List[Dict[str, Any]]:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT s.*
                FROM cashier_responsibles r
                JOIN students s ON s.id = r.student_id
                ORDER BY (s.serial_number IS NULL OR s.serial_number = 0), s.serial_number, s.class_name, s.last_name, s.first_name
            ''')
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def delete_product(self, product_id: int) -> bool:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('DELETE FROM products WHERE id = ?', (int(product_id or 0),))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def cashier_purchase(self, *, student_id: int, product_id: int, qty: int = 1,
                         station_type: str = 'cashier') -> Dict[str, Any]:
        """רכישה אטומית: מלאי + (אופציונלי) הורדת נקודות לפי דגל המוצר."""
        qty = int(qty or 1)
        if qty < 1:
            qty = 1

        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            conn.execute('BEGIN IMMEDIATE')

            cursor.execute('SELECT * FROM products WHERE id = ?', (int(product_id or 0),))
            prod_row = cursor.fetchone()
            if not prod_row:
                conn.rollback()
                return {'ok': False, 'error': 'מוצר לא נמצא'}
            prod = dict(prod_row)
            if int(prod.get('is_active', 1) or 0) != 1:
                conn.rollback()
                return {'ok': False, 'error': 'המוצר לא פעיל'}

            price_each = int(prod.get('price_points', 0) or 0)
            deduct = 1 if int(prod.get('deduct_points', 1) or 0) == 1 else 0
            total_points = price_each * qty

            stock_qty = prod.get('stock_qty', None)
            if stock_qty is not None:
                try:
                    stock_qty = int(stock_qty)
                except Exception:
                    stock_qty = None
            if stock_qty is not None and stock_qty < qty:
                conn.rollback()
                return {'ok': False, 'error': 'אין מספיק מלאי'}

            cursor.execute('SELECT * FROM students WHERE id = ?', (int(student_id or 0),))
            stu_row = cursor.fetchone()
            if not stu_row:
                conn.rollback()
                return {'ok': False, 'error': 'תלמיד לא נמצא'}
            stu = dict(stu_row)

            old_points = int(stu.get('points', 0) or 0)
            new_points = old_points
            if deduct == 1:
                if old_points < total_points:
                    conn.rollback()
                    return {'ok': False, 'error': 'אין מספיק נקודות'}
                new_points = old_points - total_points

            if stock_qty is not None:
                cursor.execute(
                    'UPDATE products SET stock_qty = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                    (int(stock_qty - qty), int(product_id or 0))
                )

            if deduct == 1 and new_points != old_points:
                cursor.execute(
                    'UPDATE students SET points = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                    (int(new_points), int(student_id or 0))
                )
                try:
                    cursor.execute(
                        '''
                        INSERT INTO points_log (student_id, old_points, new_points, delta, reason, actor_name, action_type)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        ''',
                        (
                            int(student_id or 0),
                            int(old_points),
                            int(new_points),
                            int(new_points - old_points),
                            f"קניה: {str(prod.get('name') or '').strip()} x{qty}",
                            'cashier',
                            'purchase'
                        )
                    )
                except Exception:
                    pass

            try:
                cursor.execute(
                    '''
                    INSERT INTO purchases_log (student_id, product_id, qty, points_each, total_points, deduct_points, station_type)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''',
                    (int(student_id or 0), int(product_id or 0), int(qty), int(price_each), int(total_points), int(deduct), str(station_type or 'cashier'))
                )
            except Exception:
                pass

            conn.commit()
            return {
                'ok': True,
                'student_id': int(student_id or 0),
                'product_id': int(product_id or 0),
                'product_name': str(prod.get('name') or '').strip(),
                'qty': int(qty),
                'price_each': int(price_each),
                'total_points': int(total_points),
                'deduct_points': int(deduct),
                'old_points': int(old_points),
                'new_points': int(new_points),
                'stock_left': None if stock_qty is None else int(stock_qty - qty),
            }
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            return {'ok': False, 'error': str(e)}
        finally:
            conn.close()

    def has_student_received_time_bonus_group_today(self, student_id: int, group_name: str) -> bool:
        """בדיקה אם תלמיד כבר קיבל היום בונוס כלשהו מקבוצת בונוס זמנים."""
        from datetime import date

        if not group_name:
            return False

        today = date.today().isoformat()

        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT COUNT(*) as count
            FROM time_bonus_given g
            JOIN time_bonus_schedules s ON s.id = g.bonus_schedule_id
            WHERE g.student_id = ?
              AND g.given_date = ?
              AND COALESCE(s.group_name, s.name) = ?
        ''', (student_id, today, group_name))

        row = cursor.fetchone()
        conn.close()
        return (row and row['count'] > 0)

    def get_time_bonus_group_given_count_today(self, group_name: str) -> int:
        """כמה תלמידים קיבלו היום בונוס כלשהו מקבוצת בונוס זמנים (לכל תלמידים)."""
        from datetime import date

        if not group_name:
            return 0

        today = date.today().isoformat()

        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT COUNT(*) as count
                FROM time_bonus_given g
                JOIN time_bonus_schedules s ON s.id = g.bonus_schedule_id
                WHERE g.given_date = ?
                  AND COALESCE(s.group_name, s.name) = ?
            ''', (today, group_name))
            row = cursor.fetchone()
            return int(row['count'] if row else 0)
        except Exception:
            return 0
        finally:
            conn.close()

    def get_time_bonus_group_given_count_today_for_class(self, group_name: str, class_name: str) -> int:
        """כמה תלמידים מכיתה מסוימת קיבלו היום בונוס מקבוצת בונוס זמנים."""
        from datetime import date

        if not group_name or not class_name:
            return 0

        today = date.today().isoformat()

        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT COUNT(*) as count
                FROM time_bonus_given g
                JOIN time_bonus_schedules s ON s.id = g.bonus_schedule_id
                JOIN students st ON st.id = g.student_id
                WHERE g.given_date = ?
                  AND COALESCE(s.group_name, s.name) = ?
                  AND COALESCE(st.class_name, '') = ?
            ''', (today, group_name, class_name))
            row = cursor.fetchone()
            return int(row['count'] if row else 0)
        except Exception:
            return 0
        finally:
            conn.close()

    def has_anyone_received_time_bonus_group_today(self, group_name: str) -> bool:
        """בדיקה אם כבר ניתן היום בונוס כלשהו מקבוצת בונוס זמנים (לכל תלמיד)."""
        from datetime import date

        if not group_name:
            return False

        today = date.today().isoformat()

        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT COUNT(*) as count
            FROM time_bonus_given g
            JOIN time_bonus_schedules s ON s.id = g.bonus_schedule_id
            WHERE g.given_date = ?
              AND COALESCE(s.group_name, s.name) = ?
        ''', (today, group_name))

        row = cursor.fetchone()
        conn.close()
        return (row and row['count'] > 0)
    
    def get_student_by_id(self, student_id: int) -> Optional[Dict[str, Any]]:
        """שליפת פרטי תלמיד לפי מזהה"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM students WHERE id = ?', (student_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return dict(row)
        return None
    
    def set_student_free_fix_blocked(self, student_id: int, is_blocked: bool) -> bool:
        """חסימה או ביטול חסימה של תיקופים חינם לתלמיד"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                UPDATE students
                SET is_free_fix_blocked = ?
                WHERE id = ?
            ''', (1 if is_blocked else 0, student_id))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"שגיאה בעדכון חסימת תיקופים חינם: {e}")
            conn.close()
            return False
    
    def is_student_free_fix_blocked(self, student_id: int) -> bool:
        """בדיקה האם תלמיד חסום מתיקופים חינם"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT is_free_fix_blocked FROM students WHERE id = ?', (student_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row and row['is_free_fix_blocked']:
            return True
        return False
    
    def log_card_validation(self, student_id: int, card_number: str) -> bool:
        """רישום תיקוף כרטיס (למעקב אחר ספאם)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO card_validations (student_id, card_number)
                VALUES (?, ?)
            ''', (student_id, card_number))
            try:
                self._log_change(
                    cursor,
                    entity_type='card_validation',
                    entity_id=str(student_id or ''),
                    action_type='insert',
                    payload={'student_id': student_id, 'card_number': card_number}
                )
            except Exception:
                pass
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"שגיאה ברישום תיקוף כרטיס: {e}")
            conn.close()
            return False

    def _log_change(self, cursor, *, entity_type: str, entity_id: str, action_type: str, payload: Optional[Dict[str, Any]] = None) -> None:
        try:
            payload_json = json.dumps(payload or {}, ensure_ascii=False)
        except Exception:
            payload_json = '{}'
        try:
            cursor.execute(
                '''
                INSERT INTO change_log (entity_type, entity_id, action_type, payload_json)
                VALUES (?, ?, ?, ?)
                ''',
                (str(entity_type or ''), str(entity_id or ''), str(action_type or ''), payload_json)
            )
        except Exception:
            pass
    
    def get_recent_validations_count(self, student_id: int, minutes: int = 1) -> int:
        """ספירת תיקופים של תלמיד בדקות האחרונות"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT COUNT(*) as count
            FROM card_validations
            WHERE student_id = ?
            AND validated_at >= datetime('now', '-' || ? || ' minutes')
        ''', (student_id, minutes))
        
        row = cursor.fetchone()
        conn.close()
        return row['count'] if row else 0
    
    def is_card_blocked(self, student_id: int) -> tuple:
        """בדיקה האם כרטיס חסום כרגע
        
        Returns:
            (is_blocked, block_end_time, reason)
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT block_end, block_reason
            FROM card_blocks
            WHERE student_id = ?
            AND block_end > datetime('now')
            ORDER BY block_end DESC
            LIMIT 1
        ''', (student_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return True, row['block_end'], row['block_reason']
        return False, None, None
    
    def block_card(self, student_id: int, card_number: str, duration_minutes: int, 
                   reason: str = "ניצול יתר של המערכת", violation_count: int = 1) -> bool:
        """חסימת כרטיס לפרק זמן מסוים"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO card_blocks 
                (student_id, card_number, block_start, block_end, block_reason, violation_count)
                VALUES (?, ?, datetime('now'), datetime('now', '+' || ? || ' minutes'), ?, ?)
            ''', (student_id, card_number, duration_minutes, reason, violation_count))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"שגיאה בחסימת כרטיס: {e}")
            conn.close()
            return False
    
    def unblock_card(self, student_id: int) -> bool:
        """ביטול חסימת כרטיס (ע"י מנהל)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                UPDATE card_blocks
                SET block_end = datetime('now')
                WHERE student_id = ?
                AND block_end > datetime('now')
            ''', (student_id,))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"שגיאה בביטול חסימת כרטיס: {e}")
            conn.close()
            return False
    
    def get_violation_count(self, student_id: int) -> int:
        """קבלת מספר העבירות של תלמיד (כמה פעמים נחסם)"""
        try:
            student_id = int(student_id or 0)
        except Exception:
            student_id = 0
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT COALESCE(MAX(violation_count), 0) as count
            FROM card_blocks
            WHERE student_id = ?
        ''', (student_id,))
        
        row = cursor.fetchone()
        conn.close()
        return row['count'] if row else 0
    
    def clear_old_validations(self, hours: int = 24) -> bool:
        """ניקוי תיקופים ישנים (תחזוקה)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                DELETE FROM card_validations
                WHERE validated_at < datetime('now', '-' || ? || ' hours')
            ''', (hours,))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"שגיאה בניקוי תיקופים ישנים: {e}")
            conn.close()
            return False

    def log_anti_spam_event(self, *, student_id: int, card_number: str, event_type: str,
                            rule_count: Optional[int] = None, rule_minutes: Optional[int] = None,
                            duration_minutes: Optional[int] = None, recent_count: Optional[int] = None,
                            message: str = '') -> bool:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                '''
                INSERT INTO anti_spam_events
                    (student_id, card_number, event_type, rule_count, rule_minutes, duration_minutes, recent_count, message)
                VALUES
                    (?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    int(student_id or 0),
                    str(card_number or '').strip(),
                    str(event_type or '').strip(),
                    rule_count,
                    rule_minutes,
                    duration_minutes,
                    recent_count,
                    str(message or ''),
                )
            )
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"שגיאה ברישום אירוע אנטי-ספאם: {e}")
            conn.close()
            return False

    def get_recent_anti_spam_events_report(self, *, days: int = 7, event_types: Optional[List[str]] = None,
                                          limit: int = 5000) -> List[Dict[str, Any]]:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            try:
                dd = int(days or 0)
            except Exception:
                dd = 7
            if dd <= 0:
                dd = 7

            et = []
            if isinstance(event_types, list) and event_types:
                for x in event_types:
                    s = str(x or '').strip().lower()
                    if s:
                        et.append(s)
            if not et:
                et = ['warning', 'block']

            placeholders = ','.join(['?'] * len(et))
            cursor.execute(
                f'''
                SELECT
                    e.created_at,
                    e.event_type,
                    e.student_id,
                    e.card_number,
                    e.rule_count,
                    e.rule_minutes,
                    e.duration_minutes,
                    e.recent_count,
                    e.message,
                    s.first_name,
                    s.last_name,
                    s.class_name
                FROM anti_spam_events e
                LEFT JOIN students s ON s.id = e.student_id
                WHERE e.created_at >= datetime('now', '-' || ? || ' days')
                  AND LOWER(COALESCE(e.event_type,'')) IN ({placeholders})
                ORDER BY e.created_at DESC
                LIMIT ?
                ''',
                [int(dd)] + list(et) + [int(limit or 5000)]
            )
            rows = cursor.fetchall() or []
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_recent_card_blocks_report(self, *, days: int = 7, limit: int = 5000) -> List[Dict[str, Any]]:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            try:
                dd = int(days or 0)
            except Exception:
                dd = 7
            if dd <= 0:
                dd = 7
            cursor.execute(
                '''
                SELECT
                    b.block_start AS created_at,
                    b.block_end,
                    b.student_id,
                    b.card_number,
                    b.block_reason,
                    b.violation_count,
                    s.first_name,
                    s.last_name,
                    s.class_name
                FROM card_blocks b
                LEFT JOIN students s ON s.id = b.student_id
                WHERE b.block_start >= datetime('now', '-' || ? || ' days')
                ORDER BY b.block_start DESC
                LIMIT ?
                ''',
                (int(dd), int(limit or 5000))
            )
            rows = cursor.fetchall() or []
            out: List[Dict[str, Any]] = []
            for r in rows:
                d = dict(r)
                d['event_type'] = 'block'
                d['message'] = d.get('block_reason')
                out.append(d)
            return out
        finally:
            conn.close()
    
    def get_all_students(self) -> List[Dict[str, Any]]:
        """שליפת כל התלמידים"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM students ORDER BY (serial_number IS NULL OR serial_number = 0), serial_number, last_name, first_name')
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]

    def get_max_student_points(self) -> int:
        """קבלת מקסימום נקודות קיים במאגר התלמידים"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT MAX(points) as max_points FROM students')
            row = cursor.fetchone()
            try:
                if row and row['max_points'] is not None:
                    return int(row['max_points'])
            except Exception:
                pass
            return 0
        finally:
            conn.close()

    def get_max_student_points_by_class(self, class_name: str) -> int:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cn = str(class_name or '').strip()
            if not cn:
                return 0
            cursor.execute('SELECT MAX(points) as max_points FROM students WHERE TRIM(COALESCE(class_name, \'\')) = ?', (cn,))
            row = cursor.fetchone()
            try:
                if row and row['max_points'] is not None:
                    return int(row['max_points'])
            except Exception:
                pass
            return 0
        finally:
            conn.close()
    
    def set_teacher_bonus_limits(self, teacher_id: int,
                                 max_points_per_student: Optional[int],
                                 max_total_runs: Optional[int]) -> bool:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                UPDATE teachers
                SET bonus_max_points_per_student = ?,
                    bonus_max_total_runs = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (max_points_per_student, max_total_runs, teacher_id))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            conn.close()
            print(f"שגיאה בעדכון הגבלת בונוס למורה: {e}")
            return False
    
    def update_student_points(self, student_id: int, points: int, 
                            reason: str = "", added_by: str = "") -> bool:
        """עדכון נקודות תלמיד"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            # אכיפה בסיסית של "מקסימום נקודות" ברמת DB
            # (בזרימות לא-אינטראקטיביות, כמו העמדה הציבורית, אין חלון אישור)
            try:
                ev = self.evaluate_points_against_max(proposed_points=int(points))
                pol = str(ev.get('policy') or 'none').strip().lower()
                st = str(ev.get('status') or 'ok').strip().lower()
                if pol == 'block' and st == 'exceed':
                    try:
                        conn.close()
                    except Exception:
                        pass
                    return False
            except Exception:
                # לא חוסמים עדכון נקודות בגלל כשל בחישוב
                pass

            # שליפת הנקודות הקודמות
            cursor.execute('SELECT points FROM students WHERE id = ?', (student_id,))
            row = cursor.fetchone()
            old_points = row[0] if row else 0
            
            # עדכון הנקודות
            cursor.execute('''
                UPDATE students 
                SET points = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (points, student_id))
            
            # רישום בהיסטוריה
            points_diff = points - old_points
            cursor.execute('''
                INSERT INTO points_history (student_id, points_added, reason, added_by)
                VALUES (?, ?, ?, ?)
            ''', (student_id, points_diff, reason, added_by))

            # רישום בלוג מפורט (points_log)
            # action_type נגזר מהסיבה/מבצע, כדי לא לדרוש שינוי בכל מקום שקורא לפונקציה
            try:
                reason_s = str(reason or '').strip()
                actor_s = str(added_by or '').strip()
                action_type = ''

                # מזהה האם המבצע הוא מנהל (לפי טבלת המורים) גם כששומרים שם משתמש אמיתי
                is_admin_actor = False
                try:
                    if actor_s == 'מנהל':
                        is_admin_actor = True
                    elif actor_s:
                        if not hasattr(self, '_actor_is_admin_cache'):
                            self._actor_is_admin_cache = {}
                        cache = getattr(self, '_actor_is_admin_cache', {})
                        if actor_s in cache:
                            is_admin_actor = bool(cache.get(actor_s))
                        else:
                            try:
                                cursor.execute('SELECT is_admin FROM teachers WHERE name = ? LIMIT 1', (actor_s,))
                                rr = cursor.fetchone()
                                is_admin_actor = bool(rr and int(rr['is_admin'] or 0) == 1)
                            except Exception:
                                is_admin_actor = False
                            try:
                                cache[actor_s] = bool(is_admin_actor)
                                self._actor_is_admin_cache = cache
                            except Exception:
                                pass
                except Exception:
                    is_admin_actor = False

                if 'בונוס זמנים' in reason_s or reason_s.startswith('⏰'):
                    action_type = 'בונוס זמנים'
                elif 'בונוס מורה' in reason_s or reason_s.startswith('🎁'):
                    action_type = 'בונוס מורה'
                elif 'בונוס מיוחד' in reason_s or 'מאסטר' in reason_s:
                    # זה בונוס שמופעל ע"י מנהל (בפועל דרך העמדה הציבורית)
                    action_type = 'בונוס מנהל'
                elif 'בונוס' in reason_s and is_admin_actor:
                    action_type = 'בונוס מנהל'
                elif 'עדכון מהיר' in reason_s:
                    action_type = 'עדכון מהיר'
                elif 'סנכרון מ-Excel' in reason_s or 'ייבוא מ-Excel' in reason_s:
                    action_type = 'Excel'
                elif reason_s in ('UNDO', 'REDO') or reason_s.startswith('UNDO') or reason_s.startswith('REDO'):
                    action_type = 'ביטול/שחזור'
                else:
                    if is_admin_actor:
                        action_type = 'מנהל'
                    elif actor_s == 'מערכת':
                        action_type = 'מערכת'
                    elif actor_s:
                        action_type = 'מורה'
                    else:
                        action_type = ''

                cursor.execute('''
                    INSERT INTO points_log (student_id, old_points, new_points, delta, reason, actor_name, action_type)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (int(student_id), int(old_points), int(points), int(points_diff), reason_s, actor_s, str(action_type)))
            except Exception:
                pass
            try:
                self._log_change(
                    cursor,
                    entity_type='student_points',
                    entity_id=str(student_id or ''),
                    action_type='update',
                    payload={
                        'old_points': int(old_points),
                        'new_points': int(points),
                        'reason': str(reason or '').strip(),
                        'added_by': str(added_by or '').strip()
                    }
                )
            except Exception:
                pass
            # לא מפילים עדכון נקודות בגלל לוג
            pass
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            conn.close()
            print(f"שגיאה בעדכון נקודות: {e}")
            return False

    def get_points_log_for_student(self, student_id: int) -> list:
        """שליפת היסטוריית נקודות מפורטת לתלמיד אחד (לייצוא)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT id,
                       student_id,
                       old_points,
                       new_points,
                       delta,
                       reason,
                       actor_name,
                       action_type,
                       datetime(created_at, 'localtime') AS created_at
                  FROM points_log
                 WHERE student_id = ?
                 ORDER BY datetime(created_at) ASC, id ASC
            ''', (int(student_id),))
            rows = cursor.fetchall() or []
            out = [dict(r) for r in rows]

            sig_points_log = set()
            try:
                for r in out:
                    ts = str(r.get('created_at') or '').strip()
                    try:
                        delta_v = int(r.get('delta') or 0)
                    except Exception:
                        delta_v = 0
                    rs = str(r.get('reason') or '').strip()
                    an = str(r.get('actor_name') or '').strip()
                    if ts:
                        sig_points_log.add((ts, delta_v, rs, an))
            except Exception:
                sig_points_log = set()

            # legacy points_history (older DBs / older app versions)
            cursor.execute('''
                SELECT id,
                       student_id,
                       points_added AS delta,
                       reason,
                       added_by AS actor_name,
                       '' AS action_type,
                       datetime(added_at, 'localtime') AS created_at
                  FROM points_history
                 WHERE student_id = ?
                 ORDER BY datetime(added_at) ASC, id ASC
            ''', (int(student_id),))
            rows2 = cursor.fetchall() or []

            def _infer_action_type(reason: str, actor_name: str) -> str:
                try:
                    rs = str(reason or '').strip()
                    an = str(actor_name or '').strip()
                except Exception:
                    rs = ''
                    an = ''

                is_admin_actor = False
                try:
                    if an == 'מנהל':
                        is_admin_actor = True
                    elif an:
                        if not hasattr(self, '_actor_is_admin_cache'):
                            self._actor_is_admin_cache = {}
                        cache = getattr(self, '_actor_is_admin_cache', {})
                        if an in cache:
                            is_admin_actor = bool(cache.get(an))
                        else:
                            try:
                                cursor.execute('SELECT is_admin FROM teachers WHERE name = ? LIMIT 1', (an,))
                                rr = cursor.fetchone()
                                is_admin_actor = bool(rr and int(rr['is_admin'] or 0) == 1)
                            except Exception:
                                is_admin_actor = False
                            try:
                                cache[an] = bool(is_admin_actor)
                                self._actor_is_admin_cache = cache
                            except Exception:
                                pass
                except Exception:
                    is_admin_actor = False

                if 'בונוס זמנים' in rs or rs.startswith('⏰'):
                    return 'בונוס זמנים'
                if 'בונוס מורה' in rs or rs.startswith('🎁'):
                    return 'בונוס מורה'
                if 'בונוס מיוחד' in rs or 'מאסטר' in rs:
                    return 'בונוס מנהל'
                if 'בונוס' in rs and is_admin_actor:
                    return 'בונוס מנהל'
                if 'עדכון מהיר' in rs:
                    return 'עדכון מהיר'
                if 'סנכרון מ-Excel' in rs or 'ייבוא מ-Excel' in rs:
                    return 'Excel'
                if rs in ('UNDO', 'REDO') or rs.startswith('UNDO') or rs.startswith('REDO'):
                    return 'ביטול/שחזור'
                if is_admin_actor:
                    return 'מנהל'
                if an == 'מערכת':
                    return 'מערכת'
                if an:
                    return 'מורה'
                return ''

            out2 = []
            for r in rows2:
                d = dict(r)
                d['old_points'] = None
                d['new_points'] = None
                try:
                    d['delta'] = int(d.get('delta') or 0)
                except Exception:
                    d['delta'] = 0
                try:
                    ts2 = str(d.get('created_at') or '').strip()
                    rs2 = str(d.get('reason') or '').strip()
                    an2 = str(d.get('actor_name') or '').strip()
                    if ts2 and (ts2, int(d.get('delta') or 0), rs2, an2) in sig_points_log:
                        continue
                except Exception:
                    pass
                try:
                    if not str(d.get('action_type') or '').strip():
                        d['action_type'] = _infer_action_type(d.get('reason'), d.get('actor_name'))
                except Exception:
                    pass
                out2.append(d)

            # merge & sort by timestamp
            merged = []
            for d in (out or []):
                d['_src'] = 'points_log'
                merged.append(d)
            for d in (out2 or []):
                d['_src'] = 'points_history'
                merged.append(d)

            def _sort_key(x: dict):
                ts = str(x.get('created_at') or '').strip()
                src = str(x.get('_src') or '')
                try:
                    xid = int(x.get('id') or 0)
                except Exception:
                    xid = 0
                return (ts, 0 if src == 'points_history' else 1, xid)

            merged.sort(key=_sort_key)
            for d in merged:
                try:
                    d.pop('_src', None)
                except Exception:
                    pass
            return merged
        except Exception:
            return []
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def get_daily_points_summary_matrix(self, *, allowed_classes: Optional[List[str]] = None) -> Tuple[List[Dict[str, Any]], List[str]]:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            where_students = ''
            params_students: List[Any] = []
            allowed = [str(c).strip() for c in (allowed_classes or []) if str(c).strip()]
            if allowed:
                where_students = ' WHERE class_name IN (' + ','.join(['?'] * len(allowed)) + ')'
                params_students = list(allowed)

            cursor.execute(
                f'''
                SELECT id, serial_number, class_name, first_name, last_name
                  FROM students
                  {where_students}
                 ORDER BY class_name, last_name, first_name, serial_number, id
                ''',
                tuple(params_students)
            )
            students = [dict(r) for r in (cursor.fetchall() or [])]

            join_students = ''
            where_log = ''
            params_log: List[Any] = []
            if allowed:
                join_students = ' JOIN students s ON s.id = pl.student_id '
                where_log = ' WHERE s.class_name IN (' + ','.join(['?'] * len(allowed)) + ') '
                params_log = list(allowed)

            sql = (
                'SELECT pl.student_id AS student_id, '
                "date(datetime(pl.created_at, 'localtime')) AS day, "
                'SUM(pl.delta) AS delta_sum, '
                'COUNT(*) AS cnt '
                'FROM points_log pl '
                + str(join_students or '')
                + str(where_log or '')
                + 'GROUP BY pl.student_id, day '
                + 'ORDER BY day ASC'
            )
            cursor.execute(sql, tuple(params_log))
            rows = [dict(r) for r in (cursor.fetchall() or [])]

            day_set: set = set()
            by_student_day: Dict[int, Dict[str, int]] = {}
            has_row: set = set()
            for r in rows:
                try:
                    sid = int(r.get('student_id') or 0)
                except Exception:
                    sid = 0
                day = str(r.get('day') or '').strip()
                try:
                    cnt = int(r.get('cnt') or 0)
                except Exception:
                    cnt = 0
                try:
                    delta_sum = int(r.get('delta_sum') or 0)
                except Exception:
                    delta_sum = 0
                if sid <= 0 or not day or cnt <= 0:
                    continue
                day_set.add(day)
                by_student_day.setdefault(sid, {})[day] = int(delta_sum)
                has_row.add((sid, day))

            days = sorted(day_set)

            def _fmt_day(d: str) -> str:
                try:
                    y, m, dd = d.split('-', 2)
                    yy = str(y)[-2:]
                    return f"{int(dd)}.{int(m)}.{yy}"
                except Exception:
                    return d

            headers = [_fmt_day(d) for d in days]

            out_rows: List[Dict[str, Any]] = []
            for s in students:
                sid = int(s.get('id') or 0)
                base = {
                    "מס' סידורי": s.get('serial_number') if s.get('serial_number') is not None else '',
                    'שם משפחה': str(s.get('last_name') or '').strip(),
                    'שם פרטי': str(s.get('first_name') or '').strip(),
                    'כיתה': str(s.get('class_name') or '').strip(),
                }
                m = by_student_day.get(sid, {})
                for iso_day, hdr in zip(days, headers):
                    if (sid, iso_day) not in has_row:
                        base[hdr] = ''
                    else:
                        base[hdr] = int(m.get(iso_day) or 0)
                out_rows.append(base)

            return out_rows, headers
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def get_points_log_for_actor(self, actor_name: str, *, limit: int = 20000) -> List[Dict[str, Any]]:
        """שליפת לוג פעולות (points_log) לפי מבצע (actor_name) – מי ביצע פעולות על נקודות.

        מחזיר גם פרטי תלמיד (שם/כיתה/מס' סידורי) כדי לאפשר ייצוא פעולות מורה.
        """
        actor = str(actor_name or '').strip()
        if not actor:
            return []
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                '''
                SELECT pl.id,
                       datetime(pl.created_at, 'localtime') AS created_at,
                       pl.actor_name,
                       pl.action_type,
                       pl.reason,
                       pl.student_id,
                       pl.old_points,
                       pl.new_points,
                       pl.delta,
                       s.serial_number,
                       s.class_name,
                       s.first_name,
                       s.last_name
                  FROM points_log pl
                  LEFT JOIN students s ON s.id = pl.student_id
                 WHERE pl.actor_name = ?
                 ORDER BY datetime(pl.created_at) DESC, pl.id DESC
                 LIMIT ?
                ''',
                (actor, int(limit or 0))
            )
            rows = cursor.fetchall() or []
            return [dict(r) for r in rows]
        except Exception:
            return []
        finally:
            try:
                conn.close()
            except Exception:
                pass
    
    def add_points(self, student_id: int, points_to_add: int, 
                   reason: str = "", added_by: str = "") -> bool:
        """הוספת נקודות לתלמיד"""
        student = self.get_student_by_id(student_id)
        if student:
            new_points = student['points'] + points_to_add
            return self.update_student_points(student_id, new_points, reason, added_by)
        return False
    
    def subtract_points(self, student_id: int, points_to_subtract: int, 
                       reason: str = "", added_by: str = "") -> bool:
        """חיסור נקודות מתלמיד"""
        student = self.get_student_by_id(student_id)
        if student:
            new_points = max(0, student['points'] - points_to_subtract)  # לא לרדת מתחת ל-0
            return self.update_student_points(student_id, new_points, reason, added_by)
        return False
    
    def update_card_number(self, student_id: int, card_number: str) -> bool:
        """עדכון מספר כרטיס לתלמיד"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                UPDATE students 
                SET card_number = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (card_number, student_id))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            conn.close()
            print(f"שגיאה בעדכון כרטיס: {e}")
            return False
    
    def update_photo_number(self, student_id: int, photo_number: str) -> bool:
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                UPDATE students 
                SET photo_number = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (photo_number if photo_number else None, student_id))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            conn.close()
            print(f"שגיאה בעדכון תמונה: {e}")
            return False

    def update_serial_number(self, student_id: int, serial_number: Optional[int]) -> bool:
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                UPDATE students 
                SET serial_number = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (serial_number, student_id))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            conn.close()
            print(f"שגיאה בעדכון מס' סידורי: {e}")
            return False
    
    def update_private_message(self, student_id: int, message: str) -> bool:
        """עדכון הודעה פרטית לתלמיד"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                UPDATE students 
                SET private_message = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (message if message else None, student_id))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            conn.close()
            print(f"שגיאה בעדכון הודעה: {e}")
            return False
    
    def search_students(self, search_term: str) -> List[Dict[str, Any]]:
        """חיפוש תלמידים לפי שם או ת"ז"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        search_pattern = f"%{search_term}%"
        cursor.execute('''
            SELECT * FROM students 
            WHERE last_name LIKE ? 
               OR first_name LIKE ? 
               OR id_number LIKE ?
               OR card_number LIKE ?
            ORDER BY (serial_number IS NULL OR serial_number = 0), serial_number, last_name, first_name
        ''', (search_pattern, search_pattern, search_pattern, search_pattern))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def clear_all_students(self):
        """מחיקת כל התלמידים (לשימוש בייבוא מחדש)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM students')
        cursor.execute('DELETE FROM points_history')
        cursor.execute('DELETE FROM swipe_log')
        
        conn.commit()
        conn.close()

    def delete_student(self, student_id: int) -> bool:
        """מחיקת תלמיד יחיד וכל ההיסטוריה שלו."""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute('DELETE FROM points_history WHERE student_id = ?', (student_id,))
            cursor.execute('DELETE FROM swipe_log WHERE student_id = ?', (student_id,))
            cursor.execute('DELETE FROM students WHERE id = ?', (student_id,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            conn.close()
            print(f"שגיאה במחיקת תלמיד: {e}")
            return False

    def log_swipe(self, student_id: int, card_number: str = "", station_type: str = "public") -> bool:
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO swipe_log (student_id, card_number, station_type)
                VALUES (?, ?, ?)
            ''', (student_id, card_number if card_number else None, station_type))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            conn.close()
            print(f"שגיאה ברישום תיקוף: {e}")
            return False


    def get_swipe_count_for_student(self, student_id: int, station_type: Optional[str] = None) -> int:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            if station_type:
                cursor.execute(
                    'SELECT COUNT(*) FROM swipe_log WHERE student_id = ? AND station_type = ?',
                    (int(student_id), str(station_type))
                )
            else:
                cursor.execute(
                    'SELECT COUNT(*) FROM swipe_log WHERE student_id = ?',
                    (int(student_id),)
                )
            row = cursor.fetchone()
            if row:
                try:
                    return int(row[0] or 0)
                except Exception:
                    return 0
            return 0
        except Exception:
            return 0
        finally:
            conn.close()

    def get_student_tier_index(self, student_id: int) -> Optional[int]:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT last_tier_index FROM student_tier_state WHERE student_id = ?', (int(student_id),))
            row = cursor.fetchone()
            if not row:
                return None
            try:
                return int(row[0]) if row[0] is not None else None
            except Exception:
                return None
        except Exception:
            return None
        finally:
            conn.close()

    def set_student_tier_index(self, student_id: int, tier_index: int) -> bool:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                '''
                INSERT INTO student_tier_state (student_id, last_tier_index, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(student_id) DO UPDATE SET
                    last_tier_index = excluded.last_tier_index,
                    updated_at = CURRENT_TIMESTAMP
                ''',
                (int(student_id), int(tier_index))
            )
            conn.commit()
            return True
        except Exception:
            return False
        finally:
            conn.close()

    def insert_swipe(self, student_id: int, swiped_at: str = None,
                     card_number: str = "", station_type: str = "public") -> bool:
        """הוספת רשומת תיקוף עם תאריך/שעה מפורשים (לשימוש בייבוא).

        swiped_at בפורמט ISO "YYYY-MM-DD HH:MM:SS". אם לא יינתן, ישמש הערך
        הדיפולטי של מסד הנתונים (CURRENT_TIMESTAMP).
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            if swiped_at:
                cursor.execute('''
                    INSERT INTO swipe_log (student_id, card_number, station_type, swiped_at)
                    VALUES (?, ?, ?, ?)
                ''', (student_id, card_number if card_number else None, station_type, swiped_at))
            else:
                cursor.execute('''
                    INSERT INTO swipe_log (student_id, card_number, station_type)
                    VALUES (?, ?, ?)
                ''', (student_id, card_number if card_number else None, station_type))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            conn.close()
            print(f"שגיאה ברישום תיקוף (ייבוא): {e}")
            return False

    def upsert_first_swipe_for_date(self, student_id: int, swiped_at: str,
                                    card_number: str = "", station_type: str = "public") -> bool:
        if not swiped_at:
            return False
        date_part = str(swiped_at)[:10]
        if len(date_part) != 10:
            return False

        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            conn.execute('BEGIN IMMEDIATE')
            cursor.execute('''
                SELECT id
                FROM swipe_log
                WHERE student_id = ?
                  AND station_type = ?
                  AND DATE(swiped_at) = ?
                ORDER BY swiped_at ASC, id ASC
                LIMIT 1
            ''', (int(student_id or 0), str(station_type or 'public'), str(date_part)))
            row = cursor.fetchone()

            # If there is already a swipe that day, only overwrite the FIRST swipe when the new time is earlier.
            if row and row['id'] is not None:
                cursor.execute('SELECT swiped_at FROM swipe_log WHERE id = ? LIMIT 1', (int(row['id']),))
                r2 = cursor.fetchone()
                try:
                    existing_swiped_at = str((r2['swiped_at'] if isinstance(r2, sqlite3.Row) else r2[0]) or '') if r2 else ''
                except Exception:
                    try:
                        existing_swiped_at = str(r2[0] or '') if r2 else ''
                    except Exception:
                        existing_swiped_at = ''
                if existing_swiped_at and str(swiped_at) >= existing_swiped_at:
                    conn.commit()
                    return True

            if row and row['id'] is not None:
                cursor.execute('''
                    UPDATE swipe_log
                    SET swiped_at = ?, card_number = COALESCE(?, card_number)
                    WHERE id = ?
                ''', (str(swiped_at), (card_number if card_number else None), int(row['id'])))
            else:
                cursor.execute('''
                    INSERT INTO swipe_log (student_id, card_number, station_type, swiped_at)
                    VALUES (?, ?, ?, ?)
                ''', (int(student_id or 0), (card_number if card_number else None), str(station_type or 'public'), str(swiped_at)))

            conn.commit()
            return True
        except Exception as e:
            try:
                conn.rollback()
            except Exception:
                pass
            print(f"שגיאה בדריסת תיקוף ראשון לתאריך: {e}")
            return False
        finally:
            conn.close()

    def get_total_school_days(self, station_type: str = "public") -> int:
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT COUNT(DISTINCT DATE(swiped_at)) AS days
            FROM swipe_log
            WHERE station_type = ? AND strftime('%w', swiped_at) != '6'
        ''', (station_type,))
        row = cursor.fetchone()
        conn.close()
        
        if row and row[0] is not None:
            return int(row[0])
        return 0

    def get_swipe_totals_for_students(self, student_ids: List[int], station_type: str = "public") -> Dict[int, int]:
        if not student_ids:
            return {}
        
        conn = self.get_connection()
        cursor = conn.cursor()
        
        placeholders = ','.join('?' * len(student_ids))
        params = list(student_ids) + [station_type]
        cursor.execute(f'''
            SELECT student_id, COUNT(*) AS total_swipes
            FROM swipe_log
            WHERE student_id IN ({placeholders})
              AND station_type = ?
              AND strftime('%w', swiped_at) != '6'
            GROUP BY student_id
        ''', params)
        rows = cursor.fetchall()
        conn.close()
        
        totals: Dict[int, int] = {}
        for row in rows:
            totals[row['student_id']] = row['total_swipes']
        return totals
    
    # ===== הגדרות =====
    
    def get_setting(self, key: str, default: str = None) -> str:
        """קבלת ערך הגדרה"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT value FROM settings WHERE key = ?', (key,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return row['value']
        return default
    
    def set_setting(self, key: str, value: str):
        """עדכון הגדרה"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO settings (key, value, updated_at) 
            VALUES (?, ?, CURRENT_TIMESTAMP)
        ''', (key, value))

        try:
            self._log_change(
                cursor,
                entity_type='setting',
                entity_id=str(key or ''),
                action_type='update',
                payload={'key': str(key or ''), 'value': str(value or '')}
            )
        except Exception:
            pass
        
        conn.commit()
        conn.close()
    
    # ===== סטטיסטיקות =====
    
    def get_class_average(self, class_name: str) -> float:
        """חישוב ממוצע נקודות לכיתה"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT AVG(points) as average 
            FROM students 
            WHERE class_name = ? AND class_name IS NOT NULL AND class_name != ''
        ''', (class_name,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row and row['average'] is not None:
            return round(row['average'], 1)
        return 0.0
    
    def get_overall_average(self) -> float:
        """חישוב ממוצע נקודות כללי"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT AVG(points) as average FROM students')
        row = cursor.fetchone()
        conn.close()
        
        if row and row['average'] is not None:
            return round(row['average'], 1)
        return 0.0
    
    def get_all_classes_statistics(self) -> List[Dict[str, Any]]:
        """קבלת סטטיסטיקות לכל הכיתות"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT 
                class_name,
                COUNT(*) as student_count,
                AVG(points) as average_points,
                MIN(points) as min_points,
                MAX(points) as max_points
            FROM students
            WHERE class_name IS NOT NULL AND class_name != ''
            GROUP BY class_name
            ORDER BY class_name
        ''')
        
        rows = cursor.fetchall()
        conn.close()
        
        stats = []
        for row in rows:
            stats.append({
                'class_name': row['class_name'],
                'student_count': row['student_count'],
                'average_points': round(row['average_points'], 1) if row['average_points'] else 0.0,
                'min_points': row['min_points'] or 0,
                'max_points': row['max_points'] or 0
            })
        
        return stats
    
    # ========================================
    # פונקציות בונוס זמנים
    # ========================================
    
    def get_all_time_bonuses(self) -> List[Dict[str, Any]]:
        """קבלת כל לוחות הזמנים של בונוס"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM time_bonus_schedules
            ORDER BY start_time
        ''')
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def add_time_bonus(self, name: str, start_time: str, end_time: str, bonus_points: int, group_name: str = None,
                       is_general: int = 1, classes: str = None, days_of_week: str = None, is_shown_public: int = 1,
                       sound_key: str = None) -> int:
        """הוספת לוח זמנים חדש לבונוס"""
        def _normalize_time_str(t: str) -> str:
            try:
                s = str(t or '').strip()
                if not s:
                    return s
                parts = s.split(':')
                if len(parts) != 2:
                    return s
                hh = int(parts[0])
                mm = int(parts[1])
                if hh < 0 or hh > 23 or mm < 0 or mm > 59:
                    return s
                return f"{hh:02d}:{mm:02d}"
            except Exception:
                return str(t or '').strip()

        start_time = _normalize_time_str(start_time)
        end_time = _normalize_time_str(end_time)

        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO time_bonus_schedules (name, group_name, start_time, end_time, bonus_points, sound_key, is_general, classes, days_of_week, is_shown_public, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        ''', (name, group_name, start_time, end_time, bonus_points, sound_key, int(is_general or 0), classes, days_of_week, int(is_shown_public or 0)))
        
        bonus_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return bonus_id
    
    def update_time_bonus(self, bonus_id: int, name: str, start_time: str,
                         end_time: str, bonus_points: int, is_active: int, group_name: str = None,
                         is_general: int = 1, classes: str = None, days_of_week: str = None, is_shown_public: int = 1,
                         sound_key: str = None) -> bool:
        """עדכון לוח זמנים קיים"""
        def _normalize_time_str(t: str) -> str:
            try:
                s = str(t or '').strip()
                if not s:
                    return s
                parts = s.split(':')
                if len(parts) != 2:
                    return s
                hh = int(parts[0])
                mm = int(parts[1])
                if hh < 0 or hh > 23 or mm < 0 or mm > 59:
                    return s
                return f"{hh:02d}:{mm:02d}"
            except Exception:
                return str(t or '').strip()

        start_time = _normalize_time_str(start_time)
        end_time = _normalize_time_str(end_time)

        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                UPDATE time_bonus_schedules
                SET name = ?, group_name = ?, start_time = ?, end_time = ?,
                    bonus_points = ?, sound_key = ?, is_general = ?, classes = ?, days_of_week = ?, is_shown_public = ?,
                    is_active = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (name, group_name, start_time, end_time, bonus_points,
                  sound_key, int(is_general or 0), classes, days_of_week, int(is_shown_public or 0), int(is_active or 0), bonus_id))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            conn.close()
            print(f"שגיאה בעדכון בונוס זמנים: {e}")
            return False

    def get_time_bonus_groups(self) -> Dict[str, List[Dict[str, Any]]]:
        """קבלת בונוסי זמנים מקובצים לפי קבוצה (group_name/שם)."""
        bonuses = self.get_all_time_bonuses()
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for b in bonuses:
            g = (b.get('group_name') or b.get('name') or '').strip()
            if not g:
                g = f"בונוס {b.get('id', '')}".strip()
            groups.setdefault(g, []).append(b)
        for g in list(groups.keys()):
            groups[g] = sorted(groups[g], key=lambda x: (x.get('start_time') or ''))
        return groups
    
    def delete_time_bonus(self, bonus_id: int) -> bool:
        """מחיקת לוח זמנים"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('DELETE FROM time_bonus_schedules WHERE id = ?', (bonus_id,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            conn.close()
            print(f"שגיאה במחיקת בונוס זמנים: {e}")
            return False
    
    def _parse_bonus_classes(self, classes: Optional[str]) -> List[str]:
        try:
            if not classes:
                return []
            s = str(classes)
            s = s.replace('\u05f3', ',').replace('\u05f4', ',')
            s = s.replace(';', ',')
            parts = [p.strip() for p in s.split(',')]
            out = []
            for p in parts:
                if p:
                    out.append(p)
            return out
        except Exception:
            return []

    def _time_bonus_applies_to_class(self, bonus_row: Dict[str, Any], class_name: Optional[str]) -> bool:
        try:
            # שורות ישנות שנוצרו לפני הוספת העמודות עלולות להגיע עם NULL.
            # נתייחס אליהן כברירת מחדל כ"כללי" כדי לשמור על תאימות לאחור.
            # חשוב: אם הערך הוא 0 מפורש (לא כללי) אסור להפוך אותו ל-1.
            is_general_val = bonus_row.get('is_general', None)
            is_general = 1
            if is_general_val is not None:
                try:
                    is_general = int(is_general_val)
                except Exception:
                    is_general = 1
            if is_general == 1:
                return True
            if not class_name:
                return False
            classes = self._parse_bonus_classes(bonus_row.get('classes'))
            return class_name.strip() in set(classes)
        except Exception:
            return False

    def get_active_time_bonus_now(self, class_name: Optional[str] = None,
                                 only_shown_public: Optional[bool] = None,
                                 only_general: Optional[bool] = None,
                                 now_dt=None) -> Optional[Dict[str, Any]]:
        """בדיקה אם יש בונוס זמנים פעיל ברגע זה (או בזמן נתון באמצעות now_dt)"""
        from datetime import datetime

        def _weekday_he(dt: datetime) -> str:
            # Python: Monday=0..Sunday=6  |  Hebrew UI requested: א,ב,ג,ד,ה,ו,ש (א=Sunday)
            m = {
                0: 'ב',
                1: 'ג',
                2: 'ד',
                3: 'ה',
                4: 'ו',
                5: 'ש',
                6: 'א',
            }
            return m.get(int(dt.weekday()), '')

        def _parse_days_of_week(s: Optional[str]) -> set:
            try:
                raw = str(s or '').strip()
            except Exception:
                raw = ''
            if not raw:
                return set()
            raw = raw.replace(';', ',').replace('\u05f3', ',').replace('\u05f4', ',')
            parts = [p.strip() for p in raw.split(',')]
            out = set()
            for p in parts:
                if not p:
                    continue
                # ננרמל לצורת אות אחת (א/ב/ג/ד/ה/ו/ש)
                p1 = p[0]
                if p1 in set(['א', 'ב', 'ג', 'ד', 'ה', 'ו', 'ש']):
                    out.add(p1)
            return out

        def _time_to_minutes(t: str) -> Optional[int]:
            try:
                s = str(t or '').strip()
                if not s:
                    return None
                # Backward compatibility: some legacy data uses '.' as separator (e.g. '7.30')
                s = s.replace('.', ':')
                parts = s.split(':')
                if len(parts) != 2:
                    return None
                hh = int(parts[0])
                mm = int(parts[1])
                if hh < 0 or hh > 23 or mm < 0 or mm > 59:
                    return None
                return hh * 60 + mm
            except Exception:
                return None

        if now_dt is None:
            now_dt = datetime.now()
        current_time = now_dt.strftime('%H:%M')
        cur_min = _time_to_minutes(current_time)
        
        conn = self.get_connection()
        cursor = conn.cursor()

        # נביא את כל הבונוסים הפעילים, ונסנן לפי טווח זמן בצורה מספרית
        # כדי לתמוך גם בנתונים קיימים שמכילים שעות בפורמט H:MM.
        cursor.execute('''
            SELECT * FROM time_bonus_schedules
            WHERE is_active = 1
        ''')
        
        rows = cursor.fetchall()
        conn.close()

        candidates: List[Dict[str, Any]] = [dict(r) for r in rows]

        if cur_min is not None:
            filtered = []
            for r in candidates:
                s_min = _time_to_minutes(r.get('start_time'))
                e_min = _time_to_minutes(r.get('end_time'))
                if s_min is None or e_min is None:
                    continue
                if cur_min < s_min or cur_min > e_min:
                    continue
                filtered.append(r)
            candidates = filtered
        if only_general is True:
            def _is_general_row(rr: Dict[str, Any]) -> bool:
                v = rr.get('is_general', None)
                if v is None:
                    return True
                try:
                    return int(v) == 1
                except Exception:
                    return True
            candidates = [r for r in candidates if _is_general_row(r)]
        if only_shown_public is True:
            def _is_shown_row(rr: Dict[str, Any]) -> bool:
                v = rr.get('is_shown_public', None)
                if v is None:
                    return True
                try:
                    return int(v) == 1
                except Exception:
                    return True
            candidates = [r for r in candidates if _is_shown_row(r)]
        if class_name is not None:
            candidates = [r for r in candidates if self._time_bonus_applies_to_class(r, class_name)]

        # סינון לפי ימים בשבוע (אם הוגדר)
        cur_day = _weekday_he(now_dt)
        if cur_day:
            filtered = []
            for r in candidates:
                days_set = _parse_days_of_week(r.get('days_of_week'))
                # days_set ריק = כל הימים
                if days_set and cur_day not in days_set:
                    continue
                filtered.append(r)
            candidates = filtered

        if not candidates:
            return None
        # בעת חפיפה בין כמה בונוסים פעילים: עדיפות לפי שעת התחלה המאוחרת.
        # זה תואם את ההגדרה במערכת (ומונע בלבול כאשר יש כמה בונוסים פעילים במקביל).
        def _sort_key(x: Dict[str, Any]):
            start = str(x.get('start_time') or '')
            pts = int(x.get('bonus_points', 0) or 0)
            return (start, pts)

        candidates = sorted(candidates, key=_sort_key, reverse=True)
        return candidates[0]

    def has_student_received_time_bonus_on_date(self, student_id: int, bonus_schedule_id: int, given_date: str) -> bool:
        """בדיקה אם תלמיד כבר קיבל בונוס זמנים בתאריך נתון (YYYY-MM-DD)."""
        if not given_date:
            return False
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT COUNT(*) as count FROM time_bonus_given
            WHERE student_id = ? AND bonus_schedule_id = ? AND given_date = ?
        ''', (int(student_id or 0), int(bonus_schedule_id or 0), str(given_date)))
        row = cursor.fetchone()
        conn.close()
        try:
            return int(row['count'] if row else 0) > 0
        except Exception:
            return False

    def record_time_bonus_given_on_date(self, student_id: int, bonus_schedule_id: int, given_date: str, *, given_at: str = None) -> bool:
        """רישום שתלמיד קיבל בונוס זמנים בתאריך נתון (YYYY-MM-DD).

        אם given_at מסופק (YYYY-MM-DD HH:MM:SS) – נשמור אותו כדי שייצוא נוכחות יציג את שעת התיקוף המקורית.
        """
        if not given_date:
            return False
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            if given_at:
                # upsert: keep unique constraint but update given_at to the desired time
                cursor.execute('''
                    INSERT INTO time_bonus_given (student_id, bonus_schedule_id, given_date, given_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(student_id, bonus_schedule_id, given_date)
                    DO UPDATE SET given_at = excluded.given_at
                ''', (int(student_id or 0), int(bonus_schedule_id or 0), str(given_date), str(given_at)))
            else:
                cursor.execute('''
                    INSERT OR IGNORE INTO time_bonus_given (student_id, bonus_schedule_id, given_date)
                    VALUES (?, ?, ?)
                ''', (int(student_id or 0), int(bonus_schedule_id or 0), str(given_date)))
            conn.commit()
            conn.close()
            return True
        except Exception:
            conn.close()
            return False

    def has_student_received_time_bonus_group_on_date(self, student_id: int, group_name: str, given_date: str) -> bool:
        """בדיקה אם תלמיד כבר קיבל בתאריך נתון בונוס כלשהו מקבוצת בונוס זמנים."""
        if not group_name or not given_date:
            return False
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT COUNT(*) as count
            FROM time_bonus_given g
            JOIN time_bonus_schedules s ON s.id = g.bonus_schedule_id
            WHERE g.student_id = ?
              AND g.given_date = ?
              AND COALESCE(s.group_name, s.name) = ?
        ''', (int(student_id or 0), str(given_date), str(group_name)))
        row = cursor.fetchone()
        conn.close()
        try:
            return int(row['count'] if row else 0) > 0
        except Exception:
            return False

    def get_student_time_bonus_for_group_on_date(self, student_id: int, group_name: str, given_date: str) -> Optional[Dict[str, Any]]:
        """קבלת בונוס הזמנים שנרשם בפועל לתלמיד בקבוצה/תאריך, כולל נקודות ושעת given_at.

        מחזיר None אם אין רשומה.
        """
        if not student_id or not group_name or not given_date:
            return None
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                SELECT g.bonus_schedule_id, g.given_at,
                       s.name, COALESCE(s.group_name, s.name) AS group_name,
                       s.start_time, s.end_time, s.bonus_points
                FROM time_bonus_given g
                JOIN time_bonus_schedules s ON s.id = g.bonus_schedule_id
                WHERE g.student_id = ?
                  AND g.given_date = ?
                  AND COALESCE(s.group_name, s.name) = ?
                ORDER BY g.given_at ASC, g.id ASC
                LIMIT 1
            ''', (int(student_id or 0), str(given_date), str(group_name)))
            row = cursor.fetchone()
            if not row:
                return None
            return dict(row)
        except Exception:
            return None
        finally:
            conn.close()

    def replace_student_time_bonus_for_group_on_date(
        self,
        student_id: int,
        group_name: str,
        given_date: str,
        new_bonus_schedule_id: int,
        *,
        given_at: str,
    ) -> bool:
        """החלפת הבונוס שנרשם לתלמיד בקבוצת בונוס זמנים בתאריך נתון.

        מוחק את כל הרשומות של התלמיד בקבוצה הזו באותו יום, ואז רושם את הבונוס החדש (upsert) עם given_at.
        לא נותן נקודות בפני עצמו – הקריאה שמעל צריכה לתת נקודות/הפרשים.
        """
        if not student_id or not group_name or not given_date or not new_bonus_schedule_id or not given_at:
            return False
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            conn.execute('BEGIN IMMEDIATE')
            cursor.execute('''
                DELETE FROM time_bonus_given
                WHERE id IN (
                    SELECT g.id
                    FROM time_bonus_given g
                    JOIN time_bonus_schedules s ON s.id = g.bonus_schedule_id
                    WHERE g.student_id = ?
                      AND g.given_date = ?
                      AND COALESCE(s.group_name, s.name) = ?
                )
            ''', (int(student_id), str(given_date), str(group_name)))

            cursor.execute('''
                INSERT INTO time_bonus_given (student_id, bonus_schedule_id, given_date, given_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(student_id, bonus_schedule_id, given_date)
                DO UPDATE SET given_at = excluded.given_at
            ''', (int(student_id), int(new_bonus_schedule_id), str(given_date), str(given_at)))

            conn.commit()
            return True
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            return False
        finally:
            conn.close()

    def update_time_bonus_given_at_for_group_on_date(self, student_id: int, group_name: str, given_date: str, *, given_at: str) -> bool:
        """עדכון given_at (שעת התיקוף לייצוא נוכחות) לכל הרשומות של תלמיד בקבוצת בונוס מסוימת בתאריך נתון.

        מיועד לתיקון ידני: לא יוצר רשומות חדשות ולא נותן נקודות – רק מיישר את שעת הייצוא.
        """
        if not student_id or not group_name or not given_date or not given_at:
            return False
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                UPDATE time_bonus_given
                SET given_at = ?
                WHERE id IN (
                    SELECT g.id
                    FROM time_bonus_given g
                    JOIN time_bonus_schedules s ON s.id = g.bonus_schedule_id
                    WHERE g.student_id = ?
                      AND g.given_date = ?
                      AND COALESCE(s.group_name, s.name) = ?
                )
            ''', (str(given_at), int(student_id), str(given_date), str(group_name)))
            conn.commit()
            conn.close()
            return True
        except Exception:
            conn.close()
            return False

    def update_time_bonus_given_at_for_student_on_date(self, student_id: int, given_date: str, *, given_at: str) -> bool:
        if not student_id or not given_date or not given_at:
            return False
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                UPDATE time_bonus_given
                SET given_at = ?
                WHERE student_id = ?
                  AND given_date = ?
            ''', (str(given_at), int(student_id), str(given_date)))
            conn.commit()
            conn.close()
            return True
        except Exception:
            conn.close()
            return False

    def update_time_bonus_given_at_for_student_bonus_on_date(self, student_id: int, bonus_schedule_id: int, given_date: str, *, given_at: str) -> bool:
        if not student_id or not bonus_schedule_id or not given_date or not given_at:
            return False
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                UPDATE time_bonus_given
                SET given_at = ?
                WHERE student_id = ?
                  AND bonus_schedule_id = ?
                  AND given_date = ?
            ''', (str(given_at), int(student_id), int(bonus_schedule_id), str(given_date)))
            conn.commit()
            conn.close()
            return True
        except Exception:
            conn.close()
            return False

    # NOTE: date-based time-bonus helpers are defined once above.
    
    def has_student_received_time_bonus_today(self, student_id: int, bonus_schedule_id: int) -> bool:
        """בדיקה אם תלמיד כבר קיבל בונוס זמנים היום"""
        from datetime import date
        
        today = date.today().isoformat()
        
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT COUNT(*) as count FROM time_bonus_given
            WHERE student_id = ? AND bonus_schedule_id = ? AND given_date = ?
        ''', (student_id, bonus_schedule_id, today))
        
        row = cursor.fetchone()
        conn.close()
        
        return row['count'] > 0
    
    def record_time_bonus_given(self, student_id: int, bonus_schedule_id: int) -> bool:
        """רישום שתלמיד קיבל בונוס זמנים היום"""
        from datetime import date
        
        today = date.today().isoformat()
        
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT OR IGNORE INTO time_bonus_given (student_id, bonus_schedule_id, given_date)
                VALUES (?, ?, ?)
            ''', (int(student_id or 0), int(bonus_schedule_id or 0), str(today)))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            conn.close()
            print(f"שגיאה ברישום בונוס זמנים: {e}")
            return False

    # ========================================
    # חסימות / חופשות לעמדה הציבורית בלבד
    # ========================================

    def get_all_public_closures(self) -> List[Dict[str, Any]]:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM public_closures
            ORDER BY enabled DESC,
                     repeat_weekly DESC,
                     start_at ASC
        ''')
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def add_public_closure(self,
                           title: str,
                           start_at: str,
                           end_at: str,
                           subtitle: str = None,
                           enabled: int = 1,
                           repeat_weekly: int = 0,
                           weekly_start_day: str = None,
                           weekly_start_time: str = None,
                           weekly_end_day: str = None,
                           weekly_end_time: str = None,
                           image_path_portrait: str = None,
                           image_path_landscape: str = None) -> int:
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO public_closures (
                title, subtitle, start_at, end_at,
                repeat_weekly, weekly_start_day, weekly_start_time, weekly_end_day, weekly_end_time,
                image_path_portrait, image_path_landscape,
                enabled
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            title, subtitle, start_at, end_at,
            int(repeat_weekly or 0), weekly_start_day, weekly_start_time, weekly_end_day, weekly_end_time,
            image_path_portrait, image_path_landscape,
            int(enabled or 0)
        ))
        cid = cursor.lastrowid
        conn.commit()
        conn.close()
        return int(cid or 0)

    def update_public_closure(self,
                              closure_id: int,
                              title: str,
                              start_at: str,
                              end_at: str,
                              subtitle: str = None,
                              enabled: int = 1,
                              repeat_weekly: int = 0,
                              weekly_start_day: str = None,
                              weekly_start_time: str = None,
                              weekly_end_day: str = None,
                              weekly_end_time: str = None,
                              image_path_portrait: str = None,
                              image_path_landscape: str = None) -> bool:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('''
                UPDATE public_closures
                SET title = ?, subtitle = ?, start_at = ?, end_at = ?,
                    repeat_weekly = ?, weekly_start_day = ?, weekly_start_time = ?, weekly_end_day = ?, weekly_end_time = ?,
                    image_path_portrait = ?, image_path_landscape = ?,
                    enabled = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (
                title, subtitle, start_at, end_at,
                int(repeat_weekly or 0), weekly_start_day, weekly_start_time, weekly_end_day, weekly_end_time,
                image_path_portrait, image_path_landscape,
                int(enabled or 0), int(closure_id)
            ))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            conn.close()
            print(f"שגיאה בעדכון חסימה: {e}")
            return False

    def delete_public_closure(self, closure_id: int) -> bool:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('DELETE FROM public_closures WHERE id = ?', (int(closure_id),))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            conn.close()
            print(f"שגיאה במחיקת חסימה: {e}")
            return False

    def get_active_public_closure_now(self, *, screen_orientation: str = None) -> Optional[Dict[str, Any]]:
        """בודק אם יש כרגע חסימה פעילה לעמדה הציבורית. מחזיר dict עם פרטי החסימה."""
        from datetime import datetime

        def _parse_dt(s: str) -> Optional[datetime]:
            try:
                ss = str(s or '').strip()
                if not ss:
                    return None
                # נתמוך גם ב-YYYY-MM-DDTHH:MM וגם ב-YYYY-MM-DD HH:MM
                ss = ss.replace('T', ' ')
                if len(ss) == 16:
                    ss = ss + ':00'
                return datetime.strptime(ss[:19], '%Y-%m-%d %H:%M:%S')
            except Exception:
                return None

        now = datetime.now()

        def _weekday_he(dt: datetime) -> str:
            m = {0: 'ב', 1: 'ג', 2: 'ד', 3: 'ה', 4: 'ו', 5: 'ש', 6: 'א'}
            return m.get(int(dt.weekday()), '')

        def _day_he_to_index(d: str) -> Optional[int]:
            try:
                dd = str(d or '').strip()
            except Exception:
                dd = ''
            if not dd:
                return None
            m = {'א': 0, 'ב': 1, 'ג': 2, 'ד': 3, 'ה': 4, 'ו': 5, 'ש': 6}
            return m.get(dd)

        def _time_to_minutes(t: str) -> Optional[int]:
            try:
                s = str(t or '').strip()
                if not s:
                    return None
                parts = s.split(':')
                if len(parts) != 2:
                    return None
                hh = int(parts[0])
                mm = int(parts[1])
                if hh < 0 or hh > 23 or mm < 0 or mm > 59:
                    return None
                return hh * 60 + mm
            except Exception:
                return None

        cur_day = _weekday_he(now)
        cur_day_idx = _day_he_to_index(cur_day)
        cur_time_min = _time_to_minutes(now.strftime('%H:%M'))
        cur_week_min = None
        if cur_day_idx is not None and cur_time_min is not None:
            cur_week_min = cur_day_idx * 1440 + cur_time_min

        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM public_closures WHERE enabled = 1')
        rows = cursor.fetchall()
        conn.close()

        best = None
        for r0 in rows:
            r = dict(r0)
            try:
                if int(r.get('repeat_weekly', 0) or 0) == 1:
                    sd = str(r.get('weekly_start_day') or '').strip()
                    ed = str(r.get('weekly_end_day') or '').strip()
                    st = str(r.get('weekly_start_time') or '').strip()
                    et = str(r.get('weekly_end_time') or '').strip()
                    if not (sd and ed and st and et and cur_week_min is not None):
                        continue

                    sd_i = _day_he_to_index(sd)
                    ed_i = _day_he_to_index(ed)
                    st_m = _time_to_minutes(st)
                    et_m = _time_to_minutes(et)
                    if sd_i is None or ed_i is None or st_m is None or et_m is None:
                        continue

                    start_week_min = sd_i * 1440 + st_m
                    end_week_min = ed_i * 1440 + et_m

                    wraps = end_week_min < start_week_min
                    cur_m = int(cur_week_min)
                    if wraps:
                        end_week_min += 7 * 1440
                        if cur_m < start_week_min:
                            cur_m += 7 * 1440

                    if start_week_min <= cur_m <= end_week_min:
                        best = r
                        break
                    continue

                sdt = _parse_dt(r.get('start_at'))
                edt = _parse_dt(r.get('end_at'))
                if not sdt or not edt:
                    continue
                if sdt <= now <= edt:
                    best = r
                    break
            except Exception:
                continue

        if not best:
            return None

        # בחירת תמונה לפי אוריינטציה (אם נשלח)
        try:
            orient = str(screen_orientation or '').strip().lower()
        except Exception:
            orient = ''
        if orient:
            if orient == 'portrait' and best.get('image_path_portrait'):
                best['image_path'] = best.get('image_path_portrait')
            elif orient == 'landscape' and best.get('image_path_landscape'):
                best['image_path'] = best.get('image_path_landscape')
            else:
                best['image_path'] = best.get('image_path_portrait') or best.get('image_path_landscape')
        else:
            best['image_path'] = best.get('image_path_portrait') or best.get('image_path_landscape')

        return best

    def seed_public_holidays_template(self, *, days_ahead: int = 450, israel: bool = True) -> int:
        """יוצר (במצב disabled) תבנית בסיס לחגים לשנה הקרובה לפי תאריך עברי.
        התבנית נועדה לעריכה ידנית בעמדת הניהול.
        """
        try:
            from datetime import timedelta, date as pydate
            import jewish_calendar
        except Exception:
            return 0

        if not getattr(jewish_calendar, 'is_available', lambda: False)():
            return 0

        # אם כבר קיימים חגים (כותרת שמכילה "חג"/"ראש השנה" וכו') לא ניצור שוב.
        try:
            existing = self.get_all_public_closures()
        except Exception:
            existing = []
        try:
            if any(('תבנית חג' in str(x.get('subtitle') or '')) for x in (existing or [])):
                return 0
        except Exception:
            pass

        created = 0
        today = pydate.today()
        items = jewish_calendar.upcoming_holidays(start=today, days=int(days_ahead), israel=bool(israel))
        for it in (items or []):
            try:
                g = it.gregorian
                title = str(it.title_he or '').strip()
                heb = str(it.hebrew_date_he or '').strip()
                if not title:
                    continue
                # תבנית: ברירת מחדל 16:00-20:00 (ניתן לעריכה ידנית)
                start_at = f"{g.isoformat()} 16:00:00"
                end_at = f"{g.isoformat()} 20:00:00"
                subtitle = f"תבנית חג (לעריכה): {heb}".strip()
                self.add_public_closure(
                    title=title,
                    subtitle=subtitle,
                    start_at=start_at,
                    end_at=end_at,
                    enabled=0,
                )
                created += 1
            except Exception:
                continue

        return created

    def get_first_swipe_times_for_date(self, given_date: str, station_type: str = "public") -> Dict[int, str]:
        """מיפוי student_id -> זמן תיקוף ראשון (HH.MM) לתאריך נתון."""
        from datetime import datetime

        if not given_date:
            return {}

        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT student_id, MIN(swiped_at) AS first_swipe
            FROM swipe_log
            WHERE DATE(swiped_at) = ?
              AND station_type = ?
              AND student_id IS NOT NULL
            GROUP BY student_id
        ''', (given_date, station_type))

        rows = cursor.fetchall()
        conn.close()

        out: Dict[int, str] = {}
        for r in rows:
            sid = r['student_id']
            sw = str(r['first_swipe'] or '')
            if not sw:
                continue
            time_str = ''
            try:
                # swiped_at is stored as a local time string (YYYY-MM-DD HH:MM:SS)
                dt_local = datetime.strptime(sw[:19], "%Y-%m-%d %H:%M:%S")
                time_str = dt_local.strftime("%H.%M")
            except Exception:
                try:
                    hhmm = sw[11:16]
                    if hhmm and len(hhmm) == 5:
                        time_str = hhmm.replace(':', '.')
                except Exception:
                    time_str = ''
            if time_str:
                out[int(sid)] = time_str
        return out

    def get_time_bonus_given_for_date(self, given_date: str) -> List[Dict[str, Any]]:
        """קבלת כל רישומי בונוס זמנים לתאריך מסוים (מטבלת time_bonus_given)."""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT * FROM time_bonus_given
            WHERE given_date = ?
        ''', (given_date,))

        rows = cursor.fetchall()
        conn.close()

        return [dict(row) for row in rows]
    
    def get_time_bonus_given_for_bonus(self, bonus_schedule_id: int) -> List[Dict[str, Any]]:
        """קבלת כל רישומי בונוס זמנים עבור בונוס מסוים (לכל התאריכים)."""
        conn = self.get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT * FROM time_bonus_given
            WHERE bonus_schedule_id = ?
        ''', (bonus_schedule_id,))

        rows = cursor.fetchall()
        conn.close()

        return [dict(row) for row in rows]
    
    # ========================================
    # פונקציות ניהול מורים והרשאות
    # ========================================
    
    def add_teacher(self, name: str, card_number: str = "", is_admin: bool = False,
                    card_number2: str = "", card_number3: str = "",
                    can_edit_student_card: bool = True, can_edit_student_photo: bool = True) -> int:
        """הוספת מורה חדש"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO teachers (name, card_number, card_number2, card_number3, is_admin, can_edit_student_card, can_edit_student_photo)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                name,
                card_number if card_number else None,
                card_number2 if card_number2 else None,
                card_number3 if card_number3 else None,
                1 if is_admin else 0,
                1 if can_edit_student_card else 0,
                1 if can_edit_student_photo else 0,
            ))
            
            teacher_id = cursor.lastrowid
            conn.commit()
            conn.close()
            return teacher_id
        except Exception as e:
            conn.close()
            print(f"שגיאה בהוספת מורה: {e}")
            return 0
    
    def get_teacher_by_card(self, card_number: str) -> Optional[Dict[str, Any]]:
        """שליפת פרטי מורה לפי מספר כרטיס"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # תמיכה בכמה כרטיסים לכל מורה
        cursor.execute(
            'SELECT * FROM teachers WHERE card_number = ? OR card_number2 = ? OR card_number3 = ? LIMIT 1',
            (card_number, card_number, card_number)
        )
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return dict(row)
        return None
    
    def get_teacher_by_id(self, teacher_id: int) -> Optional[Dict[str, Any]]:
        """שליפת פרטי מורה לפי מזהה"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM teachers WHERE id = ?', (teacher_id,))
        row = cursor.fetchone()
        conn.close()
        
        if row:
            return dict(row)
        return None
    
    def get_all_teachers(self) -> List[Dict[str, Any]]:
        """שליפת כל המורים"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM teachers ORDER BY name')
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def update_teacher(self, teacher_id: int, name: str = None, card_number: str = None,
                       is_admin: bool = None, card_number2: str = None, card_number3: str = None,
                       can_edit_student_card: Optional[bool] = None, can_edit_student_photo: Optional[bool] = None) -> bool:
        """עדכון פרטי מורה"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            teacher = self.get_teacher_by_id(teacher_id)
            if not teacher:
                return False
            
            if name is not None:
                cursor.execute('UPDATE teachers SET name = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                             (name, teacher_id))
            
            if card_number is not None:
                cursor.execute('UPDATE teachers SET card_number = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                             (card_number if card_number else None, teacher_id))

            if card_number2 is not None:
                cursor.execute('UPDATE teachers SET card_number2 = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                             (card_number2 if card_number2 else None, teacher_id))

            if card_number3 is not None:
                cursor.execute('UPDATE teachers SET card_number3 = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                             (card_number3 if card_number3 else None, teacher_id))
            
            if is_admin is not None:
                cursor.execute('UPDATE teachers SET is_admin = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                             (1 if is_admin else 0, teacher_id))

            if can_edit_student_card is not None:
                cursor.execute(
                    'UPDATE teachers SET can_edit_student_card = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                    (1 if can_edit_student_card else 0, teacher_id)
                )

            if can_edit_student_photo is not None:
                cursor.execute(
                    'UPDATE teachers SET can_edit_student_photo = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                    (1 if can_edit_student_photo else 0, teacher_id)
                )
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            conn.close()
            print(f"שגיאה בעדכון מורה: {e}")
            return False
    
    def delete_teacher(self, teacher_id: int) -> bool:
        """מחיקת מורה"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('DELETE FROM teachers WHERE id = ?', (teacher_id,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            conn.close()
            print(f"שגיאה במחיקת מורה: {e}")
            return False
    
    def add_teacher_class(self, teacher_id: int, class_name: str) -> bool:
        """הוספת שיוך של מורה לכיתה"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT OR IGNORE INTO teacher_classes (teacher_id, class_name)
                VALUES (?, ?)
            ''', (teacher_id, class_name))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            conn.close()
            print(f"שגיאה בהוספת כיתה למורה: {e}")
            return False
    
    def remove_teacher_class(self, teacher_id: int, class_name: str) -> bool:
        """הסרת שיוך של מורה מכיתה"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                DELETE FROM teacher_classes 
                WHERE teacher_id = ? AND class_name = ?
            ''', (teacher_id, class_name))
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            conn.close()
            print(f"שגיאה בהסרת כיתה ממורה: {e}")
            return False
    
    def get_teacher_classes(self, teacher_id: int) -> List[str]:
        """קבלת רשימת כיתות של מורה"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT class_name FROM teacher_classes 
            WHERE teacher_id = ?
            ORDER BY class_name
        ''', (teacher_id,))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [row['class_name'] for row in rows]

    def get_teacher_classes_stats(self, teacher_id: int) -> List[Dict[str, Any]]:
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                '''
                SELECT tc.class_name AS class_name,
                       COUNT(s.id) AS students_count,
                       COALESCE(SUM(s.points), 0) AS total_points
                  FROM teacher_classes tc
                  LEFT JOIN students s ON s.class_name = tc.class_name
                 WHERE tc.teacher_id = ?
                 GROUP BY tc.class_name
                 ORDER BY tc.class_name
                ''',
                (int(teacher_id or 0),)
            )
            rows = cursor.fetchall() or []
            return [dict(r) for r in rows]
        finally:
            conn.close()
    
    def get_students_by_teacher(self, teacher_id: int) -> List[Dict[str, Any]]:
        """קבלת כל התלמידים של מורה (לפי הכיתות שלו)"""
        classes = self.get_teacher_classes(teacher_id)
        
        if not classes:
            return []
        
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # בניית שאילתה עם IN
        placeholders = ','.join('?' * len(classes))
        cursor.execute(f'''
            SELECT * FROM students 
            WHERE class_name IN ({placeholders})
            ORDER BY class_name, last_name, first_name
        ''', classes)
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
    
    def get_all_classes_stats(self) -> List[Dict[str, Any]]:
        """קבלת סטטיסטיקות של כל הכיתות במערכת (לחישוב ממוצע כללי, מינימום, מקסימום)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                '''
                SELECT class_name,
                       COUNT(id) AS students_count,
                       COALESCE(SUM(points), 0) AS total_points
                  FROM students
                 WHERE class_name IS NOT NULL AND class_name != ''
                 GROUP BY class_name
                 ORDER BY class_name
                '''
            )
            rows = cursor.fetchall() or []
            return [dict(r) for r in rows]
        finally:
            conn.close()
    
    def get_teacher_bonus(self, teacher_id: int) -> int:
        """קבלת הגדרת בונוס למורה (נקודות לכל תלמיד בסבב)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT bonus_points FROM teacher_bonus WHERE teacher_id = ?', (teacher_id,))
            row = cursor.fetchone()
            conn.close()
            if row and row['bonus_points'] is not None:
                try:
                    return int(row['bonus_points'])
                except (TypeError, ValueError):
                    return 0
            return 0
        except Exception as e:
            conn.close()
            print(f"שגיאה בשליפת בונוס מורה: {e}")
            return 0
    
    def set_teacher_bonus(self, teacher_id: int, bonus_points: int) -> bool:
        """עדכון הגדרת בונוס למורה (נקודות לכל תלמיד בסבב)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            # מחיקה והכנסה מחדש כדי להימנע מבעיות תאימות עם ON CONFLICT
            cursor.execute('DELETE FROM teacher_bonus WHERE teacher_id = ?', (teacher_id,))
            cursor.execute('''
                INSERT INTO teacher_bonus (teacher_id, bonus_points, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
            ''', (teacher_id, bonus_points))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            conn.close()
            print(f"שגיאה בעדכון בונוס מורה: {e}")
            return False
    
    def increment_teacher_bonus_runs(self, teacher_id: int) -> bool:
        from datetime import date

        today = date.today().isoformat()

        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT bonus_runs_used, bonus_runs_reset_date FROM teachers WHERE id = ?', (teacher_id,))
            row = cursor.fetchone()
            if not row:
                conn.close()
                return False

            last_reset = row['bonus_runs_reset_date']
            current_used = row['bonus_runs_used'] if row['bonus_runs_used'] is not None else 0

            if last_reset == today:
                new_used = current_used + 1
            else:
                new_used = 1

            cursor.execute('''
                UPDATE teachers
                SET bonus_runs_used = ?,
                    bonus_runs_reset_date = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''' , (new_used, today, teacher_id))

            conn.commit()
            success = cursor.rowcount > 0
            conn.close()
            return success
        except Exception as e:
            conn.close()
            print(f"שגיאה בעדכון מונה הפעלות בונוס למורה: {e}")
            return False

    def increment_teacher_bonus_points_used(self, teacher_id: int, delta_points: int) -> bool:
        """הגדלת סך נקודות הבונוס שמורה חילק היום לתלמידים (ספירה יומית)."""
        from datetime import date

        today = date.today().isoformat()

        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('SELECT bonus_points_used, bonus_points_reset_date FROM teachers WHERE id = ?', (teacher_id,))
            row = cursor.fetchone()
            if not row:
                conn.close()
                return False

            last_reset = row['bonus_points_reset_date']
            current_points = row['bonus_points_used'] if row['bonus_points_used'] is not None else 0

            if last_reset == today:
                new_points = current_points + max(0, int(delta_points))
            else:
                new_points = max(0, int(delta_points))

            cursor.execute('''
                UPDATE teachers
                SET bonus_points_used = ?,
                    bonus_points_reset_date = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (new_points, today, teacher_id))

            conn.commit()
            success = cursor.rowcount > 0
            conn.close()
            return success
        except Exception as e:
            conn.close()
            print(f"שגיאה בעדכון סך נקודות בונוס למורה: {e}")
            return False
    
    def get_all_class_names(self) -> List[str]:
        """קבלת רשימת כל הכיתות במערכת"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT DISTINCT class_name 
            FROM students 
            WHERE class_name IS NOT NULL AND class_name != ''
            ORDER BY class_name
        ''')
        
        rows = cursor.fetchall()
        conn.close()
        
        return [row['class_name'] for row in rows]
    
    def migrate_comma_separated_data(self):
        """המרה חד-פעמית של נתונים עם פסיקים לפורמט החדש (מופעל אוטומטית בעת עדכון)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            # בדיקה אם ההמרה כבר רצה
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='migration_log'")
            if not cursor.fetchone():
                cursor.execute('''
                    CREATE TABLE migration_log (
                        migration_name TEXT PRIMARY KEY,
                        executed_at TEXT NOT NULL
                    )
                ''')
                conn.commit()
            
            cursor.execute("SELECT migration_name FROM migration_log WHERE migration_name = 'comma_to_checkbox_v1'")
            if cursor.fetchone():
                conn.close()
                return
            
            # המרת teacher_classes - הנתונים כבר מאוחסנים נכון (שורה לכל כיתה)
            # אין צורך בהמרה
            
            # המרת time_bonus_rules - classes ו-days_of_week
            try:
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='time_bonus_rules'")
                has_time_bonus_rules = bool(cursor.fetchone())
            except Exception:
                has_time_bonus_rules = False

            if has_time_bonus_rules:
                cursor.execute("SELECT id, classes, days_of_week FROM time_bonus_rules")
                bonus_rules = cursor.fetchall()
                for rule in bonus_rules:
                    rule_id = rule['id']
                    classes = str(rule['classes'] or '').strip()
                    days = str(rule['days_of_week'] or '').strip()

                    # הנתונים כבר בפורמט נכון (מופרדים בפסיקים)
                    # אין צורך בהמרה - הקוד החדש קורא אותם נכון
                    pass
            
            # המרת products - allowed_classes
            cursor.execute("SELECT id, allowed_classes FROM products")
            products = cursor.fetchall()
            for prod in products:
                prod_id = prod['id']
                allowed = str(prod['allowed_classes'] or '').strip()
                
                # הנתונים כבר בפורמט נכון (מופרדים בפסיקים)
                # אין צורך בהמרה - הקוד החדש קורא אותם נכון
                pass
            
            # המרת scheduled_services - allowed_classes, queue_priority_custom
            cursor.execute("SELECT id, allowed_classes, queue_priority_custom FROM scheduled_services")
            services = cursor.fetchall()
            for svc in services:
                svc_id = svc['id']
                allowed = str(svc['allowed_classes'] or '').strip()
                qp_custom = str(svc['queue_priority_custom'] or '').strip()
                
                # הנתונים כבר בפורמט נכון (מופרדים בפסיקים)
                # אין צורך בהמרה - הקוד החדש קורא אותם נכון
                pass
            
            # סימון ההמרה כהושלמה
            cursor.execute(
                "INSERT INTO migration_log (migration_name, executed_at) VALUES (?, ?)",
                ('comma_to_checkbox_v1', datetime.now().isoformat())
            )
            conn.commit()
            conn.close()
            
        except Exception as e:
            conn.close()
            print(f"שגיאה בהמרת נתונים: {e}")
