# SchoolPoints Cloud Sync Service (Minimal)

שירות ענן מינימלי לסנכרון שינויי DB מהעמדות המקומיות.

## הפעלה מקומית
```bash
pip install -r cloud_service/requirements.txt
uvicorn cloud_service.app:app --host 0.0.0.0 --port 8000
```

## DigitalOcean App Platform
**Run Command:**
```
uvicorn cloud_service.app:app --host 0.0.0.0 --port 8080
```

## Endpoint
- `POST /sync/push` עם Header: `api_key`

