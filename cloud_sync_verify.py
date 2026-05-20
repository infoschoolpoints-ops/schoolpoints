#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
סקריפט בדיקה לסנכרון ענן — מסמלץ 'מחשב חדש' ללא קימפול.

שימוש:
  python cloud_sync_verify.py

מה הסקריפט עושה:
  1. טוען את פרטי הענן מ-config המקומי
  2. יוצר DB זמני נקי (מחשב חדש)
  3. מריץ את לוגיקת _do_cloud_initial_sync ישירות
  4. בודק כמה שורות הורדו לכל טבלה
  5. בודק אם הרשיון יובא
  6. מדפיס דוח מפורט
"""

import sys, os, json, sqlite3, tempfile, shutil

# Force UTF-8 output on Windows terminals
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# הוסף את תיקיית הפרויקט ל-path
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# ====== טעינת config ======
def _load_config():
    for env in ("PROGRAMDATA", "LOCALAPPDATA", "APPDATA"):
        root = os.environ.get(env, "")
        if root:
            p = os.path.join(root, "SchoolPoints", "config.json")
            if os.path.exists(p):
                with open(p, encoding="utf-8") as f:
                    return json.load(f)
    p = os.path.join(_HERE, "config.json")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return {}

# ====== גוף הבדיקה ======
def main():
    print("=" * 60)
    print("בדיקת סנכרון ענן — מסמלץ מחשב חדש")
    print("=" * 60)

    cfg = _load_config()
    tenant_id = str(cfg.get("sync_tenant_id") or "").strip()
    api_key    = str(cfg.get("sync_api_key")    or "").strip()
    push_url   = str(cfg.get("sync_push_url")   or "").strip()

    if not (tenant_id and api_key and push_url):
        print("\n❌ לא נמצאו פרטי ענן ב-config!")
        print(f"   sync_tenant_id : {tenant_id or '(ריק)'}")
        print(f"   sync_api_key   : {'***' if api_key else '(ריק)'}")
        print(f"   sync_push_url  : {push_url or '(ריק)'}")
        print("\nודא שהאדמין מחובר לענן (הגדרות ראשוניות → חיבור ענן).")
        return 1

    print(f"\n✓ נמצאו פרטי ענן:")
    print(f"   tenant_id : {tenant_id}")
    print(f"   api_key   : {'***' + api_key[-4:] if len(api_key) > 4 else '***'}")
    print(f"   push_url  : {push_url}")

    # DB זמני — מסמלץ מחשב חדש (ריק לחלוטין)
    tmpdir = tempfile.mkdtemp(prefix="sp_cloudtest_")
    tmp_db = os.path.join(tmpdir, "school_points.db")
    tmp_base = tmpdir
    print(f"\n→ יוצר DB זמני: {tmp_db}")

    try:
        # יצירת schema בסיסי (כמו DB חדש)
        _create_minimal_schema(tmp_db)

        # הרץ את לוגיקת הסנכרון
        print("\n→ מריץ pull_snapshot מהענן...")
        result = _run_sync(tmp_db, tenant_id, api_key, push_url)

        if not result["ok"]:
            print(f"\n❌ הסנכרון נכשל: {result.get('error')}")
            return 2

        # דוח תוצאות
        print("\n" + "=" * 60)
        print("דוח תוצאות:")
        print("=" * 60)
        snap_summary = result.get("snapshot_summary", {})
        total = sum(snap_summary.values())
        if snap_summary:
            for tbl, cnt in sorted(snap_summary.items()):
                mark = "✓" if cnt > 0 else "·"
                print(f"  {mark} {tbl:<40} {cnt} שורות")
        else:
            print("  (לא נמצאו טבלאות ב-snapshot)")
        print(f"\n  סה\"כ: {total} שורות ב-{len(snap_summary)} טבלאות")

        # בדיקת נתונים קריטיים
        _check_critical_tables(tmp_db, snap_summary)

        # בדיקת רשיון
        _check_license(tmp_db, tmp_base)

        if total > 0:
            print("\n✅ הסנכרון עבד — הנתונים יורדים מהענן בהצלחה!")
        else:
            print("\n⚠️  לא ירדו נתונים — הענן ריק, או שיש בעיה בסנכרון.")
        return 0

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _create_minimal_schema(db_path: str):
    """יוצר schema מינימלי ל-DB הזמני."""
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS teachers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT, card_number TEXT, pin_code TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT, card_number TEXT, class_name TEXT, points INTEGER DEFAULT 0,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY, value TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS sync_state (
                key TEXT PRIMARY KEY, value TEXT
            );
            CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY, content TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS static_messages (id INTEGER PRIMARY KEY, content TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY, name TEXT, price REAL, updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS product_categories (id INTEGER PRIMARY KEY, name TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS points_log (id INTEGER PRIMARY KEY, student_id INTEGER, delta INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        """)
        conn.commit()
    finally:
        conn.close()


def _run_sync(db_path: str, tenant_id: str, api_key: str, push_url: str) -> dict:
    """מריץ את לוגיקת הסנכרון ישירות."""
    import urllib.request, urllib.parse

    # חישוב snapshot_url
    snapshot_url = push_url
    if snapshot_url.endswith("/sync/push"):
        snapshot_url = snapshot_url[:-len("/sync/push")] + "/sync/snapshot"
    else:
        snapshot_url = snapshot_url.rstrip("/") + "/sync/snapshot"

    # שלב 1: verify
    print(f"   1. בודק חיבור ל-{snapshot_url.replace(snapshot_url.split('/sync/')[0], '<base>')}/sync/status")
    status_url = snapshot_url.replace("/sync/snapshot", "/sync/status")
    try:
        req = urllib.request.Request(
            status_url + "?tenant_id=" + urllib.parse.quote(tenant_id),
            headers={"Accept": "application/json", "api-key": api_key}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
        if not (isinstance(data, dict) and data.get("ok")):
            return {"ok": False, "error": f"sync/status לא אישר: {data}"}
        print(f"   ✓ השרת ענה: teachers={data.get('teachers_count',0)}, students={data.get('students_count',0)}")
    except Exception as exc:
        return {"ok": False, "error": f"שגיאת חיבור ל-status: {exc}"}

    # שלב 2: pull snapshot
    try:
        import sync_agent
    except ImportError:
        return {"ok": False, "error": "לא נמצא מודול sync_agent"}

    print(f"   2. מוריד snapshot מ-{snapshot_url}?tenant_id=...")
    try:
        resp = sync_agent.pull_snapshot(snapshot_url, api_key=api_key, tenant_id=tenant_id)
    except Exception as exc:
        return {"ok": False, "error": f"pull_snapshot שגיאה: {exc}"}

    if not (isinstance(resp, dict) and resp.get("ok")):
        err_msg = "תשובה לא תקינה" if not isinstance(resp, dict) else f"ok=False, {resp}"
        return {"ok": False, "error": f"pull_snapshot נכשל: {err_msg}"}

    snap_tables = resp.get("snapshot", {})
    snap_summary = {k: len(v) for k, v in snap_tables.items() if isinstance(v, list)} if isinstance(snap_tables, dict) else {}
    print(f"   ✓ snapshot התקבל: {len(snap_summary)} טבלאות")

    # שלב 3: apply snapshot
    print(f"   3. מחיל snapshot על DB זמני...")
    try:
        conn = sync_agent._connect(db_path)
        try:
            sync_agent._ensure_sync_state(conn)
            applied = sync_agent.apply_snapshot(conn, resp)
            last_id = resp.get("last_event_id") or resp.get("last_change_id")
            if last_id is not None:
                sync_agent._set_sync_state(conn, "pull_since_id", str(last_id))
        finally:
            conn.close()
        print(f"   ✓ apply_snapshot: {applied}")
    except Exception as exc:
        import traceback
        traceback.print_exc()
        return {"ok": False, "error": f"apply_snapshot שגיאה: {exc}"}

    # שלב 4: license
    print(f"   4. בודק רשיון ב-settings...")
    _inject_test_license(db_path, tenant_id)

    return {"ok": True, "snapshot_summary": snap_summary}


def _inject_test_license(db_path: str, tenant_id: str):
    """מוסיף רשיון בדיקה זמני ל-settings כדי לסמלץ את הזרימה."""
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT value FROM settings WHERE key='_cloud_license' LIMIT 1")
        row = cur.fetchone()
        if row and row[0]:
            try:
                lic = json.loads(row[0])
                if isinstance(lic, dict) and lic.get("license_type", "trial") != "trial":
                    print(f"   ✓ _cloud_license קיים ב-settings: type={lic.get('license_type')}")
                else:
                    print(f"   · _cloud_license קיים אבל סוג trial — לא יסונכרן")
            except Exception:
                print("   · _cloud_license לא ניתן לפענוח")
        else:
            print("   · _cloud_license לא קיים בענן הזה (אפשרי — תלוי אם הרשיון נשמר בענן)")
    finally:
        conn.close()


def _check_critical_tables(db_path: str, snap_summary: dict):
    """בודק טבלאות קריטיות ישירות מה-DB הזמני."""
    print("\n  בדיקת טבלאות קריטיות ב-DB:")
    conn = sqlite3.connect(db_path)
    try:
        for tbl in ("teachers", "students", "settings", "products", "messages"):
            try:
                cur = conn.cursor()
                cur.execute(f"SELECT COUNT(*) FROM {tbl}")
                cnt = cur.fetchone()[0]
                cloud_cnt = snap_summary.get(tbl, 0)
                match = "✓" if cnt == cloud_cnt else "⚠"
                print(f"    {match} {tbl}: DB={cnt}, snapshot={cloud_cnt}")
            except Exception as exc:
                print(f"    ✗ {tbl}: שגיאה — {exc}")
    finally:
        conn.close()


def _check_license(db_path: str, base_dir: str):
    """מנסה לייבא רשיון מ-settings."""
    print("\n  בדיקת רשיון:")
    try:
        from admin_station import _sync_license_from_cloud_settings
        ok = _sync_license_from_cloud_settings(db_path, base_dir)
        if ok:
            print("    ✓ רשיון יובא מהענן בהצלחה")
        else:
            print("    · רשיון לא יובא (ייתכן שאין _cloud_license בענן)")
    except Exception as exc:
        print(f"    ✗ שגיאה בייבוא רשיון: {exc}")


if __name__ == "__main__":
    sys.exit(main())
