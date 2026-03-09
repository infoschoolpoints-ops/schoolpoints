from __future__ import annotations

from dataclasses import dataclass
from datetime import date as pydate
from typing import List, Optional, Dict


try:
    from pyluach import dates, parshios

    _PYLUACH_AVAILABLE = True
except Exception:
    dates = None
    parshios = None
    _PYLUACH_AVAILABLE = False


@dataclass(frozen=True)
class JewishDayInfo:
    weekday_he: str
    hebrew_date_he: str
    parsha_he: Optional[str]
    holiday_he: Optional[str]


@dataclass(frozen=True)
class JewishListItem:
    gregorian: pydate
    hebrew_date_he: str
    title_he: str


def is_available() -> bool:
    return _PYLUACH_AVAILABLE


def _greg_from_pydate(d: pydate):
    if not _PYLUACH_AVAILABLE:
        raise RuntimeError("pyluach not available")
    return dates.GregorianDate.from_pydate(d)


def _normalize_hebrew_quotes(text: Optional[str]) -> str:
    if text is None:
        return ""
    # החלפת גרש/גרשיים עבריים (U+05F3/U+05F4) לתווים סטנדרטיים
    # כדי למנוע ריבועים במקרים שהפונט לא מכיל את התווים.
    result = (
        str(text)
        .replace("\u05F3", "'")
        .replace("\u05F4", '"')
    )
    return result if result else ""


def hebrew_date_from_gregorian_str(gregorian_date: str, *, israel: bool = True) -> str:
    """Convert YYYY-MM-DD (Gregorian) to Hebrew date string for UI/printing.

    Returns empty string if conversion is unavailable or input is invalid.
    """
    if not _PYLUACH_AVAILABLE:
        return ""
    s = str(gregorian_date or '').strip()
    if not s:
        return ""
    try:
        y, m, d = s.split('-', 2)
        g = dates.GregorianDate(int(y), int(m), int(d))
        heb = g.to_heb()
        # Get current Hebrew date for comparison
        today = pydate.today()
        today_heb = dates.GregorianDate(today.year, today.month, today.day).to_heb()
        
        # If it's today's date, return today's Hebrew date
        if (g.year == today.year and g.month == today.month and g.day == today.day):
            return _normalize_hebrew_quotes(today_heb.hebrew_date_string()) or ""
        
        # Otherwise return the requested date
        return _normalize_hebrew_quotes(heb.hebrew_date_string()) or ""
    except Exception:
        return ""


def get_today_info(today: Optional[pydate] = None, *, israel: bool = True) -> Optional[JewishDayInfo]:
    if not _PYLUACH_AVAILABLE:
        return None

    today = today or pydate.today()
    greg = _greg_from_pydate(today)
    heb = greg.to_heb()

    weekday_he = _normalize_hebrew_quotes((f"יום {heb:%*A}").strip())
    hebrew_date_he = _normalize_hebrew_quotes(heb.hebrew_date_string())

    parsha_he = _normalize_hebrew_quotes(parshios.getparsha_string(greg, hebrew=True, israel=israel))

    holiday_he = _normalize_hebrew_quotes(heb.holiday(israel=israel, hebrew=True, prefix_day=True))

    return JewishDayInfo(
        weekday_he=weekday_he,
        hebrew_date_he=hebrew_date_he,
        parsha_he=parsha_he,
        holiday_he=holiday_he,
    )


def upcoming_parshios(
    start: Optional[pydate] = None,
    *,
    weeks: int = 12,
    israel: bool = True,
) -> List[JewishListItem]:
    if not _PYLUACH_AVAILABLE:
        return []

    if weeks < 1:
        return []

    start = start or pydate.today()
    g0 = _greg_from_pydate(start).shabbos()

    out: List[JewishListItem] = []
    for i in range(weeks):
        g = g0 + (i * 7)
        heb = g.to_heb()
        greg_py = g.to_pydate()

        parsha = _normalize_hebrew_quotes(parshios.getparsha_string(g, hebrew=True, israel=israel))
        if parsha:
            title = f"פרשת {parsha}".strip()
        else:
            hol = _normalize_hebrew_quotes(heb.holiday(israel=israel, hebrew=True, prefix_day=True))
            title = hol or ""
        if title:
            out.append(
                JewishListItem(
                    gregorian=greg_py,
                    hebrew_date_he=_normalize_hebrew_quotes(heb.hebrew_date_string()) or "",
                    title_he=title,
                )
            )

    return out


def upcoming_holidays(
    start: Optional[pydate] = None,
    *,
    days: int = 120,
    israel: bool = True,
) -> List[JewishListItem]:
    if not _PYLUACH_AVAILABLE:
        return []

    if days < 1:
        return []

    start = start or pydate.today()
    g0 = _greg_from_pydate(start)

    out: List[JewishListItem] = []
    last_title: Optional[str] = None

    for i in range(days):
        g = g0 + i
        heb = g.to_heb()
        hol = _normalize_hebrew_quotes(heb.holiday(israel=israel, hebrew=True, prefix_day=True))
        if not hol:
            continue

        if hol == last_title:
            continue
        last_title = hol

        out.append(
            JewishListItem(
                gregorian=g.to_pydate(),
                hebrew_date_he=_normalize_hebrew_quotes(heb.hebrew_date_string()) or "",
                title_he=hol,
            )
        )

    return out


# ---------- המרת מספרים לאותיות עבריות ----------

_ONES = ['', 'א', 'ב', 'ג', 'ד', 'ה', 'ו', 'ז', 'ח', 'ט']
_TENS = ['', 'י', 'כ', 'ל', 'מ', 'נ', 'ס', 'ע', 'פ', 'צ']
_HUNDREDS = ['', 'ק', 'ר', 'ש', 'ת']


def _num_to_heb_raw(n: int) -> str:
    """המרת מספר (1-999) לאותיות עבריות ללא גרש/גרשיים."""
    if n <= 0:
        return ''
    parts = []
    while n >= 400:
        parts.append('ת')
        n -= 400
    if n >= 100:
        parts.append(_HUNDREDS[n // 100])
        n %= 100
    if n == 15:
        parts.append('ט')
        parts.append('ו')
        n = 0
    elif n == 16:
        parts.append('ט')
        parts.append('ז')
        n = 0
    if n >= 10:
        parts.append(_TENS[n // 10])
        n %= 10
    if n > 0:
        parts.append(_ONES[n])
    return ''.join(parts)


def number_to_hebrew_letters(n: int, with_punctuation: bool = True) -> str:
    """המרת מספר לאותיות עבריות עם גרש/גרשיים.
    דוגמאות: 1→א׳, 15→ט״ו, 785→תשפ״ה
    """
    raw = _num_to_heb_raw(n)
    if not raw:
        return ''
    if not with_punctuation:
        return raw
    if len(raw) == 1:
        return raw + "'"
    return raw[:-1] + '"' + raw[-1]


def hebrew_day_display_list() -> list:
    """מחזיר רשימה של 30 ימים בעברית: ['', \"א'\", \"ב'\", ... \"ל'\"]"""
    return [''] + [number_to_hebrew_letters(i) for i in range(1, 31)]


def hebrew_day_from_display(display: str) -> int:
    """המרת תצוגת יום עברי חזרה למספר."""
    display = display.strip().replace('"', '').replace("'", '').replace('״', '').replace('׳', '')
    if not display:
        return 0
    _heb_vals = {'א': 1, 'ב': 2, 'ג': 3, 'ד': 4, 'ה': 5, 'ו': 6, 'ז': 7, 'ח': 8, 'ט': 9,
                 'י': 10, 'כ': 20, 'ל': 30, 'מ': 40, 'נ': 50, 'ס': 60, 'ע': 70, 'פ': 80, 'צ': 90}
    return sum(_heb_vals.get(c, 0) for c in display)


def hebrew_year_display(year: int) -> str:
    """המרת שנה עברית (5750-5900) לתצוגה: 5785 → תשפ״ה"""
    if year <= 0:
        return ''
    remainder = year % 1000
    return number_to_hebrew_letters(remainder)


def hebrew_year_from_display(display: str) -> int:
    """המרת תצוגת שנה עברית למספר: תשפ״ה → 5785"""
    display = display.strip().replace('"', '').replace("'", '').replace('״', '').replace('׳', '')
    if not display:
        return 0
    _heb_vals = {'א': 1, 'ב': 2, 'ג': 3, 'ד': 4, 'ה': 5, 'ו': 6, 'ז': 7, 'ח': 8, 'ט': 9,
                 'י': 10, 'כ': 20, 'ל': 30, 'מ': 40, 'נ': 50, 'ס': 60, 'ע': 70, 'פ': 80, 'צ': 90,
                 'ק': 100, 'ר': 200, 'ש': 300, 'ת': 400}
    val = sum(_heb_vals.get(c, 0) for c in display)
    if val > 0:
        val += 5000
    return val


def hebrew_year_display_list(start: int = 5750, end: int = 5800) -> list:
    """רשימת שנים עבריות לבחירה."""
    return [''] + [hebrew_year_display(y) for y in range(start, end + 1)]


_HEBREW_MONTHS = {
    1: 'ניסן', 2: 'אייר', 3: 'סיון', 4: 'תמוז', 5: 'אב', 6: 'אלול',
    7: 'תשרי', 8: 'חשון', 9: 'כסלו', 10: 'טבת', 11: 'שבט', 12: 'אדר',
    13: "אדר ב'",
}


def get_hebrew_month_name(month: int) -> str:
    return _HEBREW_MONTHS.get(month, '')


def get_today_hebrew_date_parts(today: Optional[pydate] = None) -> Optional[Dict[str, int]]:
    """מחזיר dict עם day, month, year של התאריך העברי של היום."""
    if not _PYLUACH_AVAILABLE:
        return None
    try:
        today = today or pydate.today()
        greg = _greg_from_pydate(today)
        heb = greg.to_heb()
        return {'day': heb.day, 'month': heb.month, 'year': heb.year}
    except Exception:
        return None


def is_leap_year_hebrew(year: int) -> bool:
    """בדיקה אם שנה עברית היא מעוברת."""
    if not _PYLUACH_AVAILABLE:
        return False
    try:
        from pyluach import hebrewcal
        return hebrewcal.Year(year).leap
    except Exception:
        # Fallback: שנה מעוברת אם year % 19 in (0,3,6,8,11,14,17)
        return (year % 19) in (0, 3, 6, 8, 11, 14, 17)


def build_birthday_news_items(
    students: list,
    *,
    message_template: str = '',
    bar_mitzvah_template: str = '',
) -> List[str]:
    """בונה הודעות יום הולדת לטיקר מתוך רשימת תלמידים שחוגגים היום.

    students: רשימת dict עם first_name, last_name, class_name, gender,
              hebrew_birth_year.
    message_template: תבנית הודעה רגילה. placeholders: {name}, {class}, {suffix}
    bar_mitzvah_template: תבנית בר/בת מצווה. placeholders: {name}, {class}, {bar_bat}
    """
    if not students:
        return []

    heb_today = get_today_hebrew_date_parts()
    current_year = heb_today['year'] if heb_today else 0

    if not message_template:
        message_template = '🎂 מזל טוב ל{name} מכיתה {class} ליום הולד{suffix}!'
    if not bar_mitzvah_template:
        bar_mitzvah_template = '🎉 מזל טוב ל{name} מכיתה {class} לרגל {bar_bat}!'

    items: List[str] = []
    for s in students:
        try:
            fname = str(s.get('first_name') or '').strip()
            lname = str(s.get('last_name') or '').strip()
            cls = str(s.get('class_name') or '').strip()
            gender = str(s.get('gender') or '').strip().upper()
            birth_year = int(s.get('hebrew_birth_year') or 0)

            name = f"{fname} {lname}".strip()
            if not name:
                continue

            # בדיקת בר/בת מצווה
            is_bar = False
            is_bat = False
            if birth_year > 0 and current_year > 0:
                age = current_year - birth_year
                if gender == 'M' and age == 13:
                    is_bar = True
                elif gender == 'F' and age == 12:
                    is_bat = True

            if is_bar:
                msg = bar_mitzvah_template.replace('{name}', name).replace('{class}', cls).replace('{bar_bat}', 'בר המצווה שלו')
            elif is_bat:
                msg = bar_mitzvah_template.replace('{name}', name).replace('{class}', cls).replace('{bar_bat}', 'בת המצווה שלה')
            else:
                suffix = 'תו' if gender == 'M' else ('תה' if gender == 'F' else 'תו')
                msg = message_template.replace('{name}', name).replace('{class}', cls).replace('{suffix}', suffix)

            items.append(msg)
        except Exception:
            continue
    return items


def build_calendar_news_items(
    *,
    israel: bool,
    show_weekday: bool,
    show_hebrew_date: bool,
    show_parsha: bool,
    show_holidays: bool,
) -> List[str]:
    info = get_today_info(israel=israel)
    if not info:
        return []

    items: List[str] = []
    if show_weekday and info.weekday_he:
        items.append(info.weekday_he)
    if show_hebrew_date and info.hebrew_date_he:
        items.append(info.hebrew_date_he)
    if show_parsha and info.parsha_he:
        items.append(f"פרשת {info.parsha_he}")
    if show_holidays and info.holiday_he:
        items.append(f"{info.holiday_he}")

    return items


def render_preview_list(
    *,
    israel: bool,
    weeks: int = 12,
    days: int = 120,
) -> Dict[str, str]:
    parsha_items = upcoming_parshios(weeks=weeks, israel=israel)
    holiday_items = upcoming_holidays(days=days, israel=israel)

    parsha_lines: List[str] = []
    for it in parsha_items:
        g = it.gregorian.strftime("%d/%m/%Y")
        parsha_lines.append(f"{g}  |  {it.hebrew_date_he}  |  {it.title_he}")

    holiday_lines: List[str] = []
    for it in holiday_items:
        g = it.gregorian.strftime("%d/%m/%Y")
        holiday_lines.append(f"{g}  |  {it.hebrew_date_he}  |  {it.title_he}")

    return {
        "parshios": "\n".join(parsha_lines),
        "holidays": "\n".join(holiday_lines),
    }
