# -*- coding: utf-8 -*-
"""
מנהל צלילים למערכת SchoolPoints
מטפל בהשמעת צלילים בעמדה הציבורית
"""

import os
import threading
from typing import Optional, Dict
import json
import time

# ננסה לייבא pygame, אם לא קיים נשתמש ב-winsound
try:
    import pygame
    try:
        pygame.mixer.init()
        USE_PYGAME = True
    except Exception:
        import winsound
        USE_PYGAME = False
        print("⚠️ pygame לא זמין, משתמש ב-winsound (תמיכה מוגבלת ל-WAV בלבד)")
except ImportError:
    import winsound
    USE_PYGAME = False
    print("⚠️ pygame לא זמין, משתמש ב-winsound (תמיכה מוגבלת ל-WAV בלבד)")


class SoundManager:
    """מנהל השמעת צלילים"""
    
    def __init__(self, base_dir: str, sounds_dir: str = None):
        """
        אתחול מנהל הצלילים
        
        Args:
            base_dir: תיקיית הבסיס של המערכת
        """
        self.base_dir = base_dir
        if sounds_dir:
            self.sounds_dir = os.path.abspath(str(sounds_dir))
        else:
            self.sounds_dir = os.path.join(base_dir, 'sounds')
        self.enabled = True
        self.volume = 1.0  # 0.0 - 1.0
        self.sound_cache: Dict[str, any] = {}
        self._sound_index_cache: Optional[Dict[str, str]] = None
        self._sound_index_cache_ts = 0.0
        self._sound_index_cache_ttl_sec = 30.0

        # pygame.mixer.music הוא ערוץ יחיד; נשתמש בנעילה כדי למנוע התנגשויות
        self._music_lock = threading.Lock()
        
        # יצירת תיקיית צלילים אם לא קיימת
        try:
            if not os.path.exists(self.sounds_dir):
                os.makedirs(self.sounds_dir, exist_ok=True)
        except Exception:
            # אם נתיב רשת/נתיב חסום – לא מפילים את האפליקציה, פשוט נמשיך בלי ליצור תיקייה
            pass
    
    def set_enabled(self, enabled: bool):
        """הפעלה/כיבוי של השמעת צלילים"""
        self.enabled = enabled
    
    def set_volume(self, volume: float):
        """
        קביעת עוצמת השמע
        
        Args:
            volume: ערך בין 0.0 (שקט) ל-1.0 (מלא)
        """
        self.volume = max(0.0, min(1.0, volume))
        if USE_PYGAME:
            pygame.mixer.music.set_volume(self.volume)
            try:
                for v in (self.sound_cache or {}).values():
                    try:
                        if hasattr(v, 'set_volume'):
                            v.set_volume(self.volume)
                    except Exception:
                        continue
            except Exception:
                pass
    
    def load_sound(self, sound_path: str) -> bool:
        """
        טעינת צליל לזיכרון (cache)
        
        Args:
            sound_path: נתיב מלא לקובץ הצליל
            
        Returns:
            True אם הצליל נטען בהצלחה
        """
        if not os.path.exists(sound_path):
            print(f"⚠️ קובץ צליל לא נמצא: {sound_path}")
            return False
        
        # בדיקת גודל קובץ (אזהרה אם גדול מ-500KB)
        file_size = os.path.getsize(sound_path)
        if file_size > 500 * 1024:
            print(f"⚠️ קובץ צליל גדול מדי ({file_size / 1024:.1f}KB): {sound_path}")
        
        try:
            if USE_PYGAME:
                ext = str(os.path.splitext(sound_path)[1] or '').lower()
                try:
                    sound = pygame.mixer.Sound(sound_path)
                    sound.set_volume(self.volume)
                    self.sound_cache[sound_path] = sound
                    return True
                except Exception:
                    # בחלק מהתקנות pygame לא יודע לטעון MP3 כ-Sound.
                    # נשתמש ב-mixer.music כ-fallback לערוץ יחיד.
                    if ext in ('.mp3', '.ogg'):
                        self.sound_cache[sound_path] = ('music', sound_path)
                        return True
                    raise
            else:
                # עם winsound לא צריך לטעון מראש
                self.sound_cache[sound_path] = sound_path
            return True
        except Exception as e:
            print(f"❌ שגיאה בטעינת צליל {sound_path}: {e}")
            return False
    
    def play_sound(self, sound_path: str, async_play: bool = True):
        """
        השמעת צליל
        
        Args:
            sound_path: נתיב מלא לקובץ הצליל
            async_play: האם להשמיע באופן אסינכרוני (לא חוסם)
        """
        if not self.enabled:
            return
        
        if not sound_path:
            return

        # winsound תומך רק ב-WAV – אם נשלח MP3/OGG ננסה למצוא קובץ WAV תואם
        if (not USE_PYGAME) and sound_path.lower().endswith(('.mp3', '.ogg')):
            try:
                base, _ext = os.path.splitext(sound_path)
                wav_path = base + '.wav'
                if os.path.exists(wav_path):
                    sound_path = wav_path
            except Exception:
                pass

        if not os.path.exists(sound_path):
            return
        
        # טעינת הצליל אם עדיין לא בcache
        if sound_path not in self.sound_cache:
            if not self.load_sound(sound_path):
                return
        
        # השמעה
        if async_play:
            thread = threading.Thread(target=self._play_sound_sync, args=(sound_path,))
            thread.daemon = True
            thread.start()
        else:
            self._play_sound_sync(sound_path)
    
    def _play_sound_sync(self, sound_path: str):
        """השמעה סינכרונית (פנימית)"""
        try:
            if USE_PYGAME:
                sound = self.sound_cache.get(sound_path)
                if sound:
                    # music fallback
                    try:
                        if isinstance(sound, tuple) and len(sound) >= 2 and str(sound[0]) == 'music':
                            with self._music_lock:
                                pygame.mixer.music.load(str(sound[1]))
                                pygame.mixer.music.set_volume(self.volume)
                                pygame.mixer.music.play()
                            return
                    except Exception:
                        pass

                    try:
                        sound.play()
                    except Exception:
                        # אם נכשל – ננסה fallback ל-music עבור mp3/ogg
                        try:
                            ext = str(os.path.splitext(sound_path)[1] or '').lower()
                        except Exception:
                            ext = ''
                        if ext in ('.mp3', '.ogg'):
                            try:
                                with self._music_lock:
                                    pygame.mixer.music.load(sound_path)
                                    pygame.mixer.music.set_volume(self.volume)
                                    pygame.mixer.music.play()
                                return
                            except Exception:
                                pass
            else:
                # winsound - תמיכה רק ב-WAV
                if sound_path.lower().endswith('.wav'):
                    winsound.PlaySound(sound_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
        except Exception as e:
            print(f"❌ שגיאה בהשמעת צליל: {e}")
    
    def stop_all(self):
        """עצירת כל הצלילים"""
        if USE_PYGAME:
            pygame.mixer.stop()
            try:
                pygame.mixer.music.stop()
            except Exception:
                pass

    def _build_sound_index(self) -> Dict[str, str]:
        sounds: Dict[str, str] = {}
        if not os.path.exists(self.sounds_dir):
            return sounds

        if USE_PYGAME:
            priorities = {'.wav': 30, '.mp3': 20, '.ogg': 10}
            allowed = {'.wav', '.mp3', '.ogg'}
        else:
            priorities = {'.wav': 30}
            allowed = {'.wav'}

        for root, _, files in os.walk(self.sounds_dir):
            for filename in files:
                try:
                    ext = str(os.path.splitext(filename)[1] or '').lower()
                except Exception:
                    ext = ''
                if ext not in allowed:
                    continue
                name = os.path.splitext(filename)[0]
                path = os.path.join(root, filename)
                key = str(name).strip().lower()
                if not key:
                    continue
                prev = sounds.get(key)
                if not prev:
                    sounds[key] = path
                    continue
                try:
                    prev_ext = str(os.path.splitext(prev)[1] or '').lower()
                except Exception:
                    prev_ext = ''
                if int(priorities.get(ext, 0)) > int(priorities.get(prev_ext, 0)):
                    sounds[key] = path
        return sounds

    def _get_sound_index(self) -> Dict[str, str]:
        try:
            ttl = float(self._sound_index_cache_ttl_sec or 0)
        except Exception:
            ttl = 0.0
        now = time.time()
        if self._sound_index_cache is not None and ttl > 0 and (now - self._sound_index_cache_ts) < ttl:
            return self._sound_index_cache
        sounds = self._build_sound_index()
        self._sound_index_cache = sounds
        self._sound_index_cache_ts = now
        return sounds

    def invalidate_sound_index(self) -> None:
        self._sound_index_cache = None
        self._sound_index_cache_ts = 0.0

    def resolve_sound(self, keys) -> Optional[str]:
        try:
            sounds = self._get_sound_index()
        except Exception:
            sounds = {}

        if not sounds:
            return None

        token_index: Dict[str, str] = {}
        token_counts: Dict[str, int] = {}
        try:
            for full_key, path in (sounds or {}).items():
                try:
                    tok = str(full_key).strip().lower().split(' ')[0]
                except Exception:
                    tok = ''
                if not tok:
                    continue
                token_counts[tok] = int(token_counts.get(tok, 0) or 0) + 1
                # נשמור נתיב כלשהו, נשתמש בו רק אם ייחודי
                if tok not in token_index:
                    token_index[tok] = path
        except Exception:
            token_index = {}
            token_counts = {}

        for k in (keys or []):
            try:
                kk = str(k).strip().lower()
            except Exception:
                kk = ''
            if not kk:
                continue
            if kk in sounds:
                return sounds[kk]
            try:
                tok = str(kk).split(' ')[0].strip().lower()
            except Exception:
                tok = ''
            if tok and int(token_counts.get(tok, 0) or 0) == 1:
                p = token_index.get(tok)
                if p:
                    return p
        return None
    
    def get_default_sounds(self) -> Dict[str, str]:
        """
        החזרת רשימת צלילים ברירת מחדל
        
        Returns:
            מילון עם שמות צלילים ונתיבים
        """
        default_sounds = {}
        
        if os.path.exists(self.sounds_dir):
            for root, _, files in os.walk(self.sounds_dir):
                for filename in files:
                    if filename.lower().endswith(('.wav', '.mp3', '.ogg')):
                        name = os.path.splitext(filename)[0]
                        path = os.path.join(root, filename)
                        default_sounds[name] = path
        
        return default_sounds
    
    def preload_sounds(self, sound_paths: list):
        """
        טעינה מראש של רשימת צלילים
        
        Args:
            sound_paths: רשימת נתיבים לצלילים
        """
        for path in sound_paths:
            if path and os.path.exists(path):
                self.load_sound(path)


# דוגמה לשימוש
if __name__ == "__main__":
    # בדיקה
    manager = SoundManager(os.path.dirname(__file__))
    print(f"מנהל צלילים אותחל. pygame: {USE_PYGAME}")
    print(f"תיקיית צלילים: {manager.sounds_dir}")
    
    default_sounds = manager.get_default_sounds()
    print(f"\nצלילים זמינים: {len(default_sounds)}")
    for name, path in default_sounds.items():
        print(f"  - {name}: {path}")
