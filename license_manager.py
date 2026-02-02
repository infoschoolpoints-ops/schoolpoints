import os
import json
import hmac
import hashlib
from datetime import date
import ctypes
import stat
import time
import socket
import base64
from typing import Optional, Tuple, List, Dict, Any

TRIAL_DAYS = 7
MONTHLY_WARNING_DAYS = 7
BASIC_MAX_STATIONS = 2
EXTENDED_MAX_STATIONS = 5
UNLIMITED_MAX_STATIONS = 999
OLD_MACHINE_ID = hashlib.sha256(b"schoolpoints-machine").hexdigest()[:16]

# שם קובץ הרישיון – גנרי וללא המילה "license"
LICENSE_FILE_NAME = ".sp_core.dat"

# מפתח סודי לחתימה על הרישיון ולקודי הפעלה
_HMAC_SECRET = b"SchoolPoints-Offline-License-Key-2024-11-Strong-Secret"


def _lic_debug(msg: str) -> None:
    """רישום הודעת דיבוג לרכיב הרישוי לקובץ לוג מקומי.

    חשוב: לעולם לא זורק חריגות, כדי שלא יפיל את התוכנה.
    """
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(base_dir, "license_manager.log")
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


def _normalize_key(key: str) -> str:
    """ניקוי מחרוזת לקוד רישוי: אותיות/ספרות בלבד, באותיות גדולות.

    מקבל גם None ומחזיר מחרוזת ריקה במקרה כזה.
    """
    return "".join(ch for ch in (key or "").upper() if ch.isalnum())


def _format_key_groups(core: str, group: int = 5) -> str:
    core = _normalize_key(core)
    if not core:
        return ''
    groups = [core[i : i + group] for i in range(0, len(core), group)]
    return "-".join(groups)


def _parse_ymd(s: str) -> Optional[date]:
    try:
        s = str(s or '').strip()
        if not s:
            return None
        y, m, d = map(int, s.split('-', 2))
        return date(y, m, d)
    except Exception:
        return None


def _date_to_iso(d: date) -> str:
    try:
        return d.isoformat()
    except Exception:
        return str(d)


def _add_days(d: date, days: int) -> date:
    # Avoid importing datetime.timedelta; keep logic local and safe
    try:
        from datetime import timedelta
        return d + timedelta(days=int(days))
    except Exception:
        return d


def _xor_bytes(data: bytes, key: bytes) -> bytes:
    if not data:
        return b''
    if not key:
        return data
    out = bytearray(len(data))
    klen = len(key)
    for i, b in enumerate(data):
        out[i] = b ^ key[i % klen]
    return bytes(out)


def _make_payload_activation_key(
    school_name: str,
    system_code: str,
    *,
    days_valid: int,
    max_stations: int,
    allow_cashier: bool,
) -> str:
    """ייצור קוד הפעלה עם payload (סכמה SP5).

    הקוד מכיל מידע "מוצפן"/מוסתר (JSON + XOR) וחתום (HMAC), ומקושר לקוד המערכת.
    בפועל התוקף מתחיל מרגע ההפעלה, ולא מקוד ההפעלה עצמו.
    """
    school_name = (school_name or '').strip()
    sys_norm = _normalize_key(system_code)
    if not school_name or not sys_norm:
        return ''

    try:
        days_valid = int(days_valid)
    except Exception:
        days_valid = 0
    try:
        max_stations = int(max_stations)
    except Exception:
        max_stations = BASIC_MAX_STATIONS
    if days_valid < 1:
        days_valid = 1

    payload = {
        'v': 'SP5',
        'school': school_name,
        'sys': sys_norm,
        'days': int(days_valid),
        'max': int(max_stations),
        'cashier': bool(allow_cashier),
    }

    raw = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    sig = hmac.new(_HMAC_SECRET, raw, hashlib.sha256).digest()[:10]

    key_stream = hashlib.sha256(_HMAC_SECRET + sys_norm.encode('utf-8')).digest()
    blob = raw + sig
    enc = _xor_bytes(blob, key_stream)
    token = base64.b32encode(enc).decode('ascii').replace('=', '').upper()

    # Add a visible prefix so we can route to the right validator
    return _format_key_groups('SP5' + token, 5)


def _decode_payload_activation_key(school_name: str, license_key: str, system_code: str) -> Optional[dict]:
    try:
        sys_norm = _normalize_key(system_code)
        if not sys_norm:
            return None
        k = _normalize_key(license_key)
        if not k.startswith('SP5'):
            return None
        core = k[3:]
        if not core:
            return None

        # base32 requires padding
        pad_len = (-len(core)) % 8
        core_padded = core + ('=' * pad_len)
        enc = base64.b32decode(core_padded.encode('ascii'))

        key_stream = hashlib.sha256(_HMAC_SECRET + sys_norm.encode('utf-8')).digest()
        blob = _xor_bytes(enc, key_stream)
        if len(blob) < 12:
            return None

        raw = blob[:-10]
        sig = blob[-10:]
        exp_sig = hmac.new(_HMAC_SECRET, raw, hashlib.sha256).digest()[:10]
        if not hmac.compare_digest(sig, exp_sig):
            return None

        payload = json.loads(raw.decode('utf-8'))
        if not isinstance(payload, dict):
            return None

        if str(payload.get('v') or '').strip().upper() != 'SP5':
            return None

        school_in = str(payload.get('school') or '').strip()
        if school_in != str(school_name or '').strip():
            return None

        if _normalize_key(str(payload.get('sys') or '')) != sys_norm:
            return None

        return payload
    except Exception:
        return None


def _make_key_for_profile(school_name: str, profile_name: str, max_stations: int) -> str:
    """יוצר מחרוזת קוד הפעלה "ישנה" עבור שם מוסד וסוג רישיון (ללא קוד מערכת).

    נשמר לתאימות לאחור בלבד.
    הפורמט למשתמש: XXXXX-XXXXX-XXXXX-XXXXX (רק אותיות/ספרות גדולות).
    """
    school_name = (school_name or "").strip()
    plain = f"{school_name}|{profile_name}|{max_stations}|SP1"
    digest = hmac.new(_HMAC_SECRET, plain.encode("utf-8"), hashlib.sha256).hexdigest().upper()
    core = digest[:20]
    groups = [core[i : i + 5] for i in range(0, 20, 5)]
    return "-".join(groups)


def _make_activation_key_for_profile(
    school_name: str,
    system_code: str,
    profile_name: str,
    max_stations: int,
) -> str:
    """יוצר מחרוזת קוד הפעלה חדשה עבור שם מוסד, קוד מערכת וסוג רישיון.

    הפורמט למשתמש: XXXXX-XXXXX-XXXXX-XXXXX (רק אותיות/ספרות גדולות).
    """
    school_name = (school_name or "").strip()
    sys_norm = _normalize_key(system_code)
    plain = f"{school_name}|{sys_norm}|{profile_name}|{max_stations}|SP2"
    digest = hmac.new(_HMAC_SECRET, plain.encode("utf-8"), hashlib.sha256).hexdigest().upper()
    core = digest[:20]
    groups = [core[i : i + 5] for i in range(0, 20, 5)]
    return "-".join(groups)


def _make_monthly_license_key(
    school_name: str,
    system_code: str,
    expiry_date: str,
    max_stations: int,
) -> str:
    """יוצר קוד הפעלה לרישיון חודשי עם תאריך תפוגה.

    Args:
        school_name: שם המוסד
        system_code: קוד המערכת
        expiry_date: תאריך תפוגה (YYYY-MM-DD)
        max_stations: מספר תחנות מקסימלי

    Returns:
        קוד הפעלה בפורמט XXXXX-XXXXX-XXXXX-XXXXX
    """
    school_name = (school_name or "").strip()
    sys_norm = _normalize_key(system_code)
    exp_norm = (expiry_date or "").strip()
    plain = f"{school_name}|{sys_norm}|MONTHLY|{exp_norm}|{max_stations}|SP3"
    digest = hmac.new(_HMAC_SECRET, plain.encode("utf-8"), hashlib.sha256).hexdigest().upper()
    core = digest[:20]
    groups = [core[i : i + 5] for i in range(0, 20, 5)]
    return "-".join(groups)


def _make_monthly_license_key_with_cashier(
    school_name: str,
    system_code: str,
    expiry_date: str,
    max_stations: int,
    allow_cashier: bool,
) -> str:
    school_name = (school_name or "").strip()
    sys_norm = _normalize_key(system_code)
    exp_norm = (expiry_date or "").strip()
    tag = "CASHIER" if bool(allow_cashier) else "NO_CASHIER"
    plain = f"{school_name}|{sys_norm}|MONTHLY|{tag}|{exp_norm}|{max_stations}|SP4"
    digest = hmac.new(_HMAC_SECRET, plain.encode("utf-8"), hashlib.sha256).hexdigest().upper()
    core = digest[:20]
    groups = [core[i : i + 5] for i in range(0, 20, 5)]
    return "-".join(groups)


def validate_monthly_license_key(school_name: str, license_key: str, system_code: str, expiry_date: str) -> tuple:
    """בדיקת קוד הפעלה לרישיון חודשי עם תאריך תפוגה.
    
    Args:
        school_name: שם המוסד
        license_key: קוד הרישיון
        system_code: קוד המערכת
        expiry_date: תאריך תפוגה (YYYY-MM-DD)
    
    Returns:
        (is_valid, max_stations, allow_cashier) - True אם הקוד תקין
    """
    if not license_key or not system_code or not expiry_date:
        return False, None, None
    
    norm_user = _normalize_key(license_key)
    school_name = (school_name or "").strip()
    
    # נסה מספרי תחנות שונים
    for max_stations in [BASIC_MAX_STATIONS, EXTENDED_MAX_STATIONS, UNLIMITED_MAX_STATIONS]:
        expected = _normalize_key(
            _make_monthly_license_key_with_cashier(school_name, system_code, expiry_date, max_stations, True)
        )
        if norm_user == expected:
            return True, max_stations, True

        expected = _normalize_key(
            _make_monthly_license_key_with_cashier(school_name, system_code, expiry_date, max_stations, False)
        )
        if norm_user == expected:
            return True, max_stations, False

        expected = _normalize_key(
            _make_monthly_license_key(school_name, system_code, expiry_date, max_stations)
        )
        if norm_user == expected:
            return True, max_stations, True

    return False, None, None


def validate_license_key(school_name: str, license_key: str, system_code: Optional[str] = None):
    """בדיקת קוד הפעלה מול שם מוסד (עם או בלי קוד מערכת).

    מחזיר (license_type, max_stations) אם תקין, אחרת (None, None).
    license_type: "basic" / "extended" / "unlimited".

    אם system_code סופק – תיבדק קודם התאמה לפי הסכמה החדשה (תלוית קוד מערכת).
    אם לא נמצא התאמה, תתבצע בדיקה לפי הסכמה הישנה לצורך תאימות לאחור.
    """
    if not license_key:
        return None, None

    norm_user = _normalize_key(license_key)
    school_name = (school_name or "").strip()

    profiles = {
        "BASIC": BASIC_MAX_STATIONS,
        "EXTENDED": EXTENDED_MAX_STATIONS,
        "UNLIMITED": UNLIMITED_MAX_STATIONS,
    }

    sys_norm = _normalize_key(system_code) if system_code else ""

    # קודם ננסה התאמה לפי הסכמה החדשה – קוד תלוי מערכת
    if sys_norm:
        for profile_name, max_st in profiles.items():
            expected = _normalize_key(
                _make_activation_key_for_profile(school_name, sys_norm, profile_name, max_st)
            )
            if norm_user == expected:
                return profile_name.lower(), max_st

    # תאימות לאחור – קודים ישנים שלא תלויים בקוד מערכת
    for profile_name, max_st in profiles.items():
        expected = _normalize_key(_make_key_for_profile(school_name, profile_name, max_st))
        if norm_user == expected:
            return profile_name.lower(), max_st

    return None, None


def generate_license_key(school_name: str, license_type: str) -> str:
    """יצירת קוד רישיון עבור שם מוסד וסוג רישיון.

    license_type יכול להיות: "basic", "extended", "unlimited" (לא תלוי רישיות).
    """
    school_name = (school_name or "").strip()
    if not school_name:
        raise ValueError("יש להזין שם מוסד לצורך יצירת קוד רישיון")

    lt = (license_type or "").strip().lower()
    if lt == "basic":
        profile_name = "BASIC"
        max_stations = BASIC_MAX_STATIONS
    elif lt == "extended":
        profile_name = "EXTENDED"
        max_stations = EXTENDED_MAX_STATIONS
    elif lt == "unlimited":
        profile_name = "UNLIMITED"
        max_stations = UNLIMITED_MAX_STATIONS
    else:
        raise ValueError(f"סוג רישיון לא מוכר: {license_type}")

    return _make_key_for_profile(school_name, profile_name, max_stations)


def generate_activation_key(school_name: str, system_code: str, license_type: str) -> str:
    """יצירת קוד הפעלה חדש עבור שם מוסד + קוד מערכת + סוג רישיון.

    זהו הקוד המומלץ לשימוש מול מוסדות:
    • המוסד מעביר: שם מוסד + קוד מערכת שהמערכת מציגה לו.
    • אתה בוחר סוג רישיון (basic/extended/unlimited) ומייצר קוד הפעלה.

    קוד זה יהיה תקף רק למחשב שבו נוצר קוד המערכת ולשם המוסד שהוזן.
    """
    school_name = (school_name or "").strip()
    if not school_name:
        raise ValueError("יש להזין שם מוסד לצורך יצירת קוד הפעלה")

    sys_norm = _normalize_key(system_code)
    if not sys_norm:
        raise ValueError("יש להזין קוד מערכת לצורך יצירת קוד הפעלה")

    lt = (license_type or "").strip().lower()
    if lt == "basic":
        profile_name = "BASIC"
        max_stations = BASIC_MAX_STATIONS
    elif lt == "extended":
        profile_name = "EXTENDED"
        max_stations = EXTENDED_MAX_STATIONS
    elif lt == "unlimited":
        profile_name = "UNLIMITED"
        max_stations = UNLIMITED_MAX_STATIONS
    else:
        raise ValueError(f"סוג רישיון לא מוכר: {license_type}")

    return _make_activation_key_for_profile(school_name, sys_norm, profile_name, max_stations)


def generate_payload_activation_key(
    school_name: str,
    system_code: str,
    *,
    days_valid: int,
    max_stations: int,
    allow_cashier: bool,
) -> str:
    """יצירת קוד הפעלה חדש מסוג SP5 (term/payload).

    הקוד מכיל payload חתום עם:
    - מספר ימים לתוקף (נספר מרגע ההפעלה בפועל)
    - מספר עמדות מרבי
    - האם כולל עמדת קופה
    """
    school_name = (school_name or "").strip()
    if not school_name:
        raise ValueError("יש להזין שם מוסד לצורך יצירת קוד הפעלה")

    sys_norm = _normalize_key(system_code)
    if not sys_norm:
        raise ValueError("יש להזין קוד מערכת תקין")

    try:
        days_valid = int(days_valid)
    except Exception:
        days_valid = 0
    if days_valid < 1:
        days_valid = 1

    try:
        max_stations = int(max_stations)
    except Exception:
        max_stations = BASIC_MAX_STATIONS
    if max_stations < 1:
        max_stations = 1

    return _make_payload_activation_key(
        school_name,
        sys_norm,
        days_valid=days_valid,
        max_stations=max_stations,
        allow_cashier=bool(allow_cashier),
    )


def generate_monthly_activation_key(school_name: str, system_code: str, expiry_date: str, license_type: str) -> str:
    school_name = (school_name or "").strip()
    if not school_name:
        raise ValueError("יש להזין שם מוסד לצורך יצירת קוד הפעלה")

    sys_norm = _normalize_key(system_code)
    if not sys_norm:
        raise ValueError("יש להזין קוד מערכת לצורך יצירת קוד הפעלה")

    exp_norm = (expiry_date or "").strip()
    if not exp_norm:
        raise ValueError("יש להזין תאריך תפוגה לצורך רישיון חודשי")

    lt = (license_type or "").strip().lower()
    if lt == "basic":
        max_stations = BASIC_MAX_STATIONS
    elif lt == "extended":
        max_stations = EXTENDED_MAX_STATIONS
    elif lt == "unlimited":
        max_stations = UNLIMITED_MAX_STATIONS
    else:
        raise ValueError(f"סוג רישיון לא מוכר: {license_type}")

    return _make_monthly_license_key(school_name, sys_norm, exp_norm, max_stations)


def generate_monthly_activation_key_with_cashier(
    school_name: str,
    system_code: str,
    expiry_date: str,
    license_type: str,
    allow_cashier: bool,
) -> str:
    school_name = (school_name or "").strip()
    if not school_name:
        raise ValueError("יש להזין שם מוסד לצורך יצירת קוד הפעלה")

    sys_norm = _normalize_key(system_code)
    if not sys_norm:
        raise ValueError("יש להזין קוד מערכת לצורך יצירת קוד הפעלה")

    exp_norm = (expiry_date or "").strip()
    if not exp_norm:
        raise ValueError("יש להזין תאריך תפוגה לצורך רישיון חודשי")

    lt = (license_type or "").strip().lower()
    if lt == "basic":
        max_stations = BASIC_MAX_STATIONS
    elif lt == "extended":
        max_stations = EXTENDED_MAX_STATIONS
    elif lt == "unlimited":
        max_stations = UNLIMITED_MAX_STATIONS
    else:
        raise ValueError(f"סוג רישיון לא מוכר: {license_type}")

    return _make_monthly_license_key_with_cashier(school_name, sys_norm, exp_norm, max_stations, bool(allow_cashier))


def _sign_license(license_dict: dict) -> str:
    """חתימה על נתוני הרישיון כדי לזהות שינויים ידניים."""
    data = json.dumps(license_dict, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hmac.new(_HMAC_SECRET, data, hashlib.sha256).hexdigest()


def _get_license_dir(base_dir: str) -> str:
    """איתור תיקיית הרישיון (בד"כ תיקיית הרשת המשותפת, אחרת תיקיות הנתונים המקומיות)."""
    _lic_debug(f"_get_license_dir: base_dir={base_dir}")
    # 1. נסה להשתמש בתיקיית רשת משותפת אם מוגדרת בקובץ config.json "חי"
    try:
        config_file = None

        # קודם כל נסה לאתר config.json חי בתיקיות הנתונים (ProgramData/LocalAppData/APPDATA)
        for env_name in ("PROGRAMDATA", "LOCALAPPDATA", "APPDATA"):
            root = os.environ.get(env_name)
            if not root:
                continue
            try:
                if os.path.isdir(root) and os.access(root, os.W_OK):
                    cfg_dir = os.path.join(root, "SchoolPoints")
                    candidate = os.path.join(cfg_dir, "config.json")
                    if os.path.exists(candidate):
                        config_file = candidate
                        break
            except Exception:
                continue

        # אם לא נמצא קובץ חי, ננסה את הקובץ שבתיקיית ההתקנה (בעיקר בסביבת פיתוח)
        if config_file is None:
            candidate = os.path.join(base_dir, "config.json")
            if os.path.exists(candidate):
                config_file = candidate

        if config_file and os.path.exists(config_file):
            _lic_debug(f"_get_license_dir: using config_file={config_file}")
            with open(config_file, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            shared_folder = cfg.get("shared_folder") or cfg.get("network_root")
            _lic_debug(f"_get_license_dir: shared_folder={shared_folder}")
            if shared_folder and os.path.isdir(shared_folder):
                _lic_debug(f"_get_license_dir: returning shared_folder={shared_folder}")
                return shared_folder
    except Exception:
        pass

    # 2. ברירת מחדל: שמירת רישיון בתיקיות נתונים – עדיפות ל-PROGRAMDATA (מערכתי)
    #    ורק אם אין – LOCALAPPDATA / APPDATA למשתמש הנוכחי.
    for env_name in ("PROGRAMDATA", "LOCALAPPDATA", "APPDATA"):
        root = os.environ.get(env_name)
        if not root:
            continue
        try:
            if os.path.isdir(root) and os.access(root, os.W_OK):
                path = os.path.join(root, "SchoolPoints")
                _lic_debug(f"_get_license_dir: returning data dir {path}")
                return path
        except Exception:
            continue

    # 3. מוצא אחרון – חזרה לתיקיית האפליקציה (בעיקר בסביבת פיתוח חריגה)
    _lic_debug(f"_get_license_dir: fallback to base_dir={base_dir}")
    return base_dir


def _load_or_create_license(base_dir: str) -> Tuple[Dict[str, Any], str]:
    """טעינת קובץ רישיון אם קיים, אחרת יצירת רישיון ניסיון חדש.

    מחזיר (license_dict, license_path).
    """
    _lic_debug("_load_or_create_license: start")
    license_dir = _get_license_dir(base_dir)
    _lic_debug(f"_load_or_create_license: license_dir={license_dir}")
    license_path = os.path.join(license_dir, LICENSE_FILE_NAME)

    # תמיכה גם בשם הקובץ הישן כדי לא לשבור התקנות קיימות
    legacy_path = os.path.join(license_dir, ".sp_license.dat")

    for candidate in (license_path, legacy_path):
        if os.path.exists(candidate):
            try:
                _lic_debug(f"_load_or_create_license: loading existing {candidate}")
                with open(candidate, "r", encoding="utf-8") as f:
                    envelope = json.load(f)
                # מפתחות קצרים ("d"/"s") עם תאימות לאחור ל-"license"/"sig"
                lic = envelope.get("d") or envelope.get("license") or {}
                sig = envelope.get("s") or envelope.get("sig")
                if not isinstance(lic, dict) or not isinstance(sig, str):
                    raise ValueError("invalid license structure")
                if _sign_license(lic) != sig:
                    raise ValueError("license signature mismatch")
                _lic_debug("_load_or_create_license: loaded valid license")
                return lic, candidate
            except Exception:
                # אם יש קובץ פגום, נתחיל מניסיון חדש אבל לא נמחק אותו
                _lic_debug(f"_load_or_create_license: invalid/corrupt license at {candidate}, creating trial")
                pass

    today = date.today().isoformat()
    lic = {
        "schema": 1,
        "school_name": None,
        "license_type": "trial",  # trial / basic / extended / unlimited / monthly
        "license_key": None,
        "max_stations": BASIC_MAX_STATIONS,
        "trial_start": today,
        "expiry_date": None,  # תאריך תפוגה לרישיון חודשי (YYYY-MM-DD)
        "allow_cashier": True,
        "machines": [],  # רשימת מזהי מחשב
    }
    _lic_debug(f"_load_or_create_license: creating trial license at {license_path}")
    _save_license(lic, license_path)
    return lic, license_path


def _save_license(license_dict: dict, license_path: str) -> bool:
    try:
        dir_path = os.path.dirname(license_path) or "."
        os.makedirs(dir_path, exist_ok=True)

        # מפתחות קצרים בקובץ כדי לא לחשוף שמדובר ברישיון
        envelope = {"d": license_dict, "s": _sign_license(license_dict)}

        try:
            with open(license_path, "w", encoding="utf-8") as f:
                json.dump(envelope, f, ensure_ascii=False, indent=2)
        except (PermissionError, OSError):
            # ניסיון להסיר דגל read-only ולנסות מחדש (בעיקר אם הקובץ נפרס מהתקנה)
            wrote = False

            if os.name == "nt" and os.path.exists(license_path):
                try:
                    os.chmod(license_path, stat.S_IWRITE | stat.S_IREAD)
                    with open(license_path, "w", encoding="utf-8") as f:
                        json.dump(envelope, f, ensure_ascii=False, indent=2)
                    wrote = True
                except Exception:
                    wrote = False

            # אם אחרי ניסיון שינוי הרשאות עדיין לא הצלחנו – ננסה למחוק וליצור מחדש
            if not wrote:
                try:
                    if os.path.exists(license_path):
                        os.remove(license_path)
                    with open(license_path, "w", encoding="utf-8") as f:
                        json.dump(envelope, f, ensure_ascii=False, indent=2)
                except Exception:
                    return False

        # ניסיון לסמן את הקובץ כמוסתר/מערכתי ב-Windows (למזעור גישה ידנית)
        try:
            if os.name == "nt":
                FILE_ATTRIBUTE_HIDDEN = 0x02
                FILE_ATTRIBUTE_SYSTEM = 0x04
                ctypes.windll.kernel32.SetFileAttributesW(license_path, FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM)
        except Exception:
            # אם לא הצלחנו – מתעלמים, זה לא חוסם את הריצה
            pass

        return True
    except (PermissionError, OSError):
        # אם אין אפשרות לכתוב או ליצור תיקייה – אל תפיל את האפליקציה
        # הרישיון פשוט לא יישמר לדיסק, אלא רק בזיכרון בריצה הנוכחית.
        return False


def _get_machine_id() -> str:
    """מחזיר מזהה יציב למחשב.

    כאן נבחר מזהה קבוע ופשוט כדי למנוע לגמרי כל קריאה איטית למערכת ההפעלה
    (בלי platform, בלי uuid וכו'). זה מספיק טוב עבור מנגנון הרישוי אצלך.
    """
    # שלב 1: ניסיון להשתמש במזהה שנשמר לקובץ מקומי במיקום כתיב יציב
    mid_dir = None
    mid_path = None
    try:
        roots = []
        for env_name in ("PROGRAMDATA", "LOCALAPPDATA", "APPDATA"):
            try:
                val = os.environ.get(env_name)
            except Exception:
                val = None
            if val:
                roots.append(val)

        root = None
        for r in roots:
            try:
                if os.path.isdir(r):
                    root = r
                    break
            except Exception:
                continue

        if root is None:
            root = os.path.dirname(os.path.abspath(__file__))

        mid_dir = os.path.join(root, "SchoolPoints")
        mid_path = os.path.join(mid_dir, ".machine_id")

        try:
            if os.path.exists(mid_path):
                with open(mid_path, "r", encoding="utf-8") as f:
                    mid = f.read().strip()
                if mid:
                    return mid
        except Exception:
            pass
    except Exception:
        mid_dir = None
        mid_path = None

    # שלב 2: חישוב מזהה חדש יציב ככל האפשר לפי פרטי המחשב
    try:
        parts: List[str] = []

        # שם מחשב בסיסי (לרוב ייחודי ברשת)
        try:
            hostname = socket.gethostname()
            if hostname:
                parts.append(str(hostname))
        except Exception:
            pass

        # מספר מזהים זמינים מסביבת Windows – ללא קריאות איטיות למערכת ההפעלה
        for env_name in ("COMPUTERNAME", "PROCESSOR_IDENTIFIER", "SYSTEMDRIVE"):
            try:
                val = os.environ.get(env_name)
            except Exception:
                val = None
            if val:
                parts.append(str(val))

        base = "|".join(parts).strip()
        if not base:
            base = "schoolpoints-machine"
    except Exception:
        base = "schoolpoints-machine"

    machine_id = hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]

    # שלב 3: ניסיון לשמור את המזהה לקובץ כך שישאר קבוע גם אם משתנים פרטי המחשב (למשל שם מחשב)
    try:
        if mid_dir and mid_path:
            try:
                os.makedirs(mid_dir, exist_ok=True)
            except Exception:
                pass
            try:
                with open(mid_path, "w", encoding="utf-8") as f:
                    f.write(machine_id)
            except Exception:
                pass
    except Exception:
        pass

    return machine_id


def _format_system_code(machine_id: str) -> str:
    """המרת מזהה מחשב גולמי לקוד מערכת קריא למשתמש.

    הפורמט: XXXX-XXXX-XXXX-XXXX (16 תווים מאותיות/ספרות).
    """
    core = _normalize_key(machine_id)[:16]
    if not core:
        core = "UNKNOWN0000000000"[:16]
    groups = [core[i : i + 4] for i in range(0, len(core), 4)]
    return "-".join(groups)


class LicenseManager:
    """ניהול רישוי אופליין למערכת SchoolPoints."""

    def __init__(self, base_dir: str, station_role: str):
        _lic_debug(f"LicenseManager.__init__ start: base_dir={base_dir}, role={station_role}")
        self.base_dir = base_dir
        self.station_role = station_role  # "admin" / "public"
        self.machine_id = _get_machine_id()
        self.system_code = _format_system_code(self.machine_id)
        _lic_debug(f"LicenseManager: machine_id={self.machine_id}, system_code={self.system_code}")

        lic, path = _load_or_create_license(base_dir)
        _lic_debug(f"LicenseManager: license loaded from {path}")
        self._license = lic
        self.license_path = path

        self.school_name = lic.get("school_name")
        self.license_type = lic.get("license_type", "trial")
        self.max_stations = int(lic.get("max_stations", BASIC_MAX_STATIONS) or BASIC_MAX_STATIONS)
        self.machines = list(lic.get("machines") or [])

        self.activated_at = None
        try:
            self.activated_at = str(lic.get('activated_at') or '').strip() or None
        except Exception:
            self.activated_at = None
        try:
            self.term_days = int(lic.get('term_days') or 0)
        except Exception:
            self.term_days = 0

        self.expiry_date = None
        try:
            self.expiry_date = str(lic.get("expiry_date") or "").strip() or None
        except Exception:
            self.expiry_date = None

        self.monthly_expired = False
        if str(self.license_type or '').strip().lower() == 'monthly':
            self.monthly_expired = self._is_monthly_expired(self.expiry_date)
        try:
            if str(self.license_type or '').strip().lower() == 'monthly':
                self.monthly_days_left = self._calc_monthly_days_left(self.expiry_date)
            else:
                self.monthly_days_left = 0
        except Exception:
            self.monthly_days_left = 0

        self.term_expired = False
        if str(self.license_type or '').strip().lower() == 'term':
            self.term_expired = self._is_term_expired(self.activated_at, int(self.term_days or 0))

        self.trial_days_left = self._calc_trial_days_left()
        self.trial_expired = self.license_type == "trial" and self.trial_days_left <= 0

        self.term_days_left = self._calc_term_days_left(self.activated_at, int(self.term_days or 0))

        try:
            self.allow_cashier = bool(lic.get('allow_cashier', True))
        except Exception:
            self.allow_cashier = True

        # רישום המחשב הנוכחי בתוך מגבלת מספר העמדות
        self.over_limit = False
        self.used_stations = len(self.machines)
        self._register_current_machine_if_needed()
        _lic_debug(
            f"LicenseManager: school={self.school_name}, type={self.license_type}, "
            f"max_stations={self.max_stations}, used={self.used_stations}, over_limit={self.over_limit}"
        )

    # ===== חישובי סטטוס =====

    def _calc_trial_days_left(self) -> int:
        start = self._license.get("trial_start")
        if not start:
            return 0
        try:
            y, m, d = map(int, start.split("-"))
            start_date = date(y, m, d)
            delta = (date.today() - start_date).days
            return max(0, TRIAL_DAYS - delta)
        except Exception:
            return 0

    def _calc_monthly_days_left(self, expiry_date: Optional[str]) -> int:
        exp_dt = _parse_ymd(expiry_date or '')
        if exp_dt is None:
            return 0
        try:
            left = (exp_dt - date.today()).days
            return max(0, int(left) + 1)
        except Exception:
            return 0

    def days_until_expiry(self) -> int:
        try:
            if self.is_monthly:
                return int(getattr(self, 'monthly_days_left', 0) or 0)
            if self.is_term:
                return int(getattr(self, 'term_days_left', 0) or 0)
            if self.is_trial:
                return int(getattr(self, 'trial_days_left', 0) or 0)
        except Exception:
            return 0
        return 0

    @property
    def is_trial(self) -> bool:
        return self.license_type == "trial" and not self.trial_expired

    @property
    def is_licensed(self) -> bool:
        lt = str(self.license_type or '').strip().lower()
        if lt in {"basic", "extended", "unlimited"}:
            return True
        if lt == 'monthly':
            return not bool(getattr(self, 'monthly_expired', False))
        if lt == 'term':
            return not bool(getattr(self, 'term_expired', False))
        return False

    @property
    def is_monthly(self) -> bool:
        return str(self.license_type or '').strip().lower() == 'monthly'

    @property
    def is_term(self) -> bool:
        return str(self.license_type or '').strip().lower() == 'term'

    def _is_term_expired(self, activated_at: Optional[str], term_days: int) -> bool:
        try:
            if int(term_days or 0) <= 0:
                return True
        except Exception:
            return True
        start = _parse_ymd(activated_at or '')
        if start is None:
            return True
        # expires AFTER term_days days starting at activation day
        try:
            exp = _add_days(start, int(term_days) - 1)
            return date.today() > exp
        except Exception:
            return True

    def _calc_term_days_left(self, activated_at: Optional[str], term_days: int) -> int:
        try:
            if int(term_days or 0) <= 0:
                return 0
        except Exception:
            return 0
        start = _parse_ymd(activated_at or '')
        if start is None:
            return 0
        try:
            exp = _add_days(start, int(term_days) - 1)
            left = (exp - date.today()).days
            return max(0, int(left) + 1)
        except Exception:
            return 0

    def _is_monthly_expired(self, expiry_date: Optional[str]) -> bool:
        exp = (expiry_date or '').strip()
        if not exp:
            return True
        try:
            y, m, d = map(int, exp.split('-'))
            exp_dt = date(y, m, d)
            return date.today() > exp_dt
        except Exception:
            return True

    def _register_current_machine_if_needed(self) -> None:
        machines = set(str(m) for m in self.machines)

        # התאמה לאחור: אם ברישיון נשמר המזהה הישן והקבוע – נתעלם ממנו
        if OLD_MACHINE_ID in machines:
            machines.discard(OLD_MACHINE_ID)
            self.machines = sorted(machines)
            self._license["machines"] = self.machines

        if self.machine_id in machines:
            self.used_stations = len(machines)
            return

        if len(machines) >= self.max_stations:
            self.over_limit = True
            self.used_stations = len(machines)
            return

        machines.add(self.machine_id)
        self.machines = sorted(machines)
        self._license["machines"] = self.machines
        self.used_stations = len(self.machines)
        _save_license(self._license, self.license_path)

    # ===== API לשימוש בעמדות =====

    def can_run_public_station(self) -> bool:
        """בעמדה ציבורית מותר לרוץ רק אם לא עבר הניסיון או שיש רישיון תקף."""
        if self.over_limit:
            return False
        if getattr(self, 'is_monthly', False) and bool(getattr(self, 'monthly_expired', False)):
            return False
        if getattr(self, 'is_term', False) and bool(getattr(self, 'term_expired', False)):
            return False
        if self.is_licensed:
            return True
        # trial
        return not self.trial_expired

    def can_run_cashier_station(self) -> bool:
        if self.over_limit:
            return False
        if getattr(self, 'is_monthly', False) and bool(getattr(self, 'monthly_expired', False)):
            return False
        if getattr(self, 'is_term', False) and bool(getattr(self, 'term_expired', False)):
            return False
        if getattr(self, 'is_monthly', False) and (not bool(getattr(self, 'allow_cashier', True))):
            return False
        if getattr(self, 'is_term', False) and (not bool(getattr(self, 'allow_cashier', True))):
            return False
        if self.is_licensed:
            return True
        return not self.trial_expired

    def can_modify_data(self) -> bool:
        """האם מותר לבצע פעולות שמירה/עדכון (בעיקר לעמדת ניהול)."""
        if self.over_limit:
            return False
        if getattr(self, 'is_monthly', False) and bool(getattr(self, 'monthly_expired', False)):
            return False
        if getattr(self, 'is_term', False) and bool(getattr(self, 'term_expired', False)):
            return False
        if self.is_licensed:
            return True
        # בזמן ניסיון מותר לערוך, אחרי סיומו – צפייה בלבד
        return not self.trial_expired

    def get_block_modify_message(self) -> str:
        if self.over_limit:
            return (
                "מספר העמדות ברישיון נוצל במלואו.\n"
                "לא ניתן לבצע שינויים ממחשב נוסף ללא הרחבת רישיון."
            )
        if getattr(self, 'is_monthly', False) and bool(getattr(self, 'monthly_expired', False)):
            return (
                "הרישיון החודשי פג תוקף.\n"
                "לא ניתן לבצע שינויים עד להזנת רישיון חדש.\n\n"
                "יש להזין רישיון בעמדת הניהול (⚙ הגדרות מערכת → רישום מערכת)."
            )
        if getattr(self, 'is_term', False) and bool(getattr(self, 'term_expired', False)):
            return (
                "הרישיון פג תוקף.\n"
                "לא ניתן לבצע שינויים עד להזנת רישיון חדש.\n\n"
                "יש להזין רישיון בעמדת הניהול (⚙ הגדרות מערכת → רישום מערכת)."
            )
        if self.trial_expired and not self.is_licensed:
            return (
                "תקופת הניסיון הסתיימה. המוצר אינו מורשה לעריכה.\n"
                "ניתן לרכוש רישיון להפעלה מלאה."
            )
        return "המוצר אינו מורשה לעריכה."

    def get_startup_message(self) -> Optional[str]:
        if self.over_limit:
            return (
                "מספר העמדות ברישיון נוצל במלואו.\n"
                "לא ניתן להפעיל עמדה נוספת ללא הרחבת רישיון."
            )
        if getattr(self, 'is_monthly', False) and bool(getattr(self, 'monthly_expired', False)):
            return (
                "הרישיון החודשי פג תוקף.\n"
                "יש להזין רישיון חדש בעמדת הניהול (⚙ הגדרות מערכת → רישום מערכת)."
            )
        if getattr(self, 'is_monthly', False):
            try:
                days_left = int(getattr(self, 'monthly_days_left', 0) or 0)
            except Exception:
                days_left = 0
            if days_left > 0 and days_left <= int(MONTHLY_WARNING_DAYS):
                exp = str(getattr(self, 'expiry_date', '') or '').strip()
                suffix = f" (עד {exp})" if exp else ""
                return (
                    f"הרישיון החודשי יפוג בעוד {days_left} ימים{suffix}.\n"
                    "מומלץ לחדש את הרישיון מראש כדי למנוע הפסקת עבודה."
                )
        if getattr(self, 'is_term', False) and bool(getattr(self, 'term_expired', False)):
            return (
                "הרישיון פג תוקף.\n"
                "יש להזין רישיון חדש בעמדת הניהול (⚙ הגדרות מערכת → רישום מערכת)."
            )
        if self.is_trial:
            return (
                f"גרסת ניסיון – המוצר עדיין לא רשום.\n"
                f"נותרו {self.trial_days_left} ימים לתקופת הניסיון."
            )
        if self.trial_expired:
            return (
                "תקופת הניסיון הסתיימה.\n"
                "עמדת הניהול תפעל במצב צפייה בלבד עד להפעלת רישיון."
            )
        return None

    def get_over_limit_message(self) -> str:
        if self.school_name:
            return (
                f"מספר העמדות המרבי לרישיון של בית ספר {self.school_name} נוצל במלואו.\n"
                "לא ניתן להפעיל עמדה נוספת ללא הרחבת רישיון."
            )
        return (
            "מספר העמדות המרבי לרישיון נוצל במלואו.\n"
            "לא ניתן להפעיל עמדה נוספת ללא הרחבת רישיון."
        )

    # ===== אקטיבציה מקוד הפעלה =====

    def activate(self, school_name: str, license_key: str, expiry_date: Optional[str] = None) -> Tuple[bool, str]:
        """ניסיון אקטיבציה של רישיון חדש.

        מחזיר (success, message).
        """
        school_name = (school_name or "").strip()
        if not school_name:
            return False, "יש להזין שם מוסד."
        if not license_key:
            return False, "יש להזין קוד הפעלה."

        lic_type = None
        max_stations = None

        # קודם: סכמה חדשה עם payload (SP5) – ימים/עמדות/קופה מתחילים מרגע האקטיבציה
        try:
            payload = _decode_payload_activation_key(school_name, license_key, self.system_code)
        except Exception:
            payload = None
        if isinstance(payload, dict):
            try:
                lic_type = 'term'
                max_stations = int(payload.get('max', BASIC_MAX_STATIONS) or BASIC_MAX_STATIONS)
                allow_cashier = bool(payload.get('cashier', True))
                term_days = int(payload.get('days', 0) or 0)
                if term_days < 1:
                    term_days = 1
            except Exception:
                lic_type = None
                max_stations = None

        # קודם: רישיון רגיל (SP2) – רק אם לא קיבלנו payload
        if not lic_type:
            try:
                lic_type, max_stations = validate_license_key(school_name, license_key, self.system_code)
            except Exception:
                lic_type, max_stations = None, None

        # אם לא נמצא – ננסה רישיון חודשי אם קיים תאריך תפוגה
        exp_norm = (expiry_date or '').strip()
        allow_cashier = True

        if (not lic_type) and exp_norm:
            try:
                ok, max_st, allow_cashier_val = validate_monthly_license_key(school_name, license_key, self.system_code, exp_norm)
                if ok:
                    lic_type = 'monthly'
                    max_stations = max_st
                    allow_cashier = True if allow_cashier_val is None else bool(allow_cashier_val)
            except Exception:
                pass

        if not lic_type:
            return False, "קוד הפעלה שגוי עבור שם המוסד שהוזן."

        new_license = dict(self._license)
        new_license["school_name"] = school_name
        new_license["license_type"] = lic_type
        new_license["license_key"] = license_key.strip()
        new_license["max_stations"] = int(max_stations)
        if str(lic_type).lower() == 'monthly':
            new_license["expiry_date"] = exp_norm
            new_license["allow_cashier"] = bool(allow_cashier)
            new_license['activated_at'] = None
            new_license['term_days'] = None
        elif str(lic_type).lower() == 'term':
            # validity starts at activation time
            today = date.today()
            new_license['activated_at'] = _date_to_iso(today)
            try:
                new_license['term_days'] = int(term_days)
            except Exception:
                new_license['term_days'] = 1
            # keep an ISO expiry snapshot for UI/logging
            try:
                exp_dt = _add_days(today, int(new_license['term_days'] or 1) - 1)
                new_license['expiry_date'] = _date_to_iso(exp_dt)
            except Exception:
                new_license['expiry_date'] = None
            new_license['allow_cashier'] = bool(allow_cashier)
        else:
            new_license["expiry_date"] = None
            new_license["allow_cashier"] = True
            new_license['activated_at'] = None
            new_license['term_days'] = None
        # לאחר אקטיבציה אין משמעות לתחילת ניסיון
        new_license.setdefault("trial_start", date.today().isoformat())

        # חישוב מחודש של מיקום קובץ הרישיון לפי ההגדרות העדכניות (shared_folder וכו')
        try:
            new_dir = _get_license_dir(self.base_dir)
            if new_dir:
                self.license_path = os.path.join(new_dir, LICENSE_FILE_NAME)
        except Exception:
            # במקרה חריג נשמור בנתיב הקודם
            pass

        if not _save_license(new_license, self.license_path):
            return False, (
                "לא ניתן לשמור את קובץ הרישיון למיקום הבא:\n"
                f"{self.license_path}\n"
                "בדוק שיש הרשאת כתיבה לתיקייה/קובץ, או מחק קובץ רישיון ישן ונסה שוב."
            )

        # עדכון שדות המחלקה לאחר שנשמר בהצלחה
        self._license = new_license
        self.school_name = school_name
        self.license_type = lic_type
        self.max_stations = int(max_stations)
        try:
            self.expiry_date = str(new_license.get('expiry_date') or '').strip() or None
        except Exception:
            self.expiry_date = None
        try:
            self.allow_cashier = bool(new_license.get('allow_cashier', True))
        except Exception:
            self.allow_cashier = True
        if str(self.license_type or '').strip().lower() == 'monthly':
            self.monthly_expired = self._is_monthly_expired(self.expiry_date)
        else:
            self.monthly_expired = False
        try:
            if str(self.license_type or '').strip().lower() == 'monthly':
                self.monthly_days_left = self._calc_monthly_days_left(self.expiry_date)
            else:
                self.monthly_days_left = 0
        except Exception:
            self.monthly_days_left = 0

        try:
            self.activated_at = str(new_license.get('activated_at') or '').strip() or None
        except Exception:
            self.activated_at = None
        try:
            self.term_days = int(new_license.get('term_days') or 0)
        except Exception:
            self.term_days = 0
        if str(self.license_type or '').strip().lower() == 'term':
            self.term_expired = self._is_term_expired(self.activated_at, int(self.term_days or 0))
        else:
            self.term_expired = False
        self.term_days_left = self._calc_term_days_left(self.activated_at, int(self.term_days or 0))
        self.trial_days_left = 0
        self.trial_expired = False

        if str(lic_type).lower() == 'monthly':
            return True, f"הרישיון החודשי הופעל בהצלחה עבור בית ספר {school_name} (בתוקף עד {exp_norm})."
        if str(lic_type).lower() == 'term':
            try:
                return True, f"הרישיון הופעל בהצלחה עבור בית ספר {school_name} ({int(term_days)} ימים)."
            except Exception:
                return True, f"הרישיון הופעל בהצלחה עבור בית ספר {school_name}."
        return True, f"הרישיון הופעל בהצלחה עבור בית ספר {school_name}."
