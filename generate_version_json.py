import json
import os
from datetime import datetime

APP_VERSION = "1.6.0"


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(base_dir, 'Output')
    os.makedirs(output_dir, exist_ok=True)

    out_path = os.path.join(output_dir, 'version.json')
    iss_inc_path = os.path.join(output_dir, 'version.issinc')

    payload = {
        'version': APP_VERSION,
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'download_url': '',
        'message': 'עדכון גרסה 1.6.0: הוספת ניהול כיתות (Web), צפייה בלוגים (Web), שיפורי ממשק ותיקוני באגים.'
    }

    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    with open(iss_inc_path, 'w', encoding='utf-8') as f:
        f.write(f'#define MyAppVersion "{APP_VERSION}"\n')

    print(f"Wrote: {out_path}")
    print(f"Wrote: {iss_inc_path}")


if __name__ == '__main__':
    main()
