"""
מודול לתקשורת עם מסך לקוח VeriFone MX980L
"""

import serial
import time


class CustomerDisplay:
    """מחלקה לניהול מסך לקוח VeriFone MX980L"""
    
    def __init__(self, com_port='COM1', baud_rate=9600, enabled=False, port=None, baudrate=None):
        # Backward compatible args: port/baudrate
        if port is not None:
            com_port = port
        if baudrate is not None:
            baud_rate = baudrate

        self.port = str(com_port or 'COM1').strip() or 'COM1'
        try:
            self.baudrate = int(baud_rate or 9600)
        except Exception:
            self.baudrate = 9600
        self.enabled = bool(enabled)
        self.serial = None
        self.connected = False

        if self.enabled:
            try:
                self.connect()
            except Exception:
                pass
    
    def connect(self):
        """התחברות למסך"""
        try:
            self.serial = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=5,
                write_timeout=5,
                xonxoff=False,
                rtscts=False,
                dsrdtr=False
            )
            self.connected = True
            time.sleep(0.5)
            self.clear()
            return True
        except Exception as e:
            self.connected = False
            return False
    
    def disconnect(self):
        """ניתוק מהמסך"""
        if self.serial and self.serial.is_open:
            try:
                self.serial.close()
            except:
                pass
        self.connected = False

    def close(self):
        """תאימות: cashier_station קורא close()"""
        try:
            self.disconnect()
        except Exception:
            pass

    def _ensure_connected(self) -> bool:
        if not bool(getattr(self, 'enabled', False)):
            return False
        try:
            if self.connected and self.serial and getattr(self.serial, 'is_open', False):
                return True
        except Exception:
            pass
        try:
            return bool(self.connect())
        except Exception:
            return False
    
    def _send(self, data):
        """שליחת נתונים למסך"""
        if not self.connected or not self.serial:
            return False
        try:
            if isinstance(data, str):
                # Clean text - remove problematic characters
                data = str(data).replace('"', '').replace('"', '').replace('"', '')
                # Reverse Hebrew text for display
                data = data[::-1]
                # Encode with PC862 (as discovered from display boot screen)
                data = data.encode('cp862', errors='ignore')  # ignore instead of replace
            self.serial.write(data)
            self.serial.flush()
            time.sleep(0.1)  # Slightly longer delay
            return True
        except Exception as e:
            print(f"Display send error: {e}")
            return False
    
    def _send_text(self, text):
        """Send text to display (automatically reversed and encoded)"""
        if not self.connected or not self.serial:
            return False
        try:
            # Reverse for Hebrew RTL display
            reversed_text = text[::-1]
            # Encode with PC862
            encoded = reversed_text.encode('cp862', errors='replace')
            self.serial.write(encoded)
            self.serial.flush()
            return True
        except:
            return False
    
    def clear(self):
        """ניקוי המסך"""
        self._send(b'\x0C')
        time.sleep(0.3)
    
    def show_welcome(self, campaign_name=""):
        """הצגת הודעת ברוכים הבאים למבצע"""
        if not self._ensure_connected():
            return
        self.clear()
        if campaign_name:
            self._send(f"ברוכים הבאים למבצע {campaign_name}")
        else:
            self._send("ברוכים הבאים")
        time.sleep(0.1)
        self._send(b'\n')
        self._send("הקופה פתוחה")
    
    def show_scan_card(self):
        """הצגת בקשה להעברת כרטיס"""
        if not self._ensure_connected():
            return
        self.clear()
        self._send("העבר כרטיס תלמיד")
    
    def show_student(self, name, points):
        """הצגת ברוך הבא לתלמיד + נקודות"""
        if not self._ensure_connected():
            return
        self.clear()
        self._send(f"ברוך הבא {str(name)}")
        time.sleep(0.1)
        self._send(b'\n')
        self._send(f"יש לך {int(points)} נקודות")
    
    def show_item(self, name, price):
        """הצגת פריט שנוסף לרכישה"""
        if not self._ensure_connected():
            return
        self.clear()
        self._send(str(name))
        time.sleep(0.1)
        self._send(b'\n')
        self._send(f"{int(price)} נקודות")
    
    def show_total(self, total, balance):
        """הצגת סה"כ ויתרה"""
        if not self._ensure_connected():
            return
        self.clear()
        self._send(f"סה\"כ: {int(total)} נקודות")
        time.sleep(0.1)
        self._send(b'\n')
        self._send(f"יתרה: {int(balance)} נקודות")
    
    def show_confirm_purchase(self):
        """הצגת בקשה לאישור רכישה"""
        if not self._ensure_connected():
            return
        self.clear()
        self._send("העבר כרטיס")
        time.sleep(0.1)
        self._send(b'\n')
        self._send("לאישור הרכישה")
    
    def show_payment_complete(self, message="בהצלחה"):
        """הצגת הודעת סיום (בהצלחה / תודה רבה)"""
        if not self._ensure_connected():
            return
        self.clear()
        self._send(message)
        time.sleep(0.1)
        self._send(b'\n')
        self._send("תודה רבה")
    
    def show_error(self, message="שגיאה"):
        """הצגת הודעת שגיאה"""
        if not self._ensure_connected():
            return
        self.clear()
        self._send(message)
