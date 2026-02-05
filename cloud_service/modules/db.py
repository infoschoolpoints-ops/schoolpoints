import os
import sqlite3
import logging
from typing import Any, List, Dict, Tuple, Set

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    psycopg2 = None
    psycopg2_extras = None

from .config import USE_POSTGRES, DATABASE_URL, DATA_DIR, DB_PATH

logger = logging.getLogger("schoolpoints.db")

def get_db_connection():
    """Get a database connection (Postgres or SQLite)."""
    if USE_POSTGRES:
        if psycopg2 is None:
            raise RuntimeError('DATABASE_URL is set but psycopg2 is not installed')
        return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def sql_placeholder(sql: str) -> str:
    """Replace ? with %s for Postgres if needed."""
    if not USE_POSTGRES:
        return sql
    return sql.replace('?', '%s')

def integrity_errors() -> Tuple[Any, ...]:
    """Return tuple of integrity error classes."""
    errs = [sqlite3.IntegrityError]
    if psycopg2 is not None:
        errs.append(psycopg2.IntegrityError)
    return tuple(errs)

def tenant_schema(tenant_id: str) -> str:
    """Get schema name for tenant."""
    safe = ''.join([c for c in str(tenant_id or '').strip().lower() if (c.isalnum() or c == '_')])
    if not safe:
        safe = 'unknown'
    if safe[0].isdigit():
        safe = f"t_{safe}"
    return f"tenant_{safe}"

def table_columns(conn, table: str) -> List[str]:
    """Get column names for a table (Postgres or SQLite)."""
    if USE_POSTGRES:
        return _table_columns_postgres(conn, table)
    return _table_columns_sqlite(conn, table)

def _table_columns_sqlite(conn: sqlite3.Connection, table: str) -> List[str]:
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    rows = cur.fetchall() or []
    return [str(r['name']) for r in rows]

def _table_columns_postgres(conn, table: str) -> List[str]:
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = %s ORDER BY ordinal_position",
            (table,)
        )
        rows = cur.fetchall() or []
        if not rows:
            # Fallback for schema-based tables if needed, usually search_path handles it if set
            pass
        return [r['column_name'] for r in rows]
    except Exception:
        return []

def ensure_tenant_db_exists(tenant_id: str) -> str:
    """Ensure tenant DB exists (Schema for PG, File for SQLite). Returns path or schema."""
    if USE_POSTGRES:
        schema = tenant_schema(tenant_id)
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
            
            # Create tables in schema
            cur.execute(f'SET search_path TO "{schema}", public')
            
            # Teachers
            cur.execute('''
                CREATE TABLE IF NOT EXISTS teachers (
                    id INTEGER PRIMARY KEY,
                    name TEXT,
                    card_number TEXT,
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
                    bonus_points_reset_date DATE
                )
            ''')
            
            # Students
            cur.execute('''
                CREATE TABLE IF NOT EXISTS students (
                    id SERIAL PRIMARY KEY,
                    serial_number TEXT,
                    last_name TEXT,
                    first_name TEXT,
                    class_name TEXT,
                    points INTEGER DEFAULT 0,
                    private_message TEXT,
                    card_number TEXT,
                    id_number TEXT,
                    photo_number TEXT,
                    is_free_fix_blocked INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Points Log
            cur.execute('''
                CREATE TABLE IF NOT EXISTS points_log (
                    id SERIAL PRIMARY KEY,
                    student_id INTEGER,
                    points INTEGER,
                    reason TEXT,
                    teacher_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Points History
            cur.execute('''
                CREATE TABLE IF NOT EXISTS points_history (
                    id SERIAL PRIMARY KEY,
                    student_id INTEGER,
                    points_before INTEGER,
                    points_change INTEGER,
                    points_after INTEGER,
                    reason TEXT,
                    teacher_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Web Settings
            cur.execute('''
                CREATE TABLE IF NOT EXISTS web_settings (
                    key TEXT PRIMARY KEY,
                    value_json TEXT
                )
            ''')
            
            # Teacher Classes (Many-to-Many)
            cur.execute('''
                CREATE TABLE IF NOT EXISTS teacher_classes (
                    teacher_id INTEGER,
                    class_name TEXT,
                    PRIMARY KEY (teacher_id, class_name)
                )
            ''')

            # --- MIGRATIONS (Postgres) ---
            # Attempt to add columns if they don't exist. 
            # This is a simple migration strategy: Try ADD COLUMN, ignore if exists.
            
            # Teachers extra columns
            migrate_sqls = [
                'ALTER TABLE teachers ADD COLUMN IF NOT EXISTS card_number2 TEXT',
                'ALTER TABLE teachers ADD COLUMN IF NOT EXISTS card_number3 TEXT',
                'ALTER TABLE teachers ADD COLUMN IF NOT EXISTS can_edit_student_card INTEGER DEFAULT 1',
                'ALTER TABLE teachers ADD COLUMN IF NOT EXISTS can_edit_student_photo INTEGER DEFAULT 1',
                'ALTER TABLE teachers ADD COLUMN IF NOT EXISTS bonus_max_points_per_student INTEGER',
                'ALTER TABLE teachers ADD COLUMN IF NOT EXISTS bonus_max_total_runs INTEGER',
                'ALTER TABLE teachers ADD COLUMN IF NOT EXISTS bonus_runs_used INTEGER DEFAULT 0',
                'ALTER TABLE teachers ADD COLUMN IF NOT EXISTS bonus_runs_reset_date DATE',
                'ALTER TABLE teachers ADD COLUMN IF NOT EXISTS bonus_points_used INTEGER DEFAULT 0',
                'ALTER TABLE teachers ADD COLUMN IF NOT EXISTS bonus_points_reset_date DATE',
                
                # Students extra columns
                'ALTER TABLE students ADD COLUMN IF NOT EXISTS photo_number TEXT',
                'ALTER TABLE students ADD COLUMN IF NOT EXISTS is_free_fix_blocked INTEGER DEFAULT 0',
                'ALTER TABLE students ADD COLUMN IF NOT EXISTS serial_number TEXT'
            ]
            
            for sql in migrate_sqls:
                try:
                    cur.execute(sql)
                except Exception:
                    conn.rollback() 
                    # In PG inside transaction, error invalidates it. 
                    # Use SAVEPOINT if needed, but here we might be in auto-commit or need careful handling.
                    # Actually with psycopg2 default, we are in transaction. 
                    # "IF NOT EXISTS" handles the error for PG 9.6+.
                    # If older PG, it might fail. assuming recent PG.
                    pass
            
            conn.commit()
            return schema
        finally:
            conn.close()
            
    else:
        # SQLite
        os.makedirs(DATA_DIR, exist_ok=True)
        db_path = os.path.join(DATA_DIR, f"{tenant_id}.db")
        is_new_db = not os.path.exists(db_path)
        
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        
        if is_new_db:
            # Create new DB
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS teachers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT,
                    card_number TEXT,
                    card_number2 TEXT,
                    card_number3 TEXT,
                    is_admin INTEGER DEFAULT 0,
                    can_edit_student_card INTEGER DEFAULT 1,
                    can_edit_student_photo INTEGER DEFAULT 1,
                    bonus_max_points_per_student INTEGER,
                    bonus_max_total_runs INTEGER,
                    bonus_runs_used INTEGER DEFAULT 0,
                    bonus_runs_reset_date TEXT,
                    bonus_points_used INTEGER DEFAULT 0,
                    bonus_points_reset_date TEXT
                );
                CREATE TABLE IF NOT EXISTS students (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    serial_number TEXT,
                    last_name TEXT,
                    first_name TEXT,
                    class_name TEXT,
                    points INTEGER DEFAULT 0,
                    private_message TEXT,
                    card_number TEXT,
                    id_number TEXT,
                    photo_number TEXT,
                    is_free_fix_blocked INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS points_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    student_id INTEGER,
                    points INTEGER,
                    reason TEXT,
                    teacher_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS points_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    student_id INTEGER,
                    points INTEGER,
                    reason TEXT,
                    teacher_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS web_settings (
                    key TEXT PRIMARY KEY,
                    value_json TEXT
                );
                CREATE TABLE IF NOT EXISTS teacher_classes (
                    teacher_id INTEGER,
                    class_name TEXT,
                    PRIMARY KEY (teacher_id, class_name)
                );
            ''')
        else:
            # Ensure tables exist (if some are missing)
            conn.execute('CREATE TABLE IF NOT EXISTS web_settings (key TEXT PRIMARY KEY, value_json TEXT)')
            conn.execute('CREATE TABLE IF NOT EXISTS teacher_classes (teacher_id INTEGER, class_name TEXT, PRIMARY KEY (teacher_id, class_name))')
            
            # --- MIGRATIONS (SQLite) ---
            # SQLite doesn't support IF NOT EXISTS in ADD COLUMN nicely in all versions or multi-statement
            # We check columns manually
            
            def _ensure_col(table, col, def_sql):
                try:
                    conn.execute(f'SELECT {col} FROM {table} LIMIT 1')
                except Exception:
                    # Column missing, add it
                    try:
                        conn.execute(f'ALTER TABLE {table} ADD COLUMN {col} {def_sql}')
                    except Exception as e:
                        logger.warning(f"Failed to add column {col} to {table}: {e}")

            _ensure_col('teachers', 'card_number2', 'TEXT')
            _ensure_col('teachers', 'card_number3', 'TEXT')
            _ensure_col('teachers', 'can_edit_student_card', 'INTEGER DEFAULT 1')
            _ensure_col('teachers', 'can_edit_student_photo', 'INTEGER DEFAULT 1')
            _ensure_col('teachers', 'bonus_max_points_per_student', 'INTEGER')
            _ensure_col('teachers', 'bonus_max_total_runs', 'INTEGER')
            _ensure_col('teachers', 'bonus_runs_used', 'INTEGER DEFAULT 0')
            _ensure_col('teachers', 'bonus_runs_reset_date', 'TEXT')
            _ensure_col('teachers', 'bonus_points_used', 'INTEGER DEFAULT 0')
            _ensure_col('teachers', 'bonus_points_reset_date', 'TEXT')
            
            _ensure_col('students', 'photo_number', 'TEXT')
            _ensure_col('students', 'is_free_fix_blocked', 'INTEGER DEFAULT 0')
            _ensure_col('students', 'serial_number', 'TEXT')

        conn.commit()
        conn.close()
        return db_path

def generate_numeric_tenant_id(conn) -> str:
    """Generate a unique 8-digit tenant ID."""
    import secrets
    import datetime
    cur = conn.cursor()
    for _ in range(30):
        try:
            cand = str(secrets.randbelow(10**8)).zfill(8)
        except Exception:
            cand = str(int(datetime.datetime.utcnow().timestamp()))
        if not cand or cand[0] == '0':
            continue
        try:
            cur.execute(sql_placeholder('SELECT 1 FROM institutions WHERE tenant_id = ? LIMIT 1'), (cand,))
            if not cur.fetchone():
                return cand
        except Exception:
            continue
    return str(int(datetime.datetime.utcnow().timestamp()))

def tenant_db_connection(tenant_id: str):
    """Get connection to specific tenant DB."""
    if USE_POSTGRES:
        tid = str(tenant_id or '').strip()
        if not tid:
            raise ValueError("Missing tenant_id")
        ensure_tenant_db_exists(tid)
        schema = tenant_schema(tid)
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(f'SET search_path TO "{schema}", public')
        return conn
    
    db_path = ensure_tenant_db_exists(tenant_id)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def delete_tenant_db(tenant_id: str) -> bool:
    """Delete tenant database (Schema for PG, File for SQLite)."""
    if not tenant_id:
        return False
        
    if USE_POSTGRES:
        schema = tenant_schema(tenant_id)
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to delete tenant schema {schema}: {e}")
            return False
        finally:
            conn.close()
    else:
        # SQLite
        db_path = os.path.join(DATA_DIR, f"{tenant_id}.db")
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
                return True
            except Exception as e:
                logger.error(f"Failed to delete tenant DB file {db_path}: {e}")
                return False
        return True

def ensure_pending_registrations_table() -> None:
    """Ensure the pending_registrations table exists."""
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        try:
            if USE_POSTGRES:
                cur.execute(
                    '''
                    CREATE TABLE IF NOT EXISTS pending_registrations (
                        id BIGSERIAL PRIMARY KEY,
                        institution_name TEXT NOT NULL,
                        institution_code TEXT,
                        contact_name TEXT,
                        email TEXT NOT NULL,
                        phone TEXT,
                        password_hash TEXT,
                        plan TEXT,
                        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        payment_status TEXT DEFAULT 'pending',
                        payment_id TEXT
                    )
                    '''
                )
            else:
                cur.execute(
                    '''
                    CREATE TABLE IF NOT EXISTS pending_registrations (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        institution_name TEXT NOT NULL,
                        institution_code TEXT,
                        contact_name TEXT,
                        email TEXT NOT NULL,
                        phone TEXT,
                        password_hash TEXT,
                        plan TEXT,
                        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                        payment_status TEXT DEFAULT 'pending',
                        payment_id TEXT
                    )
                    '''
                )
        except Exception:
            pass

        try:
            if USE_POSTGRES:
                cur.execute('ALTER TABLE pending_registrations ADD COLUMN IF NOT EXISTS institution_code TEXT')
            else:
                # SQLite ALTER TABLE ADD COLUMN does not support IF NOT EXISTS in all versions, 
                # but we can try and ignore error
                cur.execute('ALTER TABLE pending_registrations ADD COLUMN institution_code TEXT')
        except Exception:
            pass
        conn.commit()
    finally:
        try: conn.close()
        except: pass
