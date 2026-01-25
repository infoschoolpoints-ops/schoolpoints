"""Cloud Sync Service (minimal skeleton)

Run locally:
  pip install -r cloud_service/requirements.txt
  uvicorn cloud_service.app:app --host 0.0.0.0 --port 8000
"""
from typing import Dict, Any, List
import os
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

app = FastAPI(title="SchoolPoints Sync")


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
    # TODO: replace with real auth + DB persistence
    expected_key = str(os.getenv('SYNC_API_KEY') or '').strip()
    if expected_key and api_key != expected_key:
        raise HTTPException(status_code=401, detail="invalid api_key")
    if not payload.tenant_id:
        raise HTTPException(status_code=400, detail="missing tenant_id")

    # placeholder behavior
    return {
        "ok": True,
        "received": len(payload.changes),
        "tenant_id": payload.tenant_id,
        "station_id": payload.station_id,
    }
