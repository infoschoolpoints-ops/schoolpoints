import os
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
