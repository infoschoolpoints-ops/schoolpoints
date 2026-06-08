import os
import re
import json
import hashlib
import secrets
import urllib.request
import urllib.parse
from typing import List, Dict, Any

def _calc_file_hash(path: str) -> str:
    hash_md5 = hashlib.md5()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    except Exception:
        return ""

def _get_local_file_manifest(root_dir: str, subdirs: List[str]) -> Dict[str, str]:
    manifest = {}
    for subdir in subdirs:
        abs_base = os.path.join(root_dir, subdir)
        if not os.path.isdir(abs_base):
            continue
        for root, _, files in os.walk(abs_base):
            for name in files:
                if name.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp', '.wav', '.mp3', '.ogg')):
                    full_path = os.path.join(root, name)
                    rel_path = os.path.relpath(full_path, root_dir).replace('\\', '/')
                    manifest[rel_path] = _calc_file_hash(full_path)
    return manifest

def normalize_assets_for_sync(base_dir: str, config: dict) -> dict:
    """Copy logo and student photos from absolute paths into base_dir/images/ for cloud sync.

    Returns a dict with updated local absolute paths (logo_path, photos_folder) if they changed.
    This is a one-way normalization — the source paths remain unchanged; we just mirror
    the files into a location the sync module can discover.
    """
    import shutil as _shutil
    images_dir = os.path.join(base_dir, 'images')
    updated: dict = {}

    # --- Logo ---
    logo_path = str(config.get('logo_path') or '').strip()
    if logo_path and os.path.isfile(logo_path):
        dest_logo_dir = os.path.join(images_dir, 'logo')
        try:
            os.makedirs(dest_logo_dir, exist_ok=True)
            fname = os.path.basename(logo_path)
            dest = os.path.join(dest_logo_dir, fname)
            src_hash = _calc_file_hash(logo_path)
            dst_hash = _calc_file_hash(dest) if os.path.exists(dest) else ''
            if src_hash != dst_hash:
                _shutil.copy2(logo_path, dest)
                print(f"[ASSET-SYNC] Copied logo to images/logo/{fname}")
            updated['logo_path'] = dest
        except Exception as e:
            print(f"[ASSET-SYNC] Logo copy failed: {e}")

    # --- Student photos ---
    photos_folder = str(config.get('photos_folder') or '').strip()
    if photos_folder and os.path.isdir(photos_folder):
        dest_photos_dir = os.path.join(images_dir, 'photos')
        try:
            os.makedirs(dest_photos_dir, exist_ok=True)
            # Skip if already inside images/ (already normalized)
            if not os.path.abspath(photos_folder).startswith(os.path.abspath(images_dir) + os.sep):
                copied = 0
                for fname in os.listdir(photos_folder):
                    if fname.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
                        src = os.path.join(photos_folder, fname)
                        dst = os.path.join(dest_photos_dir, fname)
                        src_hash = _calc_file_hash(src)
                        dst_hash = _calc_file_hash(dst) if os.path.exists(dst) else ''
                        if src_hash != dst_hash:
                            _shutil.copy2(src, dst)
                            copied += 1
                if copied > 0:
                    print(f"[ASSET-SYNC] Copied {copied} photo(s) to images/photos/")
            updated['photos_folder'] = dest_photos_dir
        except Exception as e:
            print(f"[ASSET-SYNC] Photos copy failed: {e}")

    return updated


def normalize_db_image_assets(db_path: str, base_dir: str) -> int:
    """Mirror product/ad/closure image files that are stored with absolute local
    paths into base_dir/images/<category>/ and rewrite the DB column to a relative
    path (images/<category>/<file>). This makes the files discoverable by the file
    sync (which uploads the images/ tree) and portable across stations and the cloud.

    Backward compatible:
      - Rows already relative (start with 'images/' or 'ads_media/') are skipped.
      - Absolute paths whose file is missing are left untouched.
      - A plain UPDATE fires the existing change_log triggers so the new relative
        path syncs to the cloud and other stations (also carried by full snapshot).

    Returns the number of rows updated.
    """
    import sqlite3 as _sql
    import shutil as _shutil

    if not db_path or not os.path.isfile(db_path):
        return 0

    images_dir = os.path.join(base_dir, 'images')
    # (table, column, category subfolder under images/)
    targets = [
        ('products', 'image_path', 'products'),
        ('ads_items', 'image_path', 'ads'),
        ('public_closures', 'image_path_portrait', 'closures'),
        ('public_closures', 'image_path_landscape', 'closures'),
    ]

    updated = 0
    try:
        conn = _sql.connect(db_path)
    except Exception:
        return 0
    try:
        conn.row_factory = _sql.Row
        cur = conn.cursor()
        for table, col, category in targets:
            try:
                cur.execute(
                    f'SELECT id, {col} AS v FROM {table} '
                    f'WHERE {col} IS NOT NULL AND {col} != ""'
                )
                rows = cur.fetchall()
            except Exception:
                # Table or column does not exist in this DB — skip
                continue

            dest_dir = os.path.join(images_dir, category)
            for r in rows:
                try:
                    rid = r['id']
                    val = str(r['v'] or '').strip()
                except Exception:
                    continue
                if not val:
                    continue
                norm = val.replace('\\', '/').lower()
                # Already a synced relative path
                if norm.startswith('images/') or norm.startswith('ads_media/'):
                    continue
                # Only mirror absolute paths that point to an existing file
                if not (os.path.isabs(val) and os.path.isfile(val)):
                    continue
                try:
                    base_name = os.path.basename(val)
                    safe = re.sub(r'[^0-9A-Za-z._-]', '_', base_name) or 'img'
                    fname = f"{category}_{rid}_{safe}"
                    os.makedirs(dest_dir, exist_ok=True)
                    dest = os.path.join(dest_dir, fname)
                    src_hash = _calc_file_hash(val)
                    dst_hash = _calc_file_hash(dest) if os.path.exists(dest) else ''
                    if src_hash != dst_hash:
                        _shutil.copy2(val, dest)
                    rel = f"images/{category}/{fname}"
                    try:
                        cur.execute(
                            f'UPDATE {table} SET {col} = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                            (rel, rid))
                    except Exception:
                        cur.execute(f'UPDATE {table} SET {col} = ? WHERE id = ?', (rel, rid))
                    updated += 1
                    print(f"[ASSET-SYNC] Mirrored {table}.{col} id={rid} -> {rel}")
                except Exception as e:
                    print(f"[ASSET-SYNC] mirror failed {table} id={rid}: {e}")
        if updated:
            conn.commit()
    except Exception as e:
        print(f"[ASSET-SYNC] normalize_db_image_assets error: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return updated


def apply_pulled_assets(base_dir: str) -> dict:
    """After a file-sync pull, detect images/logo/ and images/photos/ and return
    config values that should be written to local config (for new stations).
    Returns dict with logo_path and/or photos_folder if found.
    """
    result: dict = {}
    images_dir = os.path.join(base_dir, 'images')

    logo_dir = os.path.join(images_dir, 'logo')
    if os.path.isdir(logo_dir):
        for f in os.listdir(logo_dir):
            if f.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp')):
                result['logo_path'] = os.path.join(logo_dir, f)
                break

    photos_dir = os.path.join(images_dir, 'photos')
    if os.path.isdir(photos_dir):
        if any(f.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')) for f in os.listdir(photos_dir)):
            result['photos_folder'] = photos_dir

    return result


def sync_files_cycle(push_url: str, api_key: str, tenant_id: str, base_dir: str):
    if not push_url or not api_key or not tenant_id:
        return
    
    # Base URL for file operations
    base_sync_url = push_url.replace('/sync/push', '/sync/files')
    if base_sync_url == push_url:
         # Fallback if URL structure is different
         base_sync_url = push_url.rstrip('/') + '/files'

    manifest_url = f"{base_sync_url}/manifest"
    upload_url = f"{base_sync_url}/upload"
    list_url = f"{base_sync_url}/list"
    
    # 1. PUSH: Upload local files that server is missing or has different hash
    local_manifest = _get_local_file_manifest(base_dir, ['images', 'sounds'])
    
    try:
        # Ask server what it needs
        req = urllib.request.Request(
            manifest_url,
            data=json.dumps({'manifest': local_manifest}).encode('utf-8'),
            headers={'Content-Type': 'application/json', 'api-key': api_key, 'x-tenant-id': tenant_id}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            missing_on_server = data.get('missing', [])
    except Exception as e:
        print(f"[FILE-SYNC] Check manifest failed: {e}")
        return

    # Upload missing files
    for rel_path in missing_on_server:
        full_path = os.path.join(base_dir, rel_path)
        if not os.path.exists(full_path):
            continue
        
        print(f"[FILE-SYNC] Uploading {rel_path}...")
        try:
            # Simple multipart upload using internal helper or requests if available
            # Here we implement a basic multipart/form-data generator since standard lib doesn't have one
            _upload_file(upload_url, api_key, tenant_id, full_path, rel_path)
        except Exception as e:
            print(f"[FILE-SYNC] Upload {rel_path} failed: {e}")

    # 2. PULL: Download files that server has but we miss/diff
    # For now, let's focus on PUSH (Backup) as primary goal. 
    # But for a new station, PULL is critical.
    try:
        req = urllib.request.Request(
            list_url,
            headers={'api-key': api_key, 'x-tenant-id': tenant_id}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            server_manifest = json.loads(resp.read().decode('utf-8')).get('manifest', {})
    except Exception as e:
        print(f"[FILE-SYNC] Get server manifest failed: {e}")
        return

    for rel_path, remote_hash in server_manifest.items():
        local_hash = local_manifest.get(rel_path)
        if local_hash != remote_hash:
            # Download
            print(f"[FILE-SYNC] Downloading {rel_path}...")
            _download_file(push_url, api_key, tenant_id, base_dir, rel_path)

def _upload_file(url: str, api_key: str, tenant_id: str, file_path: str, rel_path: str):
    boundary = '----WebKitFormBoundary' + secrets.token_hex(16)
    with open(file_path, 'rb') as f:
        file_data = f.read()
    
    filename = os.path.basename(rel_path)
    mime_type = 'application/octet-stream'
    if filename.endswith('.jpg'): mime_type = 'image/jpeg'
    elif filename.endswith('.png'): mime_type = 'image/png'
    
    body = []
    body.append(f'--{boundary}'.encode('utf-8'))
    body.append(f'Content-Disposition: form-data; name="file"; filename="{filename}"'.encode('utf-8'))
    body.append(f'Content-Type: {mime_type}'.encode('utf-8'))
    body.append(b'')
    body.append(file_data)
    body.append(f'--{boundary}'.encode('utf-8'))
    body.append(f'Content-Disposition: form-data; name="rel_path"'.encode('utf-8'))
    body.append(b'')
    body.append(rel_path.encode('utf-8'))
    body.append(f'--{boundary}--'.encode('utf-8'))
    body.append(b'')
    
    data = b'\r\n'.join(body)
    
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            'Content-Type': f'multipart/form-data; boundary={boundary}',
            'Content-Length': str(len(data)),
            'api-key': api_key, 
            'x-tenant-id': tenant_id
        }
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        pass

def _download_file(push_url: str, api_key: str, tenant_id: str, base_dir: str, rel_path: str):
    # Use the assets endpoint logic or a specific download endpoint
    # The server app.py has /assets/{tenant_id}/{filename}, but that's for public/flat structure usually.
    # We need a secure way to download structure.
    # Let's assume we add /sync/files/download?path=...
    
    base_sync_url = push_url.replace('/sync/push', '/sync/files')
    if base_sync_url == push_url:
         base_sync_url = push_url.rstrip('/') + '/files'
    
    # We need to quote the path for query param
    encoded_path = urllib.parse.quote(rel_path)
    url = f"{base_sync_url}/download?path={encoded_path}"
    
    req = urllib.request.Request(
        url,
        headers={'api-key': api_key, 'x-tenant-id': tenant_id}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
            if data:
                dest_path = os.path.join(base_dir, rel_path)
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                with open(dest_path, 'wb') as f:
                    f.write(data)
    except Exception as e:
        print(f"[FILE-SYNC] Download {rel_path} failed: {e}")
