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
