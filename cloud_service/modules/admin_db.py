"""Admin DB migration and helpers for super-admin dashboard."""
import json
import logging
from .db import get_db_connection, sql_placeholder, tenant_db_connection
from .config import USE_POSTGRES

logger = logging.getLogger("schoolpoints.admin_db")
_ensured = False

_INST_COLS = [
    "contact_name TEXT DEFAULT ''",
    "email TEXT DEFAULT ''",
    "phone TEXT DEFAULT ''",
    "plan TEXT DEFAULT 'trial'",
    "last_login TEXT DEFAULT ''",
    "login_count INTEGER DEFAULT 0",
    "custom_price TEXT DEFAULT ''",
    "license_expiry TEXT DEFAULT ''",
    "notes TEXT DEFAULT ''",
    "max_stations INTEGER DEFAULT 2",
    "api_key TEXT DEFAULT ''",
]

# (plan_key, display_name, price_monthly, description, features_json, max_stations, is_active, sort_order, duration_months, is_featured, is_visible)
_DEFAULT_PLANS = [
    ('short', 'מסלול קצר', 700, 'תשלום ל-2 חודשים', '["גישה מלאה לכל הפיצ\u05f3רים","סנכרון ענן","עמדות ללא הגבלה","תמיכה מלאה"]', 999, 1, 1, 2, 0, 1),
    ('annual', 'מסלול שנתי', 200, 'תשלום חודשי ל-12 חודשים', '["גישה מלאה לכל הפיצ\u05f3רים","סנכרון ענן","עמדות ללא הגבלה","תמיכה מלאה","חיסכון משמעותי!"]', 999, 1, 2, 12, 1, 1),
]


def ensure_admin_tables():
    """Ensure all admin-related tables and columns exist."""
    global _ensured
    if _ensured:
        return
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        # institutions extra columns
        for col_def in _INST_COLS:
            try:
                if USE_POSTGRES:
                    cur.execute(f"ALTER TABLE institutions ADD COLUMN IF NOT EXISTS {col_def}")
                else:
                    cur.execute(f"ALTER TABLE institutions ADD COLUMN {col_def}")
                conn.commit()
            except Exception:
                try: conn.rollback()
                except: pass

        # plan_config
        cur.execute("""CREATE TABLE IF NOT EXISTS plan_config (
            plan_key TEXT PRIMARY KEY, display_name TEXT NOT NULL,
            price_monthly INTEGER DEFAULT 0, description TEXT DEFAULT '',
            features_json TEXT DEFAULT '[]', max_stations INTEGER DEFAULT 2,
            is_active INTEGER DEFAULT 1, sort_order INTEGER DEFAULT 0,
            duration_months INTEGER DEFAULT 1, is_featured INTEGER DEFAULT 0,
            is_visible INTEGER DEFAULT 1)""")
        conn.commit()
        # Add new columns if table existed before migration
        for _new_col in ['duration_months INTEGER DEFAULT 1', 'is_featured INTEGER DEFAULT 0', 'is_visible INTEGER DEFAULT 1']:
            try:
                if USE_POSTGRES:
                    cur.execute(f'ALTER TABLE plan_config ADD COLUMN IF NOT EXISTS {_new_col}')
                else:
                    cur.execute(f'ALTER TABLE plan_config ADD COLUMN {_new_col}')
                conn.commit()
            except Exception:
                try: conn.rollback()
                except: pass

        # seed defaults
        cur.execute("SELECT COUNT(*) FROM plan_config")
        row = cur.fetchone()
        cnt = int(list(row.values())[0] if isinstance(row, dict) else row[0])
        if cnt == 0:
            for p in _DEFAULT_PLANS:
                cur.execute(sql_placeholder(
                    "INSERT INTO plan_config (plan_key,display_name,price_monthly,description,features_json,max_stations,is_active,sort_order,duration_months,is_featured,is_visible)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?)"), p)
            conn.commit()

        # institution_payments
        cur.execute("""CREATE TABLE IF NOT EXISTS institution_payments (
            id BIGSERIAL PRIMARY KEY,
            tenant_id TEXT NOT NULL, amount INTEGER DEFAULT 0,
            payment_date TEXT, payment_method TEXT DEFAULT '',
            reference TEXT DEFAULT '', notes TEXT DEFAULT '',
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP)""" if USE_POSTGRES else
            """CREATE TABLE IF NOT EXISTS institution_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL, amount INTEGER DEFAULT 0,
            payment_date TEXT, payment_method TEXT DEFAULT '',
            reference TEXT DEFAULT '', notes TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        conn.commit()

        # admin_staff
        cur.execute("""CREATE TABLE IF NOT EXISTS admin_staff (
            id BIGSERIAL PRIMARY KEY,
            username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
            display_name TEXT DEFAULT '', role TEXT DEFAULT 'viewer',
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP)""" if USE_POSTGRES else
            """CREATE TABLE IF NOT EXISTS admin_staff (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
            display_name TEXT DEFAULT '', role TEXT DEFAULT 'viewer',
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        conn.commit()

        # admin_audit_log
        cur.execute("""CREATE TABLE IF NOT EXISTS admin_audit_log (
            id BIGSERIAL PRIMARY KEY,
            admin_user TEXT, action TEXT, target TEXT,
            details TEXT DEFAULT '',
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP)""" if USE_POSTGRES else
            """CREATE TABLE IF NOT EXISTS admin_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_user TEXT, action TEXT, target TEXT,
            details TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        conn.commit()

        _ensured = True
    except Exception as e:
        logger.error(f"ensure_admin_tables error: {e}")
    finally:
        try: conn.close()
        except: pass


def get_tenant_stats(tenant_id: str) -> dict:
    """Get student/teacher/station counts for a tenant."""
    stats = {'students': 0, 'teachers': 0}
    try:
        conn = tenant_db_connection(tenant_id)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM students")
        r = cur.fetchone()
        stats['students'] = int(list(r.values())[0] if isinstance(r, dict) else r[0])
        cur.execute("SELECT COUNT(*) FROM teachers")
        r = cur.fetchone()
        stats['teachers'] = int(list(r.values())[0] if isinstance(r, dict) else r[0])
        conn.close()
    except Exception:
        pass
    return stats


def get_all_plans() -> list:
    """Return all plan configs as list of dicts."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM plan_config ORDER BY sort_order")
        rows = cur.fetchall() or []
        result = []
        for r in rows:
            if isinstance(r, dict):
                result.append(r)
            elif hasattr(r, 'keys'):
                result.append({k: r[k] for k in r.keys()})
        return result
    except Exception:
        return []
    finally:
        try: conn.close()
        except: pass


def verify_staff_login(username: str, password: str) -> dict | None:
    """Verify staff username+password. Returns staff dict or None."""
    from .auth import check_password_hash
    ensure_admin_tables()
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql_placeholder(
            "SELECT * FROM admin_staff WHERE username=? AND is_active=1 LIMIT 1"), (username,))
        row = cur.fetchone()
        if not row:
            return None
        d = row_to_dict(row)
        if check_password_hash(d.get('password_hash', ''), password):
            return d
        return None
    except Exception:
        return None
    finally:
        try: conn.close()
        except: pass


def row_to_dict(r) -> dict:
    """Convert a DB row to a plain dict."""
    if isinstance(r, dict):
        return r
    if hasattr(r, 'keys'):
        return {k: r[k] for k in r.keys()}
    return {}
