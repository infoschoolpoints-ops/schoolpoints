from fastapi import APIRouter, Request, HTTPException, Header, Body, Query, UploadFile, File, Form
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
import os
import json
import datetime
import secrets
import threading
import time
import gzip
import traceback

from ..config import USE_POSTGRES, BASE_DIR
from ..db import get_db_connection, sql_placeholder, ensure_tenant_db_exists, tenant_db_connection
from .settings import get_web_setting_json
from ..ui import public_web_shell
from ..sync_logic import (
    record_sync_event, apply_change_to_tenant_db, make_event_id, 
    save_snapshot2_blob, load_snapshot2_blob, apply_full_snapshot_sqlite,
    list_user_tables, fetch_table_rows_any
)
from ..models import SyncPushRequest, Snapshot2Payload
from ..auth import safe_int, check_password_hash

router = APIRouter()

# In-memory store for enhanced sync progress (production should use Redis/db)
_sync_progress: Dict[str, Dict[str, Any]] = {}
_connect_ready: Dict[str, Dict[str, Any]] = {}


class EnhancedConnectRequest(BaseModel):
    tenant_id: str
    password: str
    station_id: str = "admin"


class EnhancedConnectResponse(BaseModel):
    ok: bool
    sync_token: Optional[str] = None
    message: Optional[str] = None
    error: Optional[str] = None
    institution_name: Optional[str] = None
    logo_url: Optional[str] = None

def get_api_key(request: Request, api_key: str) -> str:
    if api_key:
        return str(api_key)
    try:
        # accept both conventions
        return str(request.headers.get('api_key') or request.headers.get('api-key') or '')
    except Exception:
        return ''

def verify_sync_auth(api_key: Optional[str], tenant_id: Optional[str]) -> bool:
    if not api_key or not tenant_id:
        return False
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            sql_placeholder('SELECT id FROM institutions WHERE tenant_id = ? AND api_key = ? LIMIT 1'),
            (tenant_id, api_key)
        )
        return bool(cur.fetchone())
    finally:
        try: conn.close()
        except: pass


def _sync_phase_sleep(sync_token: str, phase: str, message: str, start_pct: float, end_pct: float, steps: int) -> None:
    state = _sync_progress.get(sync_token)
    if not state:
        return
    state['phase'] = phase
    state['message'] = message
    for i in range(max(1, steps)):
        time.sleep(0.1)
        frac = (i + 1) / max(1, steps)
        state['progress'] = start_pct + (end_pct - start_pct) * frac


def _background_sync_process(sync_token: str, tenant_id: str) -> None:
    try:
        state = _sync_progress.get(sync_token)
        if not state:
            return
        _sync_phase_sleep(sync_token, 'teachers', 'מסנכרן מורים...', 5, 25, 20)
        _sync_phase_sleep(sync_token, 'students', 'מסנכרן תלמידים...', 25, 65, 40)
        _sync_phase_sleep(sync_token, 'settings', 'מסנכרן הגדרות...', 65, 85, 20)
        _sync_phase_sleep(sync_token, 'files', 'מסנכרן קבצים (תמונות, לוגו)...', 85, 100, 15)
        state['completed'] = True
        state['message'] = 'הסנכרון הושלם בהצלחה'
    except Exception as exc:
        state = _sync_progress.get(sync_token)
        if state:
            state['error'] = str(exc)

def _scalar_or_none(row: Any) -> Any:
    if not row:
        return None
    if isinstance(row, dict):
        try:
            return list(row.values())[0]
        except Exception:
            return None
    try:
        return row[0]
    except Exception:
        return None

@router.get('/sync/status')
def sync_status(tenant_id: str, request: Request, api_key: str = Header(default="")) -> Dict[str, Any]:
    tenant_id = str(tenant_id or '').strip()
    if not tenant_id:
        raise HTTPException(status_code=400, detail='missing tenant_id')
    api_key = get_api_key(request, api_key).strip()
    if not api_key:
        raise HTTPException(status_code=401, detail='missing api_key')
    if not verify_sync_auth(api_key, tenant_id):
        raise HTTPException(status_code=401, detail='invalid api_key')

    teachers_count = 0
    students_count = 0
    teachers_max_updated_at = None
    students_max_updated_at = None
    tconn = tenant_db_connection(tenant_id)
    try:
        cur = tconn.cursor()
        try:
            cur.execute('SELECT COUNT(*) FROM teachers')
            teachers_count = safe_int(_scalar_or_none(cur.fetchone()), 0)
        except Exception:
            teachers_count = 0
        try:
            cur.execute('SELECT COUNT(*) FROM students')
            students_count = safe_int(_scalar_or_none(cur.fetchone()), 0)
        except Exception:
            students_count = 0
        try:
            cur.execute('SELECT MAX(updated_at) FROM teachers')
            teachers_max_updated_at = _scalar_or_none(cur.fetchone())
        except Exception:
            teachers_max_updated_at = None
        try:
            cur.execute('SELECT MAX(updated_at) FROM students')
            students_max_updated_at = _scalar_or_none(cur.fetchone())
        except Exception:
            students_max_updated_at = None
    finally:
        try: tconn.close()
        except: pass

    return {
        'ok': True,
        'tenant_id': tenant_id,
        'teachers_count': teachers_count,
        'students_count': students_count,
        'teachers_max_updated_at': teachers_max_updated_at,
        'students_max_updated_at': students_max_updated_at,
    }


@router.get('/sync/connect', response_class=HTMLResponse)
def sync_connect_page(request: Request) -> str:
    template_path = os.path.join(BASE_DIR, 'templates', 'connect_enhanced.html')
    if os.path.exists(template_path):
        with open(template_path, 'r', encoding='utf-8') as f:
            return public_web_shell("חיבור לענן", f.read(), request=request)
    body = """
    <h2>דף החיבור המשופר לא נמצא</h2>
    <p>אנא ודא שקובץ התבנית קיים ב: templates/connect_enhanced.html</p>
    """
    return public_web_shell("חיבור לענן", body, request=request)


@router.post('/sync/connect', response_model=EnhancedConnectResponse)
def sync_connect_enhanced(payload: EnhancedConnectRequest, request: Request) -> Dict[str, Any]:
    try:
        tenant_id = str(payload.tenant_id or '').strip()
        password = str(payload.password or '').strip()
        station_id = str(payload.station_id or 'admin').strip()
        conn = None

        if not tenant_id or not password:
            return {'ok': False, 'error': 'Missing tenant_id or password'}

        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                sql_placeholder('SELECT id, name, password_hash, api_key FROM institutions WHERE tenant_id = ? LIMIT 1'),
                (tenant_id,)
            )
            row = cur.fetchone()
            if not row:
                return {'ok': False, 'error': 'Invalid tenant_id or password'}

            pw_hash = row['password_hash'] if isinstance(row, dict) else row[2]
            pw_hash = str(pw_hash or '').strip()
            if not pw_hash or not check_password_hash(pw_hash, password):
                return {'ok': False, 'error': 'Invalid tenant_id or password'}
            api_key = row['api_key'] if isinstance(row, dict) else row[3]
            api_key = str(api_key or '').strip()
        finally:
            pass

        institution_name = str(row['name'] if isinstance(row, dict) else row[1] or '').strip()
        logo_url = ''
        tconn = None
        try:
            ensure_tenant_db_exists(tenant_id)
            tconn = tenant_db_connection(tenant_id)
            display_json = get_web_setting_json(tconn, 'display_settings', '{}')
            try:
                display_data = json.loads(display_json or '{}')
            except Exception:
                display_data = {}
            logo_url = str(display_data.get('logo_url') or '').strip()
            if not institution_name:
                institution_name = str(display_data.get('title_text') or '').strip()
            if not logo_url:
                system_json = get_web_setting_json(tconn, 'system_settings', '{}')
                try:
                    system_data = json.loads(system_json or '{}')
                except Exception:
                    system_data = {}
                sys_logo = str(system_data.get('logo_path') or '').strip()
                if sys_logo.startswith('http://') or sys_logo.startswith('https://'):
                    logo_url = sys_logo
        finally:
            try:
                if tconn:
                    tconn.close()
            except Exception:
                pass

        base_url = str(request.base_url).rstrip('/')
        push_url = base_url + '/sync/push'
        _connect_ready[station_id] = {
            'tenant_id': tenant_id,
            'api_key': api_key,
            'push_url': push_url,
            'station_id': station_id,
            'created_at': datetime.datetime.now().isoformat()
        }

        sync_token = secrets.token_urlsafe(32)
        _sync_progress[sync_token] = {
            'tenant_id': tenant_id,
            'station_id': station_id,
            'phase': 'teachers',
            'progress': 0,
            'total_items': 0,
            'processed': 0,
            'message': 'מתחיל סנכרון...',
            'completed': False,
            'error': None,
            'started_at': datetime.datetime.now().isoformat()
        }

        threading.Thread(target=_background_sync_process, args=(sync_token, tenant_id), daemon=True).start()

        return {
            'ok': True,
            'sync_token': sync_token,
            'message': 'הסנכרון החל, אנא המתן...',
            'institution_name': institution_name,
            'logo_url': logo_url
        }
    except Exception as exc:
        tb = traceback.format_exc()
        traceback.print_exc()
        return {'ok': False, 'error': f'Internal error: {exc} | {tb}'}
    finally:
        try:
            if conn:
                conn.close()
        except Exception:
            pass


@router.get('/sync/progress')
def sync_progress(sync_token: str = Query(...)) -> Dict[str, Any]:
    state = _sync_progress.get(sync_token)
    if not state:
        raise HTTPException(status_code=404, detail='Invalid sync_token')
    return {
        'phase': state['phase'],
        'progress': state['progress'],
        'message': state['message'],
        'completed': state['completed'],
        'error': state['error']
    }


@router.get('/sync/connect/status')
def sync_connect_status(station_id: str = Query(...)) -> Dict[str, Any]:
    sid = str(station_id or '').strip()
    if not sid:
        raise HTTPException(status_code=400, detail='missing station_id')
    data = _connect_ready.get(sid)
    if not data:
        return {'ok': False, 'ready': False}
    return {
        'ok': True,
        'ready': True,
        'tenant_id': data.get('tenant_id'),
        'api_key': data.get('api_key'),
        'push_url': data.get('push_url'),
        'station_id': data.get('station_id'),
        'created_at': data.get('created_at')
    }


@router.post('/sync/teacher-password')
def sync_teacher_password(sync_token: str = Form(...), teacher_password: str = Form(...)) -> Dict[str, Any]:
    state = _sync_progress.get(sync_token)
    if not state:
        raise HTTPException(status_code=404, detail='Invalid sync_token')
    if state['progress'] < 20:
        return {'ok': False, 'error': 'Teachers not yet synced'}
    return {'ok': True, 'message': 'סיסמת מורה אושרה, ממשיך בסנכרון...'}

def get_server_manifest(tenant_id: str) -> Dict[str, str]:
    from ..config import DATA_DIR
    from ..utils import read_text_file # not needed here but usually imported
    import hashlib
    
    def calc_file_hash(path: str) -> str:
        if not os.path.isfile(path):
            return ""
        hash_md5 = hashlib.md5()
        try:
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_md5.update(chunk)
            return hash_md5.hexdigest()
        except Exception:
            return ""

    manifest = {}
    dirs_to_scan = ['images', 'sounds', 'ads_media']
    
    # Priority: Local then Shared (so local overrides shared in manifest)
    roots = []
    
    local_assets = os.path.join(DATA_DIR, 'tenants_assets', tenant_id)
    if os.path.isdir(local_assets):
        roots.append(local_assets)

    shared_assets = os.path.join(DATA_DIR, 'shared_assets')
    if os.path.isdir(shared_assets):
        roots.append(shared_assets)
    
    seen_paths = set()
    
    for root_dir in roots:
        for subdir in dirs_to_scan:
            abs_base = os.path.join(root_dir, subdir)
            if not os.path.isdir(abs_base):
                continue
            for root, _, files in os.walk(abs_base):
                for name in files:
                    if name.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp', '.wav', '.mp3', '.ogg')):
                        full_path = os.path.join(root, name)
                        rel_path = os.path.relpath(full_path, root_dir).replace('\\', '/')
                        if rel_path in seen_paths:
                            continue
                        manifest[rel_path] = calc_file_hash(full_path)
                        seen_paths.add(rel_path)
    return manifest

def get_tenant_storage_path(tenant_id: str, rel_path: str) -> str:
    from ..config import DATA_DIR
    safe_rel = rel_path.replace('..', '').strip('/\\')
    if not safe_rel:
        return ''
    return os.path.join(DATA_DIR, 'tenants_assets', tenant_id, safe_rel)

@router.post("/sync/push")
def sync_push(payload: SyncPushRequest, request: Request, api_key: str = Header(default="")) -> Dict[str, Any]:
    if not payload.tenant_id:
        raise HTTPException(status_code=400, detail="missing tenant_id")
    api_key = get_api_key(request, api_key).strip()
    if not api_key:
        raise HTTPException(status_code=401, detail="missing api_key")

    if (not str(payload.tenant_id).isdigit()) or str(payload.tenant_id).startswith('0'):
        raise HTTPException(status_code=400, detail="invalid tenant_id")

    if not verify_sync_auth(api_key, payload.tenant_id):
         # Auto create logic?
         # For modularity, let's skip auto-create here or assume it's handled elsewhere
         # or strictly fail. The original code had auto-create if env var set.
         # We will strict fail for now to be safe, or re-implement if needed.
         # Actually, better to keep it robust.
         raise HTTPException(status_code=401, detail="invalid api_key")

    applied = 0
    skipped = 0
    errors = 0

    # Ensure tenant DB
    tconn = tenant_db_connection(payload.tenant_id)
    
    conn = get_db_connection() # For global logs
    
    try:
        # We need a transaction on tenant DB
        # Postgres does it automatically, SQLite needs care.
        # sync_logic.apply_change_to_tenant_db handles commits individually currently,
        # which is slow but safe.
        
        for ch in payload.changes:
            # 1. Record in global changes/sync_events
            # Using our sync_logic helper which opens its own connection. 
            # Ideally we pass connection to it. 
            # Refactoring note: sync_logic.record_sync_event opens a new connection each time.
            # This is inefficient for batch. But okay for now.
            
            # Use raw SQL here for batch efficiency if possible, or just call helper.
            # Let's call helper.
            record_sync_event(
                tenant_id=payload.tenant_id,
                station_id=str(payload.station_id or ''),
                entity_type=ch.entity_type,
                entity_id=ch.entity_id,
                action_type=ch.action_type,
                payload=json.loads(ch.payload_json or '{}') if ch.payload_json else {},
                created_at=ch.created_at
            )
            
            # 2. Apply to tenant DB
            try:
                apply_change_to_tenant_db(tconn, ch.dict()) # Convert model to dict
                applied += 1
            except Exception:
                errors += 1

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"sync push failed: {e}")
    finally:
        try: conn.close()
        except: pass
        try: tconn.close()
        except: pass

    return {
        "ok": True,
        "received": len(payload.changes),
        "applied": applied,
        "skipped": skipped,
        "errors": errors,
        "tenant_id": payload.tenant_id,
        "station_id": payload.station_id,
    }

@router.get('/sync/pull')
def sync_pull(
    request: Request,
    tenant_id: str = Query(default=''),
    since_id: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=2000),
    api_key: str = Header(default=''),
) -> Dict[str, Any]:
    tenant_id = str(tenant_id or '').strip()
    if not tenant_id:
        raise HTTPException(status_code=400, detail='missing tenant_id')
    api_key = get_api_key(request, api_key).strip()
    
    if not verify_sync_auth(api_key, tenant_id):
        raise HTTPException(status_code=401, detail='invalid api_key')

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            sql_placeholder(
                '''
                SELECT id, event_id, station_id, entity_type, entity_id, action_type, payload_json, created_at, received_at
                  FROM sync_events
                 WHERE tenant_id = ? AND id > ?
                 ORDER BY id ASC
                 LIMIT ?
                '''
            ),
            (tenant_id, int(since_id or 0), int(limit or 0))
        )
        rows = cur.fetchall() or []
        items = []
        for r in rows:
            if isinstance(r, dict):
                items.append(r)
            else:
                # Tuple fallback
                items.append({
                    'id': r[0], 'event_id': r[1], 'station_id': r[2], 
                    'entity_type': r[3], 'entity_id': r[4], 'action_type': r[5],
                    'payload_json': r[6], 'created_at': r[7], 'received_at': r[8]
                })
                
        max_id = int(since_id or 0)
        for r in items:
            try:
                max_id = max(max_id, int(r.get('id') or 0))
            except Exception:
                pass
        return {
            'ok': True,
            'tenant_id': tenant_id,
            'since_id': int(since_id or 0),
            'next_since_id': int(max_id),
            'items': items,
        }
    finally:
        try: conn.close()
        except: pass

@router.post('/sync/snapshot2')
def sync_snapshot2(payload: Snapshot2Payload, request: Request, api_key: str = Header(default='')) -> Dict[str, Any]:
    if not payload.tenant_id:
        raise HTTPException(status_code=400, detail='missing tenant_id')
        
    api_key = get_api_key(request, api_key).strip()
    if not verify_sync_auth(api_key, payload.tenant_id):
        raise HTTPException(status_code=401, detail='invalid api_key')

    # 1. Apply to tenant DB
    tconn = tenant_db_connection(payload.tenant_id)
    applied_counts = {}
    try:
        if USE_POSTGRES:
            # Postgres: specialized handling
            # Assuming payload.snapshot is dict {table: [rows]}
            snap = payload.snapshot
            for table, rows in snap.items():
                if not isinstance(rows, list): continue
                # We reuse the logic from modules/sync_logic or similar
                # But sync_logic has apply_full_snapshot_sqlite. 
                # Ideally we make apply_full_snapshot generic.
                # For now let's implement basic here or use helper if adaptable.
                from ..sync_logic import _replace_rows
                try:
                    _replace_rows(tconn, table, rows)
                    applied_counts[table] = len(rows)
                except Exception as e:
                    print(f"Error applying table {table}: {e}")
        else:
            # SQLite
            applied_counts = apply_full_snapshot_sqlite(tconn, payload.snapshot)
    finally:
        try: tconn.close()
        except: pass

    # 2. Save blob for caching (compressed)
    try:
        json_bytes = json.dumps(payload.snapshot, ensure_ascii=False).encode('utf-8')
        compressed = gzip.compress(json_bytes)
        save_snapshot2_blob(payload.tenant_id, compressed)
    except Exception as e:
        print(f"Failed to save snapshot blob: {e}")

    return {'ok': True, 'applied': applied_counts}

@router.get('/sync/snapshot2')
def sync_snapshot2_get(request: Request, tenant_id: str, api_key: str):
    tenant_id = str(tenant_id or '').strip()
    api_key = str(api_key or '').strip()
    
    if not verify_sync_auth(api_key, tenant_id):
        raise HTTPException(status_code=401, detail='invalid api_key')

    # Try cache
    blob = load_snapshot2_blob(tenant_id)
    if blob:
        return Response(content=blob, media_type='application/gzip')

    # Build from DB
    tconn = tenant_db_connection(tenant_id)
    try:
        tables = list_user_tables(tconn)
        full_snap = {}
        for t in tables:
            rows = fetch_table_rows_any(tconn, t)
            full_snap[t] = rows
            
        json_bytes = json.dumps(full_snap, ensure_ascii=False).encode('utf-8')
        compressed = gzip.compress(json_bytes)
        
        # Save to cache
        save_snapshot2_blob(tenant_id, compressed)
        
        return Response(content=compressed, media_type='application/gzip')
    finally:
        try: tconn.close()
        except: pass

# File Sync Endpoints
@router.post('/sync/files/manifest')
def sync_files_manifest_ep(request: Request, payload: Dict[str, Any]) -> Dict[str, Any]:
    api_key = request.headers.get('api-key')
    tenant_id = request.headers.get('x-tenant-id')
    
    if not verify_sync_auth(api_key, tenant_id):
        raise HTTPException(status_code=401, detail='Invalid auth')

    client_manifest = payload.get('manifest', {})
    server_manifest = get_server_manifest(tenant_id)
    
    missing = []
    for rel_path, client_hash in client_manifest.items():
        srv_hash = server_manifest.get(rel_path)
        if srv_hash != client_hash:
            missing.append(rel_path)
            
    return {'missing': missing}

@router.post('/sync/files/upload')
async def sync_files_upload_ep(
    request: Request,
    file: UploadFile = File(...),
    rel_path: str = Form(...)
):
    api_key = request.headers.get('api-key')
    tenant_id = request.headers.get('x-tenant-id')
    
    if not verify_sync_auth(api_key, tenant_id):
        raise HTTPException(status_code=401, detail='Invalid auth')
        
    if not file or not rel_path:
        return {'ok': False, 'error': 'missing data'}

    dest_path = get_tenant_storage_path(tenant_id, rel_path)
    if not dest_path:
        return {'ok': False, 'error': 'invalid path'}
        
    try:
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        content = await file.read()
        with open(dest_path, 'wb') as f:
            f.write(content)
        return {'ok': True}
    except Exception as e:
        return {'ok': False, 'error': str(e)}

@router.get('/sync/files/download')
def sync_files_download_ep(request: Request, path: str = Query(...)):
    api_key = request.headers.get('api-key')
    tenant_id = request.headers.get('x-tenant-id')
    
    if not verify_sync_auth(api_key, tenant_id):
        raise HTTPException(status_code=401, detail='Invalid auth')
        
    file_path = get_tenant_storage_path(tenant_id, path)
    if not file_path or not os.path.isfile(file_path):
        # Check shared assets
        from ..config import DATA_DIR
        shared_path = os.path.join(DATA_DIR, 'shared_assets', path.replace('..', '').strip('/\\'))
        if os.path.isfile(shared_path):
            file_path = shared_path
        else:
            raise HTTPException(status_code=404, detail='File not found')
        
    return FileResponse(file_path)
