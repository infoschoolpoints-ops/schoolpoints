"""
מודול מסד נתונים למערכת ניקוד בית ספרית
"""
import sqlite3
import os
import json
import shutil
import re
import uuid
import time
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
        self._last_backup_ts = 0.0
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

        self._maybe_backup_db()

        last_err = None
        for attempt in range(3):
            try:
                conn = sqlite3.connect(self.db_path, timeout=10)
                conn.row_factory = sqlite3.Row  # מאפשר גישה לעמודות לפי שם
                self._apply_pragmas(conn)
                return conn
            except sqlite3.DatabaseError as e:
                last_err = e
                if 'malformed' in str(e).lower():
                    self._handle_corrupt_db(e)
                    continue
                raise
            except sqlite3.OperationalError as e:
                last_err = e
                msg = str(e).lower()
                if attempt < 2 and ('locked' in msg or 'busy' in msg):
                    time.sleep(0.4 + 0.3 * attempt)
                    continue
                raise
        if last_err:
            raise last_err
        raise sqlite3.DatabaseError('failed to open database')

    def _cleanup_expired_holds(self, cursor) -> None:
        try:
            cursor.execute('DELETE FROM purchase_holds WHERE expires_at <= CURRENT_TIMESTAMP')
        except Exception:
            pass

    def _is_unc_path(self) -> bool:
        try:
            p = str(self.db_path or '')
        except Exception:
            return False
        return p.startswith('\\') or p.startswith('//')

    def _apply_pragmas(self, conn: sqlite3.Connection) -> None:
        # PRAGMA commands usually succeed unless the DB is corrupt or busy.
        # We allow OperationalError (busy) to be ignored if needed, but DatabaseError (corruption) must be raised.
        try:
            conn.execute('PRAGMA foreign_keys = ON')
        except sqlite3.OperationalError:
            pass
            
        try:
            conn.execute('PRAGMA busy_timeout = 10000') # Increased timeout for network latency
        except sqlite3.OperationalError:
            pass
            
        try:
            # Force DELETE mode (safe for network) instead of WAL
            # WAL mode is dangerous on network shares (mapped drives or UNC)
            conn.execute('PRAGMA journal_mode = DELETE')
            conn.execute('PRAGMA synchronous = FULL')
        except sqlite3.OperationalError:
            pass

    def _backup_dir(self) -> str:
        base = os.path.dirname(self.db_path) or '.'
        return os.path.join(base, 'backups')

    def _last_backup_path(self) -> str:
        return os.path.join(self._backup_dir(), 'school_points.last.db')

    def _maybe_backup_db(self, min_interval_s: int = 600) -> None:
        try:
            if not os.path.exists(self.db_path):
                return
        except Exception:
            return
        now = time.time()
        if (now - float(self._last_backup_ts or 0)) < int(min_interval_s):
            return
        try:
            os.makedirs(self._backup_dir(), exist_ok=True)
        except Exception:
            return
        try:
            shutil.copy2(self.db_path, self._last_backup_path())
            self._last_backup_ts = now
        except Exception:
            pass

    def _handle_corrupt_db(self, err: Exception) -> None:
        try:
            print(f"[DB] Corruption detected: {err}")
        except Exception:
            pass
        last_backup = self._last_backup_path()
        try:
            if os.path.exists(last_backup):
                shutil.copy2(last_backup, self.db_path)
                try:
                    print("[DB] Restored last backup.")
                except Exception:
                    pass
                return
        except Exception:
            pass
        try:
            if os.path.exists(self.db_path):
                ts = datetime.now().strftime('%Y%m%d_%H%M%S')
                bad = self.db_path + f".corrupt_{ts}"
                shutil.move(self.db_path, bad)
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

    def create_tables(self):
        """יצירת טבלאות אם לא קיימות"""
        # (This was cut off in the restore, but it's enough to run the class logic)
        # We don't need the full CREATE TABLE SQL to analyze the locking logic
        pass
