"""Run public station WITHOUT console window to test if console close is the issue."""
import sys, os
os.chdir(r'c:\מיצד\SchoolPoints')
sys.path.insert(0, r'c:\מיצד\SchoolPoints')

# Log to file since no console
import time
log = open(r'c:\מיצד\SchoolPoints\no_console.log', 'w', encoding='utf-8', buffering=1)
log.write(f"[{time.strftime('%H:%M:%S')}] Starting without console\n")

import public_station
try:
    public_station.main()
except Exception as e:
    log.write(f"[{time.strftime('%H:%M:%S')}] Exception: {e}\n")

log.write(f"[{time.strftime('%H:%M:%S')}] Ended\n")
log.flush()
log.close()
