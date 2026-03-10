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
                    last_swiped_at TIMESTAMP,
                    hebrew_birth_day INTEGER,
                    hebrew_birth_month INTEGER,
                    hebrew_birth_year INTEGER,
                    gender TEXT,
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

            # Core Settings (local sync settings table)
            cur.execute('''
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Time Bonus Schedules
            cur.execute('''
                CREATE TABLE IF NOT EXISTS time_bonus_schedules (
                    id BIGSERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    group_name TEXT,
                    start_time TEXT,
                    end_time TEXT,
                    bonus_points INTEGER DEFAULT 0,
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

            # Time Bonus Given
            cur.execute('''
                CREATE TABLE IF NOT EXISTS time_bonus_given (
                    id BIGSERIAL PRIMARY KEY,
                    student_id BIGINT NOT NULL,
                    bonus_schedule_id BIGINT NOT NULL,
                    given_date DATE NOT NULL,
                    given_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(student_id, bonus_schedule_id, given_date)
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

            cur.execute('''
                CREATE TABLE IF NOT EXISTS messages (
                    id BIGSERIAL PRIMARY KEY,
                    message_type TEXT NOT NULL,
                    message_text TEXT NOT NULL,
                    points_threshold INTEGER,
                    student_id BIGINT,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            cur.execute('''
                CREATE TABLE IF NOT EXISTS static_messages (
                    id BIGSERIAL PRIMARY KEY,
                    message TEXT NOT NULL,
                    show_always INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS threshold_messages (
                    id BIGSERIAL PRIMARY KEY,
                    min_points INTEGER NOT NULL,
                    max_points INTEGER NOT NULL,
                    message TEXT NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS news_items (
                    id BIGSERIAL PRIMARY KEY,
                    text TEXT NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    sort_order INTEGER,
                    start_date TEXT,
                    end_date TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS ads_items (
                    id BIGSERIAL PRIMARY KEY,
                    text TEXT NOT NULL,
                    image_path TEXT,
                    is_active INTEGER DEFAULT 1,
                    sort_order INTEGER,
                    start_date TEXT,
                    end_date TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS student_messages (
                    id BIGSERIAL PRIMARY KEY,
                    student_id BIGINT NOT NULL,
                    message TEXT NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            cur.execute('''
                CREATE TABLE IF NOT EXISTS product_categories (
                    id BIGSERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    sort_order INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    show_in_catalog INTEGER DEFAULT 1,
                    max_items_per_student INTEGER,
                    max_items_per_class INTEGER,
                    min_points_required INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(name)
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS products (
                    id BIGSERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    display_name TEXT,
                    image_path TEXT,
                    category_id BIGINT,
                    price_points INTEGER DEFAULT 0,
                    stock_qty INTEGER,
                    deduct_points INTEGER DEFAULT 1,
                    sort_order INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    allowed_classes TEXT,
                    min_points_required INTEGER DEFAULT 0,
                    max_per_student INTEGER,
                    max_per_class INTEGER,
                    price_override_min_points INTEGER,
                    price_override_points INTEGER,
                    price_override_discount_pct INTEGER,
                    consolidated_voucher INTEGER DEFAULT 0,
                    voucher_per_unit INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS product_variants (
                    id BIGSERIAL PRIMARY KEY,
                    product_id BIGINT NOT NULL,
                    variant_name TEXT NOT NULL,
                    display_name TEXT,
                    price_points INTEGER DEFAULT 0,
                    stock_qty INTEGER,
                    deduct_points INTEGER DEFAULT 1,
                    is_active INTEGER DEFAULT 1,
                    sort_order INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS cashier_responsibles (
                    student_id BIGINT PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS purchases_log (
                    id BIGSERIAL PRIMARY KEY,
                    student_id BIGINT,
                    product_id BIGINT,
                    variant_id BIGINT,
                    qty INTEGER DEFAULT 1,
                    points_each INTEGER DEFAULT 0,
                    total_points INTEGER DEFAULT 0,
                    deduct_points INTEGER DEFAULT 1,
                    station_type TEXT,
                    is_refunded INTEGER DEFAULT 0,
                    refunded_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS refunds_log (
                    id BIGSERIAL PRIMARY KEY,
                    purchase_id BIGINT NOT NULL,
                    student_id BIGINT NOT NULL,
                    refunded_points INTEGER DEFAULT 0,
                    qty INTEGER DEFAULT 1,
                    product_id BIGINT,
                    variant_id BIGINT,
                    reason TEXT,
                    approved_by_teacher_id BIGINT,
                    approved_by_teacher_name TEXT,
                    station_type TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            cur.execute('''
                CREATE TABLE IF NOT EXISTS card_blocks (
                    id BIGSERIAL PRIMARY KEY,
                    student_id BIGINT NOT NULL,
                    card_number TEXT NOT NULL,
                    block_start TIMESTAMP NOT NULL,
                    block_end TIMESTAMP NOT NULL,
                    block_reason TEXT,
                    violation_count INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS card_validations (
                    id BIGSERIAL PRIMARY KEY,
                    student_id BIGINT NOT NULL,
                    card_number TEXT NOT NULL,
                    validated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS anti_spam_events (
                    id BIGSERIAL PRIMARY KEY,
                    student_id BIGINT NOT NULL,
                    card_number TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    rule_count INTEGER,
                    rule_minutes INTEGER,
                    duration_minutes INTEGER,
                    recent_count INTEGER,
                    message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS swipe_log (
                    id BIGSERIAL PRIMARY KEY,
                    student_id BIGINT,
                    card_number TEXT,
                    station_type TEXT,
                    swiped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            cur.execute('''
                CREATE TABLE IF NOT EXISTS public_closures (
                    id BIGSERIAL PRIMARY KEY,
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

            cur.execute('''
                CREATE TABLE IF NOT EXISTS activities (
                    id BIGSERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    points INTEGER DEFAULT 0,
                    print_code TEXT,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            cur.execute('''
                CREATE TABLE IF NOT EXISTS activity_schedules (
                    id BIGSERIAL PRIMARY KEY,
                    activity_id BIGINT NOT NULL,
                    start_time TEXT,
                    end_time TEXT,
                    days_of_week TEXT,
                    start_date TEXT,
                    end_date TEXT,
                    is_general INTEGER DEFAULT 1,
                    classes TEXT,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS activity_claims (
                    id BIGSERIAL PRIMARY KEY,
                    activity_id BIGINT NOT NULL,
                    student_id BIGINT NOT NULL,
                    claim_date TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS scheduled_services (
                    id BIGSERIAL PRIMARY KEY,
                    product_id BIGINT NOT NULL,
                    duration_minutes INTEGER NOT NULL DEFAULT 10,
                    capacity_per_slot INTEGER NOT NULL DEFAULT 1,
                    start_time TEXT NOT NULL,
                    end_time TEXT NOT NULL,
                    allow_auto_time INTEGER DEFAULT 1,
                    max_per_student INTEGER,
                    max_per_class INTEGER,
                    queue_priority_mode TEXT DEFAULT 'class_asc',
                    queue_priority_custom TEXT,
                    allowed_classes TEXT,
                    min_points_required INTEGER DEFAULT 0,
                    class_grouping INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS scheduled_service_dates (
                    id BIGSERIAL PRIMARY KEY,
                    service_id BIGINT NOT NULL,
                    service_date TEXT NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS scheduled_service_reservations (
                    id BIGSERIAL PRIMARY KEY,
                    service_id BIGINT NOT NULL,
                    student_id BIGINT NOT NULL,
                    purchase_id BIGINT,
                    service_date TEXT NOT NULL,
                    slot_start_time TEXT NOT NULL,
                    duration_minutes INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            cur.execute('''
                CREATE TABLE IF NOT EXISTS teacher_bonus (
                    teacher_id BIGINT PRIMARY KEY,
                    bonus_points INTEGER NOT NULL DEFAULT 0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS student_tier_state (
                    student_id BIGINT PRIMARY KEY,
                    last_tier_index INTEGER,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
                'ALTER TABLE students ADD COLUMN IF NOT EXISTS serial_number TEXT',
                'ALTER TABLE students ADD COLUMN IF NOT EXISTS hebrew_birth_day INTEGER',
                'ALTER TABLE students ADD COLUMN IF NOT EXISTS hebrew_birth_month INTEGER',
                'ALTER TABLE students ADD COLUMN IF NOT EXISTS hebrew_birth_year INTEGER',
                'ALTER TABLE students ADD COLUMN IF NOT EXISTS gender TEXT',
                'ALTER TABLE students ADD COLUMN IF NOT EXISTS last_swiped_at TIMESTAMP',

                # Time bonus columns
                'ALTER TABLE time_bonus_schedules ADD COLUMN IF NOT EXISTS group_name TEXT',
                'ALTER TABLE time_bonus_schedules ADD COLUMN IF NOT EXISTS start_time TEXT',
                'ALTER TABLE time_bonus_schedules ADD COLUMN IF NOT EXISTS end_time TEXT',
                'ALTER TABLE time_bonus_schedules ADD COLUMN IF NOT EXISTS bonus_points INTEGER DEFAULT 0',
                'ALTER TABLE time_bonus_schedules ADD COLUMN IF NOT EXISTS sound_key TEXT',
                'ALTER TABLE time_bonus_schedules ADD COLUMN IF NOT EXISTS is_general INTEGER DEFAULT 1',
                'ALTER TABLE time_bonus_schedules ADD COLUMN IF NOT EXISTS classes TEXT',
                'ALTER TABLE time_bonus_schedules ADD COLUMN IF NOT EXISTS days_of_week TEXT',
                'ALTER TABLE time_bonus_schedules ADD COLUMN IF NOT EXISTS is_shown_public INTEGER DEFAULT 1',
                'ALTER TABLE time_bonus_schedules ADD COLUMN IF NOT EXISTS is_active INTEGER DEFAULT 1',
                'ALTER TABLE time_bonus_schedules ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP',
                'ALTER TABLE time_bonus_schedules ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP',
                'ALTER TABLE time_bonus_given ADD COLUMN IF NOT EXISTS given_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP'
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
                    last_swiped_at TIMESTAMP,
                    hebrew_birth_day INTEGER,
                    hebrew_birth_month INTEGER,
                    hebrew_birth_year INTEGER,
                    gender TEXT,
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

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS time_bonus_schedules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    group_name TEXT,
                    start_time TEXT,
                    end_time TEXT,
                    bonus_points INTEGER DEFAULT 0,
                    sound_key TEXT,
                    is_general INTEGER DEFAULT 1,
                    classes TEXT,
                    days_of_week TEXT,
                    is_shown_public INTEGER DEFAULT 1,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS time_bonus_given (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    student_id INTEGER NOT NULL,
                    bonus_schedule_id INTEGER NOT NULL,
                    given_date DATE NOT NULL,
                    given_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(student_id, bonus_schedule_id, given_date)
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_type TEXT NOT NULL,
                    message_text TEXT NOT NULL,
                    points_threshold INTEGER,
                    student_id INTEGER,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS static_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message TEXT NOT NULL,
                    show_always INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS threshold_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    min_points INTEGER NOT NULL,
                    max_points INTEGER NOT NULL,
                    message TEXT NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS news_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    sort_order INTEGER,
                    start_date TEXT,
                    end_date TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS ads_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT NOT NULL,
                    image_path TEXT,
                    is_active INTEGER DEFAULT 1,
                    sort_order INTEGER,
                    start_date TEXT,
                    end_date TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS student_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    student_id INTEGER NOT NULL,
                    message TEXT NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS product_categories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    sort_order INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    show_in_catalog INTEGER DEFAULT 1,
                    max_items_per_student INTEGER,
                    max_items_per_class INTEGER,
                    min_points_required INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(name)
                );
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
                    allowed_classes TEXT,
                    min_points_required INTEGER DEFAULT 0,
                    max_per_student INTEGER,
                    max_per_class INTEGER,
                    price_override_min_points INTEGER,
                    price_override_points INTEGER,
                    price_override_discount_pct INTEGER,
                    consolidated_voucher INTEGER DEFAULT 0,
                    voucher_per_unit INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
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
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS cashier_responsibles (
                    student_id INTEGER PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

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
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS refunds_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    purchase_id INTEGER NOT NULL,
                    student_id INTEGER NOT NULL,
                    refunded_points INTEGER DEFAULT 0,
                    qty INTEGER DEFAULT 1,
                    product_id INTEGER,
                    variant_id INTEGER,
                    reason TEXT,
                    approved_by_teacher_id INTEGER,
                    approved_by_teacher_name TEXT,
                    station_type TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS card_blocks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    student_id INTEGER NOT NULL,
                    card_number TEXT NOT NULL,
                    block_start TIMESTAMP NOT NULL,
                    block_end TIMESTAMP NOT NULL,
                    block_reason TEXT,
                    violation_count INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS card_validations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    student_id INTEGER NOT NULL,
                    card_number TEXT NOT NULL,
                    validated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
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
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS swipe_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    student_id INTEGER,
                    card_number TEXT,
                    station_type TEXT,
                    swiped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

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
                );

                CREATE TABLE IF NOT EXISTS activities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT,
                    points INTEGER DEFAULT 0,
                    print_code TEXT,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
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
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS activity_claims (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    activity_id INTEGER NOT NULL,
                    student_id INTEGER NOT NULL,
                    claim_date TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS scheduled_services (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id INTEGER NOT NULL,
                    duration_minutes INTEGER NOT NULL DEFAULT 10,
                    capacity_per_slot INTEGER NOT NULL DEFAULT 1,
                    start_time TEXT NOT NULL,
                    end_time TEXT NOT NULL,
                    allow_auto_time INTEGER DEFAULT 1,
                    max_per_student INTEGER,
                    max_per_class INTEGER,
                    queue_priority_mode TEXT DEFAULT 'class_asc',
                    queue_priority_custom TEXT,
                    allowed_classes TEXT,
                    min_points_required INTEGER DEFAULT 0,
                    class_grouping INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS scheduled_service_dates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    service_id INTEGER NOT NULL,
                    service_date TEXT NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS scheduled_service_reservations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    service_id INTEGER NOT NULL,
                    student_id INTEGER NOT NULL,
                    purchase_id INTEGER,
                    service_date TEXT NOT NULL,
                    slot_start_time TEXT NOT NULL,
                    duration_minutes INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS teacher_bonus (
                    teacher_id INTEGER PRIMARY KEY,
                    bonus_points INTEGER NOT NULL DEFAULT 0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS student_tier_state (
                    student_id INTEGER PRIMARY KEY,
                    last_tier_index INTEGER,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            ''')
        else:
            # Ensure tables exist (if some are missing)
            conn.execute('''
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
                )
            ''')
            conn.execute('''
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
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS points_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    student_id INTEGER,
                    points INTEGER,
                    reason TEXT,
                    teacher_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS points_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    student_id INTEGER,
                    points INTEGER,
                    reason TEXT,
                    teacher_name TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.execute('CREATE TABLE IF NOT EXISTS web_settings (key TEXT PRIMARY KEY, value_json TEXT)')
            conn.execute('CREATE TABLE IF NOT EXISTS teacher_classes (teacher_id INTEGER, class_name TEXT, PRIMARY KEY (teacher_id, class_name))')

            conn.execute('''
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_type TEXT NOT NULL,
                    message_text TEXT NOT NULL,
                    points_threshold INTEGER,
                    student_id INTEGER,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS static_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message TEXT NOT NULL,
                    show_always INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS threshold_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    min_points INTEGER NOT NULL,
                    max_points INTEGER NOT NULL,
                    message TEXT NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS news_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    sort_order INTEGER,
                    start_date TEXT,
                    end_date TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS ads_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT NOT NULL,
                    image_path TEXT,
                    is_active INTEGER DEFAULT 1,
                    sort_order INTEGER,
                    start_date TEXT,
                    end_date TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS student_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    student_id INTEGER NOT NULL,
                    message TEXT NOT NULL,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            conn.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS time_bonus_schedules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL, group_name TEXT, start_time TEXT, end_time TEXT,
                    bonus_points INTEGER DEFAULT 0, sound_key TEXT, is_general INTEGER DEFAULT 1,
                    classes TEXT, days_of_week TEXT, is_shown_public INTEGER DEFAULT 1,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS time_bonus_given (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    student_id INTEGER NOT NULL, bonus_schedule_id INTEGER NOT NULL,
                    given_date DATE NOT NULL, given_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(student_id, bonus_schedule_id, given_date)
                )
            ''')

            conn.execute('''
                CREATE TABLE IF NOT EXISTS product_categories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                    sort_order INTEGER DEFAULT 0, is_active INTEGER DEFAULT 1,
                    show_in_catalog INTEGER DEFAULT 1, max_items_per_student INTEGER,
                    max_items_per_class INTEGER, min_points_required INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(name)
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                    display_name TEXT, image_path TEXT, category_id INTEGER,
                    price_points INTEGER DEFAULT 0, stock_qty INTEGER,
                    deduct_points INTEGER DEFAULT 1, sort_order INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1, allowed_classes TEXT,
                    min_points_required INTEGER DEFAULT 0, max_per_student INTEGER,
                    max_per_class INTEGER, price_override_min_points INTEGER,
                    price_override_points INTEGER, price_override_discount_pct INTEGER,
                    consolidated_voucher INTEGER DEFAULT 0, voucher_per_unit INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS product_variants (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, product_id INTEGER NOT NULL,
                    variant_name TEXT NOT NULL, display_name TEXT,
                    price_points INTEGER DEFAULT 0, stock_qty INTEGER,
                    deduct_points INTEGER DEFAULT 1, is_active INTEGER DEFAULT 1,
                    sort_order INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.execute('CREATE TABLE IF NOT EXISTS cashier_responsibles (student_id INTEGER PRIMARY KEY, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS purchases_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER,
                    product_id INTEGER, variant_id INTEGER, qty INTEGER DEFAULT 1,
                    points_each INTEGER DEFAULT 0, total_points INTEGER DEFAULT 0,
                    deduct_points INTEGER DEFAULT 1, station_type TEXT,
                    is_refunded INTEGER DEFAULT 0, refunded_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS refunds_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, purchase_id INTEGER NOT NULL,
                    student_id INTEGER NOT NULL, refunded_points INTEGER DEFAULT 0,
                    qty INTEGER DEFAULT 1, product_id INTEGER, variant_id INTEGER,
                    reason TEXT, approved_by_teacher_id INTEGER,
                    approved_by_teacher_name TEXT, station_type TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            conn.execute('''
                CREATE TABLE IF NOT EXISTS card_blocks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER NOT NULL,
                    card_number TEXT NOT NULL, block_start TIMESTAMP NOT NULL,
                    block_end TIMESTAMP NOT NULL, block_reason TEXT,
                    violation_count INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS card_validations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER NOT NULL,
                    card_number TEXT NOT NULL, validated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS anti_spam_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER NOT NULL,
                    card_number TEXT NOT NULL, event_type TEXT NOT NULL,
                    rule_count INTEGER, rule_minutes INTEGER, duration_minutes INTEGER,
                    recent_count INTEGER, message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS swipe_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, student_id INTEGER,
                    card_number TEXT, station_type TEXT,
                    swiped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            conn.execute('''
                CREATE TABLE IF NOT EXISTS public_closures (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
                    subtitle TEXT, start_at TEXT NOT NULL, end_at TEXT NOT NULL,
                    repeat_weekly INTEGER DEFAULT 0, weekly_start_day TEXT,
                    weekly_start_time TEXT, weekly_end_day TEXT, weekly_end_time TEXT,
                    image_path_portrait TEXT, image_path_landscape TEXT,
                    enabled INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            conn.execute('''
                CREATE TABLE IF NOT EXISTS activities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                    description TEXT, points INTEGER DEFAULT 0, print_code TEXT,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS activity_schedules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, activity_id INTEGER NOT NULL,
                    start_time TEXT, end_time TEXT, days_of_week TEXT,
                    start_date TEXT, end_date TEXT, is_general INTEGER DEFAULT 1,
                    classes TEXT, is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS activity_claims (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, activity_id INTEGER NOT NULL,
                    student_id INTEGER NOT NULL, claim_date TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            conn.execute('''
                CREATE TABLE IF NOT EXISTS scheduled_services (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, product_id INTEGER NOT NULL,
                    duration_minutes INTEGER NOT NULL DEFAULT 10,
                    capacity_per_slot INTEGER NOT NULL DEFAULT 1,
                    start_time TEXT NOT NULL, end_time TEXT NOT NULL,
                    allow_auto_time INTEGER DEFAULT 1, max_per_student INTEGER,
                    max_per_class INTEGER, queue_priority_mode TEXT DEFAULT 'class_asc',
                    queue_priority_custom TEXT, allowed_classes TEXT,
                    min_points_required INTEGER DEFAULT 0, class_grouping INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS scheduled_service_dates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, service_id INTEGER NOT NULL,
                    service_date TEXT NOT NULL, is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS scheduled_service_reservations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, service_id INTEGER NOT NULL,
                    student_id INTEGER NOT NULL, purchase_id INTEGER,
                    service_date TEXT NOT NULL, slot_start_time TEXT NOT NULL,
                    duration_minutes INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            conn.execute('CREATE TABLE IF NOT EXISTS teacher_bonus (teacher_id INTEGER PRIMARY KEY, bonus_points INTEGER NOT NULL DEFAULT 0, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
            conn.execute('CREATE TABLE IF NOT EXISTS student_tier_state (student_id INTEGER PRIMARY KEY, last_tier_index INTEGER, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')

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
