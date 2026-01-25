"""Cloud Sync Service (minimal skeleton)

Run locally:
  pip install -r cloud_service/requirements.txt
  uvicorn cloud_service.app:app --host 0.0.0.0 --port 8000
"""
from typing import Dict, Any, List
import os
import sqlite3
from fastapi import FastAPI, Header, HTTPException, Form
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

app = FastAPI(title="SchoolPoints Sync")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
DB_PATH = os.path.join(DATA_DIR, 'cloud.db')


def _db() -> sqlite3.Connection:
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db() -> None:
    conn = _db()
    cur = conn.cursor()
    cur.execute(
        '''
        CREATE TABLE IF NOT EXISTS institutions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            api_key TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        '''
    )
    cur.execute(
        '''
        CREATE TABLE IF NOT EXISTS changes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id TEXT NOT NULL,
            station_id TEXT,
            entity_type TEXT NOT NULL,
            entity_id TEXT,
            action_type TEXT NOT NULL,
            payload_json TEXT,
            created_at TEXT,
            received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        '''
    )
    conn.commit()
    conn.close()


@app.on_event("startup")
def _startup() -> None:
    _init_db()


class ChangeItem(BaseModel):
    id: int
    entity_type: str
    entity_id: str | None = None
    action_type: str
    payload_json: str | None = None
    created_at: str | None = None


class SyncPushRequest(BaseModel):
    tenant_id: str
    station_id: str | None = None
    changes: List[ChangeItem]


@app.post("/sync/push")
def sync_push(payload: SyncPushRequest, api_key: str = Header(default="")) -> Dict[str, Any]:
    if not payload.tenant_id:
        raise HTTPException(status_code=400, detail="missing tenant_id")
    if not api_key:
        raise HTTPException(status_code=401, detail="missing api_key")

    conn = _db()
    cur = conn.cursor()
    cur.execute(
        'SELECT id FROM institutions WHERE tenant_id = ? AND api_key = ? LIMIT 1',
        (payload.tenant_id, api_key)
    )
    row = cur.fetchone()
    if not row:
        allow_auto = str(os.getenv('AUTO_CREATE_TENANT') or '').strip() == '1'
        if allow_auto:
            try:
                cur.execute(
                    'INSERT INTO institutions (tenant_id, name, api_key) VALUES (?, ?, ?)',
                    (payload.tenant_id, payload.tenant_id, api_key)
                )
                conn.commit()
                cur.execute(
                    'SELECT id FROM institutions WHERE tenant_id = ? AND api_key = ? LIMIT 1',
                    (payload.tenant_id, api_key)
                )
                row = cur.fetchone()
            except sqlite3.IntegrityError:
                row = None
        if not row:
            conn.close()
            raise HTTPException(status_code=401, detail="invalid api_key")

    for ch in payload.changes:
        cur.execute(
            '''
            INSERT INTO changes (tenant_id, station_id, entity_type, entity_id, action_type, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                payload.tenant_id,
                payload.station_id,
                ch.entity_type,
                ch.entity_id,
                ch.action_type,
                ch.payload_json,
                ch.created_at
            )
        )
    conn.commit()
    conn.close()

    # placeholder behavior
    return {
        "ok": True,
        "received": len(payload.changes),
        "tenant_id": payload.tenant_id,
        "station_id": payload.station_id,
    }


@app.get("/admin/setup", response_class=HTMLResponse)
def admin_setup_form(admin_key: str = '') -> str:
    expected = str(os.getenv('ADMIN_KEY') or '').strip()
    if expected and admin_key != expected:
        return "<h3>Invalid admin key</h3>"
    return """
    <html><body>
    <h2>Create Institution</h2>
    <form method="post">
      <label>Institution Name</label><br/>
      <input name="name"/><br/><br/>
      <label>Tenant ID</label><br/>
      <input name="tenant_id"/><br/><br/>
      <label>API Key</label><br/>
      <input name="api_key"/><br/><br/>
      <button type="submit">Create</button>
    </form>
    </body></html>
    """


@app.post("/admin/setup", response_class=HTMLResponse)
def admin_setup_submit(
    name: str = Form(...),
    tenant_id: str = Form(...),
    api_key: str = Form(...),
    admin_key: str = ''
) -> str:
    expected = str(os.getenv('ADMIN_KEY') or '').strip()
    if expected and admin_key != expected:
        return "<h3>Invalid admin key</h3>"
    conn = _db()
    cur = conn.cursor()
    try:
        cur.execute(
            'INSERT INTO institutions (tenant_id, name, api_key) VALUES (?, ?, ?)',
            (tenant_id.strip(), name.strip(), api_key.strip())
        )
        conn.commit()
        return "<h3>Institution created.</h3>"
    except sqlite3.IntegrityError:
        return "<h3>Tenant ID already exists.</h3>"
    finally:
        conn.close()


@app.get("/view/changes", response_class=HTMLResponse)
def view_changes(tenant_id: str, api_key: str) -> str:
    conn = _db()
    cur = conn.cursor()
    cur.execute(
        'SELECT id FROM institutions WHERE tenant_id = ? AND api_key = ? LIMIT 1',
        (tenant_id, api_key)
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        return "<h3>Unauthorized</h3>"
    cur.execute(
        '''
        SELECT received_at, station_id, entity_type, action_type, entity_id, payload_json
        FROM changes
        WHERE tenant_id = ?
        ORDER BY id DESC
        LIMIT 200
        ''',
        (tenant_id,)
    )
    rows = cur.fetchall() or []
    conn.close()
    items = "".join(
        f"<tr><td>{r['received_at']}</td><td>{r['station_id'] or ''}</td><td>{r['entity_type']}</td><td>{r['action_type']}</td><td>{r['entity_id'] or ''}</td><td><pre>{r['payload_json'] or ''}</pre></td></tr>"
        for r in rows
    )
    return f"""
    <html><body>
    <h2>Recent Changes</h2>
    <table border="1" cellpadding="6">
    <tr><th>Received</th><th>Station</th><th>Type</th><th>Action</th><th>Entity</th><th>Payload</th></tr>
    {items}
    </table>
    </body></html>
    """
