"""
לוגר SchoolPoints.
RotatingFileHandler - עד 5MB x 3 גיבויים.

שימוש:
    import sp_logger
    sp_logger.install()          # קורא ב-main - לוכד כל print()
    log = sp_logger.get_logger() # מחזיר logger רגיל
"""
import os
import sys
import logging
import threading
from logging.handlers import RotatingFileHandler
from datetime import datetime

_logger = None
_LOG_DIR = None
_installed = False
_install_lock = threading.Lock()


def _resolve_log_dir() -> str:
    """מחזיר תיקיית לוגים - ליד ה-EXE או ב-LOCALAPPDATA."""
    # ניסיון ראשון: ליד הקובץ / EXE
    try:
        base = os.path.dirname(os.path.abspath(sys.argv[0] or __file__))
        log_dir = os.path.join(base, 'logs')
        os.makedirs(log_dir, exist_ok=True)
        test_file = os.path.join(log_dir, '.write_test')
        with open(test_file, 'w') as f:
            f.write('ok')
        os.remove(test_file)
        return log_dir
    except Exception:
        pass
    # fallback: LOCALAPPDATA
    try:
        local = os.environ.get('LOCALAPPDATA') or os.environ.get('APPDATA') or os.path.expanduser('~')
        log_dir = os.path.join(local, 'SchoolPoints', 'logs')
        os.makedirs(log_dir, exist_ok=True)
        return log_dir
    except Exception:
        return os.path.dirname(os.path.abspath(__file__))


class _TeeStream:
    """עוטף stdout/stderr וכותב גם לקובץ לוג.
    כותב ישירות לקובץ - בטוח לאחר rotation."""

    def __init__(self, original_stream, log_path, max_bytes, backup_count):
        self._original = original_stream
        self._log_path = log_path
        self._max_bytes = max_bytes
        self._backup_count = backup_count
        self._lock = threading.Lock()
        self._file = None
        self._file_size = 0
        self._open_file()

    def _open_file(self):
        """פותח/פותח מחדש את קובץ הלוג."""
        try:
            if self._file:
                try:
                    self._file.close()
                except Exception:
                    pass
            self._file = open(self._log_path, 'a', encoding='utf-8')
            try:
                self._file_size = self._file.tell()
            except Exception:
                self._file_size = 0
        except Exception:
            self._file = None
            self._file_size = 0

    def _do_rollover(self):
        """ביצוע rotation ידני של קובץ הלוג."""
        try:
            if self._file:
                self._file.close()
                self._file = None
            # rename chain: .log.2 -> .log.3, .log.1 -> .log.2, .log -> .log.1
            for i in range(self._backup_count - 1, 0, -1):
                src = f"{self._log_path}.{i}"
                dst = f"{self._log_path}.{i + 1}"
                if os.path.exists(src):
                    try:
                        if os.path.exists(dst):
                            os.remove(dst)
                        os.rename(src, dst)
                    except Exception:
                        pass
            dst = f"{self._log_path}.1"
            try:
                if os.path.exists(dst):
                    os.remove(dst)
                os.rename(self._log_path, dst)
            except Exception:
                pass
            self._open_file()
        except Exception:
            self._open_file()

    def write(self, text):
        try:
            if self._original:
                self._original.write(text)
        except Exception:
            pass
        try:
            if text and text.strip():
                with self._lock:
                    if self._file is None:
                        self._open_file()
                    if self._file is None:
                        return
                    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    line = f"{ts} [PRINT] {text.rstrip()}\n"
                    try:
                        self._file.write(line)
                        self._file.flush()
                        self._file_size += len(line.encode('utf-8', errors='replace'))
                    except Exception:
                        # קובץ נסגר/נמחק - פתיחה מחדש
                        self._open_file()
                        if self._file:
                            try:
                                self._file.write(line)
                                self._file.flush()
                                self._file_size += len(line.encode('utf-8', errors='replace'))
                            except Exception:
                                pass
                    # rotation check
                    if self._max_bytes > 0 and self._file_size >= self._max_bytes:
                        self._do_rollover()
        except Exception:
            pass

    def flush(self):
        try:
            if self._original:
                self._original.flush()
        except Exception:
            pass

    def fileno(self):
        if self._original:
            return self._original.fileno()
        raise OSError("no fileno")

    def isatty(self):
        try:
            return self._original.isatty() if self._original else False
        except Exception:
            return False

    @property
    def encoding(self):
        try:
            return self._original.encoding if self._original else 'utf-8'
        except Exception:
            return 'utf-8'


def get_logger(name: str = 'SchoolPoints') -> logging.Logger:
    """מחזיר logger עם handler לקובץ."""
    global _logger, _LOG_DIR
    if _logger is not None:
        return _logger

    _LOG_DIR = _resolve_log_dir()
    log_path = os.path.join(_LOG_DIR, 'schoolpoints.log')

    _logger = logging.getLogger(name)
    _logger.setLevel(logging.DEBUG)

    # קובץ: 5MB x 3 גיבויים, UTF-8
    try:
        fh = RotatingFileHandler(
            log_path,
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding='utf-8',
        )
        fh.setLevel(logging.DEBUG)
        fmt = logging.Formatter(
            '%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
        )
        fh.setFormatter(fmt)
        _logger.addHandler(fh)
    except Exception:
        pass

    # קונסול (stdout) - רמת INFO ומעלה
    try:
        ch = logging.StreamHandler(sys.__stdout__ or sys.stdout)
        ch.setLevel(logging.INFO)
        ch_fmt = logging.Formatter('[%(levelname)s] %(message)s')
        ch.setFormatter(ch_fmt)
        _logger.addHandler(ch)
    except Exception:
        pass

    return _logger


def install():
    """התקנה חד-פעמית: לוכד print() וכותב לקובץ.
    בטוח לקריאה כפולה - מתבצע רק פעם אחת.
    בטוח לקריאה מ-thread - נעילה פנימית."""
    global _installed
    with _install_lock:
        if _installed:
            return
        _installed = True
    try:
        log_dir = _resolve_log_dir()
        log_path = os.path.join(log_dir, 'schoolpoints.log')
        max_bytes = 5 * 1024 * 1024
        backup_count = 3
        tee_out = _TeeStream(sys.__stdout__ or sys.stdout, log_path, max_bytes, backup_count)
        tee_err = _TeeStream(sys.__stderr__ or sys.stderr, log_path, max_bytes, backup_count)
        # כתיבת START ישירות
        try:
            with open(log_path, 'a', encoding='utf-8') as f:
                ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                f.write(f"\n{'='*60}\n{ts} [START] SchoolPoints process started\n{'='*60}\n")
            # עדכון file_size ב-tee
            try:
                tee_out._file_size = os.path.getsize(log_path)
                tee_err._file_size = os.path.getsize(log_path)
            except Exception:
                pass
        except Exception:
            pass
        sys.stdout = tee_out
        sys.stderr = tee_err
    except Exception:
        # אם נכשל - לא לשבור את התוכנית
        pass


def get_log_dir() -> str:
    """מחזיר נתיב תיקיית הלוגים."""
    global _LOG_DIR
    if _LOG_DIR:
        return _LOG_DIR
    _LOG_DIR = _resolve_log_dir()
    return _LOG_DIR or ''
