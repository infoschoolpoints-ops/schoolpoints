import os

# Build info
APP_BUILD_TAG = "2026-02-05-modular-v1"

# Base paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) # cloud_service/
ROOT_DIR = os.path.dirname(BASE_DIR) # project root
DATA_DIR = str(os.getenv('CLOUD_DATA_DIR') or '').strip() or os.path.join(BASE_DIR, 'data')

# Database
DATABASE_URL = str(os.getenv('DATABASE_URL') or '').strip()
USE_POSTGRES = bool(DATABASE_URL)
DB_PATH = os.path.join(DATA_DIR, 'cloud.db')

# Storage (DigitalOcean Spaces / AWS S3)
SPACES_REGION = str(os.getenv('SPACES_REGION') or '').strip()
SPACES_BUCKET = str(os.getenv('SPACES_BUCKET') or '').strip()
SPACES_KEY = str(os.getenv('SPACES_KEY') or '').strip()
SPACES_SECRET = str(os.getenv('SPACES_SECRET') or '').strip()
SPACES_ENDPOINT = str(os.getenv('SPACES_ENDPOINT') or '').strip() # e.g. https://fra1.digitaloceanspaces.com
SPACES_CDN_BASE_URL = str(os.getenv('SPACES_CDN_BASE_URL') or '').strip()

# Email / SMTP
SMTP_HOST = (os.getenv('SMTP_HOST') or os.getenv('SMTP_SERVER') or '').strip()
SMTP_PORT = int(os.getenv('SMTP_PORT') or 587)
SMTP_USER = (os.getenv('SMTP_USER') or '').strip()
SMTP_PASSWORD = (os.getenv('SMTP_PASSWORD') or os.getenv('SMTP_PASS') or '').strip()
SMTP_FROM = (os.getenv('SMTP_FROM') or SMTP_USER).strip()
CONTACT_EMAIL_TO = (os.getenv('CONTACT_EMAIL_TO') or SMTP_USER).strip()
REGISTRATION_NOTIFY_EMAIL = (os.getenv('REGISTRATION_NOTIFY_EMAIL') or '').strip()

# Other
MASTER_PASSWORD_HASH = "8d969eef6ecad3c29a3a629280e686cf0c3f5d5a86aff3ca12020c923adc6c92" # sha256 of 'master' (default)
ADMIN_KEY = str(os.getenv('ADMIN_KEY') or '').strip()
MASTER_LOGIN_SECRET = str(os.getenv('MASTER_LOGIN_SECRET') or '').strip()
